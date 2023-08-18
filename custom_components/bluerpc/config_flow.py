"""Adds config flow for BlueRPC Integration"""
import base64
import json
from typing import Any, Dict, Optional

import voluptuous as vol
from bluerpc_client import (
    BlueRPC,
    create_certs,
    create_keystore,
    load_certs,
    serialize_certs,
)
from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.storage import STORAGE_DIR

from .const import (
    CERT_DEFAULT_KEY_SIZE,
    CERT_DEFAULT_ORGANIZATION,
    CERT_DEFAULT_VALIDITY,
    CONF_ENCRYPTED,
    CONF_ENCRYPTION_PASSWORD,
    DEFAULT_PORT,
    DOMAIN,
)


class BlueRPCFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for BlueRPC."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize."""
        self.data = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Handle a flow initialized by the user."""
        if user_input is None:
            user_input = {}

        if CONF_HOST in user_input and CONF_PORT in user_input:
            self.data[CONF_HOST] = user_input[CONF_HOST]
            self.data[CONF_PORT] = user_input[CONF_PORT]
            self.data[CONF_ENCRYPTION_PASSWORD] = (
                user_input[CONF_ENCRYPTION_PASSWORD] or ""
            )
            self.data[CONF_NAME] = user_input.get(CONF_NAME) or self.data[
                CONF_HOST
            ] + ":" + str(self.data[CONF_PORT])

            if not (await self._check_id()):
                return self.async_abort(reason="cannot_connect")

            if (
                CONF_ENCRYPTION_PASSWORD in user_input
                and user_input[CONF_ENCRYPTION_PASSWORD] != ""
            ):
                self.data[CONF_ENCRYPTED] = await self._setup_encryption(
                    user_input[CONF_ENCRYPTION_PASSWORD]
                )
            else:
                self.data[CONF_ENCRYPTED] = False

            return self.async_create_entry(title=self.data[CONF_NAME], data=self.data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self.data.get(CONF_HOST)): str,
                    vol.Required(
                        CONF_PORT, default=self.data.get(CONF_PORT) or DEFAULT_PORT
                    ): int,
                    vol.Optional(CONF_NAME, default=self.data.get(CONF_NAME)): str,
                    vol.Optional(CONF_ENCRYPTION_PASSWORD, default=""): str,
                }
            ),
            errors={},
        )

    async def _check_id(self):
        """Try to connect with an insecure connection and get a unique id"""
        try:
            client = BlueRPC(
                self.data[CONF_HOST],
                self.data[CONF_PORT],
                None,
                None,
                None,
                "homeassistant",
                False,
                None,
                None,
            )
            await client.connect()
            await self.async_set_unique_id(client.settings.uid)
            self._abort_if_unique_id_configured(updates=self.data)
        except Exception:
            return False
        finally:
            await client.stop()

        return True

    async def async_step_zeroconf(self, discovery_info: zeroconf.ZeroconfServiceInfo):
        """Initialize flow from zeroconf."""
        self.data[CONF_HOST] = discovery_info.host
        self.data[CONF_PORT] = discovery_info.port
        self.data[CONF_NAME] = discovery_info.properties.get("name") or self.data[
            CONF_HOST
        ] + ":" + str(self.data[CONF_PORT])
        await self.async_set_unique_id(discovery_info.properties.get("uid"))
        self._abort_if_unique_id_configured(updates=self.data)
        return await self.async_step_user()

    async def _setup_encryption(self, keystore_password: str):
        # get or create encryption keys
        keys_path = self.hass.config.path(STORAGE_DIR, "bluerpc.json")
        keys_data = {}
        try:
            with open(keys_path, "r") as f:
                keys_data = json.load(f)
        except FileNotFoundError:
            pass

        country = self.hass.config.country
        cn = self.hass.config.internal_url or self.hass.config.external_url or "*"

        # if certificate authority doesn't exists, create it and create hass certs
        if "ca" not in keys_data:
            ca_key, ca_cert = create_certs(
                country=country,
                common_name=cn,
                organization=CERT_DEFAULT_ORGANIZATION,
                validity=CERT_DEFAULT_VALIDITY,
                key_size=CERT_DEFAULT_KEY_SIZE,
                signing_key=None,
            )
            keys_data["ca"] = [
                base64.b64encode(serialize_certs(ca_key)).decode("utf-8"),
                base64.b64encode(serialize_certs(ca_cert)).decode("utf-8"),
            ]

            hass_key, hass_cert = create_certs(
                country=country,
                common_name=cn,
                organization=CERT_DEFAULT_ORGANIZATION,
                validity=CERT_DEFAULT_VALIDITY,
                key_size=CERT_DEFAULT_KEY_SIZE,
                signing_key=ca_key,
                issuer_cert=ca_cert,
            )
            keys_data["hass"] = [
                base64.b64encode(serialize_certs(hass_key)).decode("utf-8"),
                base64.b64encode(serialize_certs(hass_cert)).decode("utf-8"),
            ]

            with open(keys_path, "w+") as f:
                json.dump(keys_data, f)
        else:
            ca_key, ca_cert = load_certs(
                base64.b64decode(keys_data["ca"][0]),
                base64.b64decode(keys_data["ca"][1]),
            )
            hass_key, hass_cert = load_certs(
                base64.b64decode(keys_data["hass"][0]),
                base64.b64decode(keys_data["hass"][1]),
            )

        # create worker keystore
        worker_key, worker_cert = create_certs(
            country=country,
            common_name=self.data[CONF_HOST],
            organization=CERT_DEFAULT_ORGANIZATION,
            validity=CERT_DEFAULT_VALIDITY,
            key_size=CERT_DEFAULT_KEY_SIZE,
            signing_key=ca_key,
            issuer_cert=ca_cert,
        )
        worker_keystore = create_keystore(
            worker_key, worker_cert, ca_cert, keystore_password
        )

        client = BlueRPC(
            self.data[CONF_HOST],
            self.data[CONF_PORT],
            None,
            None,
            None,
            "homeassistant",
            False,
            None,
            None,
        )
        await client.connect()
        return await client.set_keystore(worker_keystore, True, True)
