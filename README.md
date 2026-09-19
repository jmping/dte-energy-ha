<h1 align="center">⚡ DTE Integration</h1>
<p align="center"><strong>Unofficial Home Assistant integration for DTE Energy usage data</strong></p>

# DTE Energy Home Assistant Integration

A custom Home Assistant integration that fetches electric and gas usage data from DTE Energy shareable Green Button links.

> This project is unofficial and is not affiliated with, endorsed by, or sponsored by DTE Energy.

## Features

- **Combined-feed support**: one DTE Green Button link can expose both electric and gas usage
- **Electric import/export tracking**: positive intervals are grid consumption; negative intervals are tracked separately as exported energy
- **Gas usage tracking**: daily readings normalized to cubic feet
- **Energy Dashboard compatible**: electric and gas sensors use Home Assistant energy/gas device classes
- **Automatic service detection**: discovers all supported services present in the feed
- **Persistent interval ledger**: rolling DTE export windows cannot make cumulative sensors move backward
- **Revision-aware reconciliation**: changed DTE intervals are reconciled without creating false meter resets
- **24-hour polling** with historical data supplied by DTE

## Installation

### HACS custom repository

1. Add `https://github.com/jmping/dte-energy-ha` as a custom Integration repository in HACS.
2. Install DTE Energy.
3. Restart Home Assistant.
4. Add the DTE Energy integration from **Settings > Devices & Services**.

### Manual

Copy `custom_components/dte_energy` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## Configuration

1. Generate a DTE Usage Data share link from DTE's Usage History page.
2. Add the DTE Energy integration.
3. Paste the share link.

The integration inspects the complete Green Button feed. If the same link contains both DTE electric and gas UsagePoints, both sensors are created from the single config entry.

## Sensors

| Sensor | Description | Unit | Device class |
|---|---|---|---|
| DTE Electric Meter | Locally maintained cumulative grid import | kWh | energy |
| DTE Electric Export | Locally maintained cumulative grid export | kWh | energy |
| DTE Gas Meter | Locally maintained cumulative gas usage | ft³ | gas |

Existing electric installations retain the original `<config_entry_id>_electric_meter` unique ID.

## Green Button parsing

DTE exports an Atom/ESPI Green Button feed. This fork does not assume the document contains only one service. It associates IntervalBlock entries with their owning UsagePoint and classifies the UsagePoint from its ESPI ServiceCategory.

DTE electric readings in the observed feed use UOM 72 (Wh); values are normalized to kWh. Positive electric intervals are treated as grid import. Negative electric intervals are treated as grid export and accumulated as a separate positive `DTE Electric Export` counter so both Home Assistant energy sensors remain `total_increasing`. DTE gas readings are labeled CCF and are normalized to cubic feet after applying the Green Button `powerOfTenMultiplier`.

## Energy Dashboard

Under **Settings > Dashboards > Energy**:

- add **DTE Electric Meter** as grid consumption;
- add **DTE Electric Export** as return to grid, if applicable;
- add **DTE Gas Meter** as gas consumption.

## Persistent cumulative ledger

DTE's share export is treated as a rolling set of timestamped intervals, not as a lifetime meter register. On first load, the integration seeds a local ledger from every interval in the feed. On subsequent refreshes it:

- adds only intervals it has not seen before;
- updates stored values when DTE revises an existing timestamp;
- ignores intervals that disappear because the DTE export window rolled forward;
- persists the ledger in Home Assistant storage across restarts.

A downward DTE revision is carried as a pending correction rather than making a `total_increasing` entity move backward. Subsequent positive usage absorbs that correction before the cumulative sensor advances again.

Sensor attributes expose current source-window import/export totals, duplicate interval count, stored interval count, new/revised interval counts from the latest refresh, and any pending downward corrections.

## Data updates

The integration fetches the share link once every 24 hours by default. DTE data can lag actual consumption.

## Development status

The `combined-electric-gas` branch adds multi-service parsing based on a real DTE combined electric/gas Green Button export. Tariff/rate calculation is planned separately so usage parsing and billing logic remain independently testable.

## License

MIT License
