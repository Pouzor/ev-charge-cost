"""Describe charge events in the logbook."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    EVENT_CHARGE_DISCARDED,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
)
from .units import currency_symbol, format_duration

# Logbook messages are not translatable through strings.json. The frontend
# prints them after the name of the linked `charging` entity, hence the dash.
_MESSAGES = {
    "en": {
        EVENT_CHARGE_STARTED: "— session started",
        EVENT_CHARGE_ENDED: (
            "— session ended: {energy} kWh, {cost} {currency} in {duration}"
        ),
        EVENT_CHARGE_DISCARDED: "— short session discarded ({energy} kWh)",
    },
    "fr": {
        EVENT_CHARGE_STARTED: "— session démarrée",
        EVENT_CHARGE_ENDED: (
            "— session terminée : {energy} kWh, {cost} {currency} en {duration}"
        ),
        EVENT_CHARGE_DISCARDED: "— session trop courte ignorée ({energy} kWh)",
    },
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    messages = _MESSAGES.get(hass.config.language.split("-")[0], _MESSAGES["en"])

    @callback
    def describe(event: Event) -> dict[str, Any]:
        data = event.data
        message = messages[event.event_type].format(
            energy=data.get("energy_kwh"),
            cost=f"{data.get('cost', 0):.2f}",
            duration=format_duration(data.get("duration_s", 0)),
            currency=currency_symbol(data.get("currency", hass.config.currency)),
        )
        entry: dict[str, Any] = {
            LOGBOOK_ENTRY_NAME: data.get("name", DOMAIN),
            LOGBOOK_ENTRY_MESSAGE: message,
        }
        entity_id = er.async_get(hass).async_get_entity_id(
            "binary_sensor", DOMAIN, f"{data.get('entry_id')}_charging"
        )
        if entity_id:
            entry[LOGBOOK_ENTRY_ENTITY_ID] = entity_id
        return entry

    for event_type in (
        EVENT_CHARGE_STARTED,
        EVENT_CHARGE_ENDED,
        EVENT_CHARGE_DISCARDED,
    ):
        async_describe_event(DOMAIN, event_type, describe)
