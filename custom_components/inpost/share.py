"""App-to-app sharing: peer discovery and pick-what-to-share logic.

Pure functions here, no Home Assistant imports beyond config-entry typing, so the
selection rules stay unit-testable. The InPost side is described in api.py;
the short version: a share is a POST of (shipmentNumber, friendUuid) pairs, and
it shows up on the recipient's account as a normal parcel with
ownershipStatus=FRIEND carrying openCode/qrCode.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONF_ALIAS, CONF_PHONE, DOMAIN

if TYPE_CHECKING:  # keeps this module importable without the HA runtime (tests)
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def peer_entries(hass: HomeAssistant, entry: ConfigEntry) -> list[ConfigEntry]:
    """Other InPost accounts configured in this Home Assistant.

    Read from the config-entry registry rather than from loaded runtime data, so
    the order in which entries set up does not decide whether the pair sees each
    other. Ignored/disabled entries are not peers.
    """
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
        and e.disabled_by is None
        and e.source != "ignore"
        and e.data.get(CONF_PHONE)
    ]


def peer_alias(entry: ConfigEntry) -> str:
    return entry.data.get(CONF_ALIAS) or entry.data.get(CONF_PHONE) or entry.entry_id


def friend_uuid(friends: list[dict], phone: str) -> str | None:
    """UUID of the pairing with `phone`, or None when the two are not paired.

    The UUID identifies the *relationship*, not the person: two paired accounts
    each list the other under the same UUID (verified against the live API).
    Resolve it from the sharing account's own friend list regardless — that is
    the account the POST is made from.
    """
    for f in friends or []:
        if f.get("phone") and str(f["phone"]) == str(phone):
            return f.get("uuid")
    return None


def shareable(parcels: list[dict], uuid: str) -> list[str]:
    """Shipment numbers of ready parcels that still need sharing with `uuid`.

    Skips parcels InPost refuses to share (``can_share`` comes from
    ``operations.canShareParcel``) and ones already shared with that friend, so
    running this on every poll is idempotent.
    """
    out: list[str] = []
    for p in parcels or []:
        if not p.get("can_share"):
            continue
        if any(s.get("uuid") == uuid for s in p.get("shared_to") or []):
            continue
        shipment = p.get("shipment")
        if shipment:
            out.append(str(shipment))
    return out
