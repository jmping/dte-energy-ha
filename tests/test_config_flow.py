"""Tests for DTE Energy config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dte_energy.const import (
    DOMAIN,
    CONF_USAGE_LINK,
    CONF_SERVICE_TYPE,
    SERVICE_TYPE_ELECTRIC,
    SERVICE_TYPE_GAS,
)
from custom_components.dte_energy.config_flow import (
    DTEEnergyConfigFlow,
    _validate_link_format,
)


class TestLinkFormatValidation:
    """Test usage link format validation."""

    def test_valid_link_format(self):
        """Test valid DTE usage link format."""
        valid_link = "https://usagedata.dteenergy.com/link/12345678-1234-1234-1234-123456789abc"
        assert _validate_link_format(valid_link) is True

    def test_valid_link_with_whitespace(self):
        """Test valid link with surrounding whitespace."""
        valid_link = "  https://usagedata.dteenergy.com/link/12345678-1234-1234-1234-123456789abc  "
        assert _validate_link_format(valid_link) is True

    def test_invalid_link_wrong_domain(self):
        """Test invalid link with wrong domain."""
        invalid_link = "https://example.com/link/12345678-1234-1234-1234-123456789abc"
        assert _validate_link_format(invalid_link) is False

    def test_invalid_link_wrong_path(self):
        """Test invalid link with wrong path."""
        invalid_link = "https://usagedata.dteenergy.com/other/12345678-1234-1234-1234-123456789abc"
        assert _validate_link_format(invalid_link) is False

    def test_invalid_link_http(self):
        """Test that HTTP links are rejected (must be HTTPS)."""
        invalid_link = "http://usagedata.dteenergy.com/link/12345678-1234-1234-1234-123456789abc"
        assert _validate_link_format(invalid_link) is False

    def test_invalid_link_no_uuid(self):
        """Test invalid link without UUID."""
        invalid_link = "https://usagedata.dteenergy.com/link/"
        assert _validate_link_format(invalid_link) is False


class TestConfigFlow:
    """Test config flow."""

    @pytest.mark.asyncio
    async def test_form_shows_on_init(self, hass: HomeAssistant):
        """Test that the form is shown on initialization."""
        flow = DTEEnergyConfigFlow()
        flow.hass = hass

        result = await flow.async_step_user()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_successful_electric_setup(self, hass: HomeAssistant, electric_usage_xml: str):
        """Test successful setup with electric link."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=electric_usage_xml)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            flow = DTEEnergyConfigFlow()
            flow.hass = hass
            flow._async_abort_entries_match = lambda x: None

            result = await flow.async_step_user({
                CONF_USAGE_LINK: "https://usagedata.dteenergy.com/link/12345678-1234-1234-1234-123456789abc"
            })

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["title"] == "DTE Electric"
            assert result["data"][CONF_SERVICE_TYPE] == SERVICE_TYPE_ELECTRIC

    @pytest.mark.asyncio
    async def test_successful_gas_setup(self, hass: HomeAssistant, gas_usage_xml: str):
        """Test successful setup with gas link."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=gas_usage_xml)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            flow = DTEEnergyConfigFlow()
            flow.hass = hass
            flow._async_abort_entries_match = lambda x: None

            result = await flow.async_step_user({
                CONF_USAGE_LINK: "https://usagedata.dteenergy.com/link/87654321-4321-4321-4321-cba987654321"
            })

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["title"] == "DTE Gas"
            assert result["data"][CONF_SERVICE_TYPE] == SERVICE_TYPE_GAS

    @pytest.mark.asyncio
    async def test_invalid_link_format_error(self, hass: HomeAssistant):
        """Test error on invalid link format."""
        flow = DTEEnergyConfigFlow()
        flow.hass = hass

        result = await flow.async_step_user({
            CONF_USAGE_LINK: "https://example.com/invalid"
        })

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_link"}

    @pytest.mark.asyncio
    async def test_connection_error(self, hass: HomeAssistant):
        """Test error when connection fails."""
        mock_response = AsyncMock()
        mock_response.status = 500

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            flow = DTEEnergyConfigFlow()
            flow.hass = hass

            result = await flow.async_step_user({
                CONF_USAGE_LINK: "https://usagedata.dteenergy.com/link/12345678-1234-1234-1234-123456789abc"
            })

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "cannot_connect"}
