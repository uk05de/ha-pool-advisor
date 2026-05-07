"""Button-Entitäten zur Bestätigung manueller Dosierungen.

Bei Press wird die Dosis aus den korrespondierenden Number- und DateTime-
Entitäten gelesen und als Event registriert. Aktuell (Commit 2) wird der
Press nur geloggt — Persistierung und Verwendung in Predictions kommen in
einem späteren Commit.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PoolAdvisorData
from .const import DOMAIN, MANUAL_DOSE_CHEMISTRIES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: PoolAdvisorData = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ManualDoseConfirm(data, entry, key, label, name_key)
        for key, label, _, name_key in MANUAL_DOSE_CHEMISTRIES
    ]
    async_add_entities(entities)


class ManualDoseConfirm(ButtonEntity):
    """Bestätigt eine manuelle Dosierung — registriert Event."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:check-circle"

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
        self._attr_unique_id = f"{entry.entry_id}_dose_{chem_key}_confirm"
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
        return f"{prefix} Dosis bestätigen"

    async def async_press(self) -> None:
        """Liest Menge + Zeit aus den Geschwister-Entitäten und registriert das Event."""
        amount_eid = (
            f"number.{DOMAIN}_dose_{self._chem_key}_amount"  # fallback (nicht autoritativ)
        )
        time_eid = f"datetime.{DOMAIN}_dose_{self._chem_key}_time"
        # Suche die Entities über unique_id im Entity-Registry — robuster als Slug-Annahme
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        amount_entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{self._entry.entry_id}_dose_{self._chem_key}_amount"
        )
        time_entity_id = registry.async_get_entity_id(
            "datetime", DOMAIN, f"{self._entry.entry_id}_dose_{self._chem_key}_time"
        )
        amount_state = self.hass.states.get(amount_entity_id) if amount_entity_id else None
        time_state = self.hass.states.get(time_entity_id) if time_entity_id else None

        try:
            amount = float(amount_state.state) if amount_state else 0.0
        except (ValueError, TypeError):
            amount = 0.0

        # DateTime: leer → jetzt; gesetzt → Wert (für Rückdatierung)
        registered_at = dt_util.now()
        if time_state and time_state.state not in (None, "", "unknown", "unavailable"):
            parsed = dt_util.parse_datetime(time_state.state)
            if parsed is not None:
                # Zukünftige Zeitstempel auf jetzt clampen
                if parsed > dt_util.now():
                    parsed = dt_util.now()
                registered_at = parsed

        if amount <= 0:
            _LOGGER.warning(
                "Pool Advisor: %s confirm pressed with amount=0, ignoring",
                self._chem_key,
            )
            return

        _LOGGER.info(
            "Pool Advisor: dose registered — chemistry=%s amount=%.1f at=%s",
            self._chem_key,
            amount,
            registered_at.isoformat(),
        )

        # TODO Commit 5: Event in PoolAdvisorData persistieren + Predictions verwenden
        # TODO Commit 5: DateTime-Entity zurücksetzen, ggf. Number-Entity ebenfalls
