"""Config & options flow for Pool Chemistry Advisor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import selector

from .const import (
    CHLORINATION_CHOICES,
    CHLORINATION_SALT,
    CONF_CC_MAX,
    CONF_PH_DOSING,
    DEFAULT_PH_DOSING,
    PH_DOSING_CHOICES,
    CONF_CC_CRITICAL_HIGH,
    CONF_CHLORINATION,
    CONF_ENT_ALKALINITY,
    CONF_ENT_CYANURIC,
    CONF_ENT_FREE_CL,
    CONF_ENT_PH_ALERT_MAX,
    CONF_ENT_PH_ALERT_MIN,
    CONF_ENT_PH_AUTO,
    CONF_ENT_PH_MANUAL,
    CONF_ENT_PH_TARGET,
    CONF_ENT_PH_TOLERANCE_MAX,
    CONF_ENT_PH_TOLERANCE_MIN,
    CONF_ENT_REDOX,
    CONF_ENT_REDOX_ALERT_MAX,
    CONF_ENT_REDOX_ALERT_MIN,
    CONF_ENT_REDOX_TARGET,
    CONF_ENT_REDOX_TOLERANCE_MAX,
    CONF_ENT_REDOX_TOLERANCE_MIN,
    CONF_ENT_TEMPERATURE,
    CONF_ENT_TOTAL_CL,
    CONF_FC_CRITICAL_HIGH,
    CONF_FC_CRITICAL_LOW,
    CONF_FC_MAX,
    CONF_FC_MIN,
    CONF_FC_TARGET,
    CONF_NAME,
    CONF_PH_CALIB_THRESHOLD,
    CONF_PH_MINUS_NAME,
    CONF_PH_MINUS_STRENGTH,
    CONF_PH_MINUS_TYPE,
    CONF_PH_MINUS_MANUAL_NAME,
    CONF_PH_MINUS_MANUAL_STRENGTH,
    CONF_PH_MINUS_MANUAL_TYPE,
    CONF_PH_PLUS_NAME,
    CONF_PH_PLUS_STRENGTH,
    CONF_PH_PLUS_TYPE,
    CONF_POOL_VOLUME_M3,
    CONF_ROUTINE_CL_NAME,
    CONF_ROUTINE_CL_STRENGTH,
    CONF_ROUTINE_CL_TYPE,
    CONF_SHOCK_NAME,
    CONF_SHOCK_STRENGTH,
    CONF_SHOCK_TYPE,
    CONF_STALE_CYA_DAYS,
    CONF_STALE_FC_DAYS,
    CONF_STALE_PH_MANUAL_DAYS,
    CONF_STALE_TA_DAYS,
    CONF_TA_CRITICAL_HIGH,
    CONF_TA_CRITICAL_LOW,
    CONF_TA_MAX,
    CONF_TA_MIN,
    CONF_CYA_CRITICAL_HIGH,
    CONF_CYA_CRITICAL_LOW,
    CONF_CYA_MAX,
    CONF_CYA_MIN,
    CONF_CYA_NAME,
    CONF_CYA_STRENGTH,
    CONF_CYA_TARGET,
    CONF_CYA_TYPE,
    CONF_REDOX_DRIFT_THRESHOLD,
    CONF_TEST_ALKALINITY,
    CONF_TEST_CYANURIC,
    CONF_TEST_FREE_CL,
    CONF_TEST_MODE,
    CONF_TEST_PH_AUTO,
    CONF_TEST_PH_MANUAL,
    CONF_TEST_REDOX,
    CONF_TEST_TEMPERATURE,
    CONF_TEST_TOTAL_CL,
    CONF_TA_PLUS_NAME,
    CONF_TA_PLUS_STRENGTH,
    CONF_TA_PLUS_TYPE,
    CONF_TA_TARGET,
    DEFAULT_CC_MAX,
    DEFAULT_CC_CRITICAL_HIGH,
    DEFAULT_FC_CRITICAL_HIGH,
    DEFAULT_FC_CRITICAL_LOW,
    DEFAULT_FC_MAX_CLASSIC,
    DEFAULT_FC_MAX_SALT,
    DEFAULT_FC_MIN_CLASSIC,
    DEFAULT_FC_MIN_SALT,
    DEFAULT_FC_TARGET_CLASSIC,
    DEFAULT_FC_TARGET_SALT,
    DEFAULT_PH_CALIB_THRESHOLD,
    DEFAULT_STALE_CYA_DAYS,
    DEFAULT_STALE_FC_DAYS,
    DEFAULT_STALE_PH_MANUAL_DAYS,
    DEFAULT_STALE_TA_DAYS,
    DEFAULT_STRENGTH,
    CYA_CHOICES,
    CYA_PURE,
    DEFAULT_REDOX_DRIFT_THRESHOLD,
    DEFAULT_CYA_CRITICAL_HIGH,
    DEFAULT_CYA_CRITICAL_LOW,
    DEFAULT_CYA_MAX,
    DEFAULT_CYA_MIN,
    DEFAULT_CYA_STRENGTH,
    DEFAULT_CYA_TARGET,
    DEFAULT_TA_CRITICAL_HIGH,
    DEFAULT_TA_CRITICAL_LOW,
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


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Section-geschachtelte Eingaben auf flache Keys reduzieren.

    In HA ≥ 2024.8 liefert data_entry_flow.section() die Felder zwar meist
    schon flach zurück, manche Flows sehen jedoch `{"section_key": {...}}`.
    Wir ziehen alle dict-Werte eine Ebene hoch, damit self._data immer die
    gleichen Keys hat wie die Entry-Options.
    """
    out: dict[str, Any] = {}
    for k, v in user_input.items():
        if isinstance(v, dict):
            out.update(v)
        else:
            out[k] = v
    return out


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

    sondes_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_ENT_PH_AUTO, **_opt(CONF_ENT_PH_AUTO)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX, **_opt(CONF_ENT_REDOX)): _sensor_selector(),
                vol.Optional(CONF_ENT_TEMPERATURE, **_opt(CONF_ENT_TEMPERATURE)): _sensor_selector(),
            }
        ),
        {"collapsed": False},
    )
    # Setpoint + Alert-Min/Max der Bayrol-Anlage als Live-Quelle. Wenn nicht
    # konfiguriert, fällt der Advisor auf interne Defaults zurück (Pool-Advisor
    # bleibt funktional, aber zeigt nicht mehr was die Anlage tatsächlich tut).
    targets_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_ENT_PH_TARGET, **_opt(CONF_ENT_PH_TARGET)): _sensor_selector(),
                vol.Optional(CONF_ENT_PH_TOLERANCE_MIN, **_opt(CONF_ENT_PH_TOLERANCE_MIN)): _sensor_selector(),
                vol.Optional(CONF_ENT_PH_TOLERANCE_MAX, **_opt(CONF_ENT_PH_TOLERANCE_MAX)): _sensor_selector(),
                vol.Optional(CONF_ENT_PH_ALERT_MIN, **_opt(CONF_ENT_PH_ALERT_MIN)): _sensor_selector(),
                vol.Optional(CONF_ENT_PH_ALERT_MAX, **_opt(CONF_ENT_PH_ALERT_MAX)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX_TARGET, **_opt(CONF_ENT_REDOX_TARGET)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX_TOLERANCE_MIN, **_opt(CONF_ENT_REDOX_TOLERANCE_MIN)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX_TOLERANCE_MAX, **_opt(CONF_ENT_REDOX_TOLERANCE_MAX)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX_ALERT_MIN, **_opt(CONF_ENT_REDOX_ALERT_MIN)): _sensor_selector(),
                vol.Optional(CONF_ENT_REDOX_ALERT_MAX, **_opt(CONF_ENT_REDOX_ALERT_MAX)): _sensor_selector(),
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(
        {
            vol.Required("sondes"): sondes_section,
            vol.Required("anlage_targets"): targets_section,
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
            vol.Optional(CONF_ENT_TOTAL_CL, **_opt(CONF_ENT_TOTAL_CL)): _sensor_selector(),
            vol.Optional(CONF_ENT_CYANURIC, **_opt(CONF_ENT_CYANURIC)): _sensor_selector(),
        }
    )


