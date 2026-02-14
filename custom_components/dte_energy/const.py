"""Constants for the DTE Energy integration."""

DOMAIN = "dte_energy"

# Configuration keys
CONF_USAGE_LINK = "usage_link"
CONF_SERVICE_TYPE = "service_type"

# Service types
SERVICE_TYPE_ELECTRIC = "electric"
SERVICE_TYPE_GAS = "gas"

# Update interval (in hours)
DEFAULT_UPDATE_INTERVAL = 24

# Green Button XML namespaces
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}

# Unit conversions
# CCF to cubic feet (1 CCF = 100 cubic feet)
CCF_TO_CUBIC_FEET = 100
# Therms to cubic feet (approximate, depends on gas heat content)
THERMS_TO_CUBIC_FEET = 100
