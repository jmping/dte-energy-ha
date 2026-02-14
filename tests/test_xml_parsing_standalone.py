"""Standalone tests for Green Button XML parsing (no HA dependency)."""

import xml.etree.ElementTree as ET
from pathlib import Path

# Constants (copied to avoid HA imports)
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}
SERVICE_TYPE_ELECTRIC = "electric"
SERVICE_TYPE_GAS = "gas"
CCF_TO_CUBIC_FEET = 100


def parse_green_button_xml(xml_data: str) -> dict:
    """Parse Green Button XML data (standalone version for testing)."""
    root = ET.fromstring(xml_data)

    service_type = None

    # Detect service type from UsagePoint
    usage_point = root.find(".//espi:UsagePoint", NAMESPACES)
    if usage_point is not None:
        service_category = usage_point.find("espi:ServiceCategory/espi:kind", NAMESPACES)
        if service_category is not None:
            kind = int(service_category.text or "0")
            if kind == 0:
                service_type = SERVICE_TYPE_ELECTRIC
            elif kind == 1:
                service_type = SERVICE_TYPE_GAS

    # Get power of ten multiplier
    multiplier = 1.0
    reading_type = root.find(".//espi:ReadingType", NAMESPACES)
    if reading_type is not None:
        power_of_ten = reading_type.find("espi:powerOfTenMultiplier", NAMESPACES)
        if power_of_ten is not None and power_of_ten.text:
            multiplier = 10 ** int(power_of_ten.text)

    # Parse interval readings
    interval_blocks = root.findall(".//espi:IntervalBlock", NAMESPACES)
    readings = []
    total_usage = 0.0

    for block in interval_blocks:
        for interval in block.findall("espi:IntervalReading", NAMESPACES):
            value_elem = interval.find("espi:value", NAMESPACES)
            time_period = interval.find("espi:timePeriod", NAMESPACES)

            if value_elem is not None and value_elem.text:
                raw_value = float(value_elem.text)
                value = raw_value * multiplier

                start_time = None
                if time_period is not None:
                    start_elem = time_period.find("espi:start", NAMESPACES)
                    if start_elem is not None and start_elem.text:
                        start_time = int(start_elem.text)

                readings.append({"value": value, "start_time": start_time})
                total_usage += value

    # Sort by time
    readings.sort(key=lambda x: x["start_time"] or 0)

    # Convert gas units if needed
    if service_type == SERVICE_TYPE_GAS:
        uom = reading_type.find("espi:uom", NAMESPACES) if reading_type is not None else None
        if uom is not None and uom.text:
            uom_kind = int(uom.text)
            if uom_kind in (119, 169):  # therm or CCF
                total_usage *= CCF_TO_CUBIC_FEET

    return {
        "total_usage": round(total_usage, 3),
        "reading_count": len(readings),
        "service_type": service_type,
        "latest_reading": readings[-1] if readings else None,
    }


class TestElectricXMLParsing:
    """Test electric usage XML parsing."""

    def test_parse_electric_data(self):
        """Test parsing electric usage XML."""
        fixtures_path = Path(__file__).parent / "fixtures"
        xml_data = (fixtures_path / "electric_usage.xml").read_text()

        result = parse_green_button_xml(xml_data)

        assert result["service_type"] == SERVICE_TYPE_ELECTRIC
        assert result["reading_count"] == 3
        # Values: 1500, 1200, 800 with powerOfTenMultiplier=-3
        # Total = (1500 + 1200 + 800) * 0.001 = 3.5 kWh
        assert result["total_usage"] == 3.5

    def test_readings_sorted_by_time(self):
        """Test that readings are sorted by start time."""
        fixtures_path = Path(__file__).parent / "fixtures"
        xml_data = (fixtures_path / "electric_usage.xml").read_text()

        result = parse_green_button_xml(xml_data)

        # Latest reading should have highest start time
        assert result["latest_reading"]["start_time"] == 1704074400


class TestGasXMLParsing:
    """Test gas usage XML parsing."""

    def test_parse_gas_data(self):
        """Test parsing gas usage XML."""
        fixtures_path = Path(__file__).parent / "fixtures"
        xml_data = (fixtures_path / "gas_usage.xml").read_text()

        result = parse_green_button_xml(xml_data)

        assert result["service_type"] == SERVICE_TYPE_GAS
        assert result["reading_count"] == 3
        # Values: 3, 4, 5 CCF converted to cubic feet
        # Total = (3 + 4 + 5) * 100 = 1200 ft³
        assert result["total_usage"] == 1200

    def test_gas_service_type_detected(self):
        """Test gas service type is correctly detected."""
        fixtures_path = Path(__file__).parent / "fixtures"
        xml_data = (fixtures_path / "gas_usage.xml").read_text()

        result = parse_green_button_xml(xml_data)

        assert result["service_type"] == SERVICE_TYPE_GAS


class TestEdgeCases:
    """Test edge cases in XML parsing."""

    def test_empty_interval_block(self):
        """Test handling of XML with no readings."""
        xml_data = '''<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">
            <entry>
                <content>
                    <espi:UsagePoint>
                        <espi:ServiceCategory><espi:kind>0</espi:kind></espi:ServiceCategory>
                    </espi:UsagePoint>
                </content>
            </entry>
            <entry>
                <content>
                    <espi:IntervalBlock>
                    </espi:IntervalBlock>
                </content>
            </entry>
        </feed>'''

        result = parse_green_button_xml(xml_data)

        assert result["reading_count"] == 0
        assert result["total_usage"] == 0
        assert result["latest_reading"] is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
