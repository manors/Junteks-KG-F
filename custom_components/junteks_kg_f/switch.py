"""Switch platform for Junteks KG-F Coulomb Meter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import JunteksCoordinator
from .const import DOMAIN
from .protocol import build_binary_command

BINARY_CMD_OUTPUT_ON = build_binary_command(0, 208)
BINARY_CMD_OUTPUT_OFF = build_binary_command(99, 208)
ASCII_CMD_OUTPUT_ON = b":W10=1,2,1,\r\n"
ASCII_CMD_OUTPUT_OFF = b":W10=1,0,0,\r\n"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Junteks KG-F switch entities."""
    coordinator: JunteksCoordinator = hass.data[DOMAIN][entry.entry_id]
    address: str = entry.data[CONF_ADDRESS]
    async_add_entities([JunteksOutputSwitch(coordinator, address, entry.title)])


class JunteksOutputSwitch(CoordinatorEntity[JunteksCoordinator], SwitchEntity):
    """Switch to control output state & data recording on the Junteks KG-F."""

    _attr_has_entity_name = True
    _attr_translation_key = "output"
    _attr_icon = "mdi:power"

    def __init__(
        self,
        coordinator: JunteksCoordinator,
        address: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_output"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=device_name,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if output state is ON (code 0)."""
        if not self.coordinator.data or self.coordinator.data.output_state_code is None:
            return None
        return self.coordinator.data.output_state_code == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn output on."""
        await self.coordinator.async_send_command(
            BINARY_CMD_OUTPUT_ON, ASCII_CMD_OUTPUT_ON
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn output off."""
        await self.coordinator.async_send_command(
            BINARY_CMD_OUTPUT_OFF, ASCII_CMD_OUTPUT_OFF
        )
