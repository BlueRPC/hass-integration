import asyncio
import logging
import uuid
from typing import Any, Callable, TypeVar, cast

import async_timeout
import grpc
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.client import BaseBleakClient, NotifyCallback
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTServiceCollection
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant

from .characteristic import BleakGATTCharacteristicBlueRPC
from .descriptor import BleakGATTDescriptorBlueRPC
from .rpc import common_pb2, gatt_pb2, services_pb2_grpc
from .service import BleakGATTServiceBlueRPC

_LOGGER = logging.getLogger(__name__)
DEFAULT_MTU = 23
CONNECT_FREE_SLOT_TIMEOUT = 5
WAIT_SLOT_INTERVAL = 1

_WrapFuncType = TypeVar(  # pylint: disable=invalid-name
    "_WrapFuncType", bound=Callable[..., Any]
)


def grpc_error_as_bleak_error(func: _WrapFuncType) -> _WrapFuncType:
    """Define a wrapper throw grpc errors as BleakErrors."""

    async def _async_wrap_bluetooth_operation(
        self: BaseBleakClient, *args: Any, **kwargs: Any
    ) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except grpc.aio._call.AioRpcError as err:
            if err.details() == "Unexpected <class 'TimeoutError'>: ":
                raise asyncio.TimeoutError(str(err)) from err
            else:
                raise BleakError(str(err)) from err

    return cast(_WrapFuncType, _async_wrap_bluetooth_operation)


