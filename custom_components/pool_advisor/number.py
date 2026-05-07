"""Number-Entitäten für manuelle Dosierungs-Mengen.

Pro manuelle Chemie wird eine Number-Entity bereitgestellt. User kann den
Wert manuell setzen — oder er wird vom Advisor mit der aktuellen Empfehlung
vorbefüllt (kommt in einem späteren Commit). Die Werte werden via HA's
RestoreEntity persistiert.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import PoolAdvisorData
from .const import DOMAIN, MANUAL_DOSE_CHEMISTRIES, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ManualDoseAmount(data, entry, key, label, icon, name_key)
        for key, label, icon, name_key in MANUAL_DOSE_CHEMISTRIES
    ]
    entities.append(PendingDoseAmount(data, entry))
    async_add_entities(entities)


class ManualDoseAmount(NumberEntity, RestoreEntity):
    """Editierbare Menge für eine manuelle Dosierung."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        data: PoolAdvisorData,
        entry: ConfigEntry,
        chem_key: str,
        chem_label: str,
        icon: str,
        name_config_key: str,
    ) -> None:
        self._data = data
        self._entry = entry
        self._chem_key = chem_key
        self._chem_label = chem_label
        self._name_config_key = name_config_key
        self._value: float = 0.0
        # Default-Einheit g — Refinement (per Produkt-Typ ml/g) kommt später
        self._attr_native_unit_of_measurement = "g"
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_dose_{chem_key}_amount"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pool Advisor",
            model="Chemistry Recommendations",
        )

    @property
    def name(self) -> str:
        """Name nutzt bei Bedarf den User-konfigurierten Produktnamen,
        sonst das chem_label-Default ('Manuell pH-Minus' etc.)."""
        custom_name = self._entry.options.get(self._name_config_key) or self._entry.data.get(
            self._name_config_key
        )
        prefix = custom_name if custom_name else self._chem_label
        return f"{prefix} Menge"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                self._value = float(last.state)
            except (ValueError, TypeError):
                self._value = 0.0
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self._entry.entry_id}", self._handle_update
            )
        )
        # Initial-Sync mit aktueller Empfehlung sobald Advisor-Daten verfügbar
        self._sync_with_recommendation()

    @callback
    def _handle_update(self) -> None:
        """Bei jedem Advisor-Recalc: Number mit aktueller Empfehlung
        überschreiben. User-Edits sind transient — sie überleben bis zur
        nächsten Empfehlung. Workflow: Empfehlung → User glance → ggf. edit
        → Button-Press. Recalcs sind sparsam, Race-Window klein."""
        self._sync_with_recommendation()
        self.async_write_ha_state()

    def _sync_with_recommendation(self) -> None:
        """Aktualisiere _value aus aktueller Empfehlung, wenn vorhanden.
        Bei keiner aktiven Empfehlung (action != raise/lower/shock): 0."""
        try:
            self._value = self._data.recommended_dose_amount(self._chem_key)
        except AttributeError:
            # Bei Init-Race kann recommendations noch leer sein
            pass


class PendingDoseAmount(NumberEntity, RestoreEntity):
    """Generic-Pending-Slot Menge — wird per Select-Wechsel aus der
    aktuellen Empfehlung der gewählten Chemie auto-befüllt. Apply-Button
    kopiert diesen Wert in die Per-Chemie-Number-Entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "g"
    _attr_icon = "mdi:beaker-plus"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._value: float = 0.0
        self._attr_unique_id = f"{entry.entry_id}_pending_amount"
        self._attr_name = "Manuelle Dosis — Menge"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pool Advisor",
            model="Chemistry Recommendations",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                self._value = float(last.state)
            except (ValueError, TypeError):
                self._value = 0.0

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self.async_write_ha_state()

    def auto_fill_from_recommendation(self, chem_key: str) -> None:
        """Wird vom Select-Entity bei Wechsel aufgerufen."""
        try:
            self._value = self._data.recommended_dose_amount(chem_key)
        except AttributeError:
            self._value = 0.0
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self.async_write_ha_state()
