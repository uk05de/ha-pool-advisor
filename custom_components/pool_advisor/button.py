"""Buttons: Analyse durchführen + Schritt abgeschlossen."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PoolAdvisorData
from .const import DOMAIN, MODE_NORMAL, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnalyzeButton(data, entry), AdvanceStepButton(data, entry)])


class _BaseButton(ButtonEntity):
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


class AnalyzeButton(_BaseButton):
    """Capture PoolLab snapshot and recompute recommendations.

    In workflow modes, also advances the current step if that step's
    advance rule is 'analysis'."""

    _attr_translation_key = "analyze"
    _attr_name = "Analyse durchführen"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_analyze"

    async def async_press(self) -> None:
        self._data.run_analysis()
        # Auto-advance workflow if step waits for a fresh analysis
        if self._data.mode != MODE_NORMAL:
            step = self._data.current_step()
            if step.advance == "analysis":
                await self._data.async_advance_step()


class AdvanceStepButton(_BaseButton):
    """Advance the currently active workflow by one step."""

    _attr_translation_key = "advance_step"
    _attr_name = "Schritt abgeschlossen"
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, data: PoolAdvisorData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_advance_step"

    @property
    def available(self) -> bool:
        # Button only useful when in a non-normal workflow (though allowed always,
        # pressing in Normalbetrieb is harmless — just rewrites state to normal/0).
        return True

    async def async_press(self) -> None:
        if self._data.mode == MODE_NORMAL:
            return
        await self._data.async_advance_step()
