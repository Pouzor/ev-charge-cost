"""Odometer: distance between charges, consumption and cost per 100 km."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.ev_charge_cost.const import (
    CONF_ODOMETER_ENTITY,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
)

from .helpers import ENERGY, KWH, POWER, W, advance, set_state, setup_entry

ODOMETER = "sensor.car_mileage"
KM = {"unit_of_measurement": "km", "device_class": "distance"}
CALENDAR = "calendar.voiture_charge_history"


async def _charge(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, kwh: float
) -> None:
    meter = float(hass.states.get(ENERGY).state)
    set_state(hass, POWER, 3700, W)
    await advance(hass, freezer, 60)
    set_state(hass, ENERGY, meter + kwh, KWH)
    set_state(hass, POWER, 0, W)
    await advance(hass, freezer, 120)


async def _setup(hass: HomeAssistant):
    set_state(hass, POWER, 0, W)
    set_state(hass, ENERGY, 100, KWH)
    set_state(hass, ODOMETER, 800, KM)
    return await setup_entry(hass, **{CONF_ODOMETER_ENTITY: ODOMETER})


async def test_events_sensors_and_calendar(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    start = dt_util.utcnow()
    await _setup(hass)
    assert hass.states.get("sensor.voiture_last_session_distance").state == "unknown"

    await _charge(hass, freezer, 10)
    first = events[EVENT_CHARGE_ENDED][0].data
    assert first["odometer_km"] == 800
    assert first["distance_km"] is None
    assert first["kwh_per_100km"] is None

    await advance(hass, freezer, 3600)
    set_state(hass, ODOMETER, 950, KM)
    await _charge(hass, freezer, 22.5)

    started = events[EVENT_CHARGE_STARTED][1].data
    assert started["distance_km"] == 150
    assert "kwh_per_100km" not in started
    ended = events[EVENT_CHARGE_ENDED][1].data
    assert ended["distance_km"] == 150
    assert ended["kwh_per_100km"] == 15
    assert ended["cost_per_100km"] == 3.75

    def value(key: str) -> float:
        return float(hass.states.get(f"sensor.voiture_last_session_{key}").state)

    assert value("distance") == 150
    assert value("consumption") == 15
    assert value("cost_per_100_km") == 3.75
    assert (
        hass.states.get("sensor.voiture_last_session_cost_per_100_km").attributes[
            "unit_of_measurement"
        ]
        == "EUR/100 km"
    )

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": start, "end_date_time": dt_util.utcnow()},
        target={"entity_id": CALENDAR},
        blocking=True,
        return_response=True,
    )
    first_event, second_event = response[CALENDAR]["events"]
    assert first_event["summary"] == "⚡ 10.00 kWh · 2.50 €"
    assert second_event["summary"] == "⚡ 22.50 kWh · 5.62 € · 150 km"
    assert "Distance since previous charge: 150 km" in second_event["description"]
    assert "Consumption: 15.0 kWh/100 km" in second_event["description"]
    assert "Cost: 3.75 €/100 km" in second_event["description"]


async def test_reference_survives_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    entry = await _setup(hass)
    await _charge(hass, freezer, 10)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    set_state(hass, ODOMETER, 900, KM)
    await _charge(hass, freezer, 15)
    assert events[EVENT_CHARGE_ENDED][1].data["distance_km"] == 100


async def test_miles_are_converted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    await _setup(hass)
    set_state(hass, ODOMETER, 500, {"unit_of_measurement": "mi"})
    await _charge(hass, freezer, 10)
    assert events[EVENT_CHARGE_ENDED][0].data["odometer_km"] == 804.7


async def test_without_odometer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    set_state(hass, POWER, 0, W)
    set_state(hass, ENERGY, 100, KWH)
    await setup_entry(hass)
    await _charge(hass, freezer, 10)
    assert "distance_km" not in events[EVENT_CHARGE_STARTED][0].data
    assert "distance_km" not in events[EVENT_CHARGE_ENDED][0].data
    assert hass.states.get("sensor.voiture_last_session_distance") is None
