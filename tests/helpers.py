"""Helpers shared by the hass-based tests."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ev_charge_cost.const import (
    CONF_ENERGY_ENTITY,
    CONF_MIN_ENERGY_KWH,
    CONF_POWER_ENTITY,
    CONF_PRICE_FIXED,
    CONF_PRICE_MODE,
    CONF_START_DELAY_S,
    CONF_STOP_DELAY_S,
    CONF_THRESHOLD_W,
    DOMAIN,
    PRICE_MODE_FIXED,
)

POWER = "sensor.ev_power"
ENERGY = "sensor.ev_energy"
PRICE = "sensor.kwh_price"
W = {"unit_of_measurement": "W"}
KWH = {"unit_of_measurement": "kWh"}


def entry_data(**overrides: Any) -> dict[str, Any]:
    return {
        CONF_NAME: "Voiture",
        CONF_POWER_ENTITY: POWER,
        CONF_ENERGY_ENTITY: ENERGY,
        CONF_THRESHOLD_W: 200,
        CONF_START_DELAY_S: 30,
        CONF_STOP_DELAY_S: 120,
        CONF_MIN_ENERGY_KWH: 0.1,
        CONF_PRICE_MODE: PRICE_MODE_FIXED,
        CONF_PRICE_FIXED: 0.25,
        **overrides,
    }


async def setup_entry(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=POWER, title="Voiture", data=entry_data(**overrides)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def set_state(hass: HomeAssistant, entity_id: str, value: Any, attrs: dict) -> None:
    hass.states.async_set(entity_id, str(value), attrs)


async def start_charging(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, energy: float = 100
) -> MockConfigEntry:
    """Set up an entry and drive it into a confirmed session."""
    set_state(hass, POWER, 0, W)
    set_state(hass, ENERGY, energy, KWH)
    entry = await setup_entry(hass)
    set_state(hass, POWER, 3700, W)
    await advance(hass, freezer, 60)
    return entry
