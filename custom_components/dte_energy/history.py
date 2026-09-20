"""Long-term statistics import for DTE Energy interval history."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import (
    DOMAIN,
    SERVICE_TYPE_ELECTRIC,
    SERVICE_TYPE_GAS,
)

_LOGGER = logging.getLogger(__name__)

STATISTICS_VERSION = 2


def statistic_ids(entry_id: str) -> dict[str, str]:
    """Return stable external statistic IDs for a config entry."""
    safe_entry_id = entry_id.replace("-", "_").lower()
    prefix = f"{DOMAIN}:{safe_entry_id}"
    return {
        "electric_import": f"{prefix}_electric_import",
        "electric_export": f"{prefix}_electric_export",
        "gas_consumption": f"{prefix}_gas_consumption",
    }


async def async_import_interval_statistics(
    hass: HomeAssistant,
    entry_id: str,
    ledger: dict[str, Any],
    dirty_from: dict[str, int | None],
) -> bool:
    """Import DTE interval history as Home Assistant external statistics.

    The DTE export is delayed utility data, so external statistics are a better
    fit than replaying old values through the live sensor state. Statistics are
    rebuilt from the persistent signed interval ledger, preserving history even
    after intervals roll out of DTE's source window.
    """
    if "recorder" not in hass.config.components:
        _LOGGER.debug("Recorder is not loaded; skipping DTE statistics import")
        return False

    services = ledger.get("services", {})
    if not isinstance(services, dict):
        return False

    ids = statistic_ids(entry_id)

    needs_full_import = ledger.get("statistics_version") != STATISTICS_VERSION

    # If the recorder database was replaced while .storage survived, rebuild
    # the statistics even though the interval ledger itself is already current.
    if not needs_full_import:
        expected_ids: list[str] = []
        if SERVICE_TYPE_ELECTRIC in services:
            expected_ids.append(ids["electric_import"])
            electric_service = services.get(SERVICE_TYPE_ELECTRIC)
            if isinstance(electric_service, dict):
                electric_intervals = _ordered_intervals(electric_service)
                if any(value < 0 for _start, value in electric_intervals):
                    expected_ids.append(ids["electric_export"])
        if SERVICE_TYPE_GAS in services:
            expected_ids.append(ids["gas_consumption"])

        for statistic_id in expected_ids:
            last = await get_instance(hass).async_add_executor_job(
                get_last_statistics,
                hass,
                1,
                statistic_id,
                True,
                set(),
            )
            if not last:
                needs_full_import = True
                break

    imported_any = False

    electric = services.get(SERVICE_TYPE_ELECTRIC)
    if isinstance(electric, dict):
        intervals = _ordered_intervals(electric)
        if intervals:
            start_from = (
                intervals[0][0]
                if needs_full_import
                else dirty_from.get(SERVICE_TYPE_ELECTRIC)
            )
            if start_from is not None:
                import_stats, export_stats = _build_electric_statistics(
                    intervals, start_from
                )

                import_metadata = StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name="DTE Energy electric import",
                    source=DOMAIN,
                    statistic_id=ids["electric_import"],
                    unit_class=EnergyConverter.UNIT_CLASS,
                    unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                )
                has_export = any(value < 0 for _start, value in intervals)
                export_metadata = (
                    StatisticMetaData(
                        mean_type=StatisticMeanType.NONE,
                        has_sum=True,
                        name="DTE Energy electric export",
                        source=DOMAIN,
                        statistic_id=ids["electric_export"],
                        unit_class=EnergyConverter.UNIT_CLASS,
                        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    )
                    if has_export
                    else None
                )

                if import_stats:
                    async_add_external_statistics(
                        hass, import_metadata, import_stats
                    )
                    imported_any = True
                if has_export and export_metadata is not None and export_stats:
                    async_add_external_statistics(
                        hass, export_metadata, export_stats
                    )
                    imported_any = True

                _LOGGER.info(
                    "Imported %s electric import and %s export DTE "
                    "statistics from %s",
                    len(import_stats),
                    len(export_stats) if has_export else 0,
                    dt_util.utc_from_timestamp(start_from).isoformat(),
                )

    gas = services.get(SERVICE_TYPE_GAS)
    if isinstance(gas, dict):
        intervals = _ordered_intervals(gas)
        if intervals:
            start_from = (
                intervals[0][0]
                if needs_full_import
                else dirty_from.get(SERVICE_TYPE_GAS)
            )
            if start_from is not None:
                gas_stats = _build_gas_statistics(intervals, start_from)
                gas_metadata = StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name="DTE Energy gas consumption",
                    source=DOMAIN,
                    statistic_id=ids["gas_consumption"],
                    unit_class=VolumeConverter.UNIT_CLASS,
                    unit_of_measurement=UnitOfVolume.CUBIC_FEET,
                )
                if gas_stats:
                    async_add_external_statistics(
                        hass, gas_metadata, gas_stats
                    )
                    imported_any = True

                _LOGGER.info(
                    "Imported %s gas DTE statistics from %s",
                    len(gas_stats),
                    dt_util.utc_from_timestamp(start_from).isoformat(),
                )

    if needs_full_import or imported_any:
        ledger["statistics_version"] = STATISTICS_VERSION

    return needs_full_import or imported_any


def _ordered_intervals(
    service_ledger: dict[str, Any],
) -> list[tuple[int, float]]:
    """Return ledger intervals ordered by their Unix start timestamp."""
    intervals = service_ledger.get("intervals", {})
    if not isinstance(intervals, dict):
        return []

    ordered: list[tuple[int, float]] = []
    for key, value in intervals.items():
        try:
            start_text, _duration_text = str(key).split(":", 1)
            ordered.append((int(start_text), float(value)))
        except (TypeError, ValueError):
            _LOGGER.warning("Skipping invalid DTE ledger interval key %r", key)

    ordered.sort(key=lambda item: item[0])
    return ordered


def _build_electric_statistics(
    intervals: list[tuple[int, float]],
    start_from: int,
) -> tuple[list[StatisticData], list[StatisticData]]:
    """Build import and export statistics from signed electric intervals."""
    import_sum = 0.0
    export_sum = 0.0
    import_stats: list[StatisticData] = []
    export_stats: list[StatisticData] = []

    for start_ts, signed_value in intervals:
        import_value = max(signed_value, 0.0)
        export_value = max(-signed_value, 0.0)
        import_sum += import_value
        export_sum += export_value

        if start_ts < start_from:
            continue

        start: datetime = dt_util.utc_from_timestamp(start_ts)
        import_stats.append(
            StatisticData(
                start=start,
                state=import_value,
                sum=import_sum,
            )
        )
        export_stats.append(
            StatisticData(
                start=start,
                state=export_value,
                sum=export_sum,
            )
        )

    return import_stats, export_stats


def _build_gas_statistics(
    intervals: list[tuple[int, float]],
    start_from: int,
) -> list[StatisticData]:
    """Build gas-consumption statistics from interval readings."""
    total = 0.0
    stats: list[StatisticData] = []

    for start_ts, value in intervals:
        consumption = max(value, 0.0)
        total += consumption

        if start_ts < start_from:
            continue

        stats.append(
            StatisticData(
                start=dt_util.utc_from_timestamp(start_ts),
                state=consumption,
                sum=total,
            )
        )

    return stats
