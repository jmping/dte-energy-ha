# DTE Energy Home Assistant Integration

A custom Home Assistant integration that fetches energy usage data from DTE Energy using their shareable Green Button data links.

## Features

- **Electric Usage Tracking**: Hourly kWh readings with 13 months of history
- **Gas Usage Tracking**: Daily readings in cubic feet with 13 months of history
- **Energy Dashboard Compatible**: Sensors are configured with the correct device class and state class for full Home Assistant Energy Dashboard integration
- **Automatic Service Detection**: The integration automatically detects whether your link is for electric or gas service

## Installation

### Manual Installation

1. Copy the `custom_components/dte_energy` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via the UI (see Configuration below)

### HACS Installation (Manual Repository)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select "Custom repositories"
4. Add the repository URL and select "Integration" as the category
5. Install the integration
6. Restart Home Assistant

## Getting Your DTE Usage Link

1. Log in to your DTE Energy account at [newlook.dteenergy.com](https://newlook.dteenergy.com)
2. Navigate to **Usage** > **Usage History**
3. Scroll down to the **Generate Link** section
4. Click to generate a new link (or copy an existing one)
5. Copy the full URL - it should look like: `https://usagedata.dteenergy.com/link/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

**Note**: You'll need to generate separate links for electric and gas if you have both services.

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "DTE Energy"
4. Paste your DTE usage data link when prompted
5. The integration will automatically detect whether it's an electric or gas link
6. Repeat for additional links (e.g., if you have both electric and gas)

## Sensors

### Electric (if electric link provided)

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| DTE Electric Meter | Total cumulative electric usage | kWh | energy |

### Gas (if gas link provided)

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| DTE Gas Meter | Total cumulative gas usage | ft³ | gas |

## Energy Dashboard Setup

The sensors are automatically compatible with the Home Assistant Energy Dashboard:

1. Go to **Settings** > **Dashboards** > **Energy**
2. Under **Electricity grid**, click **Add consumption**
3. Select **DTE Electric Meter**
4. Under **Gas consumption**, click **Add gas source**
5. Select **DTE Gas Meter**

You can configure utility rates directly in the Energy Dashboard settings to track costs.

## Data Updates

- Data is fetched once every 24 hours by default
- DTE typically updates usage data with a 1-2 day delay
- Historical data (up to 13 months) is available through the Green Button format

## Troubleshooting

### "Cannot connect" error

- Verify the link is correct and hasn't expired
- Make sure the link is accessible from your network (try opening it in a browser)
- Check that the link format matches: `https://usagedata.dteenergy.com/link/...`

### No data appearing

- DTE may take 1-2 days to update usage data
- Check the Home Assistant logs for any error messages
- Verify the link works by opening it directly in a browser (should download an XML file)

### Sensor not appearing in Energy Dashboard

- Ensure the sensor has the correct device_class (`energy` for electric, `gas` for gas)
- Check that state_class is `total_increasing`
- Restart Home Assistant after adding the integration

## Technical Details

- **Data Format**: Green Button XML (ESPI/NAESB standard)
- **Update Interval**: 24 hours (configurable)
- **Units**:
  - Electric: kWh
  - Gas: ft³ (cubic feet)

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

MIT License
