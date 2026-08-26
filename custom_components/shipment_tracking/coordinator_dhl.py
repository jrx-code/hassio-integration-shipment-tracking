"""DataUpdateCoordinator for the DHL carrier.

The config entry holds a snapshot of the login-time cookiejar (CONF_COOKIES)
plus a stable device_id/device_name pair. The coordinator restores those
cookies into its own DhlApi instance once at setup and then calls
refresh_session() every poll — verified live to mint a fresh-``iat`` token
from cookies alone, a real sliding 30-minute window (unlike Pocztex's, see
const.py's DHL section). It deliberately does NOT write the cookie snapshot
back to entry.data every poll (same DPD/Pocztex-shaped reload-storm gotcha
those other carriers' history in this file already ran into) — the
in-memory jar carries the session for as long as this HA process runs;
only a restart falls back to the entry.data snapshot, which may by then be
stale. UNVERIFIED: whether that stored snapshot is still good after a real
restart — only in-process cookie reuse across repeated refresh_session()
calls was checked live. If it isn't, refresh_session() raises
DhlAuthError -> ConfigEntryAuthFailed -> a normal SMS reauth, same
fallback every other carrier here already has.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_dhl import DhlApi, DhlAuthError, DhlError
from .const import (
    CONF_COOKIES,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    dhl_canonical,
    dhl_is_active,
    dhl_status_pl,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_NAME = "Home Assistant"


def normalize_parcel(p: dict, *, shared: bool = False) -> dict:
    """Flatten one raw DHL shipment (list or observed endpoint) into the
    shape used by entities."""
    raw = p.get("status") or ""
    timeline = p.get("menuTimelineLabel") or {}
    return {
        "number": p.get("shipmentNumber"),
        "sender": p.get("sender"),
        "status": dhl_status_pl(raw),
        "status_raw": raw,
        "canonical": dhl_canonical(raw),
        "updated": timeline.get("dateUtc"),
        "active": dhl_is_active(raw),
        "package_type": p.get("packageType"),
        "shared": shared,
    }


class DhlCoordinator(DataUpdateCoordinator[dict]):
    """Poll one DHL account and expose active / delivered parcels."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_dhl_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = DhlApi()
        self._api.import_cookies(entry.data.get(CONF_COOKIES) or [])

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        device_id = self.entry.data[CONF_DEVICE_ID]
        access = self._api.refresh_session(device_id, DEVICE_NAME)
        own_raw = self._api.get_parcels(access).get("shipments", [])
        try:
            observed_raw = self._api.get_observed_parcels(access)
        except DhlError as err:
            # Non-fatal — own parcels still matter even if the shared-list
            # call has a transient hiccup.
            _LOGGER.debug("DHL observed-parcels fetch failed: %s", err)
            observed_raw = []
        parcels = [normalize_parcel(p) for p in own_raw]
        parcels += [normalize_parcel(p, shared=True) for p in observed_raw]
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
        except DhlAuthError as err:
            raise ConfigEntryAuthFailed("DHL session expired") from err
        except DhlError as err:
            raise UpdateFailed(str(err)) from err