def _schema_targets(defaults: dict[str, Any]) -> vol.Schema:
    def _dv(key, fallback):
        return defaults.get(key, fallback)

    # pH-Werte (Target, Toleranz, Alert) kommen alle live aus den Bayrol-
    # Bridge Number-/Sensor-Entities (siehe entities_auto). Keine pH-Sektion
    # mehr in den Pool-Advisor-Targets.
    ta_section = section(
        vol.Schema(
            {
                vol.Required(CONF_TA_MIN, default=_dv(CONF_TA_MIN, DEFAULT_TA_MIN)): _number(20, 250, 5),
                vol.Required(CONF_TA_TARGET, default=_dv(CONF_TA_TARGET, DEFAULT_TA_TARGET)): _number(20, 250, 5),
                vol.Required(CONF_TA_MAX, default=_dv(CONF_TA_MAX, DEFAULT_TA_MAX)): _number(20, 250, 5),
                vol.Required(CONF_TA_CRITICAL_LOW, default=_dv(CONF_TA_CRITICAL_LOW, DEFAULT_TA_CRITICAL_LOW)): _number(20, 250, 5),
                vol.Required(CONF_TA_CRITICAL_HIGH, default=_dv(CONF_TA_CRITICAL_HIGH, DEFAULT_TA_CRITICAL_HIGH)): _number(20, 300, 5),
            }
        ),
        {"collapsed": True},
    )
    cya_section = section(
        vol.Schema(
            {
                vol.Required(CONF_CYA_MIN, default=_dv(CONF_CYA_MIN, DEFAULT_CYA_MIN)): _number(0, 100, 1),
                vol.Required(CONF_CYA_TARGET, default=_dv(CONF_CYA_TARGET, DEFAULT_CYA_TARGET)): _number(10, 100, 5),
                vol.Required(CONF_CYA_MAX, default=_dv(CONF_CYA_MAX, DEFAULT_CYA_MAX)): _number(20, 200, 5),
                vol.Required(CONF_CYA_CRITICAL_LOW, default=_dv(CONF_CYA_CRITICAL_LOW, DEFAULT_CYA_CRITICAL_LOW)): _number(0, 100, 1),
                vol.Required(CONF_CYA_CRITICAL_HIGH, default=_dv(CONF_CYA_CRITICAL_HIGH, DEFAULT_CYA_CRITICAL_HIGH)): _number(30, 200, 5),
            }
        ),
        {"collapsed": True},
    )
    fc_section = section(
        vol.Schema(
            {
                vol.Required(CONF_FC_MIN, default=_dv(CONF_FC_MIN, DEFAULT_FC_MIN_SALT)): _number(0.0, 10.0, 0.1),
                vol.Required(CONF_FC_TARGET, default=_dv(CONF_FC_TARGET, DEFAULT_FC_TARGET_SALT)): _number(0.0, 10.0, 0.1),
                vol.Required(CONF_FC_MAX, default=_dv(CONF_FC_MAX, DEFAULT_FC_MAX_SALT)): _number(0.0, 10.0, 0.1),
                vol.Required(CONF_FC_CRITICAL_LOW, default=_dv(CONF_FC_CRITICAL_LOW, DEFAULT_FC_CRITICAL_LOW)): _number(0.0, 5.0, 0.05),
                vol.Required(CONF_FC_CRITICAL_HIGH, default=_dv(CONF_FC_CRITICAL_HIGH, DEFAULT_FC_CRITICAL_HIGH)): _number(1.0, 20.0, 0.5),
            }
        ),
        {"collapsed": True},
    )
    cc_section = section(
        vol.Schema(
            {
                vol.Required(CONF_CC_MAX, default=_dv(CONF_CC_MAX, DEFAULT_CC_MAX)): _number(0.0, 5.0, 0.05),
                vol.Required(CONF_CC_CRITICAL_HIGH, default=_dv(CONF_CC_CRITICAL_HIGH, DEFAULT_CC_CRITICAL_HIGH)): _number(0.0, 5.0, 0.05),
            }
        ),
        {"collapsed": True},
    )
    # Redox-Werte (Target, Toleranz, Alert) kommen alle live aus den Bayrol-
    # Bridge Number-/Sensor-Entities (siehe entities_auto).
    drift_section = section(
        vol.Schema(
            {
                vol.Required(CONF_PH_CALIB_THRESHOLD, default=_dv(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD)): _number(0.05, 1.0, 0.05),
                vol.Required(CONF_REDOX_DRIFT_THRESHOLD, default=_dv(CONF_REDOX_DRIFT_THRESHOLD, DEFAULT_REDOX_DRIFT_THRESHOLD)): _number(20, 200, 5),
            }
        ),
        {"collapsed": True},
    )
    stale_section = section(
        vol.Schema(
            {
                vol.Required(CONF_STALE_TA_DAYS, default=_dv(CONF_STALE_TA_DAYS, DEFAULT_STALE_TA_DAYS)): _number(1, 365, 1),
                vol.Required(CONF_STALE_PH_MANUAL_DAYS, default=_dv(CONF_STALE_PH_MANUAL_DAYS, DEFAULT_STALE_PH_MANUAL_DAYS)): _number(1, 365, 1),
                vol.Required(CONF_STALE_FC_DAYS, default=_dv(CONF_STALE_FC_DAYS, DEFAULT_STALE_FC_DAYS)): _number(1, 365, 1),
                vol.Required(CONF_STALE_CYA_DAYS, default=_dv(CONF_STALE_CYA_DAYS, DEFAULT_STALE_CYA_DAYS)): _number(1, 365, 1),
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(
        {
            vol.Required("alkalinity"): ta_section,
            vol.Required("cyanuric"): cya_section,
            vol.Required("free_chlorine"): fc_section,
            vol.Required("combined_chlorine"): cc_section,
            vol.Required("drift"): drift_section,
            vol.Required("stale"): stale_section,
        }
    )


def _opt_text(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """Optional text field with default if already set."""
    val = defaults.get(key)
    return {"default": val} if val else {}


def _schema_chemicals_auto(defaults: dict[str, Any]) -> vol.Schema:
    """Chemikalien für automatische Dosieranlage (Bayrol o.ä.).

    Diese Produkte werden vom Dosier-Controller kontinuierlich verwendet
    (typ. Liquid-Säure und Liquid-Chlor). Der Pool-Advisor zeigt für sie
    keinen manuellen Confirm-Button — der Verbrauch wird über pump_state
    automatisch erfasst.
    """
    ph_minus_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_PH_MINUS_NAME, **_opt_text(CONF_PH_MINUS_NAME, defaults)): str,
                vol.Required(
                    CONF_PH_MINUS_TYPE, default=defaults.get(CONF_PH_MINUS_TYPE, PH_MINUS_DRY_ACID)
                ): _select(PH_MINUS_CHOICES, "ph_minus"),
                vol.Required(
                    CONF_PH_MINUS_STRENGTH,
                    default=defaults.get(CONF_PH_MINUS_STRENGTH, DEFAULT_STRENGTH[PH_MINUS_DRY_ACID]),
                ): _pct_number(),
            }
        ),
        {"collapsed": False},
    )
    routine_cl_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_ROUTINE_CL_NAME, **_opt_text(CONF_ROUTINE_CL_NAME, defaults)): str,
                **(
                    {vol.Optional(CONF_ROUTINE_CL_TYPE, default=defaults[CONF_ROUTINE_CL_TYPE]): _select(SHOCK_CHOICES, "shock")}
                    if defaults.get(CONF_ROUTINE_CL_TYPE)
                    else {vol.Optional(CONF_ROUTINE_CL_TYPE): _select(SHOCK_CHOICES, "shock")}
                ),
                vol.Optional(
                    CONF_ROUTINE_CL_STRENGTH,
                    default=defaults.get(CONF_ROUTINE_CL_STRENGTH, 0),
                ): _pct_number(),
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(
        {
            vol.Required("routine_ph_minus"): ph_minus_section,
            vol.Required("routine_cl"): routine_cl_section,
        }
    )


