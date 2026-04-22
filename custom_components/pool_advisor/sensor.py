"""Recommendation sensors for Pool Chemistry Advisor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PoolAdvisorData
from .calculator import Recommendation
from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RecommendationSensor(data, entry, "ph", "pH"),
            RecommendationSensor(data, entry, "alkalinity", "Alkalität"),
            RecommendationSensor(data, entry, "chlorine", "Chlor / Shock"),
            RecommendationSensor(data, entry, "cya", "Cyanursäure"),
            DriftPhSensor(data, entry),
            DriftRedoxSensor(data, entry),
            OverallStatusSensor(data, entry),
            MarkdownSummarySensor(data, entry),
        ]
    )


def _format_steps(rec: Recommendation) -> str:
    if not rec.steps:
        return rec.reason
    parts = []
    for s in rec.steps:
        parts.append(f"{s.amount:g} {s.unit} {s.product}")
    sep = f" → warte {rec.steps[0].wait_hours}h → " if len(rec.steps) > 1 else " "
    joined = sep.join(parts) if len(rec.steps) > 1 else parts[0]
    if rec.action == "raise":
        return f"Erhöhen: {joined}"
    if rec.action == "lower":
        return f"Senken: {joined}"
    if rec.action == "shock":
        return f"Schocken: {joined}"
    return joined


class _BaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pool Advisor",
            model="Chemistry Recommendations",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self._entry.entry_id}", self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class RecommendationSensor(_BaseSensor):
    """One parameter's recommendation (pH / alkalinity / chlorine)."""

    _attr_icon = "mdi:beaker-outline"

    def __init__(
        self, data: PoolAdvisorData, entry: ConfigEntry, key: str, label: str
    ) -> None:
        super().__init__(data, entry)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}_recommendation"
        self._attr_translation_key = f"{key}_recommendation"
        self._attr_name = f"Empfehlung {label}"

    @property
    def _rec(self) -> Recommendation | None:
        return self._data.recommendations.get(self._key)

    @property
    def native_value(self) -> str:
        rec = self._rec
        if rec is None:
            return "—"
        if rec.action == "ok":
            return "OK"
        if rec.action == "no_data":
            return "Keine Daten"
        if rec.action == "watch":
            return f"Beobachten — {rec.reason}"
        return _format_steps(rec)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rec = self._rec
        if rec is None:
            return {}
        return {
            "action": rec.action,
            "reason": rec.reason,
            "delta": rec.delta,
            "note": rec.note,
            "steps": [
                {
                    "amount": s.amount,
                    "unit": s.unit,
                    "product": s.product,
                    "wait_hours": s.wait_hours,
                }
                for s in rec.steps
            ],
        }


class DriftPhSensor(_BaseSensor):
    """Drift check: Bayrol-Elektrode vs PoolLab-Photometer pH."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        # unique_id stays stable across the rename so HA keeps history
        self._attr_unique_id = f"{entry.entry_id}_calibration_ph"
        self._attr_translation_key = "drift_ph"
        self._attr_name = "Drift pH Sonde"

    @property
    def native_value(self) -> str:
        rec = self._data.recommendations.get("calibration")
        if rec is None:
            return "—"
        if rec.action == "calibrate":
            return "Drift erkannt"
        if rec.action == "no_data":
            return "Keine Daten"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rec = self._data.recommendations.get("calibration")
        ph_auto_state = None
        ph_auto_entity = self._data._cfg("entity_ph_auto")
        if ph_auto_entity:
            st = self._data.hass.states.get(ph_auto_entity)
            if st is not None:
                try:
                    ph_auto_state = float(st.state)
                except (TypeError, ValueError):
                    ph_auto_state = None
        snap = self._data.manual_snapshot.get("entity_ph_manual") or {}
        attrs: dict[str, Any] = {
            "ph_auto": ph_auto_state,
            "ph_manual": snap.get("value") if snap.get("included") else None,
            "ph_manual_measured_at": snap.get("measured_at"),
            "ph_manual_age_hours": snap.get("age_hours"),
            "ph_manual_included": snap.get("included"),
        }
        if rec is not None:
            attrs.update(
                {
                    "action": rec.action,
                    "reason": rec.reason,
                    "delta": rec.delta,
                    "note": rec.note,
                }
            )
        return attrs


from .workflow import render as _workflow_render


class DriftRedoxSensor(_BaseSensor):
    """Drift check: Bayrol redox electrode vs expected ORP from FC+pH+CYA."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_drift_redox"
        self._attr_translation_key = "drift_redox"
        self._attr_name = "Drift Redox Sonde"

    @property
    def native_value(self) -> str:
        rec = self._data.recommendations.get("drift_redox")
        if rec is None:
            return "—"
        if rec.action == "calibrate":
            return "Drift erkannt"
        if rec.action == "no_data":
            return "Keine Daten"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rec = self._data.recommendations.get("drift_redox")
        if rec is None:
            return {}
        return {
            "reason": rec.reason,
            "delta_mv": rec.delta,
            "note": rec.note,
            "action": rec.action,
        }


