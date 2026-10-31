<p align="center">
  <img src="https://raw.githubusercontent.com/Pouzor/ev-charge-cost/main/custom_components/ev_charge_cost/brand/icon.png" alt="EV Charge Cost" width="128">
</p>

# EV Charge Cost

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Release](https://img.shields.io/github/v/release/Pouzor/ev-charge-cost)](https://github.com/Pouzor/ev-charge-cost/releases)
[![Validate](https://github.com/Pouzor/ev-charge-cost/actions/workflows/validate.yml/badge.svg)](https://github.com/Pouzor/ev-charge-cost/actions/workflows/validate.yml)

Home Assistant integration (HACS) that automatically detects the charging
sessions of an electric vehicle from a monitored outlet or current clamp, and
records the **duration**, **energy (kWh)** and **cost** of each session —
with a fixed price or a price entity, including when the price changes during
the charge (off-peak / peak hours).

> 🚧 Work in progress — see [FEATURE.md](FEATURE.md) for the scope.

## Installation (HACS)

1. HACS → ⋮ menu → *Custom repositories* → `https://github.com/Pouzor/ev-charge-cost`, category *Integration*.
2. Install **EV Charge Cost**, then restart Home Assistant.
3. Settings → Devices & services → *Add integration* → **EV Charge Cost**.

## Configuration

- **Power sensor** (W/kW) — required, used to detect charging.
- **Energy meter** (cumulative kWh) — optional, more accurate than integrating the power.
- **Detection** — threshold (200 W by default), start / stop delays, minimum energy.
- **Price** — fixed or an entity (e.g. €/kWh, c€/kWh, €/MWh). Prices and
  costs use the currency configured in Home Assistant.

All settings can be changed later from the integration options.

## Entities

Per charge point: a `charging` binary sensor, the energy / cost / duration of
the session in progress and of the last session, total energy, total cost,
session count and current price — plus a **charge history calendar** with one
event per session (energy, cost, duration and price tranches).

## Events

`ev_charge_cost_charge_started`, `ev_charge_cost_charge_ended` (duration,
energy, cost, price tranches) and `ev_charge_cost_charge_discarded`. They also
show up in the logbook.

Example — notify when a charge ends:

```yaml
triggers:
  - trigger: event
    event_type: ev_charge_cost_charge_ended
actions:
  - action: notify.notify
    data:
      message: >
        Charge finished: {{ trigger.event.data.energy_kwh }} kWh,
        {{ trigger.event.data.cost }} {{ trigger.event.data.currency }} in
        {{ (trigger.event.data.duration_s / 60) | round }} min.
```

## Blueprint

A blueprint **"EV Charge Cost — notify when a charge ends"** ships with the
integration and is installed automatically in
`blueprints/automation/ev_charge_cost/` (an existing file is never
overwritten). Create an automation from it in Settings → Automations →
Blueprints, pick the charge point and a phone running the Companion app.

It can also be imported directly:

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FPouzor%2Fev-charge-cost%2Fblob%2Fmain%2Fcustom_components%2Fev_charge_cost%2Fblueprints%2Fcharge_ended_notification.yaml)

## Services

- `ev_charge_cost.stop_session` — ends the session in progress now.
- `ev_charge_cost.reset_totals` — resets the totals and the session count.

## Development

```bash
uv venv -p 3.14 .venv && uv pip install -p .venv/bin/python -r requirements_test.txt
.venv/bin/pytest -q
./scripts/install-hooks.sh   # pre-commit hook: ruff + pytest
./scripts/dev-ha.sh          # throwaway HA in Docker on http://localhost:8125
```
