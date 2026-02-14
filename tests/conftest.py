"""Fixtures for DTE Energy tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.dte_energy.const import DOMAIN


@pytest.fixture
def hass(event_loop) -> Generator[HomeAssistant, None, None]:
    """Create a Home Assistant instance for testing."""
    hass = HomeAssistant()
    hass.config.components.add("persistent_notification")
    yield hass
    event_loop.run_until_complete(hass.async_stop())


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock, None, None]:
    """Override async_setup_entry."""
    with patch(
        f"custom_components.{DOMAIN}.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def electric_usage_xml(fixtures_path: Path) -> str:
    """Load sample electric usage XML."""
    return (fixtures_path / "electric_usage.xml").read_text()


@pytest.fixture
def gas_usage_xml(fixtures_path: Path) -> str:
    """Load sample gas usage XML."""
    return (fixtures_path / "gas_usage.xml").read_text()


@pytest.fixture
def mock_aiohttp_get():
    """Mock aiohttp ClientSession.get."""
    with patch("aiohttp.ClientSession.get") as mock_get:
        yield mock_get