ACTION_ICONS = {
    "ok": "✅",
    "watch": "👁",
    "raise": "⚠",
    "lower": "⚠",
    "shock": "🚨",
    "calibrate": "🎯",
    "no_data": "❔",
}


def _build_workflow_markdown(data: "PoolAdvisorData") -> str:
    ctx = data.build_workflow_context()
    return _workflow_render(ctx, data.recommendations)


def _build_markdown(data: "PoolAdvisorData") -> str:
    """Vollständige Markdown-Empfehlung ohne Haupttitel (Card liefert den).

    Zeitstempel steht als eigener Blockquote am Anfang.
    """
    body = _workflow_render(data.build_workflow_context(), data.recommendations)
    if data.analysis_at is not None:
        local = data.analysis_at.astimezone()
        header = f"> Stand: {local.strftime('%d.%m.%Y %H:%M')}\n\n"
        return header + body
    return body


class MarkdownSummarySensor(_BaseSensor):
    """Single sensor whose `markdown` attribute holds the whole recommendation
    nicely formatted for the HA Markdown Card."""

    _attr_icon = "mdi:format-list-checks"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_markdown"
        self._attr_translation_key = "markdown"
        self._attr_name = "Empfehlung"

    @property
    def native_value(self) -> str:
        recs = self._data.recommendations
        if not recs:
            return "—"
        actions = {r.action for r in recs.values()}
        if "shock" in actions:
            return "Shock empfohlen"
        if actions & {"raise", "lower"}:
            return "Anpassung nötig"
        if "calibrate" in actions:
            return "Kalibrierung prüfen"
        if "watch" in actions:
            return "Beobachten"
        if actions == {"no_data"}:
            return "Keine Daten"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"markdown": _build_markdown(self._data)}


class OverallStatusSensor(_BaseSensor):
    """Aggregated pool status across all parameters."""

    _attr_icon = "mdi:pool"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_translation_key = "status"
        self._attr_name = "Pool Status"

    @property
    def native_value(self) -> str:
        recs = list(self._data.recommendations.values())
        if not recs:
            return "Unbekannt"
        actions = {r.action for r in recs}
        if "shock" in actions:
            return "Shock empfohlen"
        if actions & {"raise", "lower"}:
            return "Anpassung nötig"
        if "calibrate" in actions:
            return "Kalibrierung prüfen"
        if "watch" in actions:
            return "Beobachten"
        if actions == {"no_data"}:
            return "Keine Daten"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "analysis_at": (
                self._data.analysis_at.isoformat() if self._data.analysis_at else None
            ),
        }
        for key, rec in self._data.recommendations.items():
            out[f"{key}_action"] = rec.action
            out[f"{key}_reason"] = rec.reason
        # Per-parameter snapshot status (was it included in the last analysis?)
        for conf_key, label in (
            ("entity_ph_manual", "ph_manual"),
            ("entity_alkalinity", "alkalinity"),
            ("entity_free_chlorine", "free_cl"),
            ("entity_combined_chlorine", "combined_cl"),
            ("entity_total_chlorine", "total_cl"),
            ("entity_cyanuric_acid", "cyanuric"),
        ):
            snap = self._data.manual_snapshot.get(conf_key)
            if snap and snap.get("entity_id"):
                out[f"{label}_value"] = snap.get("value") if snap.get("included") else None
                out[f"{label}_measured_at"] = snap.get("measured_at")
                out[f"{label}_age_hours"] = snap.get("age_hours")
                out[f"{label}_included"] = snap.get("included")
        return out
