"""The DTE Energy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SERVICE_TYPE,
    CONF_USAGE_LINK,
    DOMAIN,
    SERVICE_TYPE_COMBINED,
)
from .coordinator import DTEEnergyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up DTE Energy from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    usage_link = entry.data[CONF_USAGE_LINK]
    configured_service_type = entry.data.get(CONF_SERVICE_TYPE)

    coordinator = DTEEnergyCoordinator(
        hass,
        usage_link,
        configured_service_type,
        entry.entry_id,
    )

    await coordinator.async_config_entry_first_refresh()

    # Existing installations may have been configured when the integration
    # only detected the first service in a combined DTE feed. Once both
    # services are discovered, migrate the entry metadata in place so users
    # keep the same config entry and electric entity unique ID.
    detected_service_type = coordinator.service_type
    if (
        detected_service_type == SERVICE_TYPE_COMBINED
        and configured_service_type != SERVICE_TYPE_COMBINED
    ):
        new_data = dict(entry.data)
        new_data[CONF_SERVICE_TYPE] = SERVICE_TYPE_COMBINED
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            title="DTE Energy",
        )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