class BlueRPCClient(BaseBleakClient):
    """BlueRPC Bleak Client."""

    def __init__(
        self,
        address_or_ble_device: BLEDevice | str,
        *args: Any,
        client: services_pb2_grpc.BlueRPCStub,
        **kwargs: Any,
    ):
        super().__init__(address_or_ble_device, *args, **kwargs)

        self._hass: HomeAssistant = kwargs["hass"]
        self._client = client
        self._device = gatt_pb2.BLEDevice(mac=self.address)
        self._is_connected = False
        self._mtu = None
        self.services = None
        self._disconnect_handler = False
        self._notif_handler = False
        self._notif_map = {}
        self._timeout = 60

    def _check_resp(self, status):
        if status.code == common_pb2.ERROR_CODE_CONNECTION_REQUIRED:
            asyncio.get_running_loop().call_soon_threadsafe(self.disconnect)
            self._disconnected_callback(self)
            raise BleakError("Not Connected")

    async def _disconnection_handler(self):
        async for resp in self._client.BLEReceiveDisconnect(common_pb2.Void()):
            if resp.mac == self.address and self._disconnected_callback:
                await self.disconnect()
                self._disconnected_callback(self)

    @grpc_error_as_bleak_error
    async def connect(self, **kwargs: Any) -> bool:
        """Connect to a specified Peripheral.

        Keyword Args:
            timeout (float): Timeout for required
                ``BleakScanner.find_device_by_address`` call. Defaults to 10.0.

        Returns:
            Boolean representing connection status.
        """
        _LOGGER.debug(f"connecting to {self.address} ...")
        # await self._wait_for_free_connection_slot(CONNECT_FREE_SLOT_TIMEOUT)

        timeout = kwargs.get("timeout", self._timeout)
        self.services_resolved = False
        resp = await self._client.BLEConnect(
            gatt_pb2.BLEConnectRequest(device=self._device), timeout=timeout
        )
        if (
            resp.status.code == common_pb2.ERROR_CODE_OK
            or resp.status.code == common_pb2.ERROR_CODE_ALREADY_CONNECTED
        ):
            if not self._disconnect_handler and self._disconnected_callback:
                self._disconnect_handler = asyncio.create_task(
                    self._disconnection_handler()
                )
            self._is_connected = True
            self._mtu = resp.mtu if resp.mtu != 0 else None
            await self.get_services()
            return True

        elif resp.status.code == common_pb2.ERROR_CODE_CONNECTION_FAILED:
            raise BleakError(
                "Failed to connect to device {0}: {1}.".format(
                    self.address, resp.status.message
                )
            )
        else:
            raise BleakError(
                "An error occured while connecting to device {0}: {1} (code: {2}).".format(
                    self.address, resp.status.message, resp.status.code
                )
            )

    @grpc_error_as_bleak_error
    async def disconnect(self) -> bool:
        """Disconnect from the peripheral device."""
        if self._is_connected:
            await self._client.BLEDisconnect(self._device, timeout=self._timeout)
            self._is_connected = False
        return True

    @grpc_error_as_bleak_error
    async def _wait_for_free_connection_slot(self, timeout: float) -> None:
        """Wait for a free connection slot."""
        async with async_timeout.timeout(timeout):
            while True:
                resp = await self._client.BLEGetDevices(common_pb2.Void())
                if (
                    resp.status.code == common_pb2.ERROR_CODE_OK
                    and resp.max_connections == 0
                    or resp.connected_devices < resp.max_connections
                ):
                    return
                await asyncio.sleep(WAIT_SLOT_INTERVAL)

    @property
    def is_connected(self) -> bool:
        """Is Connected."""
        return self._is_connected

    @property
    def mtu_size(self) -> int:
        """Get ATT MTU size for active connection."""
        return self._mtu or DEFAULT_MTU

    @grpc_error_as_bleak_error
    async def pair(self, *args: Any, **kwargs: Any) -> bool:
        """Attempt to pair."""
        resp = await self._client.BLEPair(self._device, timeout=self._timeout)
        self._check_resp(resp)
        if resp.code == common_pb2.ERROR_CODE_OK:
            return True
        elif resp.code == common_pb2.ERROR_CODE_UNSUPPORTED:
            raise NotImplementedError("Pairing is not available.")
        elif resp.code == common_pb2.ERROR_CODE_PAIRING_CODE_REQUIRED:
            _LOGGER.error(
                "Pairing with %s failed: a pairing code is required", self.address
            )
            return False
        else:
            _LOGGER.error(
                "Pairing with %s failed due to error: %s", self.address, resp.message
            )
        return False

    @grpc_error_as_bleak_error
    async def unpair(self) -> bool:
        """Attempt to unpair."""
        resp = await self._client.BLEUnpair(self._device, timeout=self._timeout)
        self._check_resp(resp)
        if resp.code == common_pb2.ERROR_CODE_OK:
            return True
        elif resp.code == common_pb2.ERROR_CODE_UNSUPPORTED:
            raise NotImplementedError("Unairing is not available.")
        else:
            _LOGGER.error(
                "Pairing with %s failed due to error: %s", self.address, resp.message
            )
        return False

    @grpc_error_as_bleak_error
    async def get_services(self, **kwargs: Any) -> BleakGATTServiceCollection:
        """Get all services registered for this GATT server.

        Returns:
           A :py:class:`bleak.backends.service.BleakGATTServiceCollection`
           with this device's services tree.
        """
        if self.services:
            return self.services
        else:
            resp = await self._client.BLEListServices(
                self._device, timeout=self._timeout
            )
            self._check_resp(resp.status)
            if resp.status.code != common_pb2.ERROR_CODE_OK:
                raise BleakError(
                    "An error occured while listing services of device {0}: {1} (code: {2}).".format(
                        self.address, resp.status.message, resp.status.code
                    )
                )

            self.services = BleakGATTServiceCollection()
            for service in resp.services:
                svc = BleakGATTServiceBlueRPC(service)
                self.services.add_service(svc)

                for characteristic in service.characteristics:
                    chr = BleakGATTCharacteristicBlueRPC(
                        characteristic, self.mtu_size - 3, svc.uuid, svc.handle
                    )
                    self.services.add_characteristic(chr)

                    for descriptor in characteristic.descriptors:
                        self.services.add_descriptor(
                            BleakGATTDescriptorBlueRPC(descriptor, chr.uuid, chr.handle)
                        )
            return self.services

    def _resolve_characteristic(
        self, char_specifier: BleakGATTCharacteristic | int | str | uuid.UUID
    ) -> BleakGATTCharacteristic:
        """Resolve a characteristic specifier to a BleakGATTCharacteristic object."""
        if (services := self.services) is None:
            raise BleakError("Services have not been resolved")
        if not isinstance(char_specifier, BleakGATTCharacteristic):
            characteristic = services.get_characteristic(char_specifier)
        else:
            characteristic = char_specifier
        if not characteristic:
            raise BleakError(f"Characteristic {char_specifier} was not found!")
        return characteristic

    @grpc_error_as_bleak_error
    async def read_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | uuid.UUID,
        **kwargs: Any,
    ) -> bytearray:
        """Perform read operation on the specified GATT characteristic.

        Args:
            char_specifier (BleakGATTCharacteristic, int, str or UUID):
                The characteristic to read from, specified by either integer
                handle, UUID or directly by the BleakGATTCharacteristic
                object representing it.
            **kwargs: Unused

        Returns:
            (bytearray) The read data.
        """
        characteristic = self._resolve_characteristic(char_specifier)
        resp = await self._client.BLEReadCharacteristic(
            gatt_pb2.BLEReadCharacteristicRequest(
                device=self._device,
                service_uuid=characteristic.service_uuid,
                uuid=characteristic.uuid,
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp.status)
        if resp.status.code != common_pb2.ERROR_CODE_OK:
            raise BleakError(
                "An error occured while reading characteristic of device {0}: {1} (code: {2}).".format(
                    self.address, resp.status.message, resp.status.code
                )
            )
        return bytearray(resp.data)

    @grpc_error_as_bleak_error
    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | uuid.UUID,
        data: bytes | bytearray | memoryview,
        response: bool = False,
    ) -> None:
        """Perform a write operation of the specified GATT characteristic.

        Args:
            char_specifier (BleakGATTCharacteristic, int, str or UUID):
                The characteristic to write to, specified by either integer
                handle, UUID or directly by the BleakGATTCharacteristic object
                representing it.
            data (bytes or bytearray): The data to send.
            response (bool): If write-with-response operation should be done.
                Defaults to `False`.
        """
        characteristic = self._resolve_characteristic(char_specifier)
        resp = await self._client.BLEWriteCharacteristic(
            gatt_pb2.BLEWriteCharacteristicRequest(
                device=self._device,
                service_uuid=characteristic.service_uuid,
                uuid=characteristic.uuid,
                data=bytes(data),
                mode=gatt_pb2.BLE_WRITE_MODE_UNK
                if response
                else gatt_pb2.BLE_WRITE_MODE_NO_RESPONSE,
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp)
        if resp.code != common_pb2.ERROR_CODE_OK:
            raise BleakError(
                "An error occured while writing characteristic of device {0}: {1} (code: {2}).".format(
                    self.address, resp.message, resp.code
                )
            )

    def _resolve_descriptor(
        self, desc_specifier: BleakGATTDescriptor | int | str | uuid.UUID
    ) -> BleakGATTDescriptor:
        """Resolve a characteristic specifier to a BleakGATTCharacteristic object."""
        if (services := self.services) is None:
            raise BleakError("Services have not been resolved")
        if not isinstance(desc_specifier, BleakGATTDescriptor):
            descriptor = services.get_descriptor(desc_specifier)
        else:
            descriptor = desc_specifier
        if not descriptor:
            raise BleakError(f"Descriptor {desc_specifier} was not found!")
        return descriptor

    @grpc_error_as_bleak_error
    async def read_gatt_descriptor(
        self, desc_specifier: BleakGATTDescriptor | int | str | uuid.UUID, **kwargs: Any
    ) -> bytearray:
        """Perform read operation on the specified GATT descriptor.

        Args:
            handle (int): The handle of the descriptor to read from.
            **kwargs: Unused

        Returns:
            (bytearray) The read data.
        """
        descriptor = self._resolve_descriptor(desc_specifier)
        resp = await self._client.BLEReadDescriptor(
            gatt_pb2.BLEReadDescriptorRequest(
                device=self._device,
                service_uuid=self._resolve_characteristic(
                    descriptor.characteristic_uuid
                ).service_uuid,
                characteristic_uuid=descriptor.characteristic_uuid,
                uuid=descriptor.uuid,
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp.status)
        if resp.status.code != common_pb2.ERROR_CODE_OK:
            raise BleakError(
                "An error occured while reading descriptor of device {0}: {1} (code: {2}).".format(
                    self.address, resp.status.message, resp.status.code
                )
            )
        return bytearray(resp.data)

    @grpc_error_as_bleak_error
    async def write_gatt_descriptor(
        self,
        desc_specifier: BleakGATTDescriptor | int | str | uuid.UUID,
        data: bytes | bytearray | memoryview,
    ) -> None:
        """Perform a write operation on the specified GATT descriptor.

        Args:
            handle (int): The handle of the descriptor to read from.
            data (bytes or bytearray): The data to send.
        """
        descriptor = self._resolve_descriptor(desc_specifier)
        resp = await self._client.BLEWriteDescriptor(
            gatt_pb2.BLEWriteDescriptorRequest(
                device=self._device,
                service_uuid=self._resolve_characteristic(
                    descriptor.characteristic_uuid
                ).service_uuid,
                characteristic_uuid=descriptor.characteristic_uuid,
                uuid=descriptor.uuid,
                data=bytes(data),
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp)
        if resp.code != common_pb2.ERROR_CODE_OK:
            raise BleakError(
                "An error occured while writing descriptor of device {0}: {1} (code: {2}).".format(
                    self.address, resp.message, resp.code
                )
            )

    @grpc_error_as_bleak_error
    async def _notify_handler(self):
        async for resp in self._client.BLEReceiveNotifications(common_pb2.Void()):
            if resp.device.mac == self.address:
                key = (resp.service_uuid, resp.uuid)
                notif_callback = None
                for k, v in self._notif_map.items():
                    if k == key or (key[0] == "" and k[1] == key[1]):
                        notif_callback = v
                handle = None
                for k, v in BleakGATTCharacteristicBlueRPC.uuids_to_handle.items():
                    if k == key or (key[0] == "" and k[1] == key[1]):
                        handle = v
                if notif_callback and handle:
                    asyncio.get_running_loop().call_soon_threadsafe(
                        notif_callback, handle, bytearray(resp.data)
                    )

    @grpc_error_as_bleak_error
    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | uuid.UUID,
        callback: NotifyCallback,
        **kwargs: Any,
    ) -> None:
        """Activate notifications/indications on a characteristic.

        Callbacks must accept two inputs. The first will be a integer handle of the
        characteristic generating the data and the second will be a ``bytearray``
        containing the data sent from the connected server.

        .. code-block:: python
            def callback(sender: int, data: bytearray):
                print(f"{sender}: {data}")
            client.start_notify(char_uuid, callback)

        Args:
            characteristic (BleakGATTCharacteristic):
                The characteristic to activate notifications/indications on a
                characteristic, specified by either integer handle, UUID or
                directly by the BleakGATTCharacteristic object representing it.
            callback (function): The function to be called on notification.
            kwargs: Unused.
        """
        characteristic = self._resolve_characteristic(char_specifier)

        if not self._notif_handler:
            self._notif_handler = asyncio.create_task(self._notify_handler())

        resp = await self._client.BLENotification(
            gatt_pb2.BLENotificationRequest(
                device=self._device,
                service_uuid=characteristic.service_uuid,
                uuid=characteristic.uuid,
                subscribe=True,
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp)
        if resp.code == common_pb2.ERROR_CODE_OK:
            self._notif_map[
                (characteristic.service_uuid, characteristic.uuid)
            ] = lambda handle, data: callback(data)
        else:
            raise BleakError(
                "An error occured while subscribing to notification of device {0}: {1} (code: {2}).".format(
                    self.address, resp.message, resp.code
                )
            )

    @grpc_error_as_bleak_error
    async def stop_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | uuid.UUID,
    ) -> None:
        """Deactivate notification/indication on a specified characteristic.

        Args:
            char_specifier (BleakGATTCharacteristic, int, str or UUID):
                The characteristic to deactivate notification/indication on,
                specified by either integer handle, UUID or directly by the
                BleakGATTCharacteristic object representing it.
        """
        characteristic = self._resolve_characteristic(char_specifier)

        resp = await self._client.BLENotification(
            gatt_pb2.BLENotificationRequest(
                device=self._device,
                service_uuid=characteristic.service_uuid,
                uuid=characteristic.uuid,
                subscribe=False,
            ),
            timeout=self._timeout,
        )
        self._check_resp(resp)
        if resp.code == common_pb2.ERROR_CODE_OK:
            del self._notif_map[(characteristic.service_uuid, characteristic.uuid)]
        else:
            raise BleakError(
                "An error occured while unsubscribing from notification of device {0}: {1} (code: {2}).".format(
                    self.address, resp.message, resp.code
                )
            )

    def __del__(self):
        if self._is_connected:
            asyncio.get_running_loop().call_soon_threadsafe(self.disconnect)
        if self._notif_handler:
            self._notif_handler.cancel()
        if self._disconnect_handler:
            self._disconnect_handler.cancel()
