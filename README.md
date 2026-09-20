<h1 align="center">⚡ DTE Integration</h1>
<p align="center"><strong>Unofficial Home Assistant integration for DTE Energy usage data</strong></p>

# DTE Energy Home Assistant Integration

A custom Home Assistant integration that fetches electric and gas usage data from DTE Energy shareable Green Button links.

> This project is unofficial and is not affiliated with, endorsed by, or sponsored by DTE Energy.

## Features

- **Combined-feed support**: one DTE Green Button link can expose both electric and gas usage
- **Electric import tracking** from DTE Green Button data; export is exposed only when the source actually contains signed negative intervals
- **Dynamic tariff source**: fetches the current MPSC-approved DTE rate books, parses Rider 18 residential outflow credits and published PSCR factors, and preserves rate-book revisions locally
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
| DTE Electric Export | Locally maintained cumulative grid export, only when the DTE source provides export intervals | kWh | energy |
| DTE Tariff Data | MPSC tariff revision fingerprint with Rider 18 / PSCR details in attributes | — | — |
| DTE Gas Meter | Locally maintained cumulative gas usage | ft³ | gas |

Existing electric installations retain the original `<config_entry_id>_electric_meter` unique ID.

## Green Button parsing

DTE exports an Atom/ESPI Green Button feed. This fork does not assume the document contains only one service. It associates IntervalBlock entries with their owning UsagePoint and classifies the UsagePoint from its ESPI ServiceCategory.

DTE electric readings in the observed feed use UOM 72 (Wh); values are normalized to kWh. Positive electric intervals are treated as grid import. Some Green Button feeds may encode export as negative intervals; when that actually occurs, the integration exposes a separate positive `DTE Electric Export` counter. The observed DTE solar feed used for development is import-only (`Energy Delivered`) and bottoms out at zero during export, so the integration does not synthesize export from those zero intervals. DTE gas readings are labeled CCF and are normalized to cubic feet after applying the Green Button `powerOfTenMultiplier`.

## Energy Dashboard

Under **Settings > Dashboards > Energy**:

- add **DTE Electric Meter** as grid consumption;
- add **DTE Electric Export** as return to grid only if your DTE feed actually exposes it; for import-only DTE solar feeds, use an inverter/gateway source such as Enphase for return-to-grid energy;
- add **DTE Gas Meter** as gas consumption.

## Persistent cumulative ledger

DTE's share export is treated as a rolling set of timestamped intervals, not as a lifetime meter register. On first load, the integration seeds a local ledger from every interval in the feed. On subsequent refreshes it:

- adds only intervals it has not seen before;
- updates stored values when DTE revises an existing timestamp;
- ignores intervals that disappear because the DTE export window rolled forward;
- persists the ledger in Home Assistant storage across restarts.

A downward DTE revision is carried as a pending correction rather than making a `total_increasing` entity move backward. Subsequent positive usage absorbs that correction before the cumulative sensor advances again.

Sensor attributes expose current source-window import/export totals, duplicate interval count, stored interval count, new/revised interval counts from the latest refresh, and any pending downward corrections.

## Historical statistics

The integration imports the timestamped DTE interval history into Home Assistant's recorder as external long-term statistics. This avoids making the full DTE rolling export appear as consumption on the day the integration was installed.

The statistics are:

- **DTE Energy electric import** — positive electric intervals, in kWh;
- **DTE Energy electric export** — created only when the DTE source contains negative electric intervals, converted to positive return-to-grid energy in kWh;
- **DTE Energy gas consumption** — daily gas intervals, in ft³.

The cumulative `sum` for each statistic is rebuilt from the persistent interval ledger. If DTE later revises an interval, the integration rewrites statistics from the earliest affected timestamp forward so subsequent cumulative sums remain correct. If the recorder database is replaced while the DTE ledger survives, the history is automatically rebuilt.

These external statistics are the preferred sources for the Home Assistant Energy Dashboard because they retain the original DTE timestamps. The live DTE meter entities remain useful as current cumulative counters and diagnostics.

## Dynamic tariff data

For electric entries, the integration also checks the Michigan Public Service Commission's current DTE rate-book page during the normal daily refresh. It discovers the current Section C and Section D PDF links instead of hard-coding revision URLs, downloads the authoritative documents, and records a SHA-256 fingerprint of the combined source.

The tariff parser currently extracts:

- residential **Rider 18** base outflow credits for D1.2, D1.7, D1.8, D1.9, D1.11, and D1.13;
- published monthly **PSCR actual factors** from Sheet C-62.00 when the current rate book contains them;
- source URLs, check time, and rate-book revision fingerprint.

The `DTE Tariff Data` diagnostic sensor exposes the parsed values as attributes. Every newly observed rate-book fingerprint is also retained in Home Assistant storage so historical tariff revisions are not overwritten.

Rider 18 states that full-service outflow is credited at the listed power-supply rate **plus the applicable PSCR factor**. The MPSC notes that its rate books can lag pending PSCR factors or very recent Commission orders, so missing future-month PSCR actuals are intentionally left unset rather than guessed.

A later tariff-calculation layer can combine these effective-dated rates with DTE import intervals and inverter-provided export intervals (for example, Enphase) without coupling billing logic to Green Button parsing.

## Data updates

The integration fetches the share link once every 24 hours by default. DTE data can lag actual consumption.

## Development status

The `dynamic-tariffs` branch adds MPSC-backed tariff discovery on top of the validated combined electric/gas history importer. Tariff source retrieval, Green Button parsing, and future billing calculations remain separate layers so each can be tested independently.

## License

MIT License
