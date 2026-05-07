"""Select-Entity für Generic-Pending-Slot.

Dropdown der manuellen Chemikalien. Beim Wechsel wird die Pending-Number-
Entity automatisch mit der aktuellen Empfehlung der gewählten Chemie
befüllt — der User muss nur noch die Apply-Taste drücken um die Werte in
den Per-Chemie-Slot zu übernehmen.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import PoolAdvisorData
from .const import DOMAIN, MANUAL_DOSE_CHEMISTRIES


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PendingChemistrySelect(data, entry)])


class PendingChemistrySelect(SelectEntity, RestoreEntity):
    """Auswahl der zu dosierenden Chemie für den Generic-Pending-Slot."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:flask-outline"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        # Mapping chem_key → display label aus const.py
        self._key_to_label: dict[str, str] = {
            key: label for key, label, _, _ in MANUAL_DOSE_CHEMISTRIES
        }
        self._label_to_key: dict[str, str] = {
            label: key for key, label in self._key_to_label.items()
        }
        self._attr_options = list(self._key_to_label.values())
        self._current: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_pending_chemistry"
        self._attr_name = "Manuelle Dosis — Chemie"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pool Advisor",
            model="Chemistry Recommendations",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self._current = last.state

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_select_option(self, option: str) -> None:
        self._current = option
        chem_key = self._label_to_key.get(option)
        if chem_key:
            self._auto_fill_pending_amount(chem_key)
        self.async_write_ha_state()

    def _auto_fill_pending_amount(self, chem_key: str) -> None:
        """Trigger Auto-Fill der Pending-Amount-Number-Entity."""
        registry = er.async_get(self.hass)
        amount_eid = registry.async_get_entity_id(
            "number", DOMAIN, f"{self._entry.entry_id}_pending_amount"
        )
        if not amount_eid:
            return
        # Direkter Zugriff auf die Entity über component data
        component = self.hass.data.get("number")
        if component is None:
            return
        for entity in component.entities:
            if entity.entity_id == amount_eid:
                # PendingDoseAmount.auto_fill_from_recommendation()
                if hasattr(entity, "auto_fill_from_recommendation"):
                    entity.auto_fill_from_recommendation(chem_key)
                break

    @property
    def selected_chem_key(self) -> str | None:
        if self._current is None:
            return None
        return self._label_to_key.get(self._current)
