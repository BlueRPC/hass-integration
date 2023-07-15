"""BleakGATTCharacteristicBlueRPC."""
from __future__ import annotations

import contextlib
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.descriptor import BleakGATTDescriptor

from .rpc import gatt_pb2

PROPERTY_MAP = {
    gatt_pb2.BLE_CHR_PROPERTY_READ: "read",
    gatt_pb2.BLE_CHR_PROPERTY_WRITE: "write",
    gatt_pb2.BLE_CHR_PROPERTY_NOTIFY: "notify",
    gatt_pb2.BLE_CHR_PROPERTY_BROADCAST: "broadcast",
    gatt_pb2.BLE_CHR_PROPERTY_EXTENDED_PROPS: "extended-properties",
    gatt_pb2.BLE_CHR_PROPERTY_INDICATE: "indicate",
    gatt_pb2.BLE_CHR_PROPERTY_SIGNED_WRITE: "authenticated-signed-writes",
    gatt_pb2.BLE_CHR_PROPERTY_WRITE_NO_RESPONSE: "write-without-response",
}


class BleakGATTCharacteristicBlueRPC(BleakGATTCharacteristic):
    """GATT Characteristic implementation for the BlueRPC backend."""

    uuids_to_handle = {}
    handle_cpt = 0

    def __init__(
        self,
        obj: gatt_pb2.BLECharacteristic,
        max_write_without_response_size: int,
        service_uuid: str,
        service_handle: int,
    ) -> None:
        """Init a BleakGATTCharacteristicBlueRPC."""
        super().__init__(obj, max_write_without_response_size)
        self.__descriptors: list[BleakGATTDescriptor] = []
        self.__service_uuid: str = service_uuid
        self.__service_handle: int = service_handle
        self.__props: list[str] = [PROPERTY_MAP[x] for x in obj.properties]
        self.__handle: int = BleakGATTCharacteristicBlueRPC.handle_cpt
        BleakGATTCharacteristicBlueRPC.uuids_to_handle[
            (service_uuid, obj.uuid)
        ] = self.__handle
        BleakGATTCharacteristicBlueRPC.handle_cpt += 1

    @property
    def service_uuid(self) -> str:
        """Uuid of the Service containing this characteristic."""
        return self.__service_uuid

    @property
    def service_handle(self) -> int:
        """Integer handle of the Service containing this characteristic."""
        return self.__service_handle

    @property
    def handle(self) -> int:
        """Integer handle for this characteristic."""
        return self.__handle

    @property
    def uuid(self) -> str:
        """Uuid of this characteristic."""
        return self.obj.uuid

    @property
    def properties(self) -> list[str]:
        """Properties of this characteristic."""
        return self.__props

    @property
    def descriptors(self) -> list[BleakGATTDescriptor]:
        """List of descriptors for this service."""
        return self.__descriptors

    def get_descriptor(self, specifier: int | str | UUID) -> BleakGATTDescriptor | None:
        """Get a descriptor by handle (int) or UUID (str or uuid.UUID)."""
        with contextlib.suppress(StopIteration):
            if isinstance(specifier, int):
                return next(filter(lambda x: x.handle == specifier, self.descriptors))
            return next(filter(lambda x: x.uuid == str(specifier), self.descriptors))
        return None

    def add_descriptor(self, descriptor: BleakGATTDescriptor) -> None:
        """Add a :py:class:`~BleakGATTDescriptor` to the characteristic.

        Should not be used by end user, but rather by `bleak` itself.
        """
        self.__descriptors.append(descriptor)
