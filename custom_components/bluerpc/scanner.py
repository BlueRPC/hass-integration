"""Bluetooth scanner for BlueRPC."""
from __future__ import annotations

import logging

from bluerpc_client import BlueRPCBLEAdvertisement, BlueRPCBLEScanner
from homeassistant.components.bluetooth import BaseHaRemoteScanner
from homeassistant.core import callback
from homeassistant.loader import async_get_bluetooth

_LOGGER = logging.getLogger(__name__)


class BlueRPCScannerHA(BaseHaRemoteScanner):
    """Scanner for BluerPC."""

    _on_disconnect = None
    _scanner = None

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

    async def start(self, client) -> bool:
        """Start the scanner"""
        svc_filters = []
        # only set filters if this is required by the worker (ex: android)
        if client.settings.ble_filters_required:
            svc_filters = await self._get_services()

        self._scanner = BlueRPCBLEScanner(
            client,
            self._advertisement,
            self._on_disconnect,
            svc_filters,
            True,
        )
        return (await self._scanner.start())

    async def stop(self):
        """Stop the scanner"""
        if self._scanner is not None:
            await self._scanner.stop()

    @callback
    def _advertisement(self, adv: BlueRPCBLEAdvertisement) -> None:
        """Call the registered callback."""
        self._async_on_advertisement(
            adv.mac_address,
            adv.rssi,
            adv.name,
            adv.service_uuids,
            adv.service_data,
            adv.manufacturer_data,
            adv.txpwr,
            {},
        )
