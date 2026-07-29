"""DataUpdateCoordinator for the InPost integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InPostApi, InPostError, NotModified, ReauthRequired, categorize_parcels
from .const import (
    CONF_ARCHIVE_LIMIT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_BASE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UA,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class InPostCoordinator(DataUpdateCoordinator[dict]):
    """Poll one InPost account and expose categorized parcels.

    The InPost client is blocking (urllib) so every call goes through the
    executor. The refresh token does not rotate; when it expires InPost signals
    reauthentication, surfaced here as ConfigEntryAuthFailed to trigger the HA
    reauth flow. A 304 (NotModified) keeps the previously fetched data.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data.get('phone', entry.entry_id)}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = InPostApi(DEFAULT_BASE, DEFAULT_UA)

    @property
    def archive_limit(self) -> int:
        return int(self.entry.options.get(CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT))

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        token = self._api.refresh(self.entry.data[CONF_REFRESH_TOKEN])
        parcels = self._api.get_parcels(token)
        cat = categorize_parcels(parcels)
        cat["archived"].sort(
            key=lambda p: p.get("stored") or p.get("expiry") or "", reverse=True
        )
        return {
            "ready": cat["ready"],
            "in_transit": cat["in_transit"],
            "archived": cat["archived"],
            "counts": {
                "ready": len(cat["ready"]),
                "in_transit": len(cat["in_transit"]),
                "archived": len(cat["archived"]),
            },
        }

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except ReauthRequired as err:
            raise ConfigEntryAuthFailed("InPost refresh token expired") from err
        except NotModified:
            # Nothing changed / rate-limited — keep the last good snapshot.
            if self.data is not None:
                return self.data
            return {
                "ready": [], "in_transit": [], "archived": [],
                "counts": {"ready": 0, "in_transit": 0, "archived": 0},
            }
        except InPostError as err:
            raise UpdateFailed(str(err)) from err
