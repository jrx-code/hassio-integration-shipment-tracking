"""DataUpdateCoordinator for the Pocztex carrier.

Account auto-discovery, like DPD/InPost — the config entry holds a
refresh_token (never the password) and this coordinator refreshes it every
poll, both to mint a fresh access token AND to keep the Keycloak session
from idling out (refresh_token lifetime observed as 30 min; refreshing at
this integration's default 15 min interval comfortably beats that).

The stored refresh_token is NOT single-use — verified live 2026-08-25 by
reusing the same one across three separate refresh calls, all successful —
so like DPD we deliberately do NOT persist the rotated one each poll.
(Persisting would call async_update_entry on entry.data, which fires this
integration's own update-listener and reloads the whole config entry every
poll cycle — exactly the DPD gotcha this avoids by not doing it.) If the
stored token eventually stops working, refresh raises PocztexAuthError ->
reauth.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_pocztex import PocztexApi, PocztexAuthError, PocztexError
from .const import (
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    pocztex_is_active,
)

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(raw: dict) -> dict:
    """Flatten one /api/customer/tracking entry into the shape used by
    entities. Poczta Polska's own ``state`` field is already a Polish label
    — no canonical/status_pl mapping needed, same as the SOAP service this
    replaced."""
    progress = raw.get("progressPercentage")
    return {
        "number": raw.get("consignmentNumber"),
        "status": raw.get("state"),
        "status_code": raw.get("stateCode"),
        "progress": progress,
        "active": pocztex_is_active(progress),
        "updated": raw.get("stateDate"),
        "direction": raw.get("direction"),
    }


class PocztexCoordinator(DataUpdateCoordinator[dict]):
    """Poll one Pocztex account and expose active/delivered parcels."""

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
        except PocztexAuthError as err:
            raise ConfigEntryAuthFailed("Pocztex session expired") from err
        except PocztexError as err:
            raise UpdateFailed(str(err)) from err
