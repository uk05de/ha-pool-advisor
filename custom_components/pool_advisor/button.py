"""Analyse durchführen — einziger Button. Captures PoolLab snapshot,
recomputes recommendations. Keine Step-Progression mehr."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PoolAdvisorData
from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnalyzeButton(data, entry)])


class AnalyzeButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "analyze"
    _attr_name = "Analyse durchführen"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_analyze"
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

    async def async_press(self) -> None:
        self._data.run_analysis()
