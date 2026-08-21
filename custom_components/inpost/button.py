"""One-shot app-to-app sharing: a button per configured peer account.

With two accounts set up, each one's device gets an "Udostępnij → <other alias>"
button. Pressing it shares every ready parcel that is not already shared with
that peer; the peer's own InPost account (and therefore their sensors, QR image
entities and cards) picks them up on its next poll.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InPostConfigEntry
from .api import InPostError
from .const import CONF_PHONE
from .entity import InPostEntity
from .share import peer_alias, peer_entries

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InPostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        InPostShareButton(coordinator, peer) for peer in peer_entries(hass, entry)
    )


class InPostShareButton(InPostEntity, ButtonEntity):
    """Share all ready parcels of this account with one peer account."""

    _attr_icon = "mdi:share-variant"

    def __init__(self, coordinator, peer: ConfigEntry) -> None:
        self._peer_phone = str(peer.data[CONF_PHONE])
        self._peer_alias = peer_alias(peer)
        # InPostEntity builds the unique id as "<own phone>_<key>", so this key
        # yields exactly share_unique_id(own, peer) — the id __init__ looks for
        # when deciding whether a running account still lacks entities for a
        # newly added one. Keep the two in step.
        super().__init__(coordinator, f"share_{self._peer_phone}")
        self._attr_name = f"Udostępnij → {self._peer_alias}"

    @property
    def available(self) -> bool:
        """Unavailable until the two InPost accounts are paired ("znajomi").

        Pairing is a one-off done in the InPost app (invitation code); it cannot
        be driven from here, so an unpaired peer is a dead button, not an error.
        """
        return (
            super().available
            and self.coordinator.friend_uuid_for(self._peer_phone) is not None
        )

    @property
    def extra_state_attributes(self) -> dict:
        uuid = self.coordinator.friend_uuid_for(self._peer_phone)
        return {
            "odbiorca": self._peer_alias,
            "telefon": self._peer_phone,
            "sparowani": uuid is not None,
            "do_udostepnienia": len(self.coordinator.pending_for(uuid)) if uuid else 0,
        }

    async def async_press(self) -> None:
        try:
            shipments = await self.coordinator.async_share_with(self._peer_phone)
        except InPostError as err:
            raise HomeAssistantError(
                f"Nie udało się udostępnić paczek do {self._peer_alias}: {err}"
            ) from err
        if not shipments:
            _LOGGER.debug("nothing to share with %s", self._peer_alias)
            return
        await self.coordinator.async_request_refresh()
