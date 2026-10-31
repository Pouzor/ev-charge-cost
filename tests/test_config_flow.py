"""Tests for the config and options flows."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_cost.const import (
    CONF_ENERGY_ENTITY,
    CONF_MIN_ENERGY_KWH,
    CONF_POWER_ENTITY,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FIXED,
    CONF_PRICE_MODE,
    CONF_START_DELAY_S,
    CONF_STOP_DELAY_S,
    CONF_THRESHOLD_W,
    DOMAIN,
    PRICE_MODE_ENTITY,
    PRICE_MODE_FIXED,
)

POWER = "sensor.pinces_consommation_power_b"
ENERGY = "sensor.pinces_consommation_energy_b"
DETECTION = {
    CONF_THRESHOLD_W: 200,
    CONF_START_DELAY_S: 30,
    CONF_STOP_DELAY_S: 120,
    CONF_MIN_ENERGY_KWH: 0.1,
}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Voiture", CONF_POWER_ENTITY: POWER, CONF_ENERGY_ENTITY: ENERGY},
    )
    assert result["step_id"] == "detection"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], DETECTION
    )
    assert result["step_id"] == "price"
    return result["flow_id"]


async def test_flow_fixed_price(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_MODE: PRICE_MODE_FIXED}
    )
    assert result["step_id"] == "price_fixed"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_FIXED: 0.2516}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Voiture"
    assert result["data"] == {
        CONF_NAME: "Voiture",
        CONF_POWER_ENTITY: POWER,
        CONF_ENERGY_ENTITY: ENERGY,
        **DETECTION,
        CONF_PRICE_MODE: PRICE_MODE_FIXED,
        CONF_PRICE_FIXED: 0.2516,
    }


async def test_flow_price_entity(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.tarif", "18.02", {"unit_of_measurement": "c€/kWh"})
    hass.states.async_set("sensor.bad_tarif", "1", {"unit_of_measurement": "W"})
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_MODE: PRICE_MODE_ENTITY}
    )
    assert result["step_id"] == "price_entity"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_ENTITY: "sensor.bad_tarif"}
    )
    assert result["errors"] == {CONF_PRICE_ENTITY: "unsupported_price_unit"}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PRICE_ENTITY: "sensor.tarif"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRICE_ENTITY] == "sensor.tarif"


async def test_flow_aborts_on_duplicate_power_sensor(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=POWER).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Voiture", CONF_POWER_ENTITY: POWER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_switches_to_fixed_and_clears_meter(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=POWER,
        title="Voiture",
        data={
            CONF_NAME: "Voiture",
            CONF_POWER_ENTITY: POWER,
            CONF_ENERGY_ENTITY: ENERGY,
            **DETECTION,
            CONF_PRICE_MODE: PRICE_MODE_ENTITY,
            CONF_PRICE_ENTITY: "sensor.tarif",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_POWER_ENTITY: POWER, **DETECTION, CONF_THRESHOLD_W: 500},
    )
    assert result["step_id"] == "price"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRICE_MODE: PRICE_MODE_FIXED}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRICE_FIXED: 0.2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    merged = {**entry.data, **entry.options}
    assert merged[CONF_ENERGY_ENTITY] is None
    assert merged[CONF_THRESHOLD_W] == 500
    assert merged[CONF_PRICE_MODE] == PRICE_MODE_FIXED
    assert merged[CONF_PRICE_FIXED] == 0.2
