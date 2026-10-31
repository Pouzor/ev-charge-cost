"""Config and options flows for EV Charge Cost."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENERGY_ENTITY,
    CONF_MIN_ENERGY_KWH,
    CONF_POWER_ENTITY,
    CONF_PRICE_ENTITY,
    CONF_PRICE_FIXED,
    CONF_PRICE_MODE,
    CONF_START_DELAY_S,
    CONF_STOP_DELAY_S,
    CONF_THRESHOLD_W,
    DEFAULT_MIN_ENERGY_KWH,
    DEFAULT_NAME,
    DEFAULT_START_DELAY_S,
    DEFAULT_STOP_DELAY_S,
    DEFAULT_THRESHOLD_W,
    DOMAIN,
    PRICE_MODE_ENTITY,
    PRICE_MODE_FIXED,
)
from .units import price_to_eur_per_kwh


def _number(
    minimum: float, maximum: float, step: float | str, unit: str
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _sources_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_POWER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(CONF_ENERGY_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
        }
    )


DETECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_THRESHOLD_W, default=DEFAULT_THRESHOLD_W): _number(
            1, 50000, 1, UnitOfPower.WATT
        ),
        vol.Required(CONF_START_DELAY_S, default=DEFAULT_START_DELAY_S): _number(
            0, 3600, 1, UnitOfTime.SECONDS
        ),
        vol.Required(CONF_STOP_DELAY_S, default=DEFAULT_STOP_DELAY_S): _number(
            0, 3600, 1, UnitOfTime.SECONDS
        ),
        vol.Required(CONF_MIN_ENERGY_KWH, default=DEFAULT_MIN_ENERGY_KWH): _number(
            0, 100, 0.01, UnitOfEnergy.KILO_WATT_HOUR
        ),
    }
)

PRICE_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_PRICE_MODE, default=PRICE_MODE_FIXED
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[PRICE_MODE_FIXED, PRICE_MODE_ENTITY],
                translation_key=CONF_PRICE_MODE,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
    }
)

PRICE_FIXED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PRICE_FIXED): _number(0, 10, "any", "€/kWh"),
    }
)

PRICE_ENTITY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PRICE_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
        ),
    }
)


def _validate_price_entity(hass: HomeAssistant, entity_id: str) -> dict[str, str]:
    """Reject a price entity whose unit cannot be converted to EUR/kWh."""
    state = hass.states.get(entity_id)
    if state is None:
        return {}
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if price_to_eur_per_kwh(1.0, unit) is None:
        return {CONF_PRICE_ENTITY: "unsupported_price_unit"}
    return {}


class EvChargeCostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a charge point: sources → detection → price."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EvChargeCostOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            self._data.update(user_input)
            return await self.async_step_detection()

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector()}
        ).extend(_sources_schema().schema)
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_detection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_price()
        return self.async_show_form(step_id="detection", data_schema=DETECTION_SCHEMA)

    async def async_step_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if user_input[CONF_PRICE_MODE] == PRICE_MODE_ENTITY:
                return await self.async_step_price_entity()
            return await self.async_step_price_fixed()
        return self.async_show_form(step_id="price", data_schema=PRICE_MODE_SCHEMA)

    async def async_step_price_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self._create()
        return self.async_show_form(
            step_id="price_fixed", data_schema=PRICE_FIXED_SCHEMA
        )

    async def async_step_price_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY])
            if not errors:
                self._data.update(user_input)
                return self._create()
        return self.async_show_form(
            step_id="price_entity", data_schema=PRICE_ENTITY_SCHEMA, errors=errors
        )

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)


class EvChargeCostOptionsFlow(OptionsFlow):
    """Edit every setting of an existing charge point."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            # Store the key explicitly so clearing the field overrides entry.data.
            self._options[CONF_ENERGY_ENTITY] = user_input.get(CONF_ENERGY_ENTITY)
            return await self.async_step_price()

        schema = _sources_schema().extend(DETECTION_SCHEMA.schema)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self._current),
        )

    async def async_step_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            if user_input[CONF_PRICE_MODE] == PRICE_MODE_ENTITY:
                return await self.async_step_price_entity()
            return await self.async_step_price_fixed()
        return self.async_show_form(
            step_id="price",
            data_schema=self.add_suggested_values_to_schema(
                PRICE_MODE_SCHEMA, self._current
            ),
        )

    async def async_step_price_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="price_fixed",
            data_schema=self.add_suggested_values_to_schema(
                PRICE_FIXED_SCHEMA, self._current
            ),
        )

    async def async_step_price_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_price_entity(self.hass, user_input[CONF_PRICE_ENTITY])
            if not errors:
                self._options.update(user_input)
                return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="price_entity",
            data_schema=self.add_suggested_values_to_schema(
                PRICE_ENTITY_SCHEMA, self._current
            ),
            errors=errors,
        )
