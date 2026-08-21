"""DataUpdateCoordinator for the InPost integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InPostApi, InPostError, NotModified, ReauthRequired, categorize_parcels
from .pickup import group_qr_data_url, pickup_groups
from .share import configured_aliases, entry_by_phone, friend_uuid, shareable
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
        # Phones of peer accounts this one auto-shares ready parcels with. Owned
        # by the auto-share switches; empty means manual (button) sharing only.
        self.auto_share: set[str] = set()
        # (shipment, friend uuid) pairs already POSTed. InPost only reflects a
        # share in the parcel payload on the next poll, so without this a share
        # issued between two refreshes would be re-sent.
        self._shared_marks: set[tuple[str, str]] = set()

    @property
    def archive_limit(self) -> int:
        return int(self.entry.options.get(CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT))

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        token = self._api.refresh(self.entry.data[CONF_REFRESH_TOKEN])
        parcels = self._api.get_parcels(token)
        try:
            friends = self._api.get_friends(token)
        except InPostError as err:
            # Sharing is a side feature; a friends-list hiccup must not blank out
            # the parcel sensors. Keep whatever list we had.
            _LOGGER.debug("friends fetch failed: %s", err)
            friends = (self.data or {}).get("friends", [])
        cat = categorize_parcels(parcels)
        cat["archived"].sort(
            key=lambda p: p.get("stored") or p.get("expiry") or "", reverse=True
        )
        groups = pickup_groups(cat["ready"])
        for g in groups:
            # rendered here (executor) — segno is blocking; attribute consumers
            # (sensor property) must not render on the event loop.
            g["qr_url"] = group_qr_data_url(g)
        return {
            "ready": cat["ready"],
            "friends": friends,
            "pickup_groups": groups,
            "in_transit": cat["in_transit"],
            "archived": cat["archived"],
            "counts": {
                "ready": len(cat["ready"]),
                "in_transit": len(cat["in_transit"]),
                "archived": len(cat["archived"]),
            },
        }

    # ---------------- app-to-app sharing ----------------
    @property
    def friends(self) -> list[dict]:
        return (self.data or {}).get("friends", [])

    @property
    def aliases(self) -> dict[str, str]:
        """Phone -> alias of every account configured in this Home Assistant."""
        return configured_aliases(self.hass)

    def friend_uuid_for(self, phone: str) -> str | None:
        return friend_uuid(self.friends, phone)

    def active(self, data: dict | None = None) -> list[dict]:
        """Ready + in-transit parcels, i.e. everything not yet closed."""
        d = data if data is not None else self.data or {}
        return list(d.get("ready", [])) + list(d.get("in_transit", []))

    def pending_for(self, uuid: str, data: dict | None = None) -> list[str]:
        """Active parcels not yet shared with `uuid` (and not shared this cycle).

        `data` overrides the coordinator snapshot — needed during a refresh,
        where self.data is still the previous cycle's.
        """
        return [
            s
            for s in shareable(self.active(data), uuid)
            if (s, uuid) not in self._shared_marks
        ]

    def _share(self, shipments: list[str], uuid: str) -> None:
        """Blocking share — runs in the executor."""
        token = self._api.refresh(self.entry.data[CONF_REFRESH_TOKEN])
        self._api.share_parcels(token, shipments, [uuid])

    async def async_share_with(self, phone: str, data: dict | None = None) -> list[str]:
        """Share every not-yet-shared ready parcel with the peer at `phone`.

        Returns the shipment numbers actually sent. Raises InPostError on API
        failure so the caller (button / switch) surfaces it to the user.
        """
        friends = (data if data is not None else self.data or {}).get("friends", [])
        uuid = friend_uuid(friends, phone)
        if not uuid:
            raise InPostError(f"not paired with {phone} on this InPost account")
        shipments = self.pending_for(uuid, data)
        if not shipments:
            return []
        await self.hass.async_add_executor_job(self._share, shipments, uuid)
        self._shared_marks.update((s, uuid) for s in shipments)
        _LOGGER.info("shared %d parcel(s) with %s", len(shipments), phone)
        await self._async_refresh_recipient(phone)
        return shipments

    async def _async_refresh_recipient(self, phone: str) -> None:
        """Pull the recipient's account now, if it is configured here too.

        InPost only reveals a share on the next poll, so without this the parcels
        would sit invisible on the receiving account for up to a full interval —
        the user clicks and nothing happens for fifteen minutes. Only reached
        after a share actually went out, so it cannot ping-pong: once there is
        nothing left to share, no refresh is requested either.
        """
        entry = entry_by_phone(self.hass, phone)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return
        peer = getattr(entry, "runtime_data", None)
        if peer is None or peer is self:
            return
        await peer.async_request_refresh()

    async def async_apply_auto_share(self, data: dict | None = None) -> None:
        """Share newly ready parcels with every peer the user switched on.

        Never raises: a failed share must not fail the refresh that triggered it,
        and the next poll retries anyway (nothing was marked as sent).
        """
        for phone in sorted(self.auto_share):
            try:
                await self.async_share_with(phone, data)
            except InPostError as err:
                _LOGGER.warning("auto-share to %s failed: %s", phone, err)

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(self._fetch)
        except ReauthRequired as err:
            raise ConfigEntryAuthFailed("InPost refresh token expired") from err
        except NotModified:
            # Nothing changed / rate-limited — keep the last good snapshot.
            if self.data is not None:
                return self.data
            return {
                "ready": [], "pickup_groups": [], "in_transit": [], "archived": [],
                "counts": {"ready": 0, "in_transit": 0, "archived": 0},
            }
        except InPostError as err:
            raise UpdateFailed(str(err)) from err

        if self.auto_share:
            await self.async_apply_auto_share(data)
        return data
