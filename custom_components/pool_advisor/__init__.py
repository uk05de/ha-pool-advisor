"""Pool Chemistry Advisor — HA integration."""
from __future__ import annotations

import logging
from datetime import datetime as _datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .calculator import (
    Recommendation,
    recommend_alkalinity,
    recommend_calibration,
    recommend_cya,
    recommend_drift_redox,
    recommend_ph,
    recommend_shock,
)
from .workflow import WorkflowContext
from .const import (
    CHLORINATION_SALT,
    CONF_CC_CRITICAL_HIGH,
    CONF_CHLORINATION,
    CONF_PH_DOSING,
    DEFAULT_PH_DOSING,
    PH_DOSING_BOTH,
    PH_DOSING_MINUS,
    PH_DOSING_PLUS,
    CONF_ENT_ALKALINITY,
    CONF_ENT_CYANURIC,
    CONF_ENT_FREE_CL,
    CONF_ENT_PH_AUTO,
    CONF_ENT_PH_ALERT_MAX,
    CONF_ENT_PH_ALERT_MIN,
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
    CONF_CC_MAX,
    CONF_FC_CRITICAL_HIGH,
    CONF_FC_CRITICAL_LOW,
    CONF_FC_MAX,
    CONF_FC_MIN,
    CONF_FC_TARGET,
    CONF_PH_CALIB_THRESHOLD,
    CONF_PH_MINUS_NAME,
    CONF_PH_MINUS_STRENGTH,
    CONF_PH_MINUS_TYPE,
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
    CONF_CYA_FORM,
    CONF_CYA_STRENGTH,
    CONF_CYA_TARGET,
    CONF_CYA_TYPE,
    CONF_REDOX_DRIFT_THRESHOLD,
    CONF_TEST_MODE,
    DEFAULT_REDOX_CRITICAL_HIGH,
    DEFAULT_REDOX_CRITICAL_LOW,
    DEFAULT_REDOX_DRIFT_THRESHOLD,
    DEFAULT_REDOX_MAX,
    DEFAULT_REDOX_MIN,
    DEFAULT_REDOX_TARGET,
    DEFAULT_STALE_CYA_DAYS,
    DEFAULT_STALE_FC_DAYS,
    DEFAULT_STALE_PH_MANUAL_DAYS,
    DEFAULT_STALE_TA_DAYS,
    TEST_VALUE_MAP,
    CONF_TA_PLUS_NAME,
    CONF_TA_PLUS_STRENGTH,
    CONF_TA_PLUS_TYPE,
    CONF_TA_TARGET,
    DEFAULT_FC_CRITICAL_HIGH,
    DEFAULT_FC_CRITICAL_LOW,
    DEFAULT_PH_CALIB_THRESHOLD,
    DEFAULT_PH_CRITICAL_HIGH,
    DEFAULT_PH_CRITICAL_LOW,
    DEFAULT_PH_MAX,
    DEFAULT_PH_MIN,
    DEFAULT_PH_TARGET,
    DEFAULT_CYA_CRITICAL_HIGH,
    DEFAULT_CYA_CRITICAL_LOW,
    DEFAULT_CYA_MAX,
    DEFAULT_CYA_MIN,
    DEFAULT_CYA_STRENGTH,
    DEFAULT_CYA_FORM,
    DEFAULT_CYA_TARGET,
    DEFAULT_TA_CRITICAL_HIGH,
    DEFAULT_TA_CRITICAL_LOW,
    DOMAIN,
    PRODUCT_LABELS,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.DATETIME,
    Platform.BUTTON,
    Platform.SELECT,
]

MANUAL_KEYS: tuple[str, ...] = (
    CONF_ENT_PH_MANUAL,
    CONF_ENT_ALKALINITY,
    CONF_ENT_FREE_CL,
    CONF_ENT_TOTAL_CL,
    CONF_ENT_CYANURIC,
)

