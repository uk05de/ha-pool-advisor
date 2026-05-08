"""Persistente Historie der bestätigten manuellen Dosierungen.

Wird via HA Storage in .storage/<key> gespeichert. Jede Confirm-Button-Press
fügt ein Event hinzu. Cumulative-Sensoren und (später) TA/FC-Predictions
nutzen diese Daten als zuverlässige Wahrheit darüber was der User
tatsächlich dosiert hat.

Schema v1:
{
  "events": [
    {"chem_key": "ph_minus_manual", "amount": 200.0, "unit": "g",
     "timestamp": "2026-05-08T10:30:00+02:00"},
    ...
  ]
}
"""
from __future__ import annotations

import logging
from datetime import datetime as _datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_FORMAT = "pool_advisor.dose_history.{entry_id}"


class DoseHistory:
    """In-memory + persistent dose-event store, scoped per ConfigEntry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY_FORMAT.format(entry_id=entry_id),
        )
        self._events: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Lade persistierte Events von Disk."""
        data = await self._store.async_load()
        if data and isinstance(data, dict) and "events" in data:
            self._events = list(data["events"])
            _LOGGER.info(
                "Pool Advisor: %d Dose-Events geladen für entry %s",
                len(self._events), self._entry_id,
            )

    async def async_add_event(
        self,
        chem_key: str,
        amount: float,
        unit: str,
        timestamp: _datetime,
    ) -> None:
        """Append a new dose event and persist to disk."""
        event = {
            "chem_key": chem_key,
            "amount": float(amount),
            "unit": unit,
            "timestamp": timestamp.isoformat(),
        }
        self._events.append(event)
        await self._store.async_save({"events": self._events})
        _LOGGER.info(
            "Pool Advisor: Dose-Event registriert: %s %.1f%s @ %s",
            chem_key, amount, unit, timestamp.isoformat(),
        )

    def events_for_chemistry(self, chem_key: str) -> list[dict[str, Any]]:
        """Alle Events einer bestimmten Chemie."""
        return [e for e in self._events if e.get("chem_key") == chem_key]

    def cumulative_for_chemistry(self, chem_key: str) -> float:
        """Lifetime-Summe der Mengen für eine Chemie."""
        return sum(
            float(e.get("amount", 0))
            for e in self._events
            if e.get("chem_key") == chem_key
        )

    def events_since(self, since: _datetime) -> list[dict[str, Any]]:
        """Events seit gegebenem Zeitpunkt."""
        since_iso = since.isoformat()
        return [
            e for e in self._events
            if e.get("timestamp", "") >= since_iso
        ]

    @property
    def all_events(self) -> list[dict[str, Any]]:
        return list(self._events)
