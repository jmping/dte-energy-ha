"""Sensor platform for DTE Energy integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SERVICE_TYPE, SERVICE_TYPE_ELECTRIC, SERVICE_TYPE_GAS
from .coordinator import DTEEnergyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DTE Energy sensors based on a config entry."""
    coordinator: DTEEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    service_type = entry.data.get(CONF_SERVICE_TYPE)

    entities: list[SensorEntity] = []

    if service_type == SERVICE_TYPE_ELECTRIC:
        entities.append(DTEElectricMeterSensor(coordinator, entry))
    elif service_type == SERVICE_TYPE_GAS:
        entities.append(DTEGasMeterSensor(coordinator, entry))

    async_add_entities(entities)


class DTEBaseSensor(CoordinatorEntity[DTEEnergyCoordinator], SensorEntity):
    """Base class for DTE Energy sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: DTEEnergyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="DTE Energy",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("total_usage")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.coordinator.data:
            return {}

        attrs = {
            "reading_count": self.coordinator.data.get("reading_count"),
        }

        latest = self.coordinator.data.get("latest_reading")
        if latest:
            attrs["latest_reading_value"] = latest.get("value")
            attrs["latest_reading_time"] = latest.get("start_time")

        return attrs


class DTEElectricMeterSensor(DTEBaseSensor):
    """Sensor for DTE Electric meter readings."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        coordinator: DTEEnergyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the electric sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_electric_meter"
        self._attr_name = "Electric Meter"


class DTEGasMeterSensor(DTEBaseSensor):
    """Sensor for DTE Gas meter readings."""

    _attr_device_class = SensorDeviceClass.GAS
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_FEET
    _attr_icon = "mdi:fire"

    def __init__(
        self,
        coordinator: DTEEnergyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the gas sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_gas_meter"
        self._attr_name = "Gas Meter"
