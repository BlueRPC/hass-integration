"""The BlueRPC Bluetooth Integration"""
import base64
import json
import logging
from collections.abc import Callable
from functools import partial

from bluerpc_client import BlueRPC, BlueRPCBleakClient, WorkerMode, load_certs
from homeassistant.components import zeroconf
from homeassistant.components.bluetooth import (
    HaBluetoothConnector,
    async_get_advertisement_callback,
    async_register_scanner,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.core import callback as hass_callback
from homeassistant.helpers.storage import STORAGE_DIR

from .const import CONF_ENCRYPTED, DOMAIN, STARTUP_MESSAGE
from .scanner import BlueRPCScannerHA

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the bluerpc component."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    zeroconf_instance = await zeroconf.async_get_instance(hass)

    try:
        if entry.data.get(CONF_ENCRYPTED):
            with open(hass.config.path(STORAGE_DIR, "bluerpc.json"), "r") as f:
                keys_data = json.load(f)
            _, ca_cert = load_certs(
                None,
                base64.b64decode(keys_data["ca"][1]),
            )
            hass_key, hass_cert = load_certs(
                base64.b64decode(keys_data["ca"][0]),
                base64.b64decode(keys_data["ca"][1]),
            )
            client = BlueRPC(
                host,
                port,
                hass_key,
                hass_cert,
                ca_cert,
                "homeassistant",
                True,
                None,
                zeroconf_instance,
            )
        else:
            client = BlueRPC(
                host,
                port,
                None,
                None,
                None,
                "homeassistant",
                True,
                None,
                zeroconf_instance,
            )
        await client.connect()

        if WorkerMode.WORKER_MODE_GATT_PASSIVE not in client.settings.supported_modes:
            _LOGGER.error("scanning not supported by this worker")
            return False

        if not await async_connect_scanner(hass, entry, client):
            return False
    except Exception as e:
        _LOGGER.error(str(e))
        return False

    return True


@hass_callback
async def _async_can_connect_factory(
    client: BlueRPC,
) -> Callable[[], bool]:
    """Create a can_connect function for a specific RuntimeEntryData instance."""

    @hass_callback
    async def _async_can_connect() -> bool:
        """Check if a given source can make another connection."""
        return client.can_connect()

    return _async_can_connect


async def async_connect_scanner(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: BlueRPC,
) -> bool:
    """Connect scanner."""
    source = entry.data.get(CONF_NAME)
    assert source is not None
    new_info_callback = async_get_advertisement_callback(hass)
    connector = HaBluetoothConnector(
        # MyPy doesn't like partials, but this is correct
        # https://github.com/python/mypy/issues/1484
        client=partial(BlueRPCBleakClient, client=client),  # type: ignore[arg-type]
        source=source,
        can_connect=_async_can_connect_factory(client),
    )
    connectable = WorkerMode.WORKER_MODE_GATT_ACTIVE in client.settings.supported_modes
    if not connectable:
        _LOGGER.info("connection not supported by this worker")
        return False

    scanner = BlueRPCScannerHA(
        hass, source, entry.title, new_info_callback, connector, connectable
    )
    if not await scanner.start(client):
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
