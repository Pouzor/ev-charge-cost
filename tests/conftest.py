"""Shared fixtures."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.ev_charge_cost.const import (
    EVENT_CHARGE_DISCARDED,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture
def events(hass: HomeAssistant) -> dict[str, list]:
    """Captured charge events, keyed by event type."""
    return {
        name: async_capture_events(hass, name)
        for name in (EVENT_CHARGE_STARTED, EVENT_CHARGE_ENDED, EVENT_CHARGE_DISCARDED)
    }
