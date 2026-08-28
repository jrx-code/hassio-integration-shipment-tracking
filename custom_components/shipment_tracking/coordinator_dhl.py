"""DataUpdateCoordinator for the DHL carrier.

The config entry holds a snapshot of the cookiejar (CONF_COOKIES) plus a
stable device_id/device_name pair. The coordinator restores those cookies
into its own DhlApi instance at setup and calls refresh_session() every
poll — verified live to mint a fresh-``iat`` token from cookies alone, a
real sliding 30-minute window (unlike Pocztex's, see const.py's DHL
section).

CORRECTED 2026-08-28, on two real live accounts. The earlier
version deliberately did NOT write the jar back to entry.data, on the
theory that the login-time snapshot would still be good after a restart.
It is not, and the first real restart proved it: both DHL entries came up
``setup_error`` / "DHL session expired". Autopsy of the stored snapshot —
cookies ``BIGipServer…``, ``TS…``, ``access-token``, ``access-signature``,
``access-remember`` — showed the stored ``access-token`` was a JWT whose
``exp`` sat at login + 30 min, i.e. ~30 hours in the past, and replaying
that whole set against /auth/refresh returned 401. Dropping the expired
``access-token`` and replaying the rest (``access-remember`` included)
returned 401 as well, so the durable half of the credential rotates too:
what refresh_session() consumes is the CURRENT jar, and the login-time one
is spent the moment the first refresh succeeds.

So the jar is now persisted back to entry.data whenever it changes, which
in practice is every poll. That write is only safe because
_async_reload_on_update (__init__.py) reloads on options changes only —
without that guard this would reload the integration every poll, the same
storm DPD and Pocztex each hit once.

RESIDUAL, known and accepted: the first refresh of a setup runs while the
entry is still SETUP_IN_PROGRESS, and persisting from there is what left
DPD's coordinator empty until a reload (see coordinator_dpd.py). So that
one jar is not written, and a restart inside the first poll interval after
a reauth can still land on a spent snapshot and ask for SMS again. Every
later restart is covered.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
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
    # menuTimelineLabel.status is the field DHL's own app renders; the TT_ code
    # in "status" is never translated anywhere in their bundle. See const.py.
    tl = timeline.get("status")
    return {
        "number": p.get("shipmentNumber"),
        "sender": p.get("sender"),
        "status": dhl_status_pl(raw, tl),
        "status_raw": raw,
        "status_timeline": tl,
        "canonical": dhl_canonical(raw, tl),
        "updated": timeline.get("dateUtc"),
        "active": dhl_is_active(raw, tl),
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

    def _persist_cookies(self) -> None:
        """Write the current jar back to entry.data if it moved.

        Skipped while the entry is still setting up — see the RESIDUAL note
        in this module's docstring.
        """
        if self.entry.state is not ConfigEntryState.LOADED:
            return
        cookies = self._api.export_cookies()
        if not cookies or cookies == self.entry.data.get(CONF_COOKIES):
            return
        _LOGGER.debug("DHL cookie jar rotated — persisting %d cookies", len(cookies))
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_COOKIES: cookies}
        )

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(self._fetch)
        except DhlAuthError as err:
            raise ConfigEntryAuthFailed("DHL session expired") from err
        except DhlError as err:
            raise UpdateFailed(str(err)) from err
        self._persist_cookies()
        return data
