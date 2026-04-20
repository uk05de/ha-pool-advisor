"""Wartungsmodus select entity."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PoolAdvisorData
from .const import CONF_WARTUNGSMODUS, DOMAIN, SIGNAL_UPDATE, WARTUNGSMODI


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WartungsmodusSelect(data, entry)])


class WartungsmodusSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "wartungsmodus"
    _attr_name = "Wartungsmodus"
    _attr_icon = "mdi:toolbox-outline"
    _attr_options = WARTUNGSMODI

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{CONF_WARTUNGSMODUS}"
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

    @property
    def current_option(self) -> str:
        return self._data.mode

    async def async_select_option(self, option: str) -> None:
        await self._data.async_set_mode(option)
