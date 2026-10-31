"""Tests for the services and the logbook descriptions."""

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_cost.const import (
    DOMAIN,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
)
from custom_components.ev_charge_cost.logbook import async_describe_events

from .helpers import ENERGY, KWH, entry_data, set_state, start_charging


async def test_stop_session_service(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, events
) -> None:
    entry = await start_charging(hass, freezer)
    set_state(hass, ENERGY, 101, KWH)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "stop_session", {"config_entry_id": entry.entry_id}, blocking=True
    )
    (ended,) = events[EVENT_CHARGE_ENDED]
    assert ended.data["energy_kwh"] == 1
    assert hass.states.get("binary_sensor.voiture_charging").state == "off"


async def test_reset_totals_service(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await start_charging(hass, freezer)
    set_state(hass, ENERGY, 101, KWH)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, "stop_session", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert hass.states.get("sensor.voiture_sessions").state == "1"

    await hass.services.async_call(
        DOMAIN, "reset_totals", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert hass.states.get("sensor.voiture_sessions").state == "0"
    assert hass.states.get("sensor.voiture_total_cost").state == "0.0"


async def test_service_rejects_unknown_or_unloaded_entry(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await start_charging(hass, freezer)
    with pytest.raises(ServiceValidationError, match="No EV Charge Cost charge point"):
        await hass.services.async_call(
            DOMAIN, "stop_session", {"config_entry_id": "nope"}, blocking=True
        )

    unloaded = MockConfigEntry(domain=DOMAIN, title="Autre", data=entry_data())
    unloaded.add_to_hass(hass)
    with pytest.raises(ServiceValidationError, match="is not loaded"):
        await hass.services.async_call(
            DOMAIN,
            "stop_session",
            {"config_entry_id": unloaded.entry_id},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("language", "started", "ended"),
    [
        ("en", "started charging", "finished charging: 22.84 kWh, 4.19 € in 6h30"),
        (
            "fr",
            "a démarré une recharge",
            "a terminé une recharge : 22.84 kWh, 4.19 € en 6h30",
        ),
    ],
)
async def test_logbook_messages(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    language: str,
    started: str,
    ended: str,
) -> None:
    entry = await start_charging(hass, freezer)
    hass.config.language = language
    describers = {}
    async_describe_events(
        hass, lambda domain, event_type, fn: describers.__setitem__(event_type, fn)
    )

    base = {"entry_id": entry.entry_id, "name": "Voiture"}
    start = describers[EVENT_CHARGE_STARTED](Event(EVENT_CHARGE_STARTED, base))
    assert start == {
        "name": "Voiture",
        "message": started,
        "entity_id": "binary_sensor.voiture_charging",
    }
    end = describers[EVENT_CHARGE_ENDED](
        Event(
            EVENT_CHARGE_ENDED,
            {**base, "energy_kwh": 22.84, "cost": 4.19, "duration_s": 23370},
        )
    )
    assert end["message"] == ended