AUTO_KEYS: tuple[str, ...] = (
    CONF_ENT_PH_AUTO,
    CONF_ENT_REDOX,
    CONF_ENT_TEMPERATURE,
)

# Bayrol-Anlage Setpoint/Alert-Entities — Live-Quelle für pH/Redox-Targets
# und kritische Schwellen. Werden wie AUTO_KEYS auf State-Changes überwacht,
# damit Setpoint-Änderungen am Bayrol-Display sofort eine Recalculation
# auslösen.
BAYROL_TARGET_KEYS: tuple[str, ...] = (
    CONF_ENT_PH_TARGET,
    CONF_ENT_PH_ALERT_MIN,
    CONF_ENT_PH_ALERT_MAX,
    CONF_ENT_PH_TOLERANCE_MIN,
    CONF_ENT_PH_TOLERANCE_MAX,
    CONF_ENT_REDOX_TARGET,
    CONF_ENT_REDOX_ALERT_MIN,
    CONF_ENT_REDOX_ALERT_MAX,
    CONF_ENT_REDOX_TOLERANCE_MIN,
    CONF_ENT_REDOX_TOLERANCE_MAX,
)

# Maps a manual-entity config key → (stale-threshold config key, default days).
# Used for "veraltet" warnings in the UI; the value itself is still used.
STALE_DAYS_MAP: dict[str, tuple[str, int]] = {
    CONF_ENT_PH_MANUAL: (CONF_STALE_PH_MANUAL_DAYS, DEFAULT_STALE_PH_MANUAL_DAYS),
    CONF_ENT_ALKALINITY: (CONF_STALE_TA_DAYS, DEFAULT_STALE_TA_DAYS),
    CONF_ENT_FREE_CL: (CONF_STALE_FC_DAYS, DEFAULT_STALE_FC_DAYS),
    CONF_ENT_TOTAL_CL: (CONF_STALE_FC_DAYS, DEFAULT_STALE_FC_DAYS),
    CONF_ENT_CYANURIC: (CONF_STALE_CYA_DAYS, DEFAULT_STALE_CYA_DAYS),
}

# Plausibility bounds — values outside are treated as "sensor offline / no data"
# to avoid wild recommendations when a dosing controller reports 0 while idle.
SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    CONF_ENT_PH_AUTO: (4.0, 10.0),
    CONF_ENT_PH_MANUAL: (4.0, 10.0),
    CONF_ENT_REDOX: (100.0, 1000.0),
    CONF_ENT_TEMPERATURE: (-10.0, 60.0),
    CONF_ENT_ALKALINITY: (5.0, 500.0),
    CONF_ENT_FREE_CL: (0.0, 20.0),
    CONF_ENT_TOTAL_CL: (0.0, 20.0),
    CONF_ENT_CYANURIC: (0.0, 300.0),
}


def _within_bounds(key: str, value: float | None) -> float | None:
    if value is None:
        return None
    bounds = SANITY_BOUNDS.get(key)
    if bounds is None:
        return value
    lo, hi = bounds
    if lo <= value <= hi:
        return value
    _LOGGER.debug(
        "Pool Advisor: implausible reading for %s: %r (allowed %.2f–%.2f) — treating as no data",
        key, value, lo, hi,
    )
    return None


