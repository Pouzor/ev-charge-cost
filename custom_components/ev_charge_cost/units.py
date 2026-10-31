"""State parsing and price unit normalization (pure helpers)."""

from __future__ import annotations

import math

# Factor converting a price expressed in the key unit to EUR/kWh.
_PRICE_FACTORS: dict[str, float] = {
    "€/kwh": 1.0,
    "eur/kwh": 1.0,
    "c€/kwh": 0.01,
    "ct/kwh": 0.01,
    "cts/kwh": 0.01,
    "€/mwh": 0.001,
    "eur/mwh": 0.001,
}


def parse_float(state: str | None) -> float | None:
    """Return the numeric value of a state, or None if not a finite number."""
    if state is None:
        return None
    try:
        value = float(state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def price_to_eur_per_kwh(value: float, unit: str | None) -> float | None:
    """Normalize a price to EUR/kWh; None if the unit is not supported.

    A missing unit is interpreted as EUR/kWh.
    """
    if not unit:
        return value
    factor = _PRICE_FACTORS.get(unit.replace(" ", "").lower())
    return value * factor if factor is not None else None
