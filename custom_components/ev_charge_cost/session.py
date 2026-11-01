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
    # Odometer reading (km) during the session, and the distance driven since
    # the previous kept session: the energy charged here replenishes it.
    odometer_km: float | None = None
    distance_km: float | None = None

    @classmethod
    def begin(cls, start: datetime, price: float | None) -> ChargeSession:
        return cls(start=start, tranches=[Tranche(start=start, price=price)])

    def set_odometer(self, km: float, reference_km: float | None) -> None:
        """Record the odometer; the distance needs a non-decreasing reference."""
        self.odometer_km = km
        self.distance_km = (
            km - reference_km
            if reference_km is not None and km >= reference_km
            else None
        )

    def _per_100km(self, value: float) -> float | None:
        if self.distance_km is None or self.distance_km <= 0:
            return None
        return value / self.distance_km * 100

    @property
    def kwh_per_100km(self) -> float | None:
        return self._per_100km(self.energy_kwh)

    @property
    def cost_per_100km(self) -> float | None:
        return self._per_100km(self.cost)

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
            **(self.distance_summary() if self.odometer_km is not None else {}),
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

    def distance_summary(self) -> dict[str, Any]:
        """Odometer, distance since the previous charge and consumption."""

        def rounded(value: float | None, digits: int) -> float | None:
            return round(value, digits) if value is not None else None

        return {
            "odometer_km": rounded(self.odometer_km, 1),
            "distance_km": rounded(self.distance_km, 1),
            "kwh_per_100km": rounded(self.kwh_per_100km, 2),
            "cost_per_100km": rounded(self.cost_per_100km, 2),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "price_estimated": self.price_estimated,
            "tranches": [t.as_dict() for t in self.tranches],
            "odometer_km": self.odometer_km,
            "distance_km": self.distance_km,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChargeSession:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]) if data["end"] else None,
            price_estimated=data["price_estimated"],
            tranches=[Tranche.from_dict(t) for t in data["tranches"]],
            # Absent from sessions stored before the odometer was supported.
            odometer_km=data.get("odometer_km"),
            distance_km=data.get("distance_km"),
        )


@dataclass
class Totals:
    """Cumulated figures over all kept sessions."""

    energy_kwh: float = 0.0
    cost: float = 0.0
    count: int = 0
    # When the totals were last reset, for the `last_reset` of TOTAL sensors.
    last_reset: datetime | None = None


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
        # Last valid odometer reading, and the odometer of the last kept
        # session: the distance of the next session is measured from it.
        self._odometer_km: float | None = None
        self._reference_km: float | None = None

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
            if self._odometer_km is not None:
                self.session.set_odometer(self._odometer_km, self._reference_km)
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

    def update_odometer(self, now: datetime, km: float | None) -> None:
        """Feed an odometer reading (km); ``None`` is ignored.

        A reading while power is drawn replaces the one taken at the start:
        cloud car integrations often refresh the odometer only after plugging
        in. Not during the stop delay, when the car may already be driving.
        """
        if km is None:
            return
        self._odometer_km = km
        if self.session is not None and self.state in (
            State.PENDING_START,
            State.CHARGING,
        ):
            self.session.set_odometer(km, self._reference_km)

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

    def reset_totals(self, now: datetime) -> None:
        self.totals = Totals(last_reset=now)

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
        # An unknown odometer invalidates the reference rather than letting the
        # next session count the distance of two charges.
        self._reference_km = session.odometer_km
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
                "last_reset": (
                    self.totals.last_reset.isoformat()
                    if self.totals.last_reset
                    else None
                ),
            },
            "price": self._price,
            "meter_kwh": self._meter_kwh,
            "below_since": self._below_since.isoformat() if self._below_since else None,
            "odometer_km": self._odometer_km,
            "reference_km": self._reference_km,
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
        totals = data["totals"]
        last_reset = totals.get("last_reset")
        self.totals = Totals(
            energy_kwh=totals["energy_kwh"],
            cost=totals["cost"],
            count=totals["count"],
            last_reset=datetime.fromisoformat(last_reset) if last_reset else None,
        )
        self._price = data["price"]
        self._meter_kwh = data["meter_kwh"]
        self._below_since = (
            datetime.fromisoformat(data["below_since"]) if data["below_since"] else None
        )
        self._odometer_km = data.get("odometer_km")
        self._reference_km = data.get("reference_km")
        if self.session is None:
            self.state = State.IDLE
