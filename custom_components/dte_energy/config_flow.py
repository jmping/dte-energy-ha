"""Config flow for DTE Energy integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_SERVICE_TYPE,
    CONF_USAGE_LINK,
    DOMAIN,
    SERVICE_TYPE_COMBINED,
    SERVICE_TYPE_ELECTRIC,
    SERVICE_TYPE_GAS,
)
from .coordinator import validate_usage_link

_LOGGER = logging.getLogger(__name__)

DTE_LINK_PATTERN = re.compile(
    r"^https://usagedata\.dteenergy\.com/link/[a-f0-9-]+$",
    re.IGNORECASE,
)


def _validate_link_format(usage_link: str) -> bool:
    """Validate the format of a DTE usage link."""
    return bool(DTE_LINK_PATTERN.match(usage_link.strip()))


async def _validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    usage_link = data[CONF_USAGE_LINK].strip()

    if not _validate_link_format(usage_link):
        raise InvalidLink(
            "The URL format is not valid. Please check the link."
        )

    try:
        result = await validate_usage_link(hass, usage_link)
    except Exception as err:
        _LOGGER.error("Error validating DTE link: %s", err)
        raise CannotConnect(
            f"Could not connect to DTE Energy: {err}"
        ) from err

    if not result.get("service_types"):
        raise CannotConnect(
            "Could not determine electric or gas service from data"
        )

    return result


class DTEEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the DTE Energy config flow."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            usage_link = user_input[CONF_USAGE_LINK].strip()

            self._async_abort_entries_match(
                {CONF_USAGE_LINK: usage_link}
            )

            try:
                info = await _validate_input(self.hass, user_input)
            except InvalidLink:
                errors["base"] = "invalid_link"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                service_types = info["service_types"]
                if len(service_types) > 1:
                    service_type = SERVICE_TYPE_COMBINED
                    title = "DTE Energy"
                else:
                    service_type = service_types[0]
                    service_name = (
                        "Electric"
                        if service_type == SERVICE_TYPE_ELECTRIC
                        else "Gas"
                    )
                    title = f"DTE {service_name}"

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_USAGE_LINK: usage_link,
                        CONF_SERVICE_TYPE: service_type,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USAGE_LINK): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidLink(HomeAssistantError):
    """Error to indicate an invalid DTE share link."""
