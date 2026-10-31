"""Charging binary sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvChargeCostConfigEntry
from .entity import EvChargeCostEntity

CHARGING = BinarySensorEntityDescription(
    key="charging",
    translation_key="charging",
    device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeCostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChargingBinarySensor(entry.runtime_data, CHARGING)])


class ChargingBinarySensor(EvChargeCostEntity, BinarySensorEntity):
    """On while a session is confirmed (charging or waiting for the stop delay)."""

    @property
    def is_on(self) -> bool:
        return self.tracker.machine.charging

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"detection_state": self.tracker.machine.state.value}
