"""Constants for the DTE Energy integration."""

DOMAIN = "dte_energy"

CONF_USAGE_LINK = "usage_link"
CONF_SERVICE_TYPE = "service_type"

SERVICE_TYPE_ELECTRIC = "electric"
SERVICE_TYPE_GAS = "gas"
SERVICE_TYPE_COMBINED = "combined"

DEFAULT_UPDATE_INTERVAL = 24

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}

CCF_TO_CUBIC_FEET = 100
