#!/usr/bin/env bash
# Spin up Home Assistant in Docker with HACS installed and this integration
# mounted.
#
# Usage:
#   ./scripts/dev-ha.sh             # start HA, follow logs
#   ./scripts/dev-ha.sh stop        # stop the container
#   ./scripts/dev-ha.sh restart     # restart container (reloads Python code)
#   ./scripts/dev-ha.sh logs        # tail logs
#   ./scripts/dev-ha.sh shell       # bash inside container
#
# HA_PORT overrides the host port (default 8125).
#
# After first start: open http://localhost:8125 → onboard → Settings → Devices
# & Services → Add Integration → "EV Charge Cost", pick sensor.fake_ev_power /
# sensor.fake_ev_energy / sensor.fake_ev_price (provided by
# dev/packages/fake_ev.yaml). Drive a charge with input_number.fake_ev_power.
# To finish the HACS setup: Add Integration → "HACS" (needs a GitHub device
# login).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker-compose.dev.yml"
SERVICE="homeassistant"
CONFIG_DIR="$ROOT/dev-config"
HA_PORT="${HA_PORT:-8125}"
HACS_ZIP_URL="https://github.com/hacs/integration/releases/latest/download/hacs.zip"

ensure_config_dir() {
  mkdir -p "$CONFIG_DIR/custom_components/ev_charge_cost"
  if [[ ! -f "$CONFIG_DIR/configuration.yaml" ]]; then
    echo "→ Seeding dev-config/configuration.yaml..."
    cp "$ROOT/dev/configuration.yaml" "$CONFIG_DIR/configuration.yaml"
    cat >> "$CONFIG_DIR/configuration.yaml" <<'YAML'

logger:
  default: info
  logs:
    custom_components.ev_charge_cost: debug
YAML
    touch "$CONFIG_DIR/automations.yaml" "$CONFIG_DIR/scripts.yaml" "$CONFIG_DIR/scenes.yaml"
  fi
}

ensure_hacs() {
  local target="$CONFIG_DIR/custom_components/hacs"
  [[ -f "$target/manifest.json" ]] && return
  echo "→ Installing HACS into dev-config/custom_components/hacs..."
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL "$HACS_ZIP_URL" -o "$tmp/hacs.zip"
  mkdir -p "$target"
  unzip -q -o "$tmp/hacs.zip" -d "$target"
  rm -rf "$tmp"
}

cmd_up() {
  ensure_config_dir
  ensure_hacs
  echo "→ Starting Home Assistant container..."
  HA_PORT="$HA_PORT" docker compose -f "$COMPOSE_FILE" up -d "$SERVICE"
  echo
  echo "✅ HA running at http://localhost:$HA_PORT"
  echo "   Following logs (Ctrl+C to stop following — container keeps running)..."
  echo
  docker compose -f "$COMPOSE_FILE" logs -f "$SERVICE"
}

cmd_stop() {
  echo "→ Stopping container..."
  docker compose -f "$COMPOSE_FILE" down
}

cmd_restart() {
  echo "→ Restarting container..."
  # `up --force-recreate` rather than `restart`: `stop` removes the container,
  # and `docker compose restart` does nothing when there is none.
  HA_PORT="$HA_PORT" docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE"
  docker compose -f "$COMPOSE_FILE" logs -f "$SERVICE"
}

cmd_logs() {
  docker compose -f "$COMPOSE_FILE" logs -f "$SERVICE"
}

cmd_shell() {
  docker compose -f "$COMPOSE_FILE" exec "$SERVICE" /bin/bash
}

case "${1:-up}" in
  up|"")   cmd_up ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  logs)    cmd_logs ;;
  shell)   cmd_shell ;;
  *)
    echo "Unknown command: $1" >&2
    echo "Usage: $0 [up|stop|restart|logs|shell]" >&2
    exit 1
    ;;
esac
