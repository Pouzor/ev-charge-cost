"""Tests for the config entry diagnostics."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.ev_charge_cost.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import ENERGY, KWH, POWER, W, advance, set_state, start_charging


async def test_diagnostics(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry = await start_charging(hass, freezer)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["config"]["power_entity"] == POWER
    assert diagnostics["currency"] == "EUR"
    assert diagnostics["machine"]["state"] == "charging"
    assert diagnostics["sources"]["power"]["state"] == "3700"
    assert (
        diagnostics["sources"]["energy"]["attributes"]["unit_of_measurement"] == "kWh"
    )
    assert "price" not in diagnostics["sources"]  # fixed price mode
    assert diagnostics["history"] == {"count": 0, "recent": []}

    set_state(hass, ENERGY, 101, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 30)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["machine"]["state"] == "pending_stop"
    assert diagnostics["next_deadline"] is not None

    await advance(hass, freezer, 120)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["history"]["count"] == 1
    assert diagnostics["history"]["recent"][0]["energy_kwh"] == 1
