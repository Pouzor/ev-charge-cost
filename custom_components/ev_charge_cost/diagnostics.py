"""Diagnostics: everything needed to understand a detection or cost issue."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import EvChargeCostConfigEntry

# Number of most recent sessions included in full.
RECENT_SESSIONS = 5


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EvChargeCostConfigEntry
) -> dict[str, Any]:
    tracker = entry.runtime_data
    machine = tracker.machine
    sources = {}
    for role, entity_id in (
        ("power", tracker.power_entity),
        ("energy", tracker.energy_entity),
        ("price", tracker.price_entity),
        ("odometer", tracker.odometer_entity),
    ):
        if entity_id is None:
            continue
        state = hass.states.get(entity_id)
        sources[role] = {
            "entity_id": entity_id,
            "state": state.state if state else None,
            "attributes": dict(state.attributes) if state else None,
            "last_updated": state.last_updated.isoformat() if state else None,
        }
    return {
        "config": {**entry.data, **entry.options},
        "currency": tracker.currency,
        "sources": sources,
        "machine": machine.as_dict(),
        "next_deadline": (
            deadline.isoformat() if (deadline := machine.next_deadline()) else None
        ),
        "history": {
            "count": len(tracker.history),
            "recent": [s.summary() for s in tracker.history[-RECENT_SESSIONS:]],
        },
    }
