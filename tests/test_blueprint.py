"""Tests for the shipped blueprint and its installation."""

from pathlib import Path

import pytest
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml_dict

from custom_components.ev_charge_cost.blueprint import SOURCE_DIR, _install

from .helpers import setup_entry

BLUEPRINT = SOURCE_DIR / "charge_ended_notification.yaml"


def _blueprint() -> Blueprint:
    return Blueprint(
        load_yaml_dict(str(BLUEPRINT)),
        expected_domain="automation",
        schema=BLUEPRINT_SCHEMA,
    )


def test_blueprint_is_valid():
    blueprint = _blueprint()
    assert set(blueprint.inputs) == {"charge_point", "notify_device", "title"}
    assert blueprint.metadata["source_url"].endswith(
        "custom_components/ev_charge_cost/blueprints/charge_ended_notification.yaml"
    )


@pytest.mark.parametrize(
    ("duration_s", "duration"), [(23370, "6h30"), (310, "5 min"), (3600, "1h00")]
)
async def test_blueprint_message(
    hass: HomeAssistant, duration_s: int, duration: str
) -> None:
    config = BlueprintInputs(
        _blueprint(),
        {
            "use_blueprint": {
                "path": "ev_charge_cost/charge_ended_notification.yaml",
                "input": {"charge_point": "entry123", "notify_device": "device123"},
            }
        },
    ).async_substitute()
    (trigger,) = config["triggers"]
    assert trigger["event_type"] == "ev_charge_cost_charge_ended"
    assert trigger["event_data"] == {"entry_id": "entry123"}
    variables_step, notify_step = config["actions"]
    assert notify_step["device_id"] == "device123"
    assert notify_step["title"] == "EV charge finished"

    # Render the variables in order, like the script engine does.
    variables = {
        "trigger": {
            "event": {
                "data": {
                    "name": "Recharge VE",
                    "energy_kwh": 22.84,
                    "cost": 4.19,
                    "currency": "EUR",
                    "duration_s": duration_s,
                    "avg_price": 0.1835,
                }
            }
        }
    }
    for name, value in variables_step["variables"].items():
        variables[name] = Template(value, hass).async_render(variables)
    message = Template(notify_step["message"], hass).async_render(variables)
    assert message == (
        f"Recharge VE: 22.84 kWh, 4.19 EUR in {duration} (avg 0.1835 EUR/kWh)."
    )


def test_install_copies_without_overwriting(tmp_path: Path):
    assert _install(tmp_path) == ["charge_ended_notification.yaml"]
    installed = tmp_path / "charge_ended_notification.yaml"
    assert installed.read_text() == BLUEPRINT.read_text()

    installed.write_text("edited by the user")
    assert _install(tmp_path) == []
    assert installed.read_text() == "edited by the user"


async def test_setup_installs_blueprint(hass: HomeAssistant) -> None:
    await setup_entry(hass)
    path = Path(
        hass.config.path("blueprints", "automation", "ev_charge_cost", BLUEPRINT.name)
    )
    assert path.exists()
