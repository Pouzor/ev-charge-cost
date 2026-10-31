"""Tests for state parsing and price normalization."""

import pytest

from custom_components.ev_charge_cost.units import (
    currency_symbol,
    parse_float,
    price_per_kwh,
)


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
    ("unit", "currency", "expected"),
    [
        (None, "EUR", 25.0),
        ("", "EUR", 25.0),
        ("€/kWh", "EUR", 25.0),
        ("EUR/kWh", "EUR", 25.0),
        ("c€/kWh", "EUR", 0.25),
        ("ct/kWh", "EUR", 0.25),
        ("€ / MWh", "EUR", 0.025),
        ("€/Wh", "EUR", 25000.0),
        ("$/kWh", "USD", 25.0),
        ("USD/kWh", "USD", 25.0),
        ("¢/kWh", "USD", 0.25),
        ("cents/kWh", "USD", 0.25),
        ("p/kWh", "GBP", 0.25),
        ("£/kWh", "GBP", 25.0),
        ("SEK/kWh", "SEK", 25.0),
        ("öre/kWh", "SEK", None),
        ("€/kWh", "USD", None),
        ("p/kWh", "EUR", None),
        ("W", "EUR", None),
        ("€", "EUR", None),
    ],
)
def test_price_per_kwh(unit, currency, expected):
    result = price_per_kwh(25.0, unit, currency)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_currency_symbol():
    assert currency_symbol("EUR") == "€"
    assert currency_symbol("SEK") == "SEK"
