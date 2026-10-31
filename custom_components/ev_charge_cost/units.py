"""State parsing and price unit normalization (pure helpers)."""

from __future__ import annotations

import math

# Symbols accepted, besides the ISO 4217 code, for the main currencies.
_SYMBOLS: dict[str, str] = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "INR": "₹",
    "KRW": "₩",
    "CHF": "Fr.",
}
# Words for a hundredth of any currency (c€, ct, cents, ¢, …).
_CENTS = {"c", "ct", "cts", "cent", "cents", "¢"}
# Factor converting a price per <key> to a price per kWh.
_ENERGY: dict[str, float] = {"wh": 1000.0, "kwh": 1.0, "mwh": 0.001}


def parse_float(state: str | None) -> float | None:
    """Return the numeric value of a state, or None if not a finite number."""
    if state is None:
        return None
    try:
        value = float(state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def format_duration(seconds: float) -> str:
    """Human duration such as "6h30" or "5 min"."""
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours}h{minutes:02d}" if hours else f"{minutes} min"


def currency_symbol(currency: str) -> str:
    """Symbol of an ISO 4217 currency, or the code itself."""
    return _SYMBOLS.get(currency, currency)


def price_per_kwh(value: float, unit: str | None, currency: str) -> float | None:
    """Normalize a price to <currency>/kWh; None if the unit is not supported.

    A missing unit is interpreted as <currency>/kWh. The money part may be the
    currency code or symbol, or cents of it (c€, ct, ¢, p for GBP…).
    """
    if not unit:
        return value
    money, slash, energy = unit.replace(" ", "").lower().partition("/")
    if not slash or energy not in _ENERGY:
        return None
    names = {currency.lower(), currency_symbol(currency).lower()}
    if money in names:
        factor = 1.0
    elif (
        money in _CENTS
        or (money[:1] == "c" and money[1:] in names)
        or (money == "p" and currency == "GBP")
    ):
        factor = 0.01
    else:
        return None
    return value * factor * _ENERGY[energy]
