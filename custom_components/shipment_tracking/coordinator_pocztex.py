"""DataUpdateCoordinator for the Pocztex carrier.

Like FedEx: no account to poll, just a user-maintained tracking-number list
in options. Unlike FedEx there's no batch endpoint in use (see api_pocztex.py
docstring — the SOAP service's batch operation returned inconsistent results
live, so this polls one number per call).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_pocztex import PocztexApi, PocztexError
from .const import CONF_SCAN_INTERVAL, CONF_TRACKING_NUMBERS, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(result: dict) -> dict:
    """Flatten one PocztexApi.track() result into the shape used by entities.

    Poczta Polska's own ``zdarzenie.nazwa`` is already a Polish label — no
    canonical/status_pl mapping needed like DPD/FedEx, and "active" comes
    straight from their ``zakonczonoObsluge`` (service completed) flag
    instead of a keyword heuristic.

    Event order (oldest-first vs newest-first) is NOT verified live — no
    real parcel with more than one event was seen this session. Assumed
    oldest-first (last item = most recent), matching how DPD/FedEx list
    their own history; if that assumption is wrong the "status" shown here
    will lag instead of leading, not silently wrong in a worse way.
    """
    if not result.get("found"):
        return {
            "number": result.get("numer"),
            "found": False,
            "status": "Nie znaleziono",
            "active": False,
            "history": [],
        }
    events = result.get("events") or []
    last = events[-1] if events else None
    history = [
        {"status": e.get("nazwa"), "raw": e.get("kod"), "date": e.get("czas")}
        for e in events
    ]
    return {
        "number": result.get("numer"),
        "found": True,
        "status": (last or {}).get("nazwa") or "—",
        "active": not result.get("zakonczono_obsluge", False),
        "sent_date": result.get("data_nadania"),
        "shipment_type": result.get("rodzaj_przesylki"),
        "history": history,
    }


class PocztexCoordinator(DataUpdateCoordinator[dict]):
    """Poll a fixed list of tracking numbers, one SOAP call per number."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_pocztex_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = PocztexApi()

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        numbers = list(self.entry.options.get(CONF_TRACKING_NUMBERS, []))
        parcels = []
        for n in numbers:
            try:
                parcels.append(normalize_parcel(self._api.track(n)))
            except PocztexError as err:
                _LOGGER.warning("Pocztex track failed for %s: %s", n, err)
        active = [p for p in parcels if p["active"]]
        delivered = [p for p in parcels if not p["active"]]
        return {
            "active": active,
            "delivered": delivered,
            "all": parcels,
            "counts": {"active": len(active), "delivered": len(delivered)},
        }

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except PocztexError as err:
            raise UpdateFailed(str(err)) from err
