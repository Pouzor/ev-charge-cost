"""Pure charge-session logic, independent from Home Assistant.

All inputs are explicit (timestamps, watts, kWh, EUR/kWh) so the whole state
machine and the cost accounting can be unit-tested without a running hass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class State(StrEnum):
    """Detection state."""

    IDLE = "idle"
    PENDING_START = "pending_start"
    CHARGING = "charging"
    PENDING_STOP = "pending_stop"


class SessionEvent(StrEnum):
    """Outcome emitted by the state machine."""

    STARTED = "started"
    ENDED = "ended"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class DetectionConfig:
    """Thresholds and delays used to detect a session."""

    threshold_w: float
    start_delay: timedelta
    stop_delay: timedelta
    min_energy_kwh: float


@dataclass
class Tranche:
    """A slice of a session billed at a single price."""

    start: datetime
    price: float | None
    end: datetime | None = None
    energy_kwh: float = 0.0

    @property
    def cost(self) -> float:
        return self.energy_kwh * self.price if self.price is not None else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "price": self.price,
            "energy_kwh": self.energy_kwh,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tranche:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]) if data["end"] else None,
            price=data["price"],
            energy_kwh=data["energy_kwh"],
        )


@dataclass
class ChargeSession:
    """A charge session; cost is always the sum of its tranches."""

    start: datetime
    tranches: list[Tranche] = field(default_factory=list)
    end: datetime | None = None
    price_estimated: bool = False

    @classmethod
    def begin(cls, start: datetime, price: float | None) -> ChargeSession:
        return cls(start=start, tranches=[Tranche(start=start, price=price)])

    @property
    def energy_kwh(self) -> float:
        return sum(t.energy_kwh for t in self.tranches)

    @property
    def cost(self) -> float:
        return sum(t.cost for t in self.tranches)

    @property
    def avg_price(self) -> float | None:
        energy = self.energy_kwh
        return self.cost / energy if energy > 0 else None

    def duration(self, now: datetime | None = None) -> timedelta:
        end = self.end or now or self.start
        return end - self.start

    def add_energy(self, kwh: float) -> None:
        self.tranches[-1].energy_kwh += kwh

    def change_price(self, now: datetime, price: float) -> None:
        """Close the current tranche and open a new one at the new price."""
        current = self.tranches[-1]
        if current.price is None:
            # Price was unknown until now: bill what was consumed at this price.
            if current.energy_kwh > 0:
                self.price_estimated = True
            current.price = price
            return
        if price == current.price:
            return
        if current.energy_kwh == 0:
            current.price = price
            return
        current.end = now
        self.tranches.append(Tranche(start=now, price=price))

    def close(self, end: datetime) -> None:
        self.end = end
        self.tranches[-1].end = end

    def summary(self) -> dict[str, Any]:
        """Payload used for bus events and entity attributes."""
        avg = self.avg_price
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "duration_s": int(self.duration().total_seconds()),
            "energy_kwh": round(self.energy_kwh, 3),
            "cost": round(self.cost, 2),
            "avg_price": round(avg, 4) if avg is not None else None,
            "price_estimated": self.price_estimated,
            "tranches": [
                {
                    "from": t.start.isoformat(),
                    "to": t.end.isoformat() if t.end else None,
                    "price": t.price,
                    "kwh": round(t.energy_kwh, 3),
                    "cost": round(t.cost, 2),
                }
                for t in self.tranches
            ],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "price_estimated": self.price_estimated,
            "tranches": [t.as_dict() for t in self.tranches],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChargeSession:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]) if data["end"] else None,
            price_estimated=data["price_estimated"],
            tranches=[Tranche.from_dict(t) for t in data["tranches"]],
        )


@dataclass
class Totals:
    """Cumulated figures over all kept sessions."""

    energy_kwh: float = 0.0
    cost: float = 0.0
    count: int = 0


Outcome = tuple[SessionEvent, ChargeSession]


class SessionMachine:
    """Detects charge sessions and accounts their energy and cost.

    Energy comes either from a cumulative meter (``update_energy``) or, when
    ``use_energy_meter`` is False, from a left Riemann sum of the power. Since
    Home Assistant does not fire a state change when a value is unchanged, the
    caller must call ``check`` periodically and at ``next_deadline``.
    """

    def __init__(
        self,
        config: DetectionConfig,
        *,
        use_energy_meter: bool,
        price: float | None = None,
    ) -> None:
        self.config = config
        self.use_energy_meter = use_energy_meter
        self.state = State.IDLE
        self.session: ChargeSession | None = None
        self.last_session: ChargeSession | None = None
        self.totals = Totals()
        self._price = price
        self._price_stale = False
        self._power_w: float | None = None
        self._power_at: datetime | None = None
        self._meter_kwh: float | None = None
        self._below_since: datetime | None = None

    @property
    def price(self) -> float | None:
        return self._price

    @property
    def charging(self) -> bool:
        return self.state in (State.CHARGING, State.PENDING_STOP)

    def update_power(self, now: datetime, watts: float | None) -> list[Outcome]:
        """Feed a new power reading; ``None`` means unavailable/unknown."""
        self._integrate(now)
        self._power_w = watts
        self._power_at = now
        if watts is None:
            return []

        above = watts > self.config.threshold_w
        if self.state is State.IDLE and above:
            self.state = State.PENDING_START
            self.session = ChargeSession.begin(now, self._price)
        elif self.state is State.PENDING_START and not above:
            self.state = State.IDLE
            self.session = None
        elif self.state is State.CHARGING and not above:
            self.state = State.PENDING_STOP
            self._below_since = now
        elif self.state is State.PENDING_STOP and above:
            self.state = State.CHARGING
            self._below_since = None
        return self.check(now)

    def update_energy(self, now: datetime, kwh: float | None) -> None:
        """Feed a cumulative meter reading (kWh); ``None`` is ignored."""
        if kwh is None:
            return
        previous, self._meter_kwh = self._meter_kwh, kwh
        if previous is None or not self.use_energy_meter:
            return
        # A decrease means the meter was reset (total_increasing semantics).
        self._add_energy(kwh - previous if kwh >= previous else kwh)

    def update_price(self, now: datetime, price: float | None) -> None:
        """Feed a new EUR/kWh price; ``None`` keeps the last known price."""
        if price is None:
            self._price_stale = True
            return
        self._integrate(now)
        self._price = price
        self._price_stale = False
        if self.session is not None:
            self.session.change_price(now, price)

    def check(self, now: datetime) -> list[Outcome]:
        """Integrate up to ``now`` and apply elapsed start/stop delays."""
        self._integrate(now)
        if self._power_w is None or self.session is None:
            return []
        if (
            self.state is State.PENDING_START
            and now - self.session.start >= self.config.start_delay
        ):
            self.state = State.CHARGING
            return [(SessionEvent.STARTED, self.session)]
        if (
            self.state is State.PENDING_STOP
            and self._below_since is not None
            and now - self._below_since >= self.config.stop_delay
        ):
            return self._finalize(self._below_since)
        return []

    def next_deadline(self) -> datetime | None:
        """When ``check`` must be called for a pending delay to elapse."""
        if self.state is State.PENDING_START and self.session is not None:
            return self.session.start + self.config.start_delay
        if self.state is State.PENDING_STOP and self._below_since is not None:
            return self._below_since + self.config.stop_delay
        return None

    def force_stop(self, now: datetime) -> list[Outcome]:
        """End the current session immediately (service call)."""
        self._integrate(now)
        if self.state is State.PENDING_START:
            self.state = State.IDLE
            self.session = None
            return []
        if self.charging:
            return self._finalize(self._below_since or now)
        return []

    def reset_totals(self) -> None:
        self.totals = Totals()

    def _add_energy(self, kwh: float) -> None:
        if self.session is None or kwh <= 0:
            return
        self.session.add_energy(kwh)
        if self._price is None or self._price_stale:
            self.session.price_estimated = True

    def _integrate(self, now: datetime) -> None:
        if self.use_energy_meter or self._power_at is None or now <= self._power_at:
            return
        if self._power_w is not None and self._power_w > 0:
            hours = (now - self._power_at).total_seconds() / 3600
            self._add_energy(self._power_w / 1000 * hours)
        self._power_at = now

    def _finalize(self, end: datetime) -> list[Outcome]:
        session = self.session
        assert session is not None
        session.close(end)
        self.state = State.IDLE
        self.session = None
        self._below_since = None
        if session.energy_kwh < self.config.min_energy_kwh:
            return [(SessionEvent.DISCARDED, session)]
        self.last_session = session
        self.totals.energy_kwh += session.energy_kwh
        self.totals.cost += session.cost
        self.totals.count += 1
        return [(SessionEvent.ENDED, session)]

    def as_dict(self) -> dict[str, Any]:
        """Serializable snapshot for persistence across restarts."""
        return {
            "state": self.state.value,
            "session": self.session.as_dict() if self.session else None,
            "last_session": self.last_session.as_dict() if self.last_session else None,
            "totals": {
                "energy_kwh": self.totals.energy_kwh,
                "cost": self.totals.cost,
                "count": self.totals.count,
            },
            "price": self._price,
            "meter_kwh": self._meter_kwh,
            "below_since": self._below_since.isoformat() if self._below_since else None,
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Load a snapshot produced by ``as_dict``.

        The power reading is not restored: transitions resume on the next
        ``update_power``.
        """
        self.state = State(data["state"])
        self.session = (
            ChargeSession.from_dict(data["session"]) if data["session"] else None
        )
        self.last_session = (
            ChargeSession.from_dict(data["last_session"])
            if data["last_session"]
            else None
        )
        self.totals = Totals(**data["totals"])
        self._price = data["price"]
        self._meter_kwh = data["meter_kwh"]
        self._below_since = (
            datetime.fromisoformat(data["below_since"]) if data["below_since"] else None
        )
        if self.session is None:
            self.state = State.IDLE
