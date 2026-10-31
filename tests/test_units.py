"""Tests for state parsing and price normalization."""

import pytest

from custom_components.ev_charge_cost.units import parse_float, price_to_eur_per_kwh


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("3.7", 3.7),
        ("0", 0.0),
        ("unavailable", None),
        ("unknown", None),
        (None, None),
        ("nan", None),
        ("inf", None),
    ],
)
def test_parse_float(state, expected):
    assert parse_float(state) == expected


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (None, 25.0),
        ("", 25.0),
        ("€/kWh", 25.0),
        ("EUR/kWh", 25.0),
        ("c€/kWh", 0.25),
        ("€ / MWh", 0.025),
        ("W", None),
    ],
)
def test_price_to_eur_per_kwh(unit, expected):
    result = price_to_eur_per_kwh(25.0, unit)
    assert result == pytest.approx(expected) if expected is not None else result is None
