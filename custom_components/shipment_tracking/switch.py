"""Standing app-to-app sharing: a switch per configured InPost peer account.

Turned on, every parcel that becomes ready on this account is shared with that
peer automatically on the next poll, mirroring one account onto the other. Turned
off, sharing only happens when the matching button is pressed. Sharing is not
undone when the switch goes off: parcels already shared stay shared, since this
client implements no unshare call (withdrawing a share is an app-side action).
DPD accounts under the same multi-carrier domain never get one — sharing is
InPost-only.

State lives in the entity (RestoreEntity), deliberately not in entry options: the
integration reloads itself on option updates, so a toggle would tear down the
whole account setup.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ShipmentConfigEntry
from .const import CONF_PHONE
from .entity import InPostEntity
from .share import peer_alias, peer_entries


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShipmentConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        InPostAutoShareSwitch(coordinator, peer) for peer in peer_entries(hass, entry)
    )


class InPostAutoShareSwitch(InPostEntity, SwitchEntity, RestoreEntity):
    """Keep every ready parcel of this account shared with one peer InPost account."""

    _attr_icon = "mdi:share-all"

    def __init__(self, coordinator, peer: ConfigEntry) -> None:
        self._peer_phone = str(peer.data[CONF_PHONE])
        self._peer_alias = peer_alias(peer)
        super().__init__(coordinator, f"auto_share_{self._peer_phone}")
        self._attr_name = f"Auto-udostępnianie → {self._peer_alias}"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            self._attr_is_on = True
            self.coordinator.auto_share.add(self._peer_phone)
            # The coordinator's first refresh runs before platforms are set up,
            # so it saw an empty auto-share set. Without this catch-up nothing
            # would be mirrored until the next poll — a whole interval of silence
            # after every restart. Scheduled, not awaited: startup must not block
            # on an InPost round-trip.
            self.hass.async_create_task(self.coordinator.async_apply_auto_share())

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.auto_share.discard(self._peer_phone)
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
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

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.auto_share.add(self._peer_phone)
        self._attr_is_on = True
        self.async_write_ha_state()
        # Catch up on whatever is already waiting instead of making the user wait
        # for the next poll.
        await self.coordinator.async_apply_auto_share()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.auto_share.discard(self._peer_phone)
        self._attr_is_on = False
        self.async_write_ha_state()
