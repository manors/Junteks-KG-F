"""Button platform for Junteks KG-F Coulomb Meter."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import JunteksCoordinator
from .const import DOMAIN
from .protocol import build_binary_command


@dataclass(frozen=True, kw_only=True)
class JunteksButtonEntityDescription(ButtonEntityDescription):
    """Describes a Junteks KG-F button entity."""

    binary_cmd: bytes
    ascii_cmd: bytes


BUTTON_DESCRIPTIONS: tuple[JunteksButtonEntityDescription, ...] = (
    JunteksButtonEntityDescription(
        key="zero_current",
        translation_key="zero_current",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:numeric-0-circle-outline",
        binary_cmd=build_binary_command(99, 164),
        ascii_cmd=b":W61=1,2,1,\r\n",
    ),
    JunteksButtonEntityDescription(
        key="clear_data",
        translation_key="clear_data",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:delete-sweep-outline",
        binary_cmd=build_binary_command(0, 163),
        ascii_cmd=b":W62=1,2,1,\r\n",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Junteks KG-F button entities."""
    coordinator: JunteksCoordinator = hass.data[DOMAIN][entry.entry_id]
    address: str = entry.data[CONF_ADDRESS]

    async_add_entities(
        JunteksButtonEntity(coordinator, description, address, entry.title)
        for description in BUTTON_DESCRIPTIONS
    )


class JunteksButtonEntity(CoordinatorEntity[JunteksCoordinator], ButtonEntity):
    """Representation of a Junteks KG-F button."""

    entity_description: JunteksButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: JunteksCoordinator,
        description: JunteksButtonEntityDescription,
        address: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=device_name,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_send_command(
            self.entity_description.binary_cmd,
            self.entity_description.ascii_cmd,
        )
