# EV Charge Cost — Functional specification

Home Assistant integration (distributed through HACS) that automatically detects
the charging sessions of an electric vehicle plugged into a monitored outlet or
circuit, and records for each session its **duration**, **energy (kWh)** and
**cost** (in the currency configured in Home Assistant).

## 1. Context / reference hardware

Reference setup: Tuya **PJ-1203A** clamp ("Bidirectional energy meter with 80A
current clamp") through Zigbee2MQTT, device `Pinces consommation`.

| Role | Entity | Unit | Notes |
|---|---|---|---|
| Car power | `sensor.pinces_consommation_power_b` | W | `measurement`, refreshed every 10 s |
| Car energy (meter) | `sensor.pinces_consommation_energy_b` | kWh | `total_increasing` |

Observed profile: ~3.7 kW while charging (16 A single phase), 0 W otherwise.

The integration must stay **generic**: any power sensor (W/kW) and, optionally,
any cumulative energy sensor (Wh/kWh) must work (Shelly, Tuya, Zigbee plugs,
etc.).

## 2. Configuration (UI config flow, no YAML)

One config entry = one charge point. Multiple instances are supported.

### Step 1 — Sources
| Field | Type | Required | Default |
|---|---|---|---|
| Name | text | yes | `Recharge VE` |
| Power sensor | entity selector (`sensor`, device_class `power`) | yes | — |
| Cumulative energy sensor | entity selector (`sensor`, device_class `energy`) | no | — |

The power sensor is the entry's unique ID: the same sensor cannot be tracked
twice.

### Step 2 — Detection
| Field | Type | Default |
|---|---|---|
| Start threshold (W) | number | 200 |
| Start delay (s) — power above threshold for | number | 30 |
| Stop delay (s) — power below threshold for | number | 120 |
| Minimum energy to keep a session (kWh) | number | 0.1 |

The delays prevent false starts (brief spikes) and false stops (the car pausing
near the end of the charge / battery balancing).

### Step 3 — Price
Either:
All prices and costs use the **currency configured in Home Assistant**
(Settings → System → General), shown below as € for the reference setup.

- **Fixed**: price per kWh (number, e.g. `0.2516`).
- **Entity**: entity selector on a `sensor` / `input_number` / `number`
  giving the kWh price. Accepted units: the currency code or symbol per `Wh`,
  `kWh` or `MWh` (`€/kWh`, `EUR/MWh`, `$/kWh`…), or cents of it (`c€/kWh`,
  `ct/kWh`, `¢/kWh`, `p/kWh` for GBP), converted automatically; no unit →
  treated as <currency>/kWh. An
  entity with any other unit is rejected by the flow.

Every setting can be changed later through the **options flow** without
removing the integration.

## 3. Session detection (state machine)

```
IDLE ──(P > threshold)──▶ PENDING_START ──(P > threshold for start_delay)──▶ CHARGING
  ▲                            │ (P ≤ threshold)                                │
  │                            ▼                                                │ (P ≤ threshold)
  └──────────────────────── IDLE                                                ▼
  ▲                                                                       PENDING_STOP
  │                                                                             │
  └──(P ≤ threshold for stop_delay)── finalize ◀────────────────────────────────┘
                                                      (P > threshold → back to CHARGING)
```

- The recorded start is the **first** crossing above the threshold (not the end
  of the confirmation delay); energy consumed during `PENDING_START` is
  included.
- The recorded end is the **last** crossing below the threshold.
- Delays are evaluated with timers scheduled at the exact deadline, not only on
  new state updates (the sensor may not republish an identical value).
- `unavailable` / `unknown` power states are ignored (neither start nor stop).
  If the sensor stays unavailable longer than `stop_delay`, the session stays
  open and resumes when the sensor comes back.
- A session below the minimum energy is discarded (no `ended` event, neither
  the last session nor the totals are updated), but an
  `ev_charge_cost_charge_discarded` event is fired.

## 4. Energy accounting

1. **When a cumulative energy sensor is configured (preferred)**: on every state
   change, `delta = value - previous_value` (converted to kWh).
   - `delta < 0` (meter reset) → `value` is used as the delta
     (`total_increasing` semantics).
   - `unavailable` / `unknown` values are ignored; the last valid value is kept
     as the reference.
2. **Otherwise**: the power is integrated with a **left** Riemann sum (the last
   value is held until the next reading). Home Assistant does not fire a state
   change when the value is unchanged, so the tracker also integrates
   periodically (~60 s tick) to avoid under-counting a steady power. Nothing is
   integrated while the sensor is unavailable.

## 5. Cost accounting — handling price changes

The cost is **never** computed as `total_energy × final_price`. It is
**accumulated per tranche**:

```
session_cost += delta_kWh × kWh_price_in_effect_when_the_delta_occurred
```

- The price in effect is the last valid value of the price entity (tracked
  continuously with `async_track_state_change_event`).
- When the price changes during a session, the **current tranche is closed**
  (energy up to that instant is billed at the previous price) before the new
  price applies. Example: off-peak → peak switch at 22:00 during a charge.
- If the price entity becomes unavailable, the last known price is used and the
  session is flagged `price_estimated: true`.
- The session keeps its list of price tranches
  (`[{from, to, price, kwh, cost}]`) for auditing.

## 6. Entities (per charge point)

| Entity | Type | Description |
|---|---|---|
| `binary_sensor.<name>_charging` | binary_sensor (`battery_charging`) | `on` during a confirmed session (`CHARGING` / `PENDING_STOP`); `detection_state` attribute |
| `sensor.<name>_session_energy` | kWh, `total_increasing` | Energy of the session in progress (0 outside a session) |
| `sensor.<name>_session_cost` | € | Cost of the session in progress (no state class: a monetary `total` would record the drop to 0 as a negative cost) |
| `sensor.<name>_session_duration` | duration (min) | Duration of the session in progress |
| `sensor.<name>_last_session_energy` | kWh | Energy of the last completed session |
| `sensor.<name>_last_session_cost` | € | Cost of the last completed session — attributes: start, end, duration, average price, tranches |
| `sensor.<name>_last_session_duration` | duration (min) | Duration of the last session |
| `sensor.<name>_total_energy` | kWh, `total_increasing` | Sum over all sessions (usable in the Energy dashboard) |
| `sensor.<name>_total_cost` | €, `total` | Sum of costs; `last_reset` is set by `reset_totals` so statistics do not record a negative cost |
| `sensor.<name>_sessions` | counter | Number of kept sessions |
| `calendar.<name>_charge_history` | calendar | One event per completed session (summary `⚡ kWh · cost`, description with duration, average price and tranches); `on` with the session in progress while charging |
| `sensor.<name>_current_price` | <currency>/kWh (diagnostic) | Price currently applied (fixed or entity) |

All entities belong to one service device named after the charge point.

## 7. Events (HA bus)

Usable in automations (`event` trigger).

### `ev_charge_cost_charge_started`
```yaml
entry_id: "…"
name: "Recharge VE"
power_entity: sensor.pinces_consommation_power_b
start: "2026-10-30T21:43:10+01:00"
```

### `ev_charge_cost_charge_ended`
```yaml
entry_id: "…"
name: "Recharge VE"
power_entity: sensor.pinces_consommation_power_b
start: "2026-10-30T21:43:10+01:00"
end: "2026-10-31T04:12:40+01:00"
duration_s: 23370
energy_kwh: 22.84
cost: 4.19
currency: EUR  # Home Assistant currency
avg_price: 0.1835
price_estimated: false
tranches:
  - {from: "2026-10-30T21:43:10+01:00", to: "2026-10-30T22:00:00+01:00", price: 0.2516, kwh: 1.05, cost: 0.26}
  - {from: "2026-10-30T22:00:00+01:00", to: "2026-10-31T04:12:40+01:00", price: 0.1802, kwh: 21.79, cost: 3.93}
```

### `ev_charge_cost_charge_discarded`
Same fields as `ended`, fired when the energy is below the minimum.

The events are also described for the **logbook** (`logbook.py`), in English
or French depending on the Home Assistant language, linked to the `charging`
binary sensor.

## 8. Persistence / robustness

- The session in progress (state, start, tranches, last meter value, last
  price) and the totals / last session are saved with
  `homeassistant.helpers.storage.Store` (`.storage/ev_charge_cost.<entry_id>`):
  delayed save (30 s) after each update, immediate save on unload.
- On Home Assistant restart the session is restored; if the power is still
  above the threshold it simply continues, otherwise it goes to `PENDING_STOP`
  and is finalized normally. With an energy meter, the energy consumed while HA
  was down is recovered from the meter delta.
- Completed sessions are kept for the history calendar in a separate store
  (`.storage/ev_charge_cost.<entry_id>.history`, last 5000 sessions), saved
  when a session ends.
- Removing the integration deletes its stored data.

## 9. Services

| Service | Description |
|---|---|
| `ev_charge_cost.stop_session` | Ends the session in progress now (finalization + `ended` event) |
| `ev_charge_cost.reset_totals` | Resets the totals and the session counter |

Both take a `config_entry_id` field (charge point selector).

## 10. HACS packaging

- `hacs.json` at the root, `custom_components/ev_charge_cost/` with
  `manifest.json` (`config_flow: true`, `iot_class: calculated`, `version`)
  and `brand/icon.png`.
- `en` and `fr` translations.
- GitHub Actions CI: `hassfest` + `hacs/action` (validation), ruff + pytest,
  release on `vX.Y.Z` tags (tag must match the manifest version).
- README with HACS installation (custom repository), screenshots, and an
  automation example (notification with the cost when a charge ends).

## 11. Out of scope (v1)

- Controlling the charge (switching the outlet, off-peak charging).
- Telling apart several vehicles on the same outlet.

## 12. Acceptance criteria

- [ ] A real ~3.7 kW charge on `power_b` creates a session, closes it after the
      stop delay and fires `charge_started` / `charge_ended`.
- [ ] A spike shorter than the start delay does not create a session.
- [ ] A pause shorter than the stop delay does not end the session.
- [ ] With an energy meter, the session `energy_kwh` equals the meter
      difference between start and end (± 0.01 kWh).
- [ ] A price change during a session produces 2 tranches and the cost equals
      the sum of the tranches.
- [ ] A Home Assistant restart in the middle of a charge loses neither the
      session nor the energy.
- [ ] Fixed and entity price modes both work and can be changed through
      options.
- [ ] `hassfest` and HACS validation pass; tests are green.
