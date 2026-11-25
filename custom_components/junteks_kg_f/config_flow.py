"""Config flow for Junteks KG-F Coulomb Meter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN


class JunteksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Junteks KG-F."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return JunteksOptionsFlow()

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        assert self._discovery_info is not None
        name = self._discovery_info.name or self._discovery_info.address

        if user_input is not None:
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: self._discovery_info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a discovered device or enter MAC."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            info = self._discovered_devices.get(address)
            title = info.name if info and info.name else f"Junteks KG-F ({address})"
            return self.async_create_entry(
                title=title,
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current_addresses:
                continue
            self._discovered_devices[info.address] = info

        if self._discovered_devices:
            # Sort matching names (BTG / KG) to the top
            sorted_items = sorted(
                self._discovered_devices.items(),
                key=lambda item: (
                    0
                    if (item[1].name or "").startswith(("BTG", "KG"))
                    else 1,
                    item[1].name or item[0],
                ),
            )
            choices = {
                addr: f"{info.name or 'Unknown'} ({addr}) [RSSI: {info.rssi}]"
                for addr, info in sorted_items
            }
            schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)})
        else:
            schema = vol.Schema({vol.Required(CONF_ADDRESS): str})

        return self.async_show_form(step_id="user", data_schema=schema)


class JunteksOptionsFlow(OptionsFlow):
    """Handle options flow for Junteks KG-F."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
