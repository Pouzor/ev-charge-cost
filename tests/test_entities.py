"""Tests for the sensor and binary_sensor entities."""

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.ev_charge_cost.const import DOMAIN

from .helpers import (
    ENERGY,
    KWH,
    POWER,
    W,
    advance,
    set_state,
    setup_entry,
    start_charging,
)

CHARGING = "binary_sensor.voiture_charging"


def _value(hass: HomeAssistant, key: str) -> float:
    return float(hass.states.get(f"sensor.voiture_{key}").state)


async def test_entities_follow_a_session(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    set_state(hass, POWER, 0, W)
    set_state(hass, ENERGY, 100, KWH)
    entry = await setup_entry(hass)

    assert hass.states.get(CHARGING).state == STATE_OFF
    assert _value(hass, "session_energy") == 0
    assert hass.states.get("sensor.voiture_last_session_cost").state == "unknown"
    assert _value(hass, "current_price") == 0.25

    set_state(hass, POWER, 3700, W)
    await advance(hass, freezer, 10)
    # Not confirmed yet: still within the start delay.
    assert hass.states.get(CHARGING).state == STATE_OFF
    assert hass.states.get(CHARGING).attributes["detection_state"] == "pending_start"

    await advance(hass, freezer, 20)
    assert hass.states.get(CHARGING).state == STATE_ON

    set_state(hass, ENERGY, 102, KWH)
    await advance(hass, freezer, 1770)
    assert _value(hass, "session_energy") == 2
    assert _value(hass, "session_cost") == 0.5
    assert _value(hass, "session_duration") == pytest.approx(30)

    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)
    assert hass.states.get(CHARGING).state == STATE_OFF
    assert _value(hass, "session_energy") == 0
    assert _value(hass, "last_session_energy") == 2
    assert _value(hass, "last_session_cost") == 0.5
    assert _value(hass, "last_session_duration") == pytest.approx(30)
    assert _value(hass, "total_energy") == 2
    assert _value(hass, "total_cost") == 0.5
    assert _value(hass, "sessions") == 1

    attrs = hass.states.get("sensor.voiture_last_session_cost").attributes
    assert attrs["energy_kwh"] == 2
    assert len(attrs["tranches"]) == 1

    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.name == "Voiture"
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 12
    assert all(e.device_id == device.id for e in entities)


async def test_totals_survive_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await start_charging(hass, freezer)
    set_state(hass, ENERGY, 101.5, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)
    assert _value(hass, "total_energy") == 1.5

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _value(hass, "total_energy") == 1.5
    assert _value(hass, "last_session_cost") == 0.375
    assert _value(hass, "sessions") == 1
