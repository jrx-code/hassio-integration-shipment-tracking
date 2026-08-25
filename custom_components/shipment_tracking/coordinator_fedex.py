"""DataUpdateCoordinator for the FedEx carrier.

Unlike DPD/InPost, there is no account to poll — the config entry holds a
Client ID/Secret pair plus a user-maintained list of tracking numbers
(options, editable without reauth since it's not a credential). No numbers
configured means nothing to track yet, not an error.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_fedex import FedexApi, FedexAuthError, FedexError
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_NUMBERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    fedex_canonical,
    fedex_is_active,
    fedex_status_pl,
)

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(result: dict) -> dict | None:
    """Flatten one ``completeTrackResults[].trackResults[0]`` entry into the
    shape used by entities. Returns None for a tracking number FedEx doesn't
    recognize (empty trackResults — typo, or not yet in their system)."""
    track_results = result.get("trackResults") or []
    if not track_results:
        return None
    r = track_results[0]
    status = r.get("latestStatusDetail") or {}
    derived = status.get("derivedCode") or ""
    text = status.get("statusByLocale") or status.get("description") or ""
    history = [
        {
            "status": e.get("eventDescription"),
            "date": e.get("date"),
            "location": (e.get("scanLocation") or {}).get("city"),
        }
        for e in (r.get("scanEvents") or [])
    ]
    ship_addr = (r.get("shipperInformation") or {}).get("address") or {}
    recv_addr = (r.get("recipientInformation") or {}).get("address") or {}
    service = r.get("serviceDetail") or {}
    return {
        "number": (r.get("trackingNumberInfo") or {}).get("trackingNumber")
        or result.get("trackingNumber"),
        "status": fedex_status_pl(derived, text),
        "status_raw": text,
        "derived_code": derived,
        "canonical": fedex_canonical(derived, text),
        "active": fedex_is_active(derived, text),
        "sender_city": ship_addr.get("city"),
        "sender_country": ship_addr.get("countryCode"),
        "recipient_city": recv_addr.get("city"),
        "service": service.get("description"),
        "history": history,
    }


class FedexCoordinator(DataUpdateCoordinator[dict]):
    """Poll a fixed list of tracking numbers with one FedEx app credential."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_fedex_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = FedexApi(entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET])

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        numbers = list(self.entry.options.get(CONF_TRACKING_NUMBERS, []))
        if not numbers:
            return {"active": [], "delivered": [], "all": [], "counts": {"active": 0, "delivered": 0}}
        token = self._api.get_access_token()
        results = self._api.track(token, numbers)
        parcels = [p for p in (normalize_parcel(r) for r in results) if p is not None]
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
        except FedexAuthError as err:
            raise ConfigEntryAuthFailed("FedEx credentials rejected") from err
        except FedexError as err:
            raise UpdateFailed(str(err)) from err
