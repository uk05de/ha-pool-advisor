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
            OverallStatusSensor(data, entry),
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
        if actions == {"no_data"}:
            return "Keine Daten"
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, rec in self._data.recommendations.items():
            out[f"{key}_action"] = rec.action
            out[f"{key}_reason"] = rec.reason
        return out
