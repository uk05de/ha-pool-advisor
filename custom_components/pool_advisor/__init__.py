"""Pool Chemistry Advisor — HA integration."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .calculator import (
    Recommendation,
    recommend_alkalinity,
    recommend_calibration,
    recommend_ph,
    recommend_shock,
)
from .const import (
    CHLORINATION_SALT,
    CONF_CC_SHOCK_AT,
    CONF_CHLORINATION,
    CONF_DOSE_INTERVAL_H,
    CONF_ENT_ALKALINITY,
    CONF_ENT_COMBINED_CL,
    CONF_ENT_FREE_CL,
    CONF_ENT_PH_AUTO,
    CONF_ENT_PH_MANUAL,
    CONF_FC_MIN,
    CONF_FC_TARGET,
    CONF_MANUAL_MAX_AGE_H,
    CONF_MAX_DOSE_FRACTION,
    CONF_PH_CALIB_THRESHOLD,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_MINUS_STRENGTH,
    CONF_PH_MINUS_TYPE,
    CONF_PH_PLUS_STRENGTH,
    CONF_PH_PLUS_TYPE,
    CONF_PH_TARGET,
    CONF_POOL_VOLUME_M3,
    CONF_SHOCK_STRENGTH,
    CONF_SHOCK_TYPE,
    CONF_TA_MAX,
    CONF_TA_MIN,
    CONF_TA_PLUS_STRENGTH,
    CONF_TA_PLUS_TYPE,
    CONF_TA_TARGET,
    DEFAULT_MANUAL_MAX_AGE_H,
    DEFAULT_PH_CALIB_THRESHOLD,
    DOMAIN,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


class PoolAdvisorData:
    """Runtime state for a single config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.recommendations: dict[str, Recommendation] = {}
        self.inputs: dict[str, float | None] = {}
        self._unsub = None

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _read(self, entity_key: str) -> float | None:
        entity_id = self._cfg(entity_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (None, "", "unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug("Non-numeric state for %s: %r", entity_id, state.state)
            return None

    def _age_hours(self, entity_key: str) -> float | None:
        entity_id = self._cfg(entity_key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        now = datetime.now(timezone.utc)
        return (now - state.last_updated).total_seconds() / 3600.0

    async def async_setup(self) -> None:
        tracked = [
            self._cfg(k)
            for k in (
                CONF_ENT_PH_AUTO,
                CONF_ENT_PH_MANUAL,
                CONF_ENT_ALKALINITY,
                CONF_ENT_FREE_CL,
                CONF_ENT_COMBINED_CL,
            )
            if self._cfg(k)
        ]

        @callback
        def _on_change(event: Event[EventStateChangedData]) -> None:
            self.recalculate()

        if tracked:
            self._unsub = async_track_state_change_event(self.hass, tracked, _on_change)
        self.recalculate()

    def recalculate(self) -> None:
        volume = float(self._cfg(CONF_POOL_VOLUME_M3, 30.0))
        chlorination_is_salt = self._cfg(CONF_CHLORINATION) == CHLORINATION_SALT
        max_frac = float(self._cfg(CONF_MAX_DOSE_FRACTION, 0.5))
        interval_h = int(self._cfg(CONF_DOSE_INTERVAL_H, 6))

        ph_auto = self._read(CONF_ENT_PH_AUTO)
        ph_manual = self._read(CONF_ENT_PH_MANUAL)
        manual_age_h = self._age_hours(CONF_ENT_PH_MANUAL)

        # Prefer manual (photometer) if present AND fresh enough; else auto.
        max_age_h = float(self._cfg(CONF_MANUAL_MAX_AGE_H, DEFAULT_MANUAL_MAX_AGE_H))
        if ph_manual is not None and (manual_age_h is None or manual_age_h <= max_age_h):
            ph_for_dosing = ph_manual
        else:
            ph_for_dosing = ph_auto

        self.inputs = {
            "ph_auto": ph_auto,
            "ph_manual": ph_manual,
            "ph_manual_age_h": manual_age_h,
            "ph_for_dosing": ph_for_dosing,
        }

        ph_rec = recommend_ph(
            current=ph_for_dosing,
            target=float(self._cfg(CONF_PH_TARGET)),
            ph_min=float(self._cfg(CONF_PH_MIN)),
            ph_max=float(self._cfg(CONF_PH_MAX)),
            volume_m3=volume,
            ph_minus_type=self._cfg(CONF_PH_MINUS_TYPE),
            ph_minus_strength_pct=float(self._cfg(CONF_PH_MINUS_STRENGTH)),
            ph_plus_type=self._cfg(CONF_PH_PLUS_TYPE),
            ph_plus_strength_pct=float(self._cfg(CONF_PH_PLUS_STRENGTH)),
            max_dose_fraction=max_frac,
            interval_h=interval_h,
        )
        ta_rec = recommend_alkalinity(
            current=self._read(CONF_ENT_ALKALINITY),
            target=float(self._cfg(CONF_TA_TARGET)),
            ta_min=float(self._cfg(CONF_TA_MIN)),
            ta_max=float(self._cfg(CONF_TA_MAX)),
            volume_m3=volume,
            ta_plus_type=self._cfg(CONF_TA_PLUS_TYPE),
            ta_plus_strength_pct=float(self._cfg(CONF_TA_PLUS_STRENGTH)),
            max_dose_fraction=max_frac,
            interval_h=interval_h,
        )
        cl_rec = recommend_shock(
            combined_cl=self._read(CONF_ENT_COMBINED_CL),
            free_cl=self._read(CONF_ENT_FREE_CL),
            fc_min=float(self._cfg(CONF_FC_MIN)),
            fc_target=float(self._cfg(CONF_FC_TARGET)),
            cc_shock_at=float(self._cfg(CONF_CC_SHOCK_AT)),
            volume_m3=volume,
            shock_type=self._cfg(CONF_SHOCK_TYPE),
            shock_strength_pct=float(self._cfg(CONF_SHOCK_STRENGTH)),
            max_dose_fraction=max_frac,
            interval_h=interval_h,
            chlorination_is_salt=chlorination_is_salt,
        )
        calib_rec = recommend_calibration(
            ph_auto=ph_auto,
            ph_manual=ph_manual,
            threshold=float(self._cfg(CONF_PH_CALIB_THRESHOLD, DEFAULT_PH_CALIB_THRESHOLD)),
            manual_age_h=manual_age_h,
            manual_max_age_h=max_age_h,
        )
        self.recommendations = {
            "ph": ph_rec,
            "alkalinity": ta_rec,
            "chlorine": cl_rec,
            "calibration": calib_rec,
        }
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def async_unload(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pool Advisor from a config entry."""
    data = PoolAdvisorData(hass, entry)
    await data.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data: PoolAdvisorData | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data is not None:
        await data.async_unload()
    return unloaded
