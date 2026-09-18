"""DataUpdateCoordinator for Orlen Paczka (track-by-number)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_orlen import OrlenApi, OrlenError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    orlen_canonical,
    orlen_is_active,
    orlen_status_pl,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_orlen_date(raw: str | None) -> str | None:
    """Convert DD-MM-YYYY, HH:MM (Orlen history format) to YYYY-MM-DD HH:MM."""
    if not raw:
        return None
    m = re.match(
        r"\A(\d{2})-(\d{2})-(\d{4}),\s*(\d{2}:\d{2})\Z",
        str(raw).strip(),
    )
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4)}"
    return str(raw).strip()


def normalize_parcel(data: dict) -> dict:
    """Flatten one Orlen api-status JSON object into the entity row shape."""
    history_raw = data.get("history") or []
    status_text = (data.get("status") or data.get("label") or "").strip()
    if not status_text and history_raw:
        status_text = (history_raw[0].get("label") or "").strip()
    history = [
        {
            "status": (h.get("label") or "").strip() or None,
            "date": _normalize_orlen_date(h.get("date")),
        }
        for h in history_raw
    ]
    updated = history[0]["date"] if history else None
    return {
        "number": data.get("number"),
        "status": orlen_status_pl(status_text),
        "status_raw": status_text or None,
        "canonical": orlen_canonical(status_text),
        "active": orlen_is_active(status_text),
        "updated": updated,
        "return": bool(data.get("return")),
        "truck_no": data.get("truckNo") if data.get("truckNo") not in (None, "Brak danych") else None,
        "history": history,
    }


class OrlenCoordinator(DataUpdateCoordinator[dict]):
    """Poll a manually maintained list of Orlen Paczka tracking numbers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_orlen_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = OrlenApi()

    def _fetch(self) -> dict:
        numbers = list(self.entry.options.get(CONF_TRACKING_NUMBERS, []))
        if not numbers:
            return {
                "active": [],
                "delivered": [],
                "all": [],
                "counts": {"active": 0, "delivered": 0},
            }
        parcels: list[dict] = []
        for number in numbers:
            try:
                raw = self._api.track(number)
            except OrlenError as err:
                _LOGGER.warning("Orlen track failed for %s: %s", number, err)
                continue
            if raw is None:
                _LOGGER.debug("Orlen: unknown tracking number %s", number)
                continue
            parcels.append(normalize_parcel(raw))
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
        except OrlenError as err:
            raise UpdateFailed(str(err)) from err
