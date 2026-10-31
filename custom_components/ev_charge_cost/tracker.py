"""Home Assistant glue around the pure SessionMachine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, CONF_NAME
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import (
    BaseUnitConverter,
    EnergyConverter,
    PowerConverter,
)

from .const import (
    CONF_ENERGY_ENTITY,
    CONF_MIN_ENERGY_KWH,
    CONF_POWER_ENTITY,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FIXED,
    CONF_PRICE_MODE,
    CONF_START_DELAY_S,
    CONF_STOP_DELAY_S,
    CONF_THRESHOLD_W,
    CURRENCY,
    DOMAIN,
    EVENT_CHARGE_DISCARDED,
    EVENT_CHARGE_ENDED,
    EVENT_CHARGE_STARTED,
    PRICE_MODE_ENTITY,
)
from .session import DetectionConfig, Outcome, SessionEvent, SessionMachine
from .units import parse_float, price_to_eur_per_kwh

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_S = 30
# HA does not fire a state change for an unchanged value: integrate anyway.
TICK_INTERVAL = timedelta(seconds=60)

_EVENTS = {
    SessionEvent.STARTED: EVENT_CHARGE_STARTED,
    SessionEvent.ENDED: EVENT_CHARGE_ENDED,
    SessionEvent.DISCARDED: EVENT_CHARGE_DISCARDED,
}


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


def _convert(
    state: State | None,
    converter: type[BaseUnitConverter],
    default_unit: str,
    target_unit: str,
) -> float | None:
    """Numeric state value converted to ``target_unit``, or None."""
    if state is None or (value := parse_float(state.state)) is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or default_unit
    try:
        return converter.convert(value, unit, target_unit)
    except HomeAssistantError:
        _LOGGER.warning("Unsupported unit %s for %s", unit, state.entity_id)
        return None


def _price(state: State | None) -> float | None:
    if state is None or (value := parse_float(state.state)) is None:
        return None
    return price_to_eur_per_kwh(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))


class ChargeTracker:
    """Feeds entity states to the SessionMachine and publishes its outcomes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry_id = entry.entry_id
        config = {**entry.data, **entry.options}
        self.name: str = config.get(CONF_NAME, entry.title)
        self.power_entity: str = config[CONF_POWER_ENTITY]
        self.energy_entity: str | None = config.get(CONF_ENERGY_ENTITY)
        self.price_entity: str | None = (
            config.get(CONF_PRICE_ENTITY)
            if config[CONF_PRICE_MODE] == PRICE_MODE_ENTITY
            else None
        )
        self._fixed_price: float | None = (
            None if self.price_entity else float(config[CONF_PRICE_FIXED])
        )
        self.machine = SessionMachine(
            DetectionConfig(
                threshold_w=float(config[CONF_THRESHOLD_W]),
                start_delay=timedelta(seconds=config[CONF_START_DELAY_S]),
                stop_delay=timedelta(seconds=config[CONF_STOP_DELAY_S]),
                min_energy_kwh=float(config[CONF_MIN_ENERGY_KWH]),
            ),
            use_energy_meter=self.energy_entity is not None,
            price=self._fixed_price,
        )
        self.signal = f"{DOMAIN}_{entry.entry_id}_update"
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._cancel_deadline: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Restore the persisted state, then start listening."""
        if data := await self._store.async_load():
            self.machine.restore(data)
        now = dt_util.utcnow()
        # Meter first so energy consumed while HA was down lands in the
        # restored session, then the price, then power drives transitions.
        if self.energy_entity:
            self.machine.update_energy(now, self._read_energy())
        if self._fixed_price is not None:
            self.machine.update_price(now, self._fixed_price)
        else:
            self.machine.update_price(now, _price(self._state(self.price_entity)))
        self._publish(self.machine.update_power(now, self._read_power()))

        self._track(self.power_entity, self._on_power)
        if self.energy_entity:
            self._track(self.energy_entity, self._on_energy)
        if self.price_entity:
            self._track(self.price_entity, self._on_price)
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, TICK_INTERVAL)
        )

    async def async_stop(self) -> None:
        """Stop listening and persist the state immediately."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._cancel_deadline:
            self._cancel_deadline()
            self._cancel_deadline = None
        await self._store.async_save(self.machine.as_dict())

    @callback
    def async_force_stop(self) -> None:
        self._publish(self.machine.force_stop(dt_util.utcnow()))

    @callback
    def async_reset_totals(self) -> None:
        self.machine.reset_totals()
        self._publish([])

    def _state(self, entity_id: str | None) -> State | None:
        return self.hass.states.get(entity_id) if entity_id else None

    def _read_power(self) -> float | None:
        return _convert(self._state(self.power_entity), PowerConverter, "W", "W")

    def _read_energy(self) -> float | None:
        return _convert(self._state(self.energy_entity), EnergyConverter, "kWh", "kWh")

    def _track(
        self, entity_id: str, action: Callable[[Event[EventStateChangedData]], None]
    ) -> None:
        self._unsubs.append(
            async_track_state_change_event(self.hass, entity_id, action)
        )

    @callback
    def _on_power(self, event: Event[EventStateChangedData]) -> None:
        self._publish(self.machine.update_power(dt_util.utcnow(), self._read_power()))

    @callback
    def _on_energy(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self.machine.update_energy(now, self._read_energy())
        self._publish(self.machine.check(now))

    @callback
    def _on_price(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self.machine.update_price(now, _price(event.data["new_state"]))
        self._publish(self.machine.check(now))

    @callback
    def _on_tick(self, now: datetime) -> None:
        self._publish(self.machine.check(now))

    @callback
    def _on_deadline(self, now: datetime) -> None:
        self._cancel_deadline = None
        self._publish(self.machine.check(now))

    @callback
    def _publish(self, outcomes: list[Outcome]) -> None:
        """Fire bus events, reschedule the pending delay, notify entities."""
        for event, session in outcomes:
            payload: dict[str, Any] = {
                "entry_id": self.entry_id,
                "name": self.name,
                "power_entity": self.power_entity,
            }
            if event is SessionEvent.STARTED:
                payload["start"] = session.start.isoformat()
            else:
                payload.update(session.summary(), currency=CURRENCY)
            _LOGGER.debug("%s: %s", _EVENTS[event], payload)
            self.hass.bus.async_fire(_EVENTS[event], payload)

        if self._cancel_deadline:
            self._cancel_deadline()
            self._cancel_deadline = None
        # A past deadline means power is unknown: the next reading resolves it.
        deadline = self.machine.next_deadline()
        if deadline is not None and deadline > dt_util.utcnow():
            self._cancel_deadline = async_track_point_in_utc_time(
                self.hass, self._on_deadline, deadline
            )

        self._store.async_delay_save(self.machine.as_dict, SAVE_DELAY_S)
        async_dispatcher_send(self.hass, self.signal)
