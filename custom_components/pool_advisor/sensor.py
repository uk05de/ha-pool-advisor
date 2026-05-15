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
from .const import DOMAIN, MANUAL_DOSE_CHEMISTRIES, SIGNAL_UPDATE
from .workflow import render as _workflow_render


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        DriftPhSensor(data, entry),
        DriftRedoxSensor(data, entry),
        MarkdownSummarySensor(data, entry),
    ]
    # Cumulative-Dose-Sensoren pro manueller Chemie — state_class total_increasing
    # macht HA-Statistics + Charts ohne weitere Setup-Schritte verfügbar.
    for chem_key, chem_label, _, _ in MANUAL_DOSE_CHEMISTRIES:
        entities.append(CumulativeDoseSensor(data, entry, chem_key, chem_label))
    # Threshold-Sensoren — Werte werden via WorkflowContext gelesen (FC dynamic
    # aus CYA-Verhältnis wenn frisch). Für Detail-Charts mit Target-/Min-/Max-
    # Linien ohne YAML-Hartkodierung. pH/Redox sind nicht hier — die kommen
    # via Bayrol-Bridge direkt als writable numbers.
    for suffix, ctx_attr, name, unit, icon in THRESHOLDS:
        entities.append(
            ThresholdSensor(data, entry, suffix, ctx_attr, name, unit, icon)
        )
    async_add_entities(entities)


# Mapping: (entity-suffix, WorkflowContext-Attribut, Friendly-Name, Unit, Icon)
# Werte werden live aus WorkflowContext gezogen — FC respektiert dadurch
# automatisch das dynamische CYA-Verhältnis (TFP-Faustregel).
THRESHOLDS: list[tuple[str, str, str, str, str]] = [
    # TA
    ("ta_target", "ta_target", "TA Ziel", "mg/l", "mdi:target"),
    ("ta_min", "ta_min", "TA Min", "mg/l", "mdi:arrow-collapse-down"),
    ("ta_max", "ta_max", "TA Max", "mg/l", "mdi:arrow-collapse-up"),
    ("ta_critical_low", "ta_critical_low", "TA Kritisch Niedrig", "mg/l", "mdi:alert-outline"),
    ("ta_critical_high", "ta_critical_high", "TA Kritisch Hoch", "mg/l", "mdi:alert-outline"),
    # FC (dynamic from CYA when fresh)
    ("fc_target", "fc_target", "FC Ziel", "mg/l", "mdi:target"),
    ("fc_min", "fc_min_val", "FC Min", "mg/l", "mdi:arrow-collapse-down"),
    ("fc_max", "fc_max", "FC Max", "mg/l", "mdi:arrow-collapse-up"),
    ("fc_critical_low", "fc_critical_low", "FC Kritisch Niedrig", "mg/l", "mdi:alert-outline"),
    ("fc_critical_high", "fc_critical_high", "FC Kritisch Hoch", "mg/l", "mdi:alert-outline"),
    # CC
    ("cc_max", "cc_max", "CC Max", "mg/l", "mdi:arrow-collapse-up"),
    ("cc_critical_high", "cc_critical_high", "CC Kritisch Hoch", "mg/l", "mdi:alert-outline"),
    # CYA
    ("cya_target", "cya_target", "CYA Ziel", "mg/l", "mdi:target"),
    ("cya_min", "cya_min", "CYA Min", "mg/l", "mdi:arrow-collapse-down"),
    ("cya_max", "cya_max", "CYA Max", "mg/l", "mdi:arrow-collapse-up"),
    ("cya_critical_low", "cya_critical_low", "CYA Kritisch Niedrig", "mg/l", "mdi:alert-outline"),
    ("cya_critical_high", "cya_critical_high", "CYA Kritisch Hoch", "mg/l", "mdi:alert-outline"),
]


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


class DriftPhSensor(_BaseSensor):
    """Drift check: Bayrol-Elektrode vs PoolLab-Photometer pH."""

    _attr_icon = "mdi:tune-variant"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
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
        if rec is None:
            return {}
        return {
            "action": rec.action,
            "reason": rec.reason,
            "delta": rec.delta,
            "note": rec.note,
        }


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
        ctx = self._data.build_workflow_context()
        return {"markdown": _workflow_render(ctx, self._data.recommendations)}


class ThresholdSensor(_BaseSensor):
    """Konfig-Schwellwert als read-only Sensor (Soll/Min/Max/Critical).

    Für ApexCharts/Mini-Graph: y-axis-Annotation kann direkt state(...) der
    Schwellwert-Entity referenzieren — keine YAML-Hartkodierung, ändert sich
    der User-Wert in der Config, folgen alle Charts ohne Anpassung.

    FC-Schwellen sind dynamisch (skalieren mit CYA-Verhältnis wenn frisch
    gemessen) — kommt automatisch aus WorkflowContext._effective_fc_bounds().
    """

    _attr_state_class = "measurement"

    def __init__(
        self,
        data: PoolAdvisorData,
        entry: ConfigEntry,
        suffix: str,
        ctx_attr: str,
        name: str,
        unit: str,
        icon: str,
    ) -> None:
        super().__init__(data, entry)
        self._ctx_attr = ctx_attr
        self._attr_unique_id = f"{entry.entry_id}_threshold_{suffix}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        try:
            ctx = self._data.build_workflow_context()
        except Exception:  # noqa: BLE001
            return None
        val = getattr(ctx, self._ctx_attr, None)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None


class CumulativeDoseSensor(_BaseSensor):
    """Lifetime-cumulative dosed amount für eine manuelle Chemie.

    state_class=total_increasing → HA Statistics ermittelt automatisch
    Tages-/Wochen-/Monats-Aggregate. Lovelace ApexCharts kann ohne weitere
    Konfiguration daraus den Tagesverlauf zeichnen.
    """

    _attr_icon = "mdi:counter"
    _attr_state_class = "total_increasing"
    _attr_native_unit_of_measurement = "g"

    def __init__(
        self,
        data: PoolAdvisorData,
        entry: ConfigEntry,
        chem_key: str,
        chem_label: str,
    ) -> None:
        super().__init__(data, entry)
        self._chem_key = chem_key
        self._attr_unique_id = f"{entry.entry_id}_dosed_cumulative_{chem_key}"
        self._attr_name = f"{chem_label} dosiert gesamt"

    @property
    def native_value(self) -> float:
        if self._data.dose_history is None:
            return 0
        return round(self._data.dose_history.cumulative_for_chemistry(self._chem_key), 1)