def _schema_chemicals_manual(defaults: dict[str, Any]) -> vol.Schema:
    """Chemikalien für manuelle Dosierung durch den User.

    Für jede dieser Chemikalien stellt Pool-Advisor Number/DateTime/Button-
    Entitäten bereit, mit denen User durchgeführte Dosierungen bestätigen
    kann. Empfehlungen werden in Number-Entity vorbefüllt.
    """
    ph_minus_manual_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_PH_MINUS_MANUAL_NAME, **_opt_text(CONF_PH_MINUS_MANUAL_NAME, defaults)): str,
                vol.Optional(
                    CONF_PH_MINUS_MANUAL_TYPE,
                    default=defaults.get(CONF_PH_MINUS_MANUAL_TYPE, PH_MINUS_DRY_ACID),
                ): _select(PH_MINUS_CHOICES, "ph_minus"),
                vol.Optional(
                    CONF_PH_MINUS_MANUAL_STRENGTH,
                    default=defaults.get(
                        CONF_PH_MINUS_MANUAL_STRENGTH, DEFAULT_STRENGTH[PH_MINUS_DRY_ACID]
                    ),
                ): _pct_number(),
            }
        ),
        {"collapsed": False},
    )
    ph_plus_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_PH_PLUS_NAME, **_opt_text(CONF_PH_PLUS_NAME, defaults)): str,
                vol.Required(
                    CONF_PH_PLUS_TYPE, default=defaults.get(CONF_PH_PLUS_TYPE, PH_PLUS_SODA)
                ): _select(PH_PLUS_CHOICES, "ph_plus"),
                vol.Required(
                    CONF_PH_PLUS_STRENGTH,
                    default=defaults.get(CONF_PH_PLUS_STRENGTH, DEFAULT_STRENGTH[PH_PLUS_SODA]),
                ): _pct_number(),
            }
        ),
        {"collapsed": True},
    )
    ta_plus_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_TA_PLUS_NAME, **_opt_text(CONF_TA_PLUS_NAME, defaults)): str,
                vol.Required(
                    CONF_TA_PLUS_TYPE, default=defaults.get(CONF_TA_PLUS_TYPE, TA_PLUS_BICARB)
                ): _select(TA_PLUS_CHOICES, "ta_plus"),
                vol.Required(
                    CONF_TA_PLUS_STRENGTH,
                    default=defaults.get(CONF_TA_PLUS_STRENGTH, DEFAULT_STRENGTH[TA_PLUS_BICARB]),
                ): _pct_number(),
            }
        ),
        {"collapsed": True},
    )
    shock_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_SHOCK_NAME, **_opt_text(CONF_SHOCK_NAME, defaults)): str,
                **(
                    {vol.Optional(CONF_SHOCK_TYPE, default=defaults[CONF_SHOCK_TYPE]): _select(SHOCK_CHOICES, "shock")}
                    if defaults.get(CONF_SHOCK_TYPE)
                    else {vol.Optional(CONF_SHOCK_TYPE): _select(SHOCK_CHOICES, "shock")}
                ),
                vol.Optional(
                    CONF_SHOCK_STRENGTH,
                    default=defaults.get(CONF_SHOCK_STRENGTH, 0),
                ): _pct_number(),
            }
        ),
        {"collapsed": True},
    )
    cya_section = section(
        vol.Schema(
            {
                vol.Optional(CONF_CYA_NAME, **_opt_text(CONF_CYA_NAME, defaults)): str,
                vol.Optional(
                    CONF_CYA_TYPE, default=defaults.get(CONF_CYA_TYPE, CYA_PURE)
                ): _select(CYA_CHOICES, "cya"),
                vol.Optional(
                    CONF_CYA_STRENGTH,
                    default=defaults.get(CONF_CYA_STRENGTH, DEFAULT_CYA_STRENGTH),
                ): _pct_number(),
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(
        {
            vol.Required("ph_minus_manual"): ph_minus_manual_section,
            vol.Required("ph_plus"): ph_plus_section,
            vol.Required("ta_plus"): ta_plus_section,
            vol.Required("shock"): shock_section,
            vol.Required("cya"): cya_section,
        }
    )


def _schema_testmodus(defaults: dict[str, Any]) -> vol.Schema:
    def _opt_num(key: str, min_v: float, max_v: float, step: float = 0.1) -> dict[str, Any]:
        current = defaults.get(key)
        kwargs = {"default": current} if current not in (None, "") else {}
        return {vol.Optional(key, **kwargs): _number(min_v, max_v, step)}

    return vol.Schema(
        {
            vol.Required(
                CONF_TEST_MODE, default=defaults.get(CONF_TEST_MODE, False)
            ): selector.BooleanSelector(),
            **_opt_num(CONF_TEST_PH_AUTO, 4.0, 10.0, 0.05),
            **_opt_num(CONF_TEST_PH_MANUAL, 4.0, 10.0, 0.05),
            **_opt_num(CONF_TEST_REDOX, 100, 1000, 5),
            **_opt_num(CONF_TEST_TEMPERATURE, -10, 60, 0.5),
            **_opt_num(CONF_TEST_ALKALINITY, 5, 500, 5),
            **_opt_num(CONF_TEST_FREE_CL, 0, 20, 0.1),
            **_opt_num(CONF_TEST_TOTAL_CL, 0, 20, 0.1),
            **_opt_num(CONF_TEST_CYANURIC, 0, 300, 1),
        }
    )


class PoolAdvisorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial config flow."""

    VERSION = 2

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
                vol.Required(CONF_PH_DOSING, default=DEFAULT_PH_DOSING): _select(
                    PH_DOSING_CHOICES, "ph_dosing"
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
            self._data.update(_flatten(user_input))
            return await self.async_step_chemicals_auto()

        is_salt = self._data.get(CONF_CHLORINATION) == CHLORINATION_SALT
        defaults = {
            CONF_FC_MIN: DEFAULT_FC_MIN_SALT if is_salt else DEFAULT_FC_MIN_CLASSIC,
            CONF_FC_TARGET: DEFAULT_FC_TARGET_SALT if is_salt else DEFAULT_FC_TARGET_CLASSIC,
            CONF_FC_MAX: DEFAULT_FC_MAX_SALT if is_salt else DEFAULT_FC_MAX_CLASSIC,
        }
        return self.async_show_form(step_id="targets", data_schema=_schema_targets(defaults))

    async def async_step_chemicals_auto(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(_flatten(user_input))
            return await self.async_step_chemicals_manual()
        return self.async_show_form(step_id="chemicals_auto", data_schema=_schema_chemicals_auto({}))

    async def async_step_chemicals_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(_flatten(user_input))
            return await self.async_step_testmodus()
        return self.async_show_form(step_id="chemicals_manual", data_schema=_schema_chemicals_manual({}))

    async def async_step_testmodus(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(step_id="testmodus", data_schema=_schema_testmodus({}))

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
                "chemicals_auto",
                "chemicals_manual",
                "testmodus",
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
                vol.Required(
                    CONF_PH_DOSING, default=cur.get(CONF_PH_DOSING, DEFAULT_PH_DOSING)
                ): _select(PH_DOSING_CHOICES, "ph_dosing"),
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
            self._data.update(_flatten(user_input))
            if self._chain:
                return await self.async_step_chemicals_auto()
            return self._save()
        return self.async_show_form(step_id="targets", data_schema=_schema_targets(self._current_all()))

    async def async_step_chemicals_auto(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(_flatten(user_input))
            if self._chain:
                return await self.async_step_chemicals_manual()
            return self._save()
        return self.async_show_form(
            step_id="chemicals_auto", data_schema=_schema_chemicals_auto(self._current_all())
        )

    async def async_step_chemicals_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(_flatten(user_input))
            if self._chain:
                return await self.async_step_testmodus()
            return self._save()
        return self.async_show_form(
            step_id="chemicals_manual", data_schema=_schema_chemicals_manual(self._current_all())
        )

    async def async_step_testmodus(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self._save()
        return self.async_show_form(
            step_id="testmodus", data_schema=_schema_testmodus(self._current_all())
        )
