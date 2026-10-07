"""DataUpdateCoordinator for the ORLEN Paczka account carrier."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_orlen_account import (
    OrlenAccountApi,
    OrlenAccountClientSecretError,
    OrlenAccountError,
    OrlenAccountReauthRequired,
)
from .const import (
    CONF_CLIENT_SECRET,
    CONF_DEVICE_ID,
    CONF_PHONE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OrlenAccountCoordinator(DataUpdateCoordinator[dict]):
    """Poll one ORLEN Paczka account (phone + deviceId) and split parcels.

    Parcels are auto-discovered from the account — every parcel addressed to the
    registered phone number — so, unlike the public-track Orlen carrier, there
    is no manual tracking-number list. The app token is app-level and refreshed
    inside the API client; the durable per-user credentials are the phone and
    deviceId stored on the config entry.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_orlen_account_{entry.data.get(CONF_PHONE, entry.entry_id)}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = OrlenAccountApi(entry.data.get(CONF_CLIENT_SECRET, ""))

    def _fetch(self) -> dict:
        parcels = self._api.get_shipments(
            self.entry.data[CONF_PHONE], self.entry.data[CONF_DEVICE_ID]
        )
        ready = [p for p in parcels if p["canonical"] == "ready_for_pickup"]
        active = [p for p in parcels if p["active"]]
        delivered = [p for p in parcels if not p["active"]]
        return {
            "ready": ready,
            "active": active,
            "delivered": delivered,
            "all": parcels,
            "counts": {
                "ready": len(ready),
                "active": len(active),
                "delivered": len(delivered),
            },
        }

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except OrlenAccountClientSecretError as err:
            # Missing (entries from before the secret became a setting) or
            # rejected secret: reauth asks for it.
            raise ConfigEntryAuthFailed(f"Orlen app client secret: {err}") from err
        except OrlenAccountReauthRequired as err:
            raise ConfigEntryAuthFailed("Orlen account no longer valid") from err
        except OrlenAccountError as err:
            raise UpdateFailed(str(err)) from err
