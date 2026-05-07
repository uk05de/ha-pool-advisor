"""DateTime-Entitäten für manuelle Dosierungs-Zeitstempel.

Semantik: Default ist 'leer / null' → bei Button-Press wird die Klick-Zeit
als Dosierzeit verwendet. Wenn User explizit einen Zeitstempel setzt (z.B.
zur Rückdatierung), wird dieser beim Button-Press verwendet. Nach erfolg-
reicher Registrierung wird der Wert zurück auf null gesetzt.
"""
from __future__ import annotations

from datetime import datetime as _datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import PoolAdvisorData
from .const import DOMAIN, MANUAL_DOSE_CHEMISTRIES, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ManualDoseTime(data, entry, key, label, name_key)
        for key, label, _, name_key in MANUAL_DOSE_CHEMISTRIES
    ]
    entities.append(PendingDoseTime(data, entry))
    async_add_entities(entities)


class ManualDoseTime(DateTimeEntity, RestoreEntity):
    """Optionaler Zeitstempel für Rückdatierung einer Dosierung."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        data: PoolAdvisorData,
        entry: ConfigEntry,
        chem_key: str,
        chem_label: str,
        name_config_key: str,
    ) -> None:
        self._data = data
        self._entry = entry
        self._chem_key = chem_key
        self._chem_label = chem_label
        self._name_config_key = name_config_key
        self._value: _datetime | None = None
        self._attr_unique_id = f"{entry.entry_id}_dose_{chem_key}_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pool Advisor",
            model="Chemistry Recommendations",
        )

    @property
    def name(self) -> str:
        custom_name = self._entry.options.get(self._name_config_key) or self._entry.data.get(
            self._name_config_key
        )
        prefix = custom_name if custom_name else self._chem_label
        return f"{prefix} Zeitpunkt"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                self._value = dt_util.parse_datetime(last.state)
            except (ValueError, TypeError):
                self._value = None
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self._entry.entry_id}", self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> _datetime | None:
        return self._value

    async def async_set_value(self, value: _datetime) -> None:
        self._value = value
        self.async_write_ha_state()

    def clear(self) -> None:
        """Zeitstempel zurücksetzen (nach Button-Press)."""
        self._value = None
        self.async_write_ha_state()


class PendingDoseTime(DateTimeEntity, RestoreEntity):
    """Generic-Pending-Slot Zeit — optional, leer = jetzt."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:clock-edit-outline"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._value: _datetime | None = None
        self._attr_unique_id = f"{entry.entry_id}_pending_time"
        self._attr_name = "Manuelle Dosis — Zeitpunkt"
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
                self._value = dt_util.parse_datetime(last.state)
            except (ValueError, TypeError):
                self._value = None

    @property
    def native_value(self) -> _datetime | None:
        return self._value

    async def async_set_value(self, value: _datetime) -> None:
        self._value = value
        self.async_write_ha_state()

    def clear(self) -> None:
        self._value = None
        self.async_write_ha_state()
