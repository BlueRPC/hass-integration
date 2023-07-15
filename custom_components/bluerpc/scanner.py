"""Bluetooth scanner for BlueRPC."""
from __future__ import annotations

import asyncio
import logging

import grpc
from homeassistant.components.bluetooth import BaseHaRemoteScanner
from homeassistant.core import callback
from homeassistant.loader import async_get_bluetooth

from .rpc import common_pb2, gatt_pb2, services_pb2_grpc

_LOGGER = logging.getLogger(__name__)


class BlueRPCScanner(BaseHaRemoteScanner):
    """Scanner for BluerPC."""

    _on_disconnect = None

    async def _get_services(self):
        """Get all service uuids defined in Home Assistant (for devices with required filters)"""
        svc = set()
        for i in await async_get_bluetooth(self.hass):
            if "service_data_uuid" in i:
                svc.add(i["service_data_uuid"])
            if "service_uuid" in i:
                svc.add(i["service_uuid"])
        return svc

    def on_disconnect(self, fun):
        """Set the callback to be called on disconnect"""
        self._on_disconnect = fun

    async def start(
        self, client: services_pb2_grpc.BlueRPCStub, filters_required: bool
    ) -> bool:
        """Start the scanner"""
        self._client = client

        try:
            f = []
            if filters_required:
                for i in await self._get_services():
                    f.append(
                        gatt_pb2.BLEScanFilter(
                            type=gatt_pb2.BLE_SCAN_FILTER_TYPE_UUID, value=i
                        )
                    )

            resp = await client.BLEScanStart(
                gatt_pb2.BLEScanRequest(interval=2000, active=True, filters=f, merge_filters=filters_required)
            )
            if (
                resp.code == common_pb2.ERROR_CODE_OK
                or resp.code == common_pb2.ERROR_CODE_SCAN_ALREADY_RUNNING
            ):
                asyncio.create_task(self._scan_handler())
                return True
            else:
                _LOGGER.error(
                    f"scanner connect error: {resp.message} (code {resp.code})"
                )
        except grpc.aio._call.AioRpcError as e:
            _LOGGER.error(str(e))

        return False

    async def stop(self):
        """Stop the scanner"""
        if self._client is not None:
            try:
                await self._client.BLEScanStop(common_pb2.Void())
            except grpc.aio._call.AioRpcError as e:
                _LOGGER.error(str(e))
            finally:
                if self._on_disconnect is not None:
                    self._on_disconnect()

    async def _scan_handler(self):
        """Background task to receive the bluetooth advertisements"""
        try:
            async for response in self._client.BLEReceiveScan(common_pb2.Void()):
                if response.status.code == common_pb2.ERROR_CODE_SCAN_STOPPED:
                    # auto restart ?
                    await self.stop()
                    break
                elif response.status.code == common_pb2.ERROR_CODE_OK:
                    self._advertisement(response)
                else:
                    _LOGGER.warning(
                        f"scanner adv error: {response.status.message} (code {response.status.code})"
                    )
        except grpc.aio._call.AioRpcError as e:
            _LOGGER.error(str(e))
            await self.stop()

    @callback
    def _advertisement(self, resp: gatt_pb2.BLEScanResponse) -> None:
        """Call the registered callback."""
        service_data: dict[str, bytes] = {}
        manufacturer_data: dict[int, bytes] = {}

        for i in resp.service_data:
            service_data[i.uuid] = bytes(i.value)
        for i in resp.manufacturer_data:
            manufacturer_data[i.uuid] = bytes(i.value)

        self._async_on_advertisement(
            resp.device.mac,
            resp.rssi,
            resp.name,
            list(resp.service_uuids),
            service_data,
            manufacturer_data,
            resp.txpwr,
            {},
        )
