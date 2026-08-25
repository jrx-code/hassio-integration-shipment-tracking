"""DataUpdateCoordinator for the DPD carrier."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_dpd import DpdApi, DpdAuthError, DpdError
from .const import (
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    dpd_canonical,
    dpd_is_active,
    dpd_status_pl,
)

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(p: dict) -> dict:
    """Flatten a raw DPD package into the shape used by entities."""
    ms = p.get("main_status") or {}
    raw = ms.get("status") or ""
    history = [
        {"status": dpd_status_pl(s.get("status")), "raw": s.get("status"), "date": s.get("date")}
        for s in (p.get("statuses") or [])
    ]
    return {
        "number": p.get("waybill"),
        "sender": (p.get("sender") or {}).get("name"),
        "status": dpd_status_pl(raw),
        "status_raw": raw,
        "canonical": dpd_canonical(raw),
        "updated": ms.get("date"),
        "active": dpd_is_active(raw),
        "history": history,
    }


class DpdCoordinator(DataUpdateCoordinator[dict]):
    """Poll one DPD account (phone) and expose active / delivered parcels.

    The DPD refresh token is not single-use (verified 2026-08-06) — the stored
    one keeps working across polls even after Keycloak issues a rotated one — so
    we deliberately do NOT persist the rotated token. (Persisting via
    async_update_entry during the first refresh interfered with entry setup and
    left the coordinator empty until a reload.) If the stored token eventually
    expires, refresh raises DpdAuthError -> reauth.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_dpd_{entry.data.get(CONF_PHONE, entry.entry_id)}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = DpdApi()

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        access, _new_refresh = self._api.refresh(self.entry.data[CONF_REFRESH_TOKEN])
        parcels = [normalize_parcel(p) for p in self._api.get_parcels(access)]
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
        except DpdAuthError as err:
            raise ConfigEntryAuthFailed("DPD token expired") from err
        except DpdError as err:
            raise UpdateFailed(str(err)) from err
