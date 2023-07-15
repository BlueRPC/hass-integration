"""Adds config flow for BlueRPC Integration"""
from typing import Any, Dict, Optional

import grpc
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from .const import DEFAULT_PORT, DOMAIN
from .rpc import common_pb2, services_pb2_grpc


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
            self.data[CONF_NAME] = user_input.get(CONF_NAME) or self.data[
                CONF_HOST
            ] + ":" + str(self.data[CONF_PORT])
            if not (await self._check_id()):
                return self.async_abort(reason="cannot_connect")
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
                }
            ),
            errors={},
        )

    async def _check_id(self):
        """Try to connect and get a unique id"""
        try:
            chan = grpc.aio.insecure_channel(
                f"{self.data[CONF_HOST]}:{self.data[CONF_PORT]}"
            )
            client = services_pb2_grpc.BlueRPCStub(chan)
            settings = await client.Hello(
                common_pb2.HelloRequest(name="HomeAssistant", version="1.0")
            )
        except Exception:
            return False
        finally:
            await chan.close()

        await self.async_set_unique_id(settings.uid)
        self._abort_if_unique_id_configured(updates=self.data)
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
