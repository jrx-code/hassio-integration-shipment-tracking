"""DataUpdateCoordinator for the Pocztex carrier.

Account auto-discovery, like DPD/InPost — the config entry holds the
credentials needed to keep polling.

CORRECTED 2026-08-26, twice, live, on Jarek's account:

1st attempt (wrong diagnosis): assumed the refresh_token's ``exp`` claim
(``iat + 1800s``) was a sliding idle timeout, and that persisting each
poll's rotated refresh_token would keep the session alive indefinitely —
implemented via async_update_entry_silently(). Deployed, then proven false
by 82 minutes of dead entity + an unchanged token in storage: refresh()
DOES mint a token with a genuinely new ``jti`` each call (confirmed by a
live login+refresh+refresh test outside HA), but ``iat``/``exp`` stay
pinned to the ORIGINAL login instant no matter how many times or how soon
after issuance refresh() is called. That's a Keycloak SSO-session-level
cap on this client (``ppsa``/``customer-front``), not a per-token idle
timer — refreshing cannot extend it, full stop, so no refresh-token-only
design can survive past 30 minutes.

Actual fix: the config entry now also stores the account password
(config_flow.py, CHANGED 2026-08-26) and this coordinator does a full
login() each poll instead of refresh() — a fresh Keycloak session, fresh
30-minute window, every ~15 minutes (this integration's default interval,
comfortably inside the window). refresh_token is no longer read; kept in
entry.data only for entries that predate this fix (harmless, unused).

DPD does NOT have this problem — its refresh_token was verified
non-expiring/reusable, a genuinely different case.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_pocztex import PocztexApi, PocztexAuthError, PocztexError
from .const import (
    CONF_EMAIL,
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
        update_interval = timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_pocztex_{entry.entry_id}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = PocztexApi()

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor. Full login every poll, not
        refresh — see module docstring for why refresh() alone can't work
        here."""
        access, _refresh = self._api.login(self.entry.data[CONF_EMAIL], self.entry.data.get(CONF_PASSWORD))
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
            raise ConfigEntryAuthFailed("Pocztex password rejected") from err
        except PocztexError as err:
            raise UpdateFailed(str(err)) from err
