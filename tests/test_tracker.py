"""Integration tests for the tracker running inside hass."""

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.ev_charge_cost.const import (
    CONF_ENERGY_ENTITY,
    CONF_MIN_ENERGY_KWH,
    CONF_POWER_ENTITY,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FIXED,
    CONF_PRICE_MODE,
    CONF_START_DELAY_S,
    CONF_STOP_DELAY_S,
    CONF_THRESHOLD_W,
    DOMAIN,
    EVENT_CHARGE_DISCARDED,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
    PRICE_MODE_ENTITY,
    PRICE_MODE_FIXED,
)
from custom_components.ev_charge_cost.session import State

POWER = "sensor.ev_power"
ENERGY = "sensor.ev_energy"
PRICE = "sensor.kwh_price"
W = {"unit_of_measurement": "W"}
KWH = {"unit_of_measurement": "kWh"}


def _data(**overrides: Any) -> dict[str, Any]:
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


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=POWER, title="Voiture", data=_data(**overrides)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _set(hass: HomeAssistant, entity_id: str, value: float, attrs: dict) -> None:
    hass.states.async_set(entity_id, str(value), attrs)


@pytest.fixture
def events(hass: HomeAssistant) -> dict[str, list]:
    return {
        name: async_capture_events(hass, name)
        for name in (EVENT_CHARGE_STARTED, EVENT_CHARGE_ENDED, EVENT_CHARGE_DISCARDED)
    }


async def test_session_with_energy_meter(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 125.85, KWH)
    entry = await _setup(hass)

    _set(hass, POWER, 3700, W)
    await hass.async_block_till_done()
    await _advance(hass, freezer, 29)
    assert events[EVENT_CHARGE_STARTED] == []
    await _advance(hass, freezer, 1)
    assert len(events[EVENT_CHARGE_STARTED]) == 1
    assert events[EVENT_CHARGE_STARTED][0].data["name"] == "Voiture"

    await _advance(hass, freezer, 3570)
    _set(hass, ENERGY, 129.55, KWH)
    _set(hass, POWER, 0, W)
    await hass.async_block_till_done()
    await _advance(hass, freezer, 119)
    assert events[EVENT_CHARGE_ENDED] == []
    await _advance(hass, freezer, 1)

    (ended,) = events[EVENT_CHARGE_ENDED]
    assert ended.data["energy_kwh"] == 3.7
    assert ended.data["cost"] == 0.93
    assert ended.data["duration_s"] == 3600
    assert ended.data["currency"] == "EUR"
    assert ended.data["entry_id"] == entry.entry_id
    assert entry.runtime_data.machine.state is State.IDLE


async def test_brief_spike_is_ignored(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 10, KWH)
    await _setup(hass)
    _set(hass, POWER, 2000, W)
    await _advance(hass, freezer, 10)
    _set(hass, POWER, 0, W)
    await _advance(hass, freezer, 300)
    assert all(not captured for captured in events.values())


async def test_price_entity_change_mid_session(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 100, KWH)
    _set(hass, PRICE, 25.16, {"unit_of_measurement": "c€/kWh"})
    await _setup(hass, **{CONF_PRICE_MODE: PRICE_MODE_ENTITY, CONF_PRICE_ENTITY: PRICE})

    _set(hass, POWER, 3700, W)
    await _advance(hass, freezer, 1000)
    _set(hass, ENERGY, 101, KWH)
    _set(hass, PRICE, 18.02, {"unit_of_measurement": "c€/kWh"})
    await _advance(hass, freezer, 1000)
    _set(hass, ENERGY, 103, KWH)
    _set(hass, POWER, 0, W)
    await _advance(hass, freezer, 120)

    (ended,) = events[EVENT_CHARGE_ENDED]
    assert [t["price"] for t in ended.data["tranches"]] == pytest.approx(
        [0.2516, 0.1802]
    )
    assert [t["kwh"] for t in ended.data["tranches"]] == [1.0, 2.0]
    assert ended.data["cost"] == round(0.2516 + 2 * 0.1802, 2)


async def test_power_integration_and_kw_unit(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    kw = {"unit_of_measurement": "kW"}
    _set(hass, POWER, 0, kw)
    await _setup(hass, **{CONF_ENERGY_ENTITY: None})

    _set(hass, POWER, 3.6, kw)
    await hass.async_block_till_done()
    # Value never changes: the periodic tick must keep integrating.
    for _ in range(60):
        await _advance(hass, freezer, 60)
    _set(hass, POWER, 0, kw)
    await _advance(hass, freezer, 120)

    (ended,) = events[EVENT_CHARGE_ENDED]
    assert ended.data["energy_kwh"] == pytest.approx(3.6, abs=0.01)
    assert ended.data["cost"] == 0.9


async def test_short_session_is_discarded(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 10, KWH)
    await _setup(hass)
    _set(hass, POWER, 3700, W)
    await _advance(hass, freezer, 40)
    _set(hass, ENERGY, 10.04, KWH)
    _set(hass, POWER, 0, W)
    await _advance(hass, freezer, 120)
    assert len(events[EVENT_CHARGE_STARTED]) == 1
    assert events[EVENT_CHARGE_ENDED] == []
    assert len(events[EVENT_CHARGE_DISCARDED]) == 1


async def test_session_survives_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 100, KWH)
    entry = await _setup(hass)
    _set(hass, POWER, 3700, W)
    await _advance(hass, freezer, 600)
    _set(hass, ENERGY, 100.6, KWH)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    # Charge goes on while the integration is down.
    await _advance(hass, freezer, 3000)
    _set(hass, ENERGY, 103.7, KWH)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.machine.state is State.CHARGING

    _set(hass, POWER, 0, W)
    await _advance(hass, freezer, 120)
    (ended,) = events[EVENT_CHARGE_ENDED]
    assert ended.data["energy_kwh"] == 3.7
    assert ended.data["duration_s"] == 3600
    assert len(events[EVENT_CHARGE_STARTED]) == 1


async def test_unavailable_power_keeps_session_open(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 100, KWH)
    entry = await _setup(hass)
    _set(hass, POWER, 3700, W)
    await _advance(hass, freezer, 60)
    hass.states.async_set(POWER, "unavailable")
    await _advance(hass, freezer, 600)
    assert entry.runtime_data.machine.state is State.CHARGING
    assert events[EVENT_CHARGE_ENDED] == []


async def test_force_stop_and_reset_totals(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    _set(hass, POWER, 0, W)
    _set(hass, ENERGY, 100, KWH)
    entry = await _setup(hass)
    _set(hass, POWER, 3700, W)
    await _advance(hass, freezer, 600)
    _set(hass, ENERGY, 101, KWH)
    await hass.async_block_till_done()

    tracker = entry.runtime_data
    tracker.async_force_stop()
    await hass.async_block_till_done()
    assert len(events[EVENT_CHARGE_ENDED]) == 1
    assert tracker.machine.totals.count == 1

    tracker.async_reset_totals()
    assert tracker.machine.totals.count == 0
