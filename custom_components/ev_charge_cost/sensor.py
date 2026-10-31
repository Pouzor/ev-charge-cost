"""Session, last-session and cumulative sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EvChargeCostConfigEntry
from .const import CURRENCY
from .entity import EvChargeCostEntity
from .session import ChargeSession, SessionMachine

PRICE_UNIT = f"{CURRENCY}/{UnitOfEnergy.KILO_WATT_HOUR}"


def _minutes(session: ChargeSession) -> float:
    return session.duration(dt_util.utcnow()).total_seconds() / 60


def _current(fn: Callable[[ChargeSession], float]) -> Callable[[SessionMachine], Any]:
    """Value of the confirmed session in progress, 0 outside a session."""
    return lambda m: fn(m.session) if m.charging and m.session else 0


def _last(fn: Callable[[ChargeSession], float]) -> Callable[[SessionMachine], Any]:
    return lambda m: fn(m.last_session) if m.last_session else None


def _last_attrs(machine: SessionMachine) -> dict[str, Any] | None:
    return machine.last_session.summary() if machine.last_session else None


@dataclass(frozen=True, kw_only=True)
class EvChargeCostSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SessionMachine], Any]
    attrs_fn: Callable[[SessionMachine], dict[str, Any] | None] = lambda _: None


def _energy(key: str, state_class: SensorStateClass | None, value_fn):
    return EvChargeCostSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        state_class=state_class,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=value_fn,
    )


def _cost(key: str, state_class: SensorStateClass | None, value_fn, **kwargs):
    return EvChargeCostSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.MONETARY,
        state_class=state_class,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=value_fn,
        **kwargs,
    )


def _duration(key: str, value_fn):
    return EvChargeCostSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=value_fn,
    )


SENSORS: tuple[EvChargeCostSensorDescription, ...] = (
    # Drops to 0 between sessions: TOTAL_INCREASING treats that as a reset.
    _energy(
        "session_energy",
        SensorStateClass.TOTAL_INCREASING,
        _current(lambda s: s.energy_kwh),
    ),
    # MONETARY only allows TOTAL, which would record the drop as negative cost.
    _cost("session_cost", None, _current(lambda s: s.cost)),
    _duration("session_duration", _current(_minutes)),
    _energy("last_session_energy", None, _last(lambda s: s.energy_kwh)),
    _cost("last_session_cost", None, _last(lambda s: s.cost), attrs_fn=_last_attrs),
    _duration("last_session_duration", _last(_minutes)),
    _energy(
        "total_energy",
        SensorStateClass.TOTAL_INCREASING,
        lambda m: m.totals.energy_kwh,
    ),
    _cost("total_cost", SensorStateClass.TOTAL, lambda m: m.totals.cost),
    EvChargeCostSensorDescription(
        key="session_count",
        translation_key="session_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.totals.count,
    ),
    EvChargeCostSensorDescription(
        key="current_price",
        translation_key="current_price",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda m: m.price,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeCostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    tracker = entry.runtime_data
    async_add_entities(EvChargeCostSensor(tracker, d) for d in SENSORS)


class EvChargeCostSensor(EvChargeCostEntity, SensorEntity):
    entity_description: EvChargeCostSensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.tracker.machine)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.tracker.machine)
