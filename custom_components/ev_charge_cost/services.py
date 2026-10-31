"""Integration-wide services targeting one charge point."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .tracker import ChargeTracker

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
SERVICE_STOP_SESSION = "stop_session"
SERVICE_RESET_TOTALS = "reset_totals"

SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})


def _tracker(hass: HomeAssistant, call: ServiceCall) -> ChargeTracker:
    entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"name": entry.title},
        )
    return entry.runtime_data


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    @callback
    def stop_session(call: ServiceCall) -> None:
        _tracker(hass, call).async_force_stop()

    @callback
    def reset_totals(call: ServiceCall) -> None:
        _tracker(hass, call).async_reset_totals()

    hass.services.async_register(DOMAIN, SERVICE_STOP_SESSION, stop_session, SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_TOTALS, reset_totals, SCHEMA)
