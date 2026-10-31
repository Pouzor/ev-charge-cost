"""Constants for the EV Charge Cost integration."""

from typing import Final

DOMAIN: Final = "ev_charge_cost"

# Config / options keys
CONF_POWER_ENTITY: Final = "power_entity"
CONF_ENERGY_ENTITY: Final = "energy_entity"
CONF_THRESHOLD_W: Final = "threshold_w"
CONF_START_DELAY_S: Final = "start_delay_s"
CONF_STOP_DELAY_S: Final = "stop_delay_s"
CONF_MIN_ENERGY_KWH: Final = "min_energy_kwh"
CONF_PRICE_MODE: Final = "price_mode"
CONF_PRICE_FIXED: Final = "price_fixed"
CONF_PRICE_ENTITY: Final = "price_entity"

PRICE_MODE_FIXED: Final = "fixed"
PRICE_MODE_ENTITY: Final = "entity"

DEFAULT_NAME: Final = "Recharge VE"
DEFAULT_THRESHOLD_W: Final = 200.0
DEFAULT_START_DELAY_S: Final = 30
DEFAULT_STOP_DELAY_S: Final = 120
DEFAULT_MIN_ENERGY_KWH: Final = 0.1

CURRENCY: Final = "EUR"

# Bus events
EVENT_CHARGE_STARTED: Final = f"{DOMAIN}_charge_started"
EVENT_CHARGE_ENDED: Final = f"{DOMAIN}_charge_ended"
EVENT_CHARGE_DISCARDED: Final = f"{DOMAIN}_charge_discarded"
