"""Data coordinator for DTE Energy integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
import xml.etree.ElementTree as ET

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CCF_TO_CUBIC_FEET,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    NAMESPACES,
    SERVICE_TYPE_COMBINED,
    SERVICE_TYPE_ELECTRIC,
    SERVICE_TYPE_GAS,
)

_LOGGER = logging.getLogger(__name__)


class DTEEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch DTE Energy usage data."""

    def __init__(
        self,
        hass: HomeAssistant,
        usage_link: str,
        service_type: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=DEFAULT_UPDATE_INTERVAL),
        )
        self.usage_link = usage_link
        # Kept for backward compatibility with existing config entries. The
        # parser now discovers every service contained in the Green Button feed.
        self._configured_service_type = service_type
        self._service_type: str | None = service_type
        self._meter_id: str | None = None

    @property
    def service_type(self) -> str | None:
        """Return the detected service type."""
        return self._service_type

    @property
    def meter_id(self) -> str | None:
        """Return the meter ID."""
        return self._meter_id

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from DTE Energy."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.usage_link,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status != 200:
                        raise UpdateFailed(
                            f"Error fetching data: HTTP {response.status}"
                        )
                    xml_data = await response.text()

            return self._parse_green_button_xml(xml_data)

        except aiohttp.ClientError as err:
            raise UpdateFailed(
                f"Error communicating with DTE Energy: {err}"
            ) from err
        except ET.ParseError as err:
            raise UpdateFailed(
                f"Error parsing Green Button XML: {err}"
            ) from err

    def _parse_green_button_xml(self, xml_data: str) -> dict[str, Any]:
        """Parse all services present in a DTE Green Button feed."""
        root = ET.fromstring(xml_data)
        entries = root.findall("atom:entry", NAMESPACES)

        if not entries:
            raise UpdateFailed("No entries found in Green Button XML")

        usage_points = self._find_usage_points(entries)
        reading_types = self._find_reading_types(entries)

        service_readings: dict[str, list[dict[str, Any]]] = {
            SERVICE_TYPE_ELECTRIC: [],
            SERVICE_TYPE_GAS: [],
        }

        for entry in entries:
            interval_blocks = entry.findall(
                "atom:content/espi:IntervalBlock", NAMESPACES
            )
            if not interval_blocks:
                continue

            service_type = self._service_for_interval_entry(
                entry, usage_points
            )
            if service_type is None:
                _LOGGER.debug(
                    "Skipping IntervalBlock entry with unknown service: %s",
                    self._entry_title(entry),
                )
                continue

            reading_type = reading_types.get(service_type)

            for block in interval_blocks:
                for interval in block.findall(
                    "espi:IntervalReading", NAMESPACES
                ):
                    parsed = self._parse_interval_reading(
                        interval, service_type, reading_type
                    )
                    if parsed is not None:
                        service_readings[service_type].append(parsed)

        services: dict[str, dict[str, Any]] = {}
        for service_type, readings in service_readings.items():
            if not readings:
                continue

            readings.sort(key=lambda item: item["start_time"] or 0)
            total_usage = sum(item["value"] for item in readings)

            services[service_type] = {
                "total_usage": round(total_usage, 3),
                "unit": (
                    "kWh"
                    if service_type == SERVICE_TYPE_ELECTRIC
                    else "ft³"
                ),
                "reading_count": len(readings),
                "latest_reading": readings[-1],
                "service_type": service_type,
                "usage_point": usage_points.get(service_type),
            }

        if not services:
            raise UpdateFailed(
                "No supported electric or gas interval data found "
                "in Green Button XML"
            )

        service_types = list(services)
        self._service_type = (
            service_types[0]
            if len(service_types) == 1
            else SERVICE_TYPE_COMBINED
        )

        # Preserve the legacy top-level shape for single-service consumers while
        # exposing the new multi-service dictionary to updated entities.
        result: dict[str, Any] = {
            "services": services,
            "service_types": service_types,
            "service_type": self._service_type,
        }
        if len(service_types) == 1:
            result.update(services[service_types[0]])

        return result

    def _find_usage_points(
        self, entries: list[ET.Element]
    ) -> dict[str, str]:
        """Map service type to UsagePoint self-link."""
        usage_points: dict[str, str] = {}

        for entry in entries:
            usage_point = entry.find(
                "atom:content/espi:UsagePoint", NAMESPACES
            )
            if usage_point is None:
                continue

            kind_text = usage_point.findtext(
                "espi:ServiceCategory/espi:kind",
                default="",
                namespaces=NAMESPACES,
            )
            service_type = self._service_from_category(kind_text)
            if service_type is None:
                continue

            self_link = self._entry_link(entry, "self")
            if self_link:
                usage_points[service_type] = self_link

        return usage_points

    def _find_reading_types(
        self, entries: list[ET.Element]
    ) -> dict[str, ET.Element]:
        """Map each supported commodity to its ReadingType."""
        reading_types: dict[str, ET.Element] = {}

        for entry in entries:
            reading_type = entry.find(
                "atom:content/espi:ReadingType", NAMESPACES
            )
            if reading_type is None:
                continue

            commodity = reading_type.findtext(
                "espi:commodity", default="", namespaces=NAMESPACES
            )
            service_type = self._service_from_commodity(commodity)
            if service_type is not None:
                reading_types[service_type] = reading_type

        return reading_types

    def _service_for_interval_entry(
        self,
        entry: ET.Element,
        usage_points: dict[str, str],
    ) -> str | None:
        """Determine which UsagePoint owns an IntervalBlock entry."""
        links = [
            link.attrib.get("href", "")
            for link in entry.findall("atom:link", NAMESPACES)
        ]

        for service_type, usage_point_href in usage_points.items():
            prefix = f"{usage_point_href}/MeterReading/"
            if any(href.startswith(prefix) for href in links):
                return service_type

        # Conservative fallback for DTE feeds whose linkage metadata is absent.
        title = self._entry_title(entry).lower()
        if "electric" in title:
            return SERVICE_TYPE_ELECTRIC
        if "gas" in title:
            return SERVICE_TYPE_GAS
        return None

    def _parse_interval_reading(
        self,
        interval: ET.Element,
        service_type: str,
        reading_type: ET.Element | None,
    ) -> dict[str, Any] | None:
        """Parse and normalize one IntervalReading."""
        value_text = interval.findtext(
            "espi:value", default="", namespaces=NAMESPACES
        )
        if not value_text:
            return None

        raw_value = float(value_text)
        value = self._normalize_value(
            raw_value, service_type, reading_type
        )

        time_period = interval.find("espi:timePeriod", NAMESPACES)
        start_time = None
        duration = None

        if time_period is not None:
            start_text = time_period.findtext(
                "espi:start", default="", namespaces=NAMESPACES
            )
            duration_text = time_period.findtext(
                "espi:duration", default="", namespaces=NAMESPACES
            )
            if start_text:
                start_time = int(start_text)
            if duration_text:
                duration = int(duration_text)

        return {
            "value": value,
            "start_time": start_time,
            "duration": duration,
        }

    def _normalize_value(
        self,
        raw_value: float,
        service_type: str,
        reading_type: ET.Element | None,
    ) -> float:
        """Normalize DTE values to kWh (electric) or ft³ (gas)."""
        multiplier = 1.0
        uom = None

        if reading_type is not None:
            power_text = reading_type.findtext(
                "espi:powerOfTenMultiplier",
                default="0",
                namespaces=NAMESPACES,
            )
            multiplier = 10 ** int(power_text or "0")

            uom_text = reading_type.findtext(
                "espi:uom", default="", namespaces=NAMESPACES
            )
            if uom_text:
                uom = int(uom_text)

        value = raw_value * multiplier

        if service_type == SERVICE_TYPE_ELECTRIC:
            # DTE's Green Button feed uses UOM 72 (Wh). Home Assistant's
            # energy sensor is exposed in kWh.
            if uom == 72:
                value /= 1000
            return value

        if service_type == SERVICE_TYPE_GAS:
            # DTE labels its gas ReadingType "Energy Delivered (CCF)" and
            # supplies the applicable power-of-ten multiplier. Normalize CCF
            # to cubic feet for Home Assistant's gas device class.
            if uom in (119, 169):
                value *= CCF_TO_CUBIC_FEET
            return value

        return value

    @staticmethod
    def _service_from_category(kind_text: str) -> str | None:
        """Translate ESPI ServiceCategory kind to integration service type."""
        if kind_text == "0":
            return SERVICE_TYPE_ELECTRIC
        if kind_text == "1":
            return SERVICE_TYPE_GAS
        return None

    @staticmethod
    def _service_from_commodity(commodity_text: str) -> str | None:
        """Translate ESPI commodity to integration service type."""
        if commodity_text == "1":
            return SERVICE_TYPE_ELECTRIC
        if commodity_text == "7":
            return SERVICE_TYPE_GAS
        return None

    @staticmethod
    def _entry_link(entry: ET.Element, rel: str) -> str | None:
        """Return an Atom link href by relation."""
        for link in entry.findall("atom:link", NAMESPACES):
            if link.attrib.get("rel") == rel:
                return link.attrib.get("href")
        return None

    @staticmethod
    def _entry_title(entry: ET.Element) -> str:
        """Return an Atom entry title."""
        return entry.findtext(
            "atom:title", default="", namespaces=NAMESPACES
        )


async def validate_usage_link(
    hass: HomeAssistant, usage_link: str
) -> dict[str, Any]:
    """Validate a DTE usage link and return discovered service info."""
    coordinator = DTEEnergyCoordinator(hass, usage_link)
    data = await coordinator._async_update_data()
    return {
        "service_type": data.get("service_type"),
        "service_types": data.get("service_types", []),
        "services": data.get("services", {}),
    }
