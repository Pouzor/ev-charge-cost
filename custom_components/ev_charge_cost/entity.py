"""Base entity shared by all EV Charge Cost platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN
from .tracker import ChargeTracker


class EvChargeCostEntity(Entity):
    """Entity refreshed whenever the tracker publishes an update."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, tracker: ChargeTracker, description: EntityDescription) -> None:
        self.tracker = tracker
        self.entity_description = description
        self._attr_unique_id = f"{tracker.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracker.entry_id)},
            name=tracker.name,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.tracker.signal, self.async_write_ha_state
            )
        )
