"""DataUpdateCoordinator for Allegro One (track-by-number)."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_allegro_one import AllegroOneApi, AllegroOneError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    allegro_one_canonical,
    allegro_one_is_active,
    allegro_one_status_pl,
)

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(data: dict) -> dict:
    """Flatten one Allegro edge /ad/tracking response into the entity row.

    Status events arrive unsorted; we order by eventTimestamp ascending
    for history and take the latest as current.
    """
    statuses = list(data.get("status") or [])
    statuses.sort(key=lambda s: s.get("eventTimestamp") or "")
    latest = statuses[-1] if statuses else {}
    text = (latest.get("description") or "").strip()
    history = [
        {
            "status": (s.get("description") or "").strip() or None,
            "date": s.get("eventTimestamp"),
        }
        for s in statuses
    ]
    return {
        "number": data.get("number"),
        "status": allegro_one_status_pl(text),
        "status_raw": text or None,
        "canonical": allegro_one_canonical(text),
        "active": allegro_one_is_active(text),
        "updated": latest.get("eventTimestamp"),
        "history": list(reversed(history)),  # newest first, matching other carriers
    }


class AllegroOneCoordinator(DataUpdateCoordinator[dict]):
    """Poll a manually maintained list of Allegro One tracking numbers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_allegro_one_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = AllegroOneApi()

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
            except AllegroOneError as err:
                _LOGGER.warning("Allegro One track failed for %s: %s", number, err)
                continue
            if raw is None:
                _LOGGER.debug("Allegro One: no history for %s", number)
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
        except AllegroOneError as err:
            raise UpdateFailed(str(err)) from err
