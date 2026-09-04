"""DataUpdateCoordinator for the DHL carrier.

The config entry holds a snapshot of the cookiejar (CONF_COOKIES) plus a
stable device_id/device_name pair. The coordinator restores those cookies
into its own DhlApi instance at setup and calls refresh_session() every
poll.

SESSION LIFETIME, measured 2026-09-04 — read this before changing the poll
interval. The DHL session is a 30-minute token carried in the
access-token/access-signature cookie pair, and /auth/refresh authenticates
with that pair. Until 2026-09-04 the minted token was never written back
into the jar, so the pair kept the login-time token and the session died 30
minutes after the SMS, whichever way we polled: both entries' modified_at
stayed pinned to the login instant, the stored token's exp sat at login+30,
and the server's 401 named that exact timestamp. api_dhl._adopt_access_token
is what fixes it. Consequence: THE POLL INTERVAL IS ALSO THE KEEPALIVE. Poll
less often than every 30 minutes and the session expires between polls and
asks for an SMS, so the interval is clamped below (DHL_MAX_INTERVAL).

The jar is persisted back to entry.data whenever it changes — now genuinely
every poll, since the token rotates. That write is only safe because
_async_reload_on_update (__init__.py) reloads on options changes only —
without that guard this would reload the integration every poll, the same
storm DPD and Pocztex each hit once.

RESIDUAL, known and accepted: the first refresh of a setup runs while the
entry is still SETUP_IN_PROGRESS, and persisting from there is what left
DPD's coordinator empty until a reload (see coordinator_dpd.py). So that one
jar is not written, and a restart inside the first poll interval after a
reauth restores the login-time jar — which is fine as long as it is younger
than 30 minutes, and it always is at that point.
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

# The minted JWT lives 30 minutes (exp - iat, decoded live on both accounts).
DHL_TOKEN_LIFETIME = timedelta(minutes=30)
# Poll with margin inside that, so a slow/failed poll still has a second
# chance before the session is gone.
DHL_MAX_INTERVAL = timedelta(minutes=20)


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
        if update_interval > DHL_MAX_INTERVAL:
            # Not a preference — the poll IS the keepalive (see module
            # docstring). A longer interval hands the user an SMS prompt
            # every time instead of parcels.
            _LOGGER.warning(
                "DHL scan interval %s exceeds the session's %s lifetime — "
                "clamping to %s, otherwise the session expires between polls",
                update_interval, DHL_TOKEN_LIFETIME, DHL_MAX_INTERVAL,
            )
            update_interval = DHL_MAX_INTERVAL
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
