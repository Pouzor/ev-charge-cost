"""Calendar of charge sessions: one event per session."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EvChargeCostConfigEntry
from .entity import EvChargeCostEntity
from .session import ChargeSession
from .units import currency_symbol, format_duration

HISTORY = EntityDescription(key="history", translation_key="history")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeCostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChargeHistoryCalendar(entry.runtime_data, HISTORY)])


class ChargeHistoryCalendar(EvChargeCostEntity, CalendarEntity):
    """Completed sessions, plus the session in progress while charging."""

    # Set on the entity: recent HA reads it from a CalendarEntityDescription,
    # which older supported versions do not have.
    _attr_initial_color: str | None = None

    @property
    def event(self) -> CalendarEvent | None:
        """The session in progress: the calendar is `on` while charging."""
        session = self._ongoing()
        return self._to_event(session) if session else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        sessions = list(self.tracker.history)
        if ongoing := self._ongoing():
            sessions.append(ongoing)
        now = dt_util.utcnow()
        return [
            self._to_event(s)
            for s in sessions
            if s.start < end_date and (s.end or now) > start_date
        ]

    def _ongoing(self) -> ChargeSession | None:
        machine = self.tracker.machine
        return machine.session if machine.charging else None

    def _to_event(self, session: ChargeSession) -> CalendarEvent:
        symbol = currency_symbol(self.tracker.currency)
        now = dt_util.utcnow()
        duration = (session.end or now) - session.start
        # The calendar is `on` only while now < end: an ongoing session ends a
        # minute ahead, pushed forward by the tracker tick.
        end = session.end or now + timedelta(minutes=1)
        end = max(end, session.start + timedelta(seconds=1))
        lines = [f"Duration: {format_duration(duration.total_seconds())}"]
        if (avg := session.avg_price) is not None:
            lines.append(f"Average price: {avg:.4f} {symbol}/kWh")
        if session.price_estimated:
            lines.append("Price estimated (price entity was unavailable)")
        for tranche in session.tranches:
            to = dt_util.as_local(tranche.end or now).strftime("%H:%M")
            price = "?" if tranche.price is None else f"{tranche.price:.4f}"
            lines.append(
                f"{dt_util.as_local(tranche.start).strftime('%H:%M')}-{to}: "
                f"{tranche.energy_kwh:.3f} kWh x {price} {symbol}/kWh "
                f"= {tranche.cost:.2f} {symbol}"
            )
        return CalendarEvent(
            start=dt_util.as_local(session.start),
            end=dt_util.as_local(end),
            summary=f"⚡ {session.energy_kwh:.2f} kWh · {session.cost:.2f} {symbol}",
            description="\n".join(lines),
            uid=f"{self.tracker.entry_id}_{session.start.isoformat()}",
        )
