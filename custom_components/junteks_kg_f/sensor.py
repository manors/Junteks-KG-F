"""Sensor platform for Junteks KG-F Coulomb Meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ADDRESS,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import JunteksCoordinator
from .const import DOMAIN
from .protocol import JunteksData


@dataclass(frozen=True, kw_only=True)
class JunteksSensorEntityDescription(SensorEntityDescription):
    """Describes a Junteks KG-F sensor entity."""

    value_fn: Callable[[JunteksData], Any]


SENSOR_DESCRIPTIONS: tuple[JunteksSensorEntityDescription, ...] = (
    JunteksSensorEntityDescription(
        key="voltage",
        translation_key="voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.voltage_v,
    ),
    JunteksSensorEntityDescription(
        key="current",
        translation_key="current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.current_a,
    ),
    JunteksSensorEntityDescription(
        key="power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.power_w,
    ),
    JunteksSensorEntityDescription(
        key="soc",
        translation_key="soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.soc_percent,
    ),
    JunteksSensorEntityDescription(
        key="remaining_capacity",
        translation_key="remaining_capacity",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        icon="mdi:battery-charging",
        value_fn=lambda d: d.remaining_capacity_ah,
    ),
    JunteksSensorEntityDescription(
        key="preset_capacity",
        translation_key="preset_capacity",
        native_unit_of_measurement="Ah",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        icon="mdi:battery-high",
        value_fn=lambda d: d.preset_capacity_ah,
    ),
    JunteksSensorEntityDescription(
        key="cumulative_capacity",
        translation_key="cumulative_capacity",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        icon="mdi:counter",
        value_fn=lambda d: d.cumulative_capacity_ah,
    ),
    JunteksSensorEntityDescription(
        key="energy",
        translation_key="energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=5,
        value_fn=lambda d: d.energy_kwh,
    ),
    JunteksSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.temperature_c,
    ),
    JunteksSensorEntityDescription(
        key="runtime",
        translation_key="runtime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.runtime_s,
    ),
    JunteksSensorEntityDescription(
        key="remaining_time",
        translation_key="remaining_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.remaining_time_min,
    ),
    JunteksSensorEntityDescription(
        key="internal_resistance",
        translation_key="internal_resistance",
        native_unit_of_measurement="mΩ",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:omega",
        value_fn=lambda d: d.internal_resistance_mohm,
    ),
    JunteksSensorEntityDescription(
        key="output_state",
        translation_key="output_state",
        icon="mdi:electric-switch",
        value_fn=lambda d: d.output_state,
    ),
    JunteksSensorEntityDescription(
        key="current_direction",
        translation_key="current_direction",
        icon="mdi:swap-horizontal",
        value_fn=lambda d: d.direction,
    ),
    JunteksSensorEntityDescription(
        key="protocol_mode",
        translation_key="protocol_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:protocol",
        value_fn=lambda d: d.protocol_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Junteks KG-F sensors from a config entry."""
    coordinator: JunteksCoordinator = hass.data[DOMAIN][entry.entry_id]
    address: str = entry.data[CONF_ADDRESS]

    async_add_entities(
        JunteksSensorEntity(coordinator, description, address, entry.title)
        for description in SENSOR_DESCRIPTIONS
    )


class JunteksSensorEntity(
    CoordinatorEntity[JunteksCoordinator], SensorEntity
):
    """Representation of a Junteks KG-F sensor."""

    entity_description: JunteksSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: JunteksCoordinator,
        description: JunteksSensorEntityDescription,
        address: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._address = address
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=device_name,
            manufacturer="Junteks",
            model=coordinator.data.model if coordinator.data else "KG-F",
            sw_version=(
                str(coordinator.data.firmware_version)
                if coordinator.data and coordinator.data.firmware_version is not None
                else None
            ),
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
