"""EV Charge Cost integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .tracker import STORAGE_VERSION, ChargeTracker, storage_key

# Entity platforms are added next (see FEATURE.md §6).
PLATFORMS: list[Platform] = []

type EvChargeCostConfigEntry = ConfigEntry[ChargeTracker]


async def async_setup_entry(
    hass: HomeAssistant, entry: EvChargeCostConfigEntry
) -> bool:
    """Set up a charge point from a config entry."""
    tracker = ChargeTracker(hass, entry)
    await tracker.async_start()
    entry.runtime_data = tracker
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: EvChargeCostConfigEntry
) -> bool:
    """Unload a config entry, persisting the current session."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the persisted sessions and totals."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: EvChargeCostConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
