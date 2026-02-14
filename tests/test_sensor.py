"""Tests for DTE Energy sensors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume

from custom_components.dte_energy.sensor import (
    DTEElectricMeterSensor,
    DTEGasMeterSensor,
)
from custom_components.dte_energy.coordinator import DTEEnergyCoordinator
from custom_components.dte_energy.const import SERVICE_TYPE_ELECTRIC, SERVICE_TYPE_GAS


class TestElectricSensor:
    """Test electric meter sensor."""

    def test_sensor_attributes(self):
        """Test electric sensor has correct attributes."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {
            "total_usage": 123.456,
            "reading_count": 100,
            "latest_reading": {"value": 1.5, "start_time": 1704074400},
        }

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Electric"

        sensor = DTEElectricMeterSensor(mock_coordinator, mock_entry)

        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
        assert sensor.icon == "mdi:flash"
        assert sensor.unique_id == "test-entry-id_electric_meter"
        assert sensor.name == "Electric Meter"

    def test_sensor_state(self):
        """Test electric sensor state value."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {
            "total_usage": 123.456,
            "reading_count": 100,
            "latest_reading": {"value": 1.5, "start_time": 1704074400},
        }

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Electric"

        sensor = DTEElectricMeterSensor(mock_coordinator, mock_entry)

        assert sensor.native_value == 123.456

    def test_sensor_extra_attributes(self):
        """Test electric sensor extra state attributes."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {
            "total_usage": 123.456,
            "reading_count": 100,
            "latest_reading": {"value": 1.5, "start_time": 1704074400},
        }

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Electric"

        sensor = DTEElectricMeterSensor(mock_coordinator, mock_entry)
        attrs = sensor.extra_state_attributes

        assert attrs["reading_count"] == 100
        assert attrs["latest_reading_value"] == 1.5
        assert attrs["latest_reading_time"] == 1704074400

    def test_sensor_no_data(self):
        """Test electric sensor with no data."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = None

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Electric"

        sensor = DTEElectricMeterSensor(mock_coordinator, mock_entry)

        assert sensor.native_value is None
        assert sensor.extra_state_attributes == {}


class TestGasSensor:
    """Test gas meter sensor."""

    def test_sensor_attributes(self):
        """Test gas sensor has correct attributes."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {
            "total_usage": 500.0,
            "reading_count": 30,
            "latest_reading": {"value": 5.0, "start_time": 1704153600},
        }

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Gas"

        sensor = DTEGasMeterSensor(mock_coordinator, mock_entry)

        assert sensor.device_class == SensorDeviceClass.GAS
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfVolume.CUBIC_FEET
        assert sensor.icon == "mdi:fire"
        assert sensor.unique_id == "test-entry-id_gas_meter"
        assert sensor.name == "Gas Meter"

    def test_sensor_state(self):
        """Test gas sensor state value."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {
            "total_usage": 500.0,
            "reading_count": 30,
            "latest_reading": {"value": 5.0, "start_time": 1704153600},
        }

        mock_entry = MagicMock()
        mock_entry.entry_id = "test-entry-id"
        mock_entry.title = "DTE Gas"

        sensor = DTEGasMeterSensor(mock_coordinator, mock_entry)

        assert sensor.native_value == 500.0


class TestEnergyDashboardCompatibility:
    """Test Energy Dashboard compatibility requirements."""

    def test_electric_sensor_dashboard_compatible(self):
        """Test electric sensor meets Energy Dashboard requirements."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {"total_usage": 100.0}

        mock_entry = MagicMock()
        mock_entry.entry_id = "test"
        mock_entry.title = "DTE Electric"

        sensor = DTEElectricMeterSensor(mock_coordinator, mock_entry)

        # Energy Dashboard requires these specific attributes
        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR

    def test_gas_sensor_dashboard_compatible(self):
        """Test gas sensor meets Energy Dashboard requirements."""
        mock_coordinator = MagicMock(spec=DTEEnergyCoordinator)
        mock_coordinator.data = {"total_usage": 100.0}

        mock_entry = MagicMock()
        mock_entry.entry_id = "test"
        mock_entry.title = "DTE Gas"

        sensor = DTEGasMeterSensor(mock_coordinator, mock_entry)

        # Energy Dashboard requires these specific attributes for gas
        assert sensor.device_class == SensorDeviceClass.GAS
        assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert sensor.native_unit_of_measurement == UnitOfVolume.CUBIC_FEET
