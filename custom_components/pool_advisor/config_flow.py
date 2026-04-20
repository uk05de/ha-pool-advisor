"""Config & options flow for Pool Chemistry Advisor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CHLORINATION_CHOICES,
    CHLORINATION_SALT,
    CONF_CC_MAX,
    CONF_CC_SHOCK_AT,
    CONF_CHLORINATION,
    CONF_DOSE_INTERVAL_H,
    CONF_ENT_ALKALINITY,
    CONF_ENT_COMBINED_CL,
    CONF_ENT_CYANURIC,
    CONF_ENT_FREE_CL,
    CONF_ENT_PH_AUTO,
    CONF_ENT_PH_MANUAL,
    CONF_ENT_REDOX,
    CONF_ENT_TEMPERATURE,
    CONF_ENT_TOTAL_CL,
    CONF_FC_MAX,
    CONF_FC_MIN,
    CONF_FC_TARGET,
    CONF_MANUAL_MAX_AGE_H,
    CONF_MAX_DOSE_FRACTION,
    CONF_NAME,
    CONF_PH_CALIB_THRESHOLD,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_MINUS_STRENGTH,
    CONF_PH_MINUS_TYPE,
    CONF_PH_PLUS_STRENGTH,
    CONF_PH_PLUS_TYPE,
    CONF_PH_TARGET,
    CONF_POOL_VOLUME_M3,
    CONF_REDOX_MAX,
    CONF_REDOX_MIN,
    CONF_REDOX_TARGET,
    CONF_SHOCK_STRENGTH,
    CONF_SHOCK_TYPE,
    CONF_TA_MAX,
    CONF_TA_MIN,
    CONF_TA_PLUS_STRENGTH,
    CONF_TA_PLUS_TYPE,
    CONF_TA_TARGET,
    DEFAULT_CC_MAX,
    DEFAULT_CC_SHOCK_AT,
    DEFAULT_DOSE_INTERVAL_H,
    DEFAULT_FC_MAX_CLASSIC,
    DEFAULT_FC_MAX_SALT,
    DEFAULT_FC_MIN_CLASSIC,
    DEFAULT_FC_MIN_SALT,
    DEFAULT_FC_TARGET_CLASSIC,
    DEFAULT_FC_TARGET_SALT,
    DEFAULT_MANUAL_MAX_AGE_H,
    DEFAULT_MAX_DOSE_FRACTION,
    DEFAULT_PH_CALIB_THRESHOLD,
    DEFAULT_PH_MAX,
    DEFAULT_PH_MIN,
    DEFAULT_PH_TARGET,
    DEFAULT_REDOX_MAX,
    DEFAULT_REDOX_MIN,
    DEFAULT_REDOX_TARGET,
    DEFAULT_STRENGTH,
    DEFAULT_TA_MAX,
    DEFAULT_TA_MIN,
    DEFAULT_TA_TARGET,
    DOMAIN,
    PH_MINUS_CHOICES,
    PH_MINUS_DRY_ACID,
    PH_PLUS_CHOICES,
    PH_PLUS_SODA,
    SHOCK_CHOICES,
    SHOCK_DICHLOR,
    TA_PLUS_BICARB,
    TA_PLUS_CHOICES,
)


def _sensor_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "number", "input_number"]))


def _pct_number() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=100, step=0.1, mode=selector.NumberSelectorMode.BOX)
    )


def _number(min_v: float, max_v: float, step: float = 0.1) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX)
    )


def _select(options: list[str], translation_key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, translation_key=translation_key, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _schema_entities_auto(defaults: dict[str, Any]) -> vol.Schema:
    def _opt(key: str) -> dict[str, Any]:
        val = defaults.get(key)
        return {"default": val} if val else {}

    return vol.Schema(
        {
            vol.Optional(CONF_ENT_PH_AUTO, **_opt(CONF_ENT_PH_AUTO)): _sensor_selector(),
            vol.Optional(CONF_ENT_REDOX, **_opt(CONF_ENT_REDOX)): _sensor_selector(),
            vol.Optional(CONF_ENT_TEMPERATURE, **_opt(CONF_ENT_TEMPERATURE)): _sensor_selector(),
        }
    )


def _schema_entities_manual(defaults: dict[str, Any]) -> vol.Schema:
    def _opt(key: str) -> dict[str, Any]:
        val = defaults.get(key)
        return {"default": val} if val else {}

    return vol.Schema(
        {
            vol.Optional(CONF_ENT_PH_MANUAL, **_opt(CONF_ENT_PH_MANUAL)): _sensor_selector(),
            vol.Optional(CONF_ENT_ALKALINITY, **_opt(CONF_ENT_ALKALINITY)): _sensor_selector(),
            vol.Optional(CONF_ENT_FREE_CL, **_opt(CONF_ENT_FREE_CL)): _sensor_selector(),
            vol.Optional(CONF_ENT_COMBINED_CL, **_opt(CONF_ENT_COMBINED_CL)): _sensor_selector(),
            vol.Optional(CONF_ENT_TOTAL_CL, **_opt(CONF_ENT_TOTAL_CL)): _sensor_selector(),
            vol.Optional(CONF_ENT_CYANURIC, **_opt(CONF_ENT_CYANURIC)): _sensor_selector(),
        }
    )


def _schema_targets(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PH_MIN, default=defaults.get(CONF_PH_MIN, DEFAULT_PH_MIN)): _number(
                6.0, 8.0, 0.05
            ),
            vol.Required(
                CONF_PH_TARGET, default=defaults.get(CONF_PH_TARGET, DEFAULT_PH_TARGET)
            ): _number(6.0, 8.0, 0.05),
            vol.Required(CONF_PH_MAX, default=defaults.get(CONF_PH_MAX, DEFAULT_PH_MAX)): _number(
                6.0, 8.0, 0.05
            ),
            vol.Required(CONF_TA_MIN, default=defaults.get(CONF_TA_MIN, DEFAULT_TA_MIN)): _number(
                20, 250, 5
            ),
            vol.Required(
                CONF_TA_TARGET, default=defaults.get(CONF_TA_TARGET, DEFAULT_TA_TARGET)
            ): _number(20, 250, 5),
            vol.Required(CONF_TA_MAX, default=defaults.get(CONF_TA_MAX, DEFAULT_TA_MAX)): _number(
                20, 250, 5
            ),
            vol.Required(
                CONF_FC_MIN, default=defaults.get(CONF_FC_MIN, DEFAULT_FC_MIN_SALT)
            ): _number(0.0, 10.0, 0.1),
            vol.Required(
                CONF_FC_TARGET, default=defaults.get(CONF_FC_TARGET, DEFAULT_FC_TARGET_SALT)
            ): _number(0.0, 10.0, 0.1),
            vol.Required(
                CONF_FC_MAX, default=defaults.get(CONF_FC_MAX, DEFAULT_FC_MAX_SALT)
            ): _number(0.0, 10.0, 0.1),
            vol.Required(CONF_CC_MAX, default=defaults.get(CONF_CC_MAX, DEFAULT_CC_MAX)): _number(
                0.0, 5.0, 0.05
            ),
            vol.Required(
                CONF_CC_SHOCK_AT, default=defaults.get(CONF_CC_SHOCK_AT, DEFAULT_CC_SHOCK_AT)
            ): _number(0.0, 5.0, 0.05),
            vol.Required(
                CONF_REDOX_MIN, default=defaults.get(CONF_REDOX_MIN, DEFAULT_REDOX_MIN)
            ): _number(400, 900, 5),
            vol.Required(
                CONF_REDOX_TARGET, default=defaults.get(CONF_REDOX_TARGET, DEFAULT_REDOX_TARGET)
            ): _number(400, 900, 5),
            vol.Required(
                CONF_REDOX_MAX, default=defaults.get(CONF_REDOX_MAX, DEFAULT_REDOX_MAX)
            ): _number(400, 900, 5),
            vol.Required(
                CONF_PH_CALIB_THRESHOLD,
                default=defaults.get(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD),
            ): _number(0.05, 1.0, 0.05),
            vol.Required(
                CONF_MANUAL_MAX_AGE_H,
                default=defaults.get(CONF_MANUAL_MAX_AGE_H, DEFAULT_MANUAL_MAX_AGE_H),
            ): _number(1, 168, 1),
        }
    )


def _schema_chemicals(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_PH_MINUS_TYPE, default=defaults.get(CONF_PH_MINUS_TYPE, PH_MINUS_DRY_ACID)
            ): _select(PH_MINUS_CHOICES, "ph_minus"),
            vol.Required(
                CONF_PH_MINUS_STRENGTH,
                default=defaults.get(CONF_PH_MINUS_STRENGTH, DEFAULT_STRENGTH[PH_MINUS_DRY_ACID]),
            ): _pct_number(),
            vol.Required(
                CONF_PH_PLUS_TYPE, default=defaults.get(CONF_PH_PLUS_TYPE, PH_PLUS_SODA)
            ): _select(PH_PLUS_CHOICES, "ph_plus"),
            vol.Required(
                CONF_PH_PLUS_STRENGTH,
                default=defaults.get(CONF_PH_PLUS_STRENGTH, DEFAULT_STRENGTH[PH_PLUS_SODA]),
            ): _pct_number(),
            vol.Required(
                CONF_TA_PLUS_TYPE, default=defaults.get(CONF_TA_PLUS_TYPE, TA_PLUS_BICARB)
            ): _select(TA_PLUS_CHOICES, "ta_plus"),
            vol.Required(
                CONF_TA_PLUS_STRENGTH,
                default=defaults.get(CONF_TA_PLUS_STRENGTH, DEFAULT_STRENGTH[TA_PLUS_BICARB]),
            ): _pct_number(),
            vol.Required(
                CONF_SHOCK_TYPE, default=defaults.get(CONF_SHOCK_TYPE, SHOCK_DICHLOR)
            ): _select(SHOCK_CHOICES, "shock"),
            vol.Required(
                CONF_SHOCK_STRENGTH,
                default=defaults.get(CONF_SHOCK_STRENGTH, DEFAULT_STRENGTH[SHOCK_DICHLOR]),
            ): _pct_number(),
        }
    )


def _schema_dosing(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MAX_DOSE_FRACTION,
                default=defaults.get(CONF_MAX_DOSE_FRACTION, DEFAULT_MAX_DOSE_FRACTION),
            ): _number(0.1, 1.0, 0.05),
            vol.Required(
                CONF_DOSE_INTERVAL_H,
                default=defaults.get(CONF_DOSE_INTERVAL_H, DEFAULT_DOSE_INTERVAL_H),
            ): _number(1, 48, 1),
        }
    )


class PoolAdvisorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_entities_auto()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Pool"): str,
                vol.Required(CONF_POOL_VOLUME_M3, default=30.0): _number(1, 1000, 0.5),
                vol.Required(CONF_CHLORINATION, default=CHLORINATION_SALT): _select(
                    CHLORINATION_CHOICES, "chlorination"
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_entities_auto(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_entities_manual()
        return self.async_show_form(step_id="entities_auto", data_schema=_schema_entities_auto({}))

    async def async_step_entities_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_targets()
        return self.async_show_form(step_id="entities_manual", data_schema=_schema_entities_manual({}))

    async def async_step_targets(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_chemicals()

        is_salt = self._data.get(CONF_CHLORINATION) == CHLORINATION_SALT
        defaults = {
            CONF_FC_MIN: DEFAULT_FC_MIN_SALT if is_salt else DEFAULT_FC_MIN_CLASSIC,
            CONF_FC_TARGET: DEFAULT_FC_TARGET_SALT if is_salt else DEFAULT_FC_TARGET_CLASSIC,
            CONF_FC_MAX: DEFAULT_FC_MAX_SALT if is_salt else DEFAULT_FC_MAX_CLASSIC,
        }
        return self.async_show_form(step_id="targets", data_schema=_schema_targets(defaults))

    async def async_step_chemicals(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_dosing()
        return self.async_show_form(step_id="chemicals", data_schema=_schema_chemicals({}))

    async def async_step_dosing(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(step_id="dosing", data_schema=_schema_dosing({}))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "PoolAdvisorOptionsFlow":
        return PoolAdvisorOptionsFlow(config_entry)


class PoolAdvisorOptionsFlow(config_entries.OptionsFlow):
    """Menu-driven reconfigure: user picks one section and edits just that.

    The menu entry "edit_all" chains through every section (initial-setup
    style) for a full re-run.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict[str, Any] = {}
        self._chain = False  # True when user picked "edit_all"

    def _current_all(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        merged.update(self._entry.data)
        merged.update(self._entry.options)
        merged.update(self._data)
        return merged

    def _save(self) -> FlowResult:
        """Persist by merging current options with new data."""
        merged = {**self._entry.options, **self._data}
        return self.async_create_entry(title="", data=merged)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "pool",
                "entities_auto",
                "entities_manual",
                "targets",
                "chemicals",
                "dosing",
                "edit_all",
            ],
        )

    async def async_step_edit_all(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Full re-run — chain through every step."""
        self._chain = True
        return await self.async_step_pool()

    async def async_step_pool(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._chain:
                return await self.async_step_entities_auto()
            return self._save()

        cur = self._current_all()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POOL_VOLUME_M3, default=cur.get(CONF_POOL_VOLUME_M3, 30.0)
                ): _number(1, 1000, 0.5),
                vol.Required(
                    CONF_CHLORINATION, default=cur.get(CONF_CHLORINATION, CHLORINATION_SALT)
                ): _select(CHLORINATION_CHOICES, "chlorination"),
            }
        )
        return self.async_show_form(step_id="pool", data_schema=schema)

    async def async_step_entities_auto(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._chain:
                return await self.async_step_entities_manual()
            return self._save()
        return self.async_show_form(
            step_id="entities_auto", data_schema=_schema_entities_auto(self._current_all())
        )

    async def async_step_entities_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._chain:
                return await self.async_step_targets()
            return self._save()
        return self.async_show_form(
            step_id="entities_manual", data_schema=_schema_entities_manual(self._current_all())
        )

    async def async_step_targets(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._chain:
                return await self.async_step_chemicals()
            return self._save()
        return self.async_show_form(step_id="targets", data_schema=_schema_targets(self._current_all()))

    async def async_step_chemicals(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if self._chain:
                return await self.async_step_dosing()
            return self._save()
        return self.async_show_form(
            step_id="chemicals", data_schema=_schema_chemicals(self._current_all())
        )

    async def async_step_dosing(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self._save()
        return self.async_show_form(step_id="dosing", data_schema=_schema_dosing(self._current_all()))
