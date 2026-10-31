"""Tests for the charge history calendar."""

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.ev_charge_cost import tracker as tracker_module

from .helpers import ENERGY, KWH, POWER, W, advance, set_state, start_charging

CALENDAR = "calendar.voiture_charge_history"


async def _events(hass: HomeAssistant, start, end) -> list[dict]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": start, "end_date_time": end},
        target={"entity_id": CALENDAR},
        blocking=True,
        return_response=True,
    )
    return response[CALENDAR]["events"]


async def _charge(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, kwh: float
) -> None:
    """Run one more confirmed session consuming ``kwh`` from the meter."""
    meter = float(hass.states.get(ENERGY).state)
    set_state(hass, POWER, 3700, W)
    await advance(hass, freezer, 60)
    set_state(hass, ENERGY, meter + kwh, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)


async def test_calendar_lists_sessions(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    start = dt_util.utcnow()
    entry = await start_charging(hass, freezer)
    assert hass.states.get(CALENDAR).state == STATE_ON
    assert hass.states.get(CALENDAR).attributes["message"].startswith("⚡ 0.00 kWh")

    set_state(hass, ENERGY, 102, KWH)
    await advance(hass, freezer, 1740)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)
    assert hass.states.get(CALENDAR).state == STATE_OFF

    (event,) = await _events(hass, start, dt_util.utcnow())
    assert event["summary"] == "⚡ 2.00 kWh · 0.50 €"
    assert dt_util.parse_datetime(event["start"]) == start
    assert dt_util.parse_datetime(event["end"]) - start == timedelta(minutes=30)
    assert "Duration: 30 min" in event["description"]
    assert "Average price: 0.2500 €/kWh" in event["description"]
    assert "2.000 kWh x 0.2500 €/kWh = 0.50 €" in event["description"]

    # Outside the requested range: nothing.
    assert (
        await _events(hass, start - timedelta(days=2), start - timedelta(days=1)) == []
    )

    # History survives a reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(await _events(hass, start, dt_util.utcnow())) == 1


async def test_discarded_sessions_are_not_listed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    start = dt_util.utcnow()
    await start_charging(hass, freezer)
    set_state(hass, ENERGY, 100.01, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)
    assert await _events(hass, start, dt_util.utcnow()) == []


async def test_history_is_capped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tracker_module, "MAX_HISTORY", 2)
    start = dt_util.utcnow()
    await start_charging(hass, freezer)
    set_state(hass, ENERGY, 101, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)
    await _charge(hass, freezer, 2)
    await _charge(hass, freezer, 3)

    events = await _events(hass, start, dt_util.utcnow())
    assert [e["summary"].split(" kWh")[0] for e in events] == ["⚡ 2.00", "⚡ 3.00"]
