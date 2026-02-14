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
    DOMAIN,
    NAMESPACES,
    SERVICE_TYPE_ELECTRIC,
    SERVICE_TYPE_GAS,
    DEFAULT_UPDATE_INTERVAL,
    CCF_TO_CUBIC_FEET,
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
        self._service_type = service_type
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
                async with session.get(self.usage_link, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status != 200:
                        raise UpdateFailed(f"Error fetching data: HTTP {response.status}")
                    xml_data = await response.text()

            return self._parse_green_button_xml(xml_data)

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with DTE Energy: {err}") from err
        except ET.ParseError as err:
            raise UpdateFailed(f"Error parsing Green Button XML: {err}") from err

    def _parse_green_button_xml(self, xml_data: str) -> dict[str, Any]:
        """Parse Green Button XML data."""
        root = ET.fromstring(xml_data)

        # Find all IntervalBlock entries
        interval_blocks = root.findall(".//espi:IntervalBlock", NAMESPACES)

        if not interval_blocks:
            raise UpdateFailed("No interval data found in Green Button XML")

        # Extract reading type info to determine service type and units
        reading_type = root.find(".//espi:ReadingType", NAMESPACES)
        if reading_type is not None:
            self._detect_service_type(reading_type)

        # Extract meter ID from UsagePoint if available
        usage_point = root.find(".//espi:UsagePoint", NAMESPACES)
        if usage_point is not None:
            service_category = usage_point.find("espi:ServiceCategory/espi:kind", NAMESPACES)
            if service_category is not None:
                # 0 = electricity, 1 = gas
                kind = int(service_category.text or "0")
                if kind == 0:
                    self._service_type = SERVICE_TYPE_ELECTRIC
                elif kind == 1:
                    self._service_type = SERVICE_TYPE_GAS

        # Collect all interval readings
        readings: list[dict[str, Any]] = []
        total_usage = 0.0
        multiplier = self._get_power_of_ten_multiplier(root)

        for block in interval_blocks:
            for interval in block.findall("espi:IntervalReading", NAMESPACES):
                value_elem = interval.find("espi:value", NAMESPACES)
                time_period = interval.find("espi:timePeriod", NAMESPACES)

                if value_elem is not None and value_elem.text:
                    # Apply power of ten multiplier
                    raw_value = float(value_elem.text)
                    value = raw_value * multiplier

                    start_time = None
                    duration = None
                    if time_period is not None:
                        start_elem = time_period.find("espi:start", NAMESPACES)
                        duration_elem = time_period.find("espi:duration", NAMESPACES)
                        if start_elem is not None and start_elem.text:
                            start_time = int(start_elem.text)
                        if duration_elem is not None and duration_elem.text:
                            duration = int(duration_elem.text)

                    readings.append({
                        "value": value,
                        "start_time": start_time,
                        "duration": duration,
                    })
                    total_usage += value

        # Sort readings by start time
        readings.sort(key=lambda x: x["start_time"] or 0)

        # Get the most recent reading
        latest_reading = readings[-1] if readings else None

        # Determine unit based on service type
        if self._service_type == SERVICE_TYPE_ELECTRIC:
            unit = "kWh"
        else:
            # For gas, convert to cubic feet if needed
            unit = "ft³"
            # If data appears to be in CCF or therms, convert
            total_usage = self._convert_gas_units(total_usage, root)

        return {
            "total_usage": round(total_usage, 3),
            "unit": unit,
            "reading_count": len(readings),
            "latest_reading": latest_reading,
            "service_type": self._service_type,
        }

    def _detect_service_type(self, reading_type: ET.Element) -> None:
        """Detect service type from ReadingType element."""
        if self._service_type:
            return  # Already set

        # Check commodity type
        # 0 = NA, 1 = electricity, 7 = natural gas
        commodity = reading_type.find("espi:commodity", NAMESPACES)
        if commodity is not None and commodity.text:
            commodity_kind = int(commodity.text)
            if commodity_kind == 1:
                self._service_type = SERVICE_TYPE_ELECTRIC
            elif commodity_kind == 7:
                self._service_type = SERVICE_TYPE_GAS
            return

        # Check unit of measure as fallback
        # 72 = Wh, 119 = therm
        uom = reading_type.find("espi:uom", NAMESPACES)
        if uom is not None and uom.text:
            uom_kind = int(uom.text)
            if uom_kind in (72, 132):  # Wh or kWh
                self._service_type = SERVICE_TYPE_ELECTRIC
            elif uom_kind in (119, 169):  # therm or CCF
                self._service_type = SERVICE_TYPE_GAS

    def _get_power_of_ten_multiplier(self, root: ET.Element) -> float:
        """Get the power of ten multiplier from ReadingType."""
        reading_type = root.find(".//espi:ReadingType", NAMESPACES)
        if reading_type is not None:
            power_of_ten = reading_type.find("espi:powerOfTenMultiplier", NAMESPACES)
            if power_of_ten is not None and power_of_ten.text:
                return 10 ** int(power_of_ten.text)
        return 1.0

    def _convert_gas_units(self, value: float, root: ET.Element) -> float:
        """Convert gas units to cubic feet if necessary."""
        reading_type = root.find(".//espi:ReadingType", NAMESPACES)
        if reading_type is not None:
            uom = reading_type.find("espi:uom", NAMESPACES)
            if uom is not None and uom.text:
                uom_kind = int(uom.text)
                # 119 = therm, 169 = CCF - convert to cubic feet
                if uom_kind in (119, 169):
                    return value * CCF_TO_CUBIC_FEET
        return value


async def validate_usage_link(hass: HomeAssistant, usage_link: str) -> dict[str, Any]:
    """Validate a DTE usage link and return service info."""
    coordinator = DTEEnergyCoordinator(hass, usage_link)
    data = await coordinator._async_update_data()
    return {
        "service_type": coordinator.service_type or data.get("service_type"),
        "total_usage": data.get("total_usage"),
        "unit": data.get("unit"),
        "reading_count": data.get("reading_count"),
    }