class PoolAdvisorData:
    """Runtime state for a single config entry.

    All readings — AUTO (Bayrol live) and MANUAL (PoolLab spot checks) — are
    read live from HA state on every recalculation. A per-parameter stale
    threshold (in days) drives a UI warning; the value itself is still used
    for dose math so recommendations remain visible after the latest test.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from .dose_history import DoseHistory  # local import vermeidet Zyklen

        self.hass = hass
        self.entry = entry
        self.recommendations: dict[str, Recommendation] = {}
        self._unsub = None
        self.dose_history = DoseHistory(hass, entry.entry_id)

    # --- config helpers ---
    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _display(self, name_key: str, type_key: str) -> str:
        """Product display name: user-given if set, else chemical fallback."""
        name = self._cfg(name_key)
        if name:
            return str(name)
        chemical = self._cfg(type_key)
        if chemical:
            return PRODUCT_LABELS.get(chemical, chemical)
        return "Produkt"

    # --- Bayrol-Target Live-Read ---
    def _read_target(self, entity_key: str, fallback: float) -> float:
        """Lies einen Setpoint/Alert-Wert live aus der konfigurierten
        Bayrol-Entity. Fallback wenn nicht konfiguriert oder Entity
        unavailable — damit der Advisor weiter rechnet auch wenn die
        Bayrol-Bridge gerade offline ist."""
        entity_id = self._cfg(entity_key)
        if not entity_id:
            return fallback
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "", "unknown", "unavailable"):
            return fallback
        try:
            return float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Non-numeric state for target %s: %r — using fallback %s",
                entity_id, state.state, fallback,
            )
            return fallback

    # --- live read (auto) ---
    def _read_live(self, entity_key: str) -> float | None:
        # Test mode short-circuit: use configured static value instead of
        # reading a real entity. Bounds still applied for consistency.
        if self._cfg(CONF_TEST_MODE, False):
            test_key = TEST_VALUE_MAP.get(entity_key)
            if test_key is not None:
                raw = self._cfg(test_key)
                if raw is None or raw == "":
                    return None
                try:
                    return _within_bounds(entity_key, float(raw))
                except (TypeError, ValueError):
                    return None
            return None

        entity_id = self._cfg(entity_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "", "unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug("Non-numeric state for %s: %r", entity_id, state.state)
            return None
        return _within_bounds(entity_key, value)

    # --- live read (manual) ---
    def _manual_value(self, key: str) -> float | None:
        """Read the most recent manual (photometer) value, regardless of age.
        Age-based gating happens separately via `_is_stale` so the UI can warn
        while calculations still use the last known reading.
        """
        return self._read_live(key)

    def _combined_chlorine(self) -> float | None:
        """Combined Chlorine = max(0, TC − FC).

        Photometer-Tests (PoolLab, etc.) messen CC nie direkt — der Wert ergibt
        sich immer aus DPD-1 (FC) und DPD-3 (TC). Frische und Stale-Status
        erben somit von FC und TC; ein eigener CC-Sensor ist redundant und in
        der Praxis veraltet.
        """
        fc = self._read_live(CONF_ENT_FREE_CL)
        tc = self._read_live(CONF_ENT_TOTAL_CL)
        if fc is None or tc is None:
            return None
        return max(0.0, tc - fc)

    def _measured_at_for(self, key: str) -> _datetime | None:
        """Timestamp of the reading (UTC). Prefers the PoolLab `measured_at`
        attribute; falls back to entity `last_updated`. Test mode returns now.
        """
        if self._cfg(CONF_TEST_MODE, False):
            return dt_util.utcnow()
        entity_id = self._cfg(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "", "unknown", "unavailable"):
            return None
        measured_at: _datetime | None = None
        raw = state.attributes.get("measured_at")
        if isinstance(raw, _datetime):
            measured_at = raw
        elif isinstance(raw, str):
            measured_at = dt_util.parse_datetime(raw)
        if measured_at is None:
            measured_at = state.last_updated
        if measured_at is None:
            return None
        if measured_at.tzinfo is None:
            measured_at = dt_util.as_utc(
                measured_at.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            )
        else:
            measured_at = dt_util.as_utc(measured_at)
        return measured_at

    def _is_stale(self, key: str) -> bool:
        """True if reading is older than configured per-parameter threshold."""
        if self._cfg(CONF_TEST_MODE, False):
            return False
        measured_at = self._measured_at_for(key)
        if measured_at is None:
            return False
        mapping = STALE_DAYS_MAP.get(key)
        if mapping is None:
            return False
        conf_key, default_days = mapping
        days = float(self._cfg(conf_key, default_days))
        return (dt_util.utcnow() - measured_at) > timedelta(days=days)

    # --- lifecycle ---
    async def async_setup(self) -> None:
        # Dose-Historie aus Disk laden bevor Sensoren erstmals rendern
        await self.dose_history.async_load()

        tracked = [
            self._cfg(k)
            for k in (*AUTO_KEYS, *MANUAL_KEYS, *BAYROL_TARGET_KEYS)
            if self._cfg(k)
        ]

        @callback
        def _on_change(event: Event[EventStateChangedData]) -> None:
            self.recalculate()

        if tracked:
            self._unsub = async_track_state_change_event(self.hass, tracked, _on_change)

        self.recalculate()

    def build_workflow_context(self) -> WorkflowContext:
        fc_b = self._effective_fc_bounds()
        stale_map = {
            "ph_manual": self._is_stale(CONF_ENT_PH_MANUAL),
            "ta": self._is_stale(CONF_ENT_ALKALINITY),
            "fc": self._is_stale(CONF_ENT_FREE_CL),
            "tc": self._is_stale(CONF_ENT_TOTAL_CL),
            "cya": self._is_stale(CONF_ENT_CYANURIC),
        }
        measured_at_map = {
            "ph_manual": self._measured_at_for(CONF_ENT_PH_MANUAL),
            "ta": self._measured_at_for(CONF_ENT_ALKALINITY),
            "fc": self._measured_at_for(CONF_ENT_FREE_CL),
            "tc": self._measured_at_for(CONF_ENT_TOTAL_CL),
            "cya": self._measured_at_for(CONF_ENT_CYANURIC),
        }
        stale_days_map = {
            "ph_manual": int(self._cfg(CONF_STALE_PH_MANUAL_DAYS, DEFAULT_STALE_PH_MANUAL_DAYS)),
            "ta": int(self._cfg(CONF_STALE_TA_DAYS, DEFAULT_STALE_TA_DAYS)),
            "fc": int(self._cfg(CONF_STALE_FC_DAYS, DEFAULT_STALE_FC_DAYS)),
            "tc": int(self._cfg(CONF_STALE_FC_DAYS, DEFAULT_STALE_FC_DAYS)),
            "cya": int(self._cfg(CONF_STALE_CYA_DAYS, DEFAULT_STALE_CYA_DAYS)),
        }
        return WorkflowContext(
            volume_m3=float(self._cfg(CONF_POOL_VOLUME_M3, 30.0)),
            ph_minus_display=self._display(CONF_PH_MINUS_NAME, CONF_PH_MINUS_TYPE),
            ph_plus_display=self._display(CONF_PH_PLUS_NAME, CONF_PH_PLUS_TYPE),
            ta_plus_display=self._display(CONF_TA_PLUS_NAME, CONF_TA_PLUS_TYPE),
            routine_cl_display=self._display(CONF_ROUTINE_CL_NAME, CONF_ROUTINE_CL_TYPE),
            shock_display=self._display(CONF_SHOCK_NAME, CONF_SHOCK_TYPE),
            shock_type=self._cfg(CONF_SHOCK_TYPE) or "",
            ph_minus_type=self._cfg(CONF_PH_MINUS_TYPE) or "",
            ph_minus_strength_pct=float(self._cfg(CONF_PH_MINUS_STRENGTH) or 0),
            shock_strength_pct=float(self._cfg(CONF_SHOCK_STRENGTH, 56)),
            cya_display=self._display(CONF_CYA_NAME, CONF_CYA_TYPE),
            cya_strength_pct=float(self._cfg(CONF_CYA_STRENGTH, DEFAULT_CYA_STRENGTH)),
            cya_form=self._cfg(CONF_CYA_FORM, DEFAULT_CYA_FORM),
            ph_auto=self._read_live(CONF_ENT_PH_AUTO),
            ph_manual=self._manual_value(CONF_ENT_PH_MANUAL),
            ta=self._manual_value(CONF_ENT_ALKALINITY),
            fc=self._manual_value(CONF_ENT_FREE_CL),
            cc=self._combined_chlorine(),
            cya=self._manual_value(CONF_ENT_CYANURIC),
            water_temp=self._read_live(CONF_ENT_TEMPERATURE),
            ph_target=self._read_target(CONF_ENT_PH_TARGET, DEFAULT_PH_TARGET),
            ta_target=float(self._cfg(CONF_TA_TARGET)),
            fc_target=fc_b["fc_target"],
            cya_target=float(self._cfg(CONF_CYA_TARGET, DEFAULT_CYA_TARGET)),
            ph_min=self._read_target(CONF_ENT_PH_TOLERANCE_MIN, DEFAULT_PH_MIN),
            ph_max=self._read_target(CONF_ENT_PH_TOLERANCE_MAX, DEFAULT_PH_MAX),
            ta_min=float(self._cfg(CONF_TA_MIN)),
            ta_max=float(self._cfg(CONF_TA_MAX)),
            # Thresholds für Color-Coding — pH/Redox kritisch aus Bayrol-Anlage
            ph_critical_low=self._read_target(CONF_ENT_PH_ALERT_MIN, DEFAULT_PH_CRITICAL_LOW),
            ph_critical_high=self._read_target(CONF_ENT_PH_ALERT_MAX, DEFAULT_PH_CRITICAL_HIGH),
            ta_critical_low=float(self._cfg(CONF_TA_CRITICAL_LOW, DEFAULT_TA_CRITICAL_LOW)),
            ta_critical_high=float(self._cfg(CONF_TA_CRITICAL_HIGH, DEFAULT_TA_CRITICAL_HIGH)),
            fc_critical_low=fc_b["fc_critical_low"],
            fc_critical_high=fc_b["fc_critical_high"],
            fc_min_val=fc_b["fc_min"],
            fc_max=fc_b["fc_max"],
            cc_max=float(self._cfg(CONF_CC_MAX)),
            cc_critical_high=float(self._cfg(CONF_CC_CRITICAL_HIGH)),
            cya_min=float(self._cfg(CONF_CYA_MIN, DEFAULT_CYA_MIN)),
            cya_max=float(self._cfg(CONF_CYA_MAX, DEFAULT_CYA_MAX)),
            cya_critical_low=float(self._cfg(CONF_CYA_CRITICAL_LOW, DEFAULT_CYA_CRITICAL_LOW)),
            cya_critical_high=float(self._cfg(CONF_CYA_CRITICAL_HIGH, DEFAULT_CYA_CRITICAL_HIGH)),
            ph_calib_threshold=float(self._cfg(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD)),
            redox_drift_threshold=float(
                self._cfg(CONF_REDOX_DRIFT_THRESHOLD, DEFAULT_REDOX_DRIFT_THRESHOLD)
            ),
            total_cl=self._manual_value(CONF_ENT_TOTAL_CL),
            redox=self._read_live(CONF_ENT_REDOX),
            redox_min=self._read_target(CONF_ENT_REDOX_TOLERANCE_MIN, DEFAULT_REDOX_MIN),
            redox_target=self._read_target(CONF_ENT_REDOX_TARGET, DEFAULT_REDOX_TARGET),
            redox_max=self._read_target(CONF_ENT_REDOX_TOLERANCE_MAX, DEFAULT_REDOX_MAX),
            redox_critical_low=self._read_target(CONF_ENT_REDOX_ALERT_MIN, DEFAULT_REDOX_CRITICAL_LOW),
            redox_critical_high=self._read_target(CONF_ENT_REDOX_ALERT_MAX, DEFAULT_REDOX_CRITICAL_HIGH),
            stale=stale_map,
            measured_at=measured_at_map,
            stale_days=stale_days_map,
        )

    async def async_unload(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    # --- effective FC-Bounds (dynamisch aus CYA wenn frisch, sonst config) ---
    def _effective_fc_bounds(self) -> dict:
        cya_now = self._manual_value(CONF_ENT_CYANURIC)
        cya_stale = self._is_stale(CONF_ENT_CYANURIC)
        fc_min_cfg = float(self._cfg(CONF_FC_MIN))
        fc_target_cfg = float(self._cfg(CONF_FC_TARGET))
        fc_max_cfg = float(self._cfg(CONF_FC_MAX))
        fc_crit_low_cfg = float(self._cfg(CONF_FC_CRITICAL_LOW, DEFAULT_FC_CRITICAL_LOW))
        fc_crit_high_cfg = float(self._cfg(CONF_FC_CRITICAL_HIGH, DEFAULT_FC_CRITICAL_HIGH))
        if cya_now is not None and not cya_stale:
            return {
                "fc_min": max(fc_min_cfg, cya_now * 0.05),
                "fc_target": max(fc_target_cfg, cya_now * 0.075),
                "fc_max": max(fc_max_cfg, cya_now * 0.15),
                "fc_critical_low": fc_crit_low_cfg,
                "fc_critical_high": max(fc_crit_high_cfg, cya_now * 0.40),
                "dynamic": True,
            }
        return {
            "fc_min": fc_min_cfg,
            "fc_target": fc_target_cfg,
            "fc_max": fc_max_cfg,
            "fc_critical_low": fc_crit_low_cfg,
            "fc_critical_high": fc_crit_high_cfg,
            "dynamic": False,
        }

    # --- the actual work ---
    def recalculate(self) -> None:
        volume = float(self._cfg(CONF_POOL_VOLUME_M3, 30.0))
        chlorination_is_salt = self._cfg(CONF_CHLORINATION) == CHLORINATION_SALT
        # Auto-detect dosing system: salt electrolysis OR a configured redox
        # entity (implies Bayrol-style dosing controller).
        has_auto_dosing = chlorination_is_salt or bool(self._cfg(CONF_ENT_REDOX))

        ph_auto = self._read_live(CONF_ENT_PH_AUTO)
        ph_manual = self._manual_value(CONF_ENT_PH_MANUAL)

        # Prefer manual (photometer) if present; else the Bayrol auto reading.
        ph_for_dosing = ph_manual if ph_manual is not None else ph_auto

        ph_dosing = self._cfg(CONF_PH_DOSING, DEFAULT_PH_DOSING)
        ph_dosing_minus = ph_dosing in (PH_DOSING_MINUS, PH_DOSING_BOTH)
        ph_dosing_plus = ph_dosing in (PH_DOSING_PLUS, PH_DOSING_BOTH)
        ph_rec = recommend_ph(
            current=ph_for_dosing,
            target=self._read_target(CONF_ENT_PH_TARGET, DEFAULT_PH_TARGET),
            ph_min=self._read_target(CONF_ENT_PH_TOLERANCE_MIN, DEFAULT_PH_MIN),
            ph_max=self._read_target(CONF_ENT_PH_TOLERANCE_MAX, DEFAULT_PH_MAX),
            ph_critical_low=self._read_target(CONF_ENT_PH_ALERT_MIN, DEFAULT_PH_CRITICAL_LOW),
            ph_critical_high=self._read_target(CONF_ENT_PH_ALERT_MAX, DEFAULT_PH_CRITICAL_HIGH),
            volume_m3=volume,
            ph_minus_type=self._cfg(CONF_PH_MINUS_TYPE),
            ph_minus_strength_pct=float(self._cfg(CONF_PH_MINUS_STRENGTH)),
            ph_minus_display=self._display(CONF_PH_MINUS_NAME, CONF_PH_MINUS_TYPE),
            ph_plus_type=self._cfg(CONF_PH_PLUS_TYPE),
            ph_plus_strength_pct=float(self._cfg(CONF_PH_PLUS_STRENGTH)),
            ph_plus_display=self._display(CONF_PH_PLUS_NAME, CONF_PH_PLUS_TYPE),
            ph_dosing_minus=ph_dosing_minus,
            ph_dosing_plus=ph_dosing_plus,
        )
        ta_rec = recommend_alkalinity(
            current=self._manual_value(CONF_ENT_ALKALINITY),
            target=float(self._cfg(CONF_TA_TARGET)),
            ta_min=float(self._cfg(CONF_TA_MIN)),
            ta_max=float(self._cfg(CONF_TA_MAX)),
            ta_critical_low=float(self._cfg(CONF_TA_CRITICAL_LOW, DEFAULT_TA_CRITICAL_LOW)),
            ta_critical_high=float(self._cfg(CONF_TA_CRITICAL_HIGH, DEFAULT_TA_CRITICAL_HIGH)),
            volume_m3=volume,
            ta_plus_type=self._cfg(CONF_TA_PLUS_TYPE),
            ta_plus_strength_pct=float(self._cfg(CONF_TA_PLUS_STRENGTH)),
            ta_plus_display=self._display(CONF_TA_PLUS_NAME, CONF_TA_PLUS_TYPE),
            # Kontext für TA-Senkung (Format C braucht pH-Erst-Dosis):
            ph_current=ph_for_dosing,
            ph_minus_type=self._cfg(CONF_PH_MINUS_TYPE),
            ph_minus_strength_pct=float(self._cfg(CONF_PH_MINUS_STRENGTH) or 0),
            ph_minus_display=self._display(CONF_PH_MINUS_NAME, CONF_PH_MINUS_TYPE),
        )
        fc_b = self._effective_fc_bounds()
        routine_strength_raw = self._cfg(CONF_ROUTINE_CL_STRENGTH)
        cl_rec = recommend_shock(
            combined_cl=self._combined_chlorine(),
            free_cl=self._manual_value(CONF_ENT_FREE_CL),
            total_cl=self._manual_value(CONF_ENT_TOTAL_CL),
            fc_min=fc_b["fc_min"],
            fc_max=fc_b["fc_max"],
            fc_target=fc_b["fc_target"],
            fc_critical_low=fc_b["fc_critical_low"],
            fc_critical_high=fc_b["fc_critical_high"],
            cc_max=float(self._cfg(CONF_CC_MAX)),
            cc_critical_high=float(self._cfg(CONF_CC_CRITICAL_HIGH)),
            volume_m3=volume,
            routine_type=self._cfg(CONF_ROUTINE_CL_TYPE),
            routine_strength_pct=(
                float(routine_strength_raw) if routine_strength_raw is not None else 0.0
            ),
            routine_display=self._display(CONF_ROUTINE_CL_NAME, CONF_ROUTINE_CL_TYPE),
            shock_type=self._cfg(CONF_SHOCK_TYPE),
            shock_strength_pct=float(self._cfg(CONF_SHOCK_STRENGTH)),
            shock_display=self._display(CONF_SHOCK_NAME, CONF_SHOCK_TYPE),
            chlorination_is_salt=chlorination_is_salt,
            has_auto_dosing=has_auto_dosing,
            cya=self._manual_value(CONF_ENT_CYANURIC),
            water_temp=self._read_live(CONF_ENT_TEMPERATURE),
        )
        calib_rec = recommend_calibration(
            ph_auto=ph_auto,
            ph_manual=ph_manual,
            threshold=float(self._cfg(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD)),
        )
        cya_rec = recommend_cya(
            current=self._manual_value(CONF_ENT_CYANURIC),
            target=float(self._cfg(CONF_CYA_TARGET, DEFAULT_CYA_TARGET)),
            cya_min=float(self._cfg(CONF_CYA_MIN, DEFAULT_CYA_MIN)),
            cya_max=float(self._cfg(CONF_CYA_MAX, DEFAULT_CYA_MAX)),
            critical_low=float(self._cfg(CONF_CYA_CRITICAL_LOW, DEFAULT_CYA_CRITICAL_LOW)),
            critical_high=float(self._cfg(CONF_CYA_CRITICAL_HIGH, DEFAULT_CYA_CRITICAL_HIGH)),
            volume_m3=volume,
            cya_display=self._display(CONF_CYA_NAME, CONF_CYA_TYPE),
            cya_strength_pct=float(self._cfg(CONF_CYA_STRENGTH, DEFAULT_CYA_STRENGTH)),
            cya_form=self._cfg(CONF_CYA_FORM, DEFAULT_CYA_FORM),
        )
        drift_redox_rec = recommend_drift_redox(
            redox_live=self._read_live(CONF_ENT_REDOX),
            free_cl=self._manual_value(CONF_ENT_FREE_CL),
            ph=ph_manual if ph_manual is not None else ph_auto,
            cya=self._manual_value(CONF_ENT_CYANURIC),
            threshold_mv=float(
                self._cfg(CONF_REDOX_DRIFT_THRESHOLD, DEFAULT_REDOX_DRIFT_THRESHOLD)
            ),
        )
        self.recommendations = {
            "ph": ph_rec,
            "alkalinity": ta_rec,
            "chlorine": cl_rec,
            "cya": cya_rec,
            "calibration": calib_rec,
            "drift_redox": drift_redox_rec,
        }
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # --- recommended-dose lookup (für Manuell-Dosing-Number-Entities) ---
    def recommended_dose_amount(self, chem_key: str) -> float:
        """Liefere die für eine manuelle Chemie aktuell empfohlene Menge.

        Mapping zwischen Empfehlungs-Slot und manueller Chemie ist
        action-basiert: pH-Lower → ph_minus_manual, pH-Raise → ph_plus,
        TA-Raise → ta_plus, Chlor-Shock/Raise → cl_manual,
        CYA-Raise → cya. Alle anderen Actions → 0 (kein pending-Dose).

        Bei mehrstufigen Empfehlungen wird die Menge des ersten Schritts
        zurückgegeben — das User dosiert pro Bestätigung einen Schritt.
        """
        rec_map = {
            "ph_minus_manual": ("ph", "lower"),
            "ph_plus": ("ph", "raise"),
            "ta_plus": ("alkalinity", "raise"),
            "cl_manual": ("chlorine", ("raise", "shock")),
            "cya": ("cya", "raise"),
        }
        mapping = rec_map.get(chem_key)
        if mapping is None:
            return 0.0
        rec_key, expected_action = mapping
        rec = self.recommendations.get(rec_key)
        if rec is None or not rec.steps:
            return 0.0
        if isinstance(expected_action, tuple):
            if rec.action not in expected_action:
                return 0.0
        else:
            if rec.action != expected_action:
                return 0.0
        return float(rec.steps[0].amount)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = PoolAdvisorData(hass, entry)
    await data.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data: PoolAdvisorData | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data is not None:
        await data.async_unload()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries between schema versions.

    v1 → v2 (Parameter-Struktur-Vereinheitlichung):
      CYA: cya_watch_at → cya_max, cya_critical_at → cya_critical_high,
           neu cya_min (default 20), neu cya_critical_low (default 0 = aus)
      CC:  cc_shock_at → cc_critical_high
      FC:  neu fc_critical_high (default 5) — nur als Setdefault
      Redox: neu redox_critical_low/high (defaults 600/800) — setdefault
    """
    _LOGGER.info("Migrating pool_advisor entry from v%s", entry.version)
    if entry.version < 2:
        new_options = {**entry.options}
        new_data = {**entry.data}
        for source in (new_options, new_data):
            # CYA renames
            if "cya_watch_at" in source:
                source["cya_max"] = source.pop("cya_watch_at")
            if "cya_critical_at" in source:
                source["cya_critical_high"] = source.pop("cya_critical_at")
            source.setdefault("cya_min", 20.0)
            source.setdefault("cya_critical_low", 0.0)
            # CC rename
            if "cc_shock_at" in source:
                source["cc_critical_high"] = source.pop("cc_shock_at")
            # FC additive
            source.setdefault("fc_critical_high", 5.0)
            # Redox additive
            source.setdefault("redox_critical_low", 600.0)
            source.setdefault("redox_critical_high", 800.0)
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2
        )
    return True
