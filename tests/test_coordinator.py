"""Tests for DTE Energy coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.dte_energy.coordinator import (
    DTEEnergyCoordinator,
    validate_usage_link,
)
from custom_components.dte_energy.const import SERVICE_TYPE_ELECTRIC, SERVICE_TYPE_GAS


class TestGreenButtonXMLParsing:
    """Test Green Button XML parsing."""

    def test_parse_electric_data(self, electric_usage_xml: str):
        """Test parsing electric usage XML."""
        coordinator = DTEEnergyCoordinator(
            hass=MagicMock(),
            usage_link="https://usagedata.dteenergy.com/link/test-uuid",
        )

        result = coordinator._parse_green_button_xml(electric_usage_xml)

        assert result["service_type"] == SERVICE_TYPE_ELECTRIC
        assert result["unit"] == "kWh"
        assert result["reading_count"] == 3
        # Values are 1500, 1200, 800 with powerOfTenMultiplier=-3 (divide by 1000)
        # Total = (1500 + 1200 + 800) * 0.001 = 3.5 kWh
        assert result["total_usage"] == 3.5

    def test_parse_gas_data(self, gas_usage_xml: str):
        """Test parsing gas usage XML."""
        coordinator = DTEEnergyCoordinator(
            hass=MagicMock(),
            usage_link="https://usagedata.dteenergy.com/link/test-uuid",
        )

        result = coordinator._parse_green_button_xml(gas_usage_xml)

        assert result["service_type"] == SERVICE_TYPE_GAS
        assert result["unit"] == "ft³"
        assert result["reading_count"] == 3
        # Values are 3, 4, 5 CCF, converted to cubic feet (x100)
        # Total = (3 + 4 + 5) * 100 = 1200 cubic feet
        assert result["total_usage"] == 1200

    def test_readings_sorted_by_time(self, electric_usage_xml: str):
        """Test that readings are sorted by start time."""
        coordinator = DTEEnergyCoordinator(
            hass=MagicMock(),
            usage_link="https://usagedata.dteenergy.com/link/test-uuid",
        )

        result = coordinator._parse_green_button_xml(electric_usage_xml)

        # Latest reading should be the one with highest start time
        assert result["latest_reading"]["start_time"] == 1704074400

    def test_service_type_detection_from_commodity(self, electric_usage_xml: str):
        """Test service type detection from commodity element."""
        coordinator = DTEEnergyCoordinator(
            hass=MagicMock(),
            usage_link="https://usagedata.dteenergy.com/link/test-uuid",
        )

        coordinator._parse_green_button_xml(electric_usage_xml)

        assert coordinator.service_type == SERVICE_TYPE_ELECTRIC


class TestCoordinatorDataFetching:
    """Test coordinator data fetching."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, electric_usage_xml: str):
        """Test successful data fetch."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=electric_usage_xml)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            coordinator = DTEEnergyCoordinator(
                hass=MagicMock(),
                usage_link="https://usagedata.dteenergy.com/link/test-uuid",
            )

            result = await coordinator._async_update_data()

            assert result["service_type"] == SERVICE_TYPE_ELECTRIC
            assert result["total_usage"] == 3.5

    @pytest.mark.asyncio
    async def test_http_error(self):
        """Test handling of HTTP errors."""
        mock_response = AsyncMock()
        mock_response.status = 404

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            coordinator = DTEEnergyCoordinator(
                hass=MagicMock(),
                usage_link="https://usagedata.dteenergy.com/link/test-uuid",
            )

            from homeassistant.helpers.update_coordinator import UpdateFailed
            with pytest.raises(UpdateFailed, match="HTTP 404"):
                await coordinator._async_update_data()


class TestValidateUsageLink:
    """Test usage link validation."""

    @pytest.mark.asyncio
    async def test_validate_electric_link(self, electric_usage_xml: str):
        """Test validating an electric usage link."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=electric_usage_xml)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await validate_usage_link(
                hass=MagicMock(),
                usage_link="https://usagedata.dteenergy.com/link/test-uuid",
            )

            assert result["service_type"] == SERVICE_TYPE_ELECTRIC
            assert result["unit"] == "kWh"
            assert result["reading_count"] == 3
