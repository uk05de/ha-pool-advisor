"""Pool Chemistry Advisor — HA integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
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
from .workflow import WorkflowContext, get_workflow, step_count
from .const import (
    CHLORINATION_SALT,
    CONF_CC_SHOCK_AT,
    CONF_CHLORINATION,
    CONF_PH_DOSING,
    DEFAULT_PH_DOSING,
    PH_DOSING_BOTH,
    PH_DOSING_MINUS,
    PH_DOSING_PLUS,
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
    CONF_FC_CRITICAL_LOW,
    CONF_FC_MIN,
    CONF_FC_TARGET,
    CONF_MANUAL_MAX_AGE_H,
    CONF_MAX_DOSE_FRACTION,
    CONF_PH_CALIB_THRESHOLD,
    CONF_PH_CRITICAL_HIGH,
    CONF_PH_CRITICAL_LOW,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_MINUS_NAME,
    CONF_PH_MINUS_STRENGTH,
    CONF_PH_MINUS_TYPE,
    CONF_PH_PLUS_NAME,
    CONF_PH_PLUS_STRENGTH,
    CONF_PH_PLUS_TYPE,
    CONF_PH_TARGET,
    CONF_POOL_VOLUME_M3,
    CONF_ROUTINE_CL_NAME,
    CONF_ROUTINE_CL_STRENGTH,
    CONF_ROUTINE_CL_TYPE,
    CONF_SHOCK_NAME,
    CONF_SHOCK_STRENGTH,
    CONF_SHOCK_TYPE,
    CONF_TA_CRITICAL_HIGH,
    CONF_TA_CRITICAL_LOW,
    CONF_TA_MAX,
    CONF_TA_MIN,
    CONF_CYA_CRITICAL_AT,
    CONF_CYA_NAME,
    CONF_CYA_STRENGTH,
    CONF_CYA_TARGET,
    CONF_CYA_TYPE,
    CONF_CYA_WATCH_AT,
    CONF_REDOX_DRIFT_THRESHOLD,
    CONF_TEST_MODE,
    DEFAULT_REDOX_DRIFT_THRESHOLD,
    TEST_VALUE_MAP,
    CONF_TA_PLUS_NAME,
    CONF_TA_PLUS_STRENGTH,
    CONF_TA_PLUS_TYPE,
    CONF_TA_TARGET,
    DEFAULT_FC_CRITICAL_LOW,
    DEFAULT_MANUAL_MAX_AGE_H,
    DEFAULT_PH_CALIB_THRESHOLD,
    DEFAULT_PH_CRITICAL_HIGH,
    DEFAULT_PH_CRITICAL_LOW,
    DEFAULT_CYA_CRITICAL_AT,
    DEFAULT_CYA_STRENGTH,
    DEFAULT_CYA_TARGET,
    DEFAULT_CYA_WATCH_AT,
    DEFAULT_TA_CRITICAL_HIGH,
    DEFAULT_TA_CRITICAL_LOW,
    DOMAIN,
    MODE_NORMAL,
    PRODUCT_LABELS,
    SIGNAL_UPDATE,
    STORAGE_KEY_WORKFLOW,
    STORAGE_VERSION,
    WARTUNGSMODI,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]

MANUAL_KEYS: tuple[str, ...] = (
    CONF_ENT_PH_MANUAL,
    CONF_ENT_ALKALINITY,
    CONF_ENT_FREE_CL,
    CONF_ENT_COMBINED_CL,
    CONF_ENT_TOTAL_CL,
    CONF_ENT_CYANURIC,
)

AUTO_KEYS: tuple[str, ...] = (
    CONF_ENT_PH_AUTO,
    CONF_ENT_REDOX,
    CONF_ENT_TEMPERATURE,
)

# Plausibility bounds — values outside are treated as "sensor offline / no data"
# to avoid wild recommendations when a dosing controller reports 0 while idle.
SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    CONF_ENT_PH_AUTO: (4.0, 10.0),
    CONF_ENT_PH_MANUAL: (4.0, 10.0),
    CONF_ENT_REDOX: (100.0, 1000.0),
    CONF_ENT_TEMPERATURE: (-10.0, 60.0),
    CONF_ENT_ALKALINITY: (5.0, 500.0),
    CONF_ENT_FREE_CL: (0.0, 20.0),
    CONF_ENT_COMBINED_CL: (0.0, 10.0),
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

    Analysis model:
      - AUTO entities (pH-Auto, Redox, Temperatur) update live.
      - MANUAL entities are captured into a *snapshot* when the user presses
        the "Analyse durchführen" button (or on setup). Each snapshot entry
        respects `measured_at` attribute of the source entity; if it's older
        than the configured window, the value is marked `included: False` and
        treated as missing in the recommendations.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.recommendations: dict[str, Recommendation] = {}
        self.manual_snapshot: dict[str, dict[str, Any]] = {}
        self.analysis_at: datetime | None = None
        self._unsub = None
        # Workflow state
        self.mode: str = MODE_NORMAL
        self.step_index: int = 0
        self.step_started_at: datetime | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_WORKFLOW}.{entry.entry_id}")

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

    # --- snapshot capture (manual) ---
    def _capture_manual(self, entity_key: str, window_h: float) -> dict[str, Any]:
        out: dict[str, Any] = {
            "entity_id": None,
            "value": None,
            "measured_at": None,
            "measured_at_source": None,
            "age_hours": None,
            "included": False,
        }
        # Test mode: use static config value, always fresh
        if self._cfg(CONF_TEST_MODE, False):
            test_key = TEST_VALUE_MAP.get(entity_key)
            if test_key is None:
                return out
            raw = self._cfg(test_key)
            if raw is None or raw == "":
                return out
            try:
                value = _within_bounds(entity_key, float(raw))
            except (TypeError, ValueError):
                return out
            if value is None:
                return out
            now = dt_util.utcnow()
            out.update(
                {
                    "entity_id": f"test:{test_key}",
                    "value": value,
                    "measured_at": now.isoformat(),
                    "measured_at_source": "test_mode",
                    "age_hours": 0.0,
                    "included": True,
                }
            )
            return out

        entity_id = self._cfg(entity_key)
        out["entity_id"] = entity_id
        if not entity_id:
            return out
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "", "unknown", "unavailable"):
            return out
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return out
        value = _within_bounds(entity_key, value)
        if value is None:
            return out

        # Prefer `measured_at` attribute (PoolLab etc.); fall back to last_updated.
        measured_at: datetime | None = None
        source = "measured_at"
        raw = state.attributes.get("measured_at")
        if isinstance(raw, datetime):
            measured_at = raw
        elif isinstance(raw, str):
            measured_at = dt_util.parse_datetime(raw)
        if measured_at is None:
            measured_at = state.last_updated
            source = "last_updated"
        if measured_at.tzinfo is None:
            # Treat naive timestamps as local time (HA convention).
            measured_at = dt_util.as_utc(
                measured_at.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            )
        else:
            measured_at = dt_util.as_utc(measured_at)

        age_h = (dt_util.utcnow() - measured_at).total_seconds() / 3600.0
        out.update(
            {
                "value": value,
                "measured_at": measured_at.isoformat(),
                "measured_at_source": source,
                "age_hours": round(age_h, 2),
                "included": age_h <= window_h,
            }
        )
        return out

    def _manual_value(self, key: str) -> float | None:
        snap = self.manual_snapshot.get(key)
        if not snap or not snap.get("included"):
            return None
        return snap.get("value")

    # --- lifecycle ---
    async def async_setup(self) -> None:
        # Restore workflow state
        stored = await self._store.async_load()
        if stored:
            mode = stored.get("mode", MODE_NORMAL)
            self.mode = mode if mode in WARTUNGSMODI else MODE_NORMAL
            self.step_index = int(stored.get("step_index", 0))
            started_at_raw = stored.get("step_started_at")
            if started_at_raw:
                self.step_started_at = dt_util.parse_datetime(started_at_raw)

        tracked = [self._cfg(k) for k in AUTO_KEYS if self._cfg(k)]

        @callback
        def _on_change(event: Event[EventStateChangedData]) -> None:
            self.recalculate()

        if tracked:
            self._unsub = async_track_state_change_event(self.hass, tracked, _on_change)

        self.run_analysis()

    async def _persist_workflow(self) -> None:
        await self._store.async_save(
            {
                "mode": self.mode,
                "step_index": self.step_index,
                "step_started_at": self.step_started_at.isoformat()
                if self.step_started_at
                else None,
            }
        )

    async def async_set_mode(self, mode: str) -> None:
        if mode not in WARTUNGSMODI:
            return
        self.mode = mode
        self.step_index = 0
        self.step_started_at = dt_util.utcnow()
        await self._persist_workflow()
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def async_try_advance_step(self) -> bool:
        """Called after run_analysis: advance if current step is satisfied.
        Returns True if advanced."""
        if self.mode == MODE_NORMAL:
            return False
        ctx = self.build_workflow_context()
        step = self.current_step()
        if not step.satisfied(ctx):
            return False
        steps = get_workflow(self.mode)
        self.step_index += 1
        self.step_started_at = dt_util.utcnow()
        if self.step_index >= len(steps):
            self.mode = MODE_NORMAL
            self.step_index = 0
        await self._persist_workflow()
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")
        return True

    def step_age_hours(self) -> float:
        if self.step_started_at is None:
            return 0.0
        return (dt_util.utcnow() - self.step_started_at).total_seconds() / 3600.0

    def current_step(self):
        steps = get_workflow(self.mode)
        if 0 <= self.step_index < len(steps):
            return steps[self.step_index]
        return steps[0]

    def build_workflow_context(self) -> WorkflowContext:
        return WorkflowContext(
            volume_m3=float(self._cfg(CONF_POOL_VOLUME_M3, 30.0)),
            ph_minus_display=self._display(CONF_PH_MINUS_NAME, CONF_PH_MINUS_TYPE),
            ph_plus_display=self._display(CONF_PH_PLUS_NAME, CONF_PH_PLUS_TYPE),
            ta_plus_display=self._display(CONF_TA_PLUS_NAME, CONF_TA_PLUS_TYPE),
            routine_cl_display=self._display(CONF_ROUTINE_CL_NAME, CONF_ROUTINE_CL_TYPE),
            shock_display=self._display(CONF_SHOCK_NAME, CONF_SHOCK_TYPE),
            shock_type=self._cfg(CONF_SHOCK_TYPE) or "",
            shock_strength_pct=float(self._cfg(CONF_SHOCK_STRENGTH, 56)),
            cya_display=self._display(CONF_CYA_NAME, CONF_CYA_TYPE),
            cya_strength_pct=float(self._cfg(CONF_CYA_STRENGTH, DEFAULT_CYA_STRENGTH)),
            ph_auto=self._read_live(CONF_ENT_PH_AUTO),
            ph_manual=self._manual_value(CONF_ENT_PH_MANUAL),
            ta=self._manual_value(CONF_ENT_ALKALINITY),
            fc=self._manual_value(CONF_ENT_FREE_CL),
            cc=self._manual_value(CONF_ENT_COMBINED_CL),
            cya=self._manual_value(CONF_ENT_CYANURIC),
            ph_target=float(self._cfg(CONF_PH_TARGET)),
            ta_target=float(self._cfg(CONF_TA_TARGET)),
            fc_target=float(self._cfg(CONF_FC_TARGET)),
            cya_target=float(self._cfg(CONF_CYA_TARGET, DEFAULT_CYA_TARGET)),
            ph_min=float(self._cfg(CONF_PH_MIN)),
            ph_max=float(self._cfg(CONF_PH_MAX)),
            ta_min=float(self._cfg(CONF_TA_MIN)),
            ta_max=float(self._cfg(CONF_TA_MAX)),
        )

    async def async_unload(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    # --- the actual work ---
    def run_analysis(self) -> None:
        """Capture a fresh manual snapshot, then recompute recommendations."""
        window_h = float(self._cfg(CONF_MANUAL_MAX_AGE_H, DEFAULT_MANUAL_MAX_AGE_H))
        self.manual_snapshot = {k: self._capture_manual(k, window_h) for k in MANUAL_KEYS}
        self.analysis_at = dt_util.utcnow()
        self.recalculate()

    def recalculate(self) -> None:
        volume = float(self._cfg(CONF_POOL_VOLUME_M3, 30.0))
        chlorination_is_salt = self._cfg(CONF_CHLORINATION) == CHLORINATION_SALT
        max_frac = float(self._cfg(CONF_MAX_DOSE_FRACTION, 0.5))
        interval_h = int(self._cfg(CONF_DOSE_INTERVAL_H, 6))
        # Auto-detect dosing system: salt electrolysis OR a configured redox
        # entity (implies Bayrol-style dosing controller).
        has_auto_dosing = chlorination_is_salt or bool(self._cfg(CONF_ENT_REDOX))

        ph_auto = self._read_live(CONF_ENT_PH_AUTO)
        ph_manual = self._manual_value(CONF_ENT_PH_MANUAL)

        # Prefer manual (photometer) if the snapshot included it; else auto.
        ph_for_dosing = ph_manual if ph_manual is not None else ph_auto

        ph_dosing = self._cfg(CONF_PH_DOSING, DEFAULT_PH_DOSING)
        ph_dosing_minus = ph_dosing in (PH_DOSING_MINUS, PH_DOSING_BOTH)
        ph_dosing_plus = ph_dosing in (PH_DOSING_PLUS, PH_DOSING_BOTH)
        ph_rec = recommend_ph(
            current=ph_for_dosing,
            target=float(self._cfg(CONF_PH_TARGET)),
            ph_min=float(self._cfg(CONF_PH_MIN)),
            ph_max=float(self._cfg(CONF_PH_MAX)),
            ph_critical_low=float(self._cfg(CONF_PH_CRITICAL_LOW, DEFAULT_PH_CRITICAL_LOW)),
            ph_critical_high=float(self._cfg(CONF_PH_CRITICAL_HIGH, DEFAULT_PH_CRITICAL_HIGH)),
            volume_m3=volume,
            ph_minus_type=self._cfg(CONF_PH_MINUS_TYPE),
            ph_minus_strength_pct=float(self._cfg(CONF_PH_MINUS_STRENGTH)),
            ph_minus_display=self._display(CONF_PH_MINUS_NAME, CONF_PH_MINUS_TYPE),
            ph_plus_type=self._cfg(CONF_PH_PLUS_TYPE),
            ph_plus_strength_pct=float(self._cfg(CONF_PH_PLUS_STRENGTH)),
            ph_plus_display=self._display(CONF_PH_PLUS_NAME, CONF_PH_PLUS_TYPE),
            max_dose_fraction=max_frac,
            interval_h=interval_h,
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
            max_dose_fraction=max_frac,
            interval_h=interval_h,
        )
        routine_strength_raw = self._cfg(CONF_ROUTINE_CL_STRENGTH)
        cl_rec = recommend_shock(
            combined_cl=self._manual_value(CONF_ENT_COMBINED_CL),
            free_cl=self._manual_value(CONF_ENT_FREE_CL),
            fc_min=float(self._cfg(CONF_FC_MIN)),
            fc_target=float(self._cfg(CONF_FC_TARGET)),
            fc_critical_low=float(self._cfg(CONF_FC_CRITICAL_LOW, DEFAULT_FC_CRITICAL_LOW)),
            cc_shock_at=float(self._cfg(CONF_CC_SHOCK_AT)),
            volume_m3=volume,
            routine_type=self._cfg(CONF_ROUTINE_CL_TYPE),
            routine_strength_pct=(
                float(routine_strength_raw) if routine_strength_raw is not None else 0.0
            ),
            routine_display=self._display(CONF_ROUTINE_CL_NAME, CONF_ROUTINE_CL_TYPE),
            shock_type=self._cfg(CONF_SHOCK_TYPE),
            shock_strength_pct=float(self._cfg(CONF_SHOCK_STRENGTH)),
            shock_display=self._display(CONF_SHOCK_NAME, CONF_SHOCK_TYPE),
            max_dose_fraction=max_frac,
            interval_h=interval_h,
            chlorination_is_salt=chlorination_is_salt,
            has_auto_dosing=has_auto_dosing,
        )
        calib_rec = recommend_calibration(
            ph_auto=ph_auto,
            ph_manual=ph_manual,
            threshold=float(self._cfg(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD)),
        )
        cya_rec = recommend_cya(
            current=self._manual_value(CONF_ENT_CYANURIC),
            target=float(self._cfg(CONF_CYA_TARGET, DEFAULT_CYA_TARGET)),
            watch_at=float(self._cfg(CONF_CYA_WATCH_AT, DEFAULT_CYA_WATCH_AT)),
            critical_at=float(self._cfg(CONF_CYA_CRITICAL_AT, DEFAULT_CYA_CRITICAL_AT)),
            volume_m3=volume,
            cya_display=self._display(CONF_CYA_NAME, CONF_CYA_TYPE),
            cya_strength_pct=float(self._cfg(CONF_CYA_STRENGTH, DEFAULT_CYA_STRENGTH)),
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
