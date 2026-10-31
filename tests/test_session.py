"""Tests for the pure session state machine."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_cost.session import (
    DetectionConfig,
    SessionEvent,
    SessionMachine,
    State,
)

T0 = datetime(2026, 10, 30, 21, 0, tzinfo=UTC)
CONFIG = DetectionConfig(
    threshold_w=200,
    start_delay=timedelta(seconds=30),
    stop_delay=timedelta(seconds=120),
    min_energy_kwh=0.1,
)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def meter_machine(price: float | None = 0.25) -> SessionMachine:
    machine = SessionMachine(CONFIG, use_energy_meter=True, price=price)
    machine.update_energy(at(0), 100.0)
    return machine


def events(outcomes):
    return [event for event, _ in outcomes]


def test_brief_spike_does_not_start_a_session():
    machine = meter_machine()
    assert machine.update_power(at(0), 3700) == []
    assert machine.state is State.PENDING_START
    assert machine.update_power(at(10), 0) == []
    assert machine.state is State.IDLE
    assert machine.session is None
    assert machine.check(at(60)) == []


def test_full_session_with_energy_meter():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    assert machine.next_deadline() == at(30)

    started = machine.check(at(30))
    assert events(started) == [SessionEvent.STARTED]
    assert started[0][1].start == at(0)
    assert machine.charging

    machine.update_energy(at(1800), 101.85)
    machine.update_energy(at(3600), 103.70)
    machine.update_power(at(3600), 5)
    assert machine.state is State.PENDING_STOP
    assert machine.next_deadline() == at(3720)
    assert machine.check(at(3700)) == []

    ended = machine.check(at(3720))
    assert events(ended) == [SessionEvent.ENDED]
    session = ended[0][1]
    assert session.end == at(3600)
    assert session.energy_kwh == pytest.approx(3.7)
    assert session.cost == pytest.approx(3.7 * 0.25)
    assert session.duration() == timedelta(hours=1)
    assert machine.state is State.IDLE
    assert machine.last_session is session
    assert machine.totals.count == 1
    assert machine.totals.energy_kwh == pytest.approx(3.7)


def test_short_pause_keeps_session_open():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_power(at(600), 0)
    assert machine.update_power(at(660), 3700) == []
    assert machine.state is State.CHARGING
    assert machine.check(at(900)) == []


def test_energy_meter_reset_counts_new_value():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(600), 101.0)
    machine.update_energy(at(1200), 0.5)
    assert machine.session.energy_kwh == pytest.approx(1.5)


def test_energy_outside_session_is_ignored():
    machine = meter_machine()
    machine.update_energy(at(10), 105.0)
    machine.update_power(at(20), 3700)
    machine.update_energy(at(30), 105.2)
    assert machine.session.energy_kwh == pytest.approx(0.2)


def test_price_change_creates_tranches():
    machine = meter_machine(price=0.2516)
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(1020), 101.05)
    machine.update_price(at(1020), 0.1802)
    machine.update_energy(at(4000), 105.0)
    machine.update_power(at(4000), 0)
    ((event, session),) = machine.check(at(4120))

    assert event is SessionEvent.ENDED
    assert [t.price for t in session.tranches] == [0.2516, 0.1802]
    assert session.tranches[0].end == at(1020)
    assert session.tranches[1].start == at(1020)
    assert session.tranches[0].energy_kwh == pytest.approx(1.05)
    assert session.tranches[1].energy_kwh == pytest.approx(3.95)
    assert session.cost == pytest.approx(1.05 * 0.2516 + 3.95 * 0.1802)
    assert session.cost == pytest.approx(sum(t.cost for t in session.tranches))


def test_price_change_without_energy_replaces_price():
    machine = meter_machine(price=0.25)
    machine.update_power(at(0), 3700)
    machine.update_price(at(5), 0.18)
    assert len(machine.session.tranches) == 1
    assert machine.session.tranches[0].price == 0.18


def test_unavailable_price_marks_session_estimated():
    machine = meter_machine(price=0.25)
    machine.update_power(at(0), 3700)
    machine.update_price(at(10), None)
    machine.update_energy(at(20), 100.5)
    assert machine.price == 0.25
    assert machine.session.price_estimated
    assert machine.session.cost == pytest.approx(0.125)


def test_unknown_price_is_applied_when_it_arrives():
    machine = meter_machine(price=None)
    machine.update_power(at(0), 3700)
    machine.update_energy(at(20), 101.0)
    machine.update_price(at(30), 0.2)
    assert machine.session.cost == pytest.approx(0.2)
    assert machine.session.price_estimated


def test_session_below_min_energy_is_discarded():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(40), 100.05)
    machine.update_power(at(40), 0)
    ((event, _),) = machine.check(at(160))
    assert event is SessionEvent.DISCARDED
    assert machine.last_session is None
    assert machine.totals.count == 0


def test_unavailable_power_freezes_transitions():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_power(at(100), 0)
    machine.update_power(at(110), None)
    assert machine.check(at(1000)) == []
    assert machine.state is State.PENDING_STOP
    machine.update_energy(at(1000), 101)
    ended = machine.update_power(at(1010), 0)
    assert events(ended) == [SessionEvent.ENDED]
    assert ended[0][1].end == at(100)


def test_power_integration_without_meter():
    machine = SessionMachine(CONFIG, use_energy_meter=False, price=0.2)
    machine.update_power(at(0), 3600)
    machine.check(at(30))
    machine.check(at(1800))  # periodic tick, value unchanged
    machine.update_power(at(3600), 1800)
    machine.update_power(at(5400), 0)
    ((event, session),) = machine.check(at(5520))
    assert event is SessionEvent.ENDED
    assert session.energy_kwh == pytest.approx(3.6 + 0.9)
    assert session.cost == pytest.approx(4.5 * 0.2)


def test_power_integration_splits_on_price_change():
    machine = SessionMachine(CONFIG, use_energy_meter=False, price=0.25)
    machine.update_power(at(0), 3600)
    machine.update_price(at(1800), 0.15)
    machine.check(at(3600))
    assert [t.energy_kwh for t in machine.session.tranches] == pytest.approx([1.8, 1.8])


def test_meter_ignored_when_using_power_integration():
    machine = SessionMachine(CONFIG, use_energy_meter=False, price=0.25)
    machine.update_energy(at(0), 100)
    machine.update_power(at(0), 3600)
    machine.update_energy(at(10), 150)
    machine.check(at(10))
    assert machine.session.energy_kwh == pytest.approx(0.01)


def test_force_stop():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(600), 101)
    ((event, session),) = machine.force_stop(at(600))
    assert event is SessionEvent.ENDED
    assert session.end == at(600)
    assert machine.state is State.IDLE


def test_force_stop_during_pending_start_drops_session():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    assert machine.force_stop(at(10)) == []
    assert machine.session is None


def test_snapshot_round_trip_resumes_session():
    machine = meter_machine(price=0.25)
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(600), 101)
    machine.update_price(at(600), 0.18)

    restored = SessionMachine(CONFIG, use_energy_meter=True)
    restored.restore(machine.as_dict())
    assert restored.state is State.CHARGING
    assert restored.price == 0.18
    assert restored.session.energy_kwh == pytest.approx(1.0)

    # Energy consumed while HA was down is recovered from the meter delta.
    restored.update_energy(at(4000), 104)
    assert restored.check(at(4000)) == []  # power unknown until next reading
    restored.update_power(at(4000), 0)
    ((event, session),) = restored.check(at(4120))
    assert event is SessionEvent.ENDED
    assert session.energy_kwh == pytest.approx(4.0)
    assert len(session.tranches) == 2


def test_summary_payload():
    machine = meter_machine(price=0.25)
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(3600), 103.7)
    machine.update_power(at(3600), 0)
    ((_, session),) = machine.check(at(3720))
    summary = session.summary()
    assert summary["duration_s"] == 3600
    assert summary["energy_kwh"] == 3.7
    assert summary["cost"] == 0.93
    assert summary["avg_price"] == 0.25
    assert summary["tranches"][0]["to"] == at(3600).isoformat()


def test_reset_totals_records_reset_time_and_survives_snapshot():
    machine = meter_machine()
    machine.update_power(at(0), 3700)
    machine.check(at(30))
    machine.update_energy(at(600), 101)
    machine.force_stop(at(600))
    assert machine.totals.last_reset is None

    machine.reset_totals(at(700))
    assert machine.totals.count == 0
    assert machine.totals.last_reset == at(700)

    restored = SessionMachine(CONFIG, use_energy_meter=True)
    restored.restore(machine.as_dict())
    assert restored.totals.last_reset == at(700)


def test_restore_snapshot_without_last_reset():
    """Snapshots written by v0.1.0 have no last_reset key."""
    machine = meter_machine()
    data = machine.as_dict()
    del data["totals"]["last_reset"]
    restored = SessionMachine(CONFIG, use_energy_meter=True)
    restored.restore(data)
    assert restored.totals.last_reset is None
