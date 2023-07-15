"""The BlueRPC Bluetooth Integration"""
import logging
from collections.abc import Callable
from functools import partial

import grpc
from homeassistant.components.bluetooth import (
    HaBluetoothConnector,
    async_get_advertisement_callback,
    async_register_scanner,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.core import callback as hass_callback

from .client import BlueRPCClient
from .const import DOMAIN, STARTUP_MESSAGE
from .rpc import common_pb2, services_pb2_grpc
from .scanner import BlueRPCScanner

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the bluerpc component."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    try:
        client = services_pb2_grpc.BlueRPCStub(
            grpc.aio.insecure_channel(f"{host}:{port}")
        )
        settings = await client.Hello(
            common_pb2.HelloRequest(name="HomeAssistant", version="1.0")
        )
        _LOGGER.info(
            f"connected to {settings.name} v{settings.version} ({settings.operating_system}: {settings.operating_system_version})"
        )
        if common_pb2.WORKER_MODE_GATT_PASSIVE not in settings.supported_modes:
            _LOGGER.error("scanning not supported by this worker")
            return False
        if not await async_connect_scanner(hass, entry, client, settings):
            return False
    except Exception as e:
        _LOGGER.error(str(e))
        return False

    return True


@hass_callback
def _async_can_connect_factory(
    client: services_pb2_grpc.BlueRPCStub,
) -> Callable[[], bool]:
    """Create a can_connect function for a specific RuntimeEntryData instance."""

    @hass_callback
    def _async_can_connect() -> bool:
        """Check if a given source can make another connection."""
        return True
        try:
            resp = client.BLEGetDevices(common_pb2.Void())
            assert resp.status.code == common_pb2.ERROR_CODE_OK
            assert (
                resp.max_connections == 0
                or resp.connected_devices < resp.max_connections
            )
            return True
        except Exception as e:
            _LOGGER.error(str(e))
            return False

    return _async_can_connect


async def async_connect_scanner(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: services_pb2_grpc.BlueRPCStub,
    settings: common_pb2.HelloResponse,
) -> bool:
    """Connect scanner."""
    assert entry.data.get(CONF_NAME) is not None
    source = entry.data.get(CONF_NAME)
    new_info_callback = async_get_advertisement_callback(hass)
    connector = HaBluetoothConnector(
        # MyPy doesn't like partials, but this is correct
        # https://github.com/python/mypy/issues/1484
        client=partial(BlueRPCClient, client=client),  # type: ignore[arg-type]
        source=source,
        can_connect=_async_can_connect_factory(client),
    )
    connectable = common_pb2.WORKER_MODE_GATT_ACTIVE in settings.supported_modes
    if not connectable:
        _LOGGER.info("connection not supported by this worker")
        return False
    scanner = BlueRPCScanner(
        hass, source, entry.title, new_info_callback, connector, connectable
    )
    if not await scanner.start(client, settings.ble_filters_required):
        return False
    unload_callbacks = [
        async_register_scanner(hass, scanner, True),
        scanner.async_setup(),
    ]

    @hass_callback
    def _async_unload() -> None:
        for callback in unload_callbacks:
            callback()

    scanner.on_disconnect(_async_unload)

    return True
