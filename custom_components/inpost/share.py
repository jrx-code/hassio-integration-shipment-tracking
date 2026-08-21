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


def entry_by_phone(hass: HomeAssistant, phone: str) -> ConfigEntry | None:
    """The configured account owning `phone`, if this Home Assistant has one."""
    for e in hass.config_entries.async_entries(DOMAIN):
        if str(e.data.get(CONF_PHONE) or "") == str(phone):
            return e
    return None


def configured_aliases(hass: HomeAssistant) -> dict[str, str]:
    """Phone -> alias for every account configured here.

    Lets a parcel shared by another household account be labelled with the name
    used in Home Assistant, instead of whatever (often nothing) InPost stores.
    """
    out: dict[str, str] = {}
    for e in hass.config_entries.async_entries(DOMAIN):
        phone = e.data.get(CONF_PHONE)
        if phone:
            out[str(phone)] = e.data.get(CONF_ALIAS) or str(phone)
    return out


def share_unique_id(owner_phone: str, peer_phone: str) -> str:
    """Unique id of the sharing button on `owner_phone` aimed at `peer_phone`.

    One definition, used both when creating the entity and when checking whether
    an already-running account still lacks it.
    """
    return f"{owner_phone}_share_{peer_phone}"


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
    """Shipment numbers among `parcels` that still need sharing with `uuid`.

    Callers pass every *active* parcel — ready and in transit alike. InPost allows
    sharing well before a parcel reaches the locker (``operations.canShareParcel``
    is already true in transit), and sharing early means the peer sees the whole
    journey and receives the pickup code the moment it exists, instead of up to
    one polling interval later.

    Skips parcels InPost refuses to share and ones already shared with that
    friend, so running this on every poll is idempotent. A parcel someone shared
    *with us* is skipped too: InPost reports ``canShareParcel: false`` on the
    recipient's copy, so it cannot be passed along a second time.
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


def own_only(parcels: list[dict]) -> list[dict]:
    """Parcels this account actually owns.

    A parcel handed to a friend stays ours (``OWN`` with ``shared_to`` filled in);
    only the friend's copy is ``FRIEND``. Parcels with no ownership field at all
    predate the flag and count as ours.
    """
    return [p for p in parcels or [] if p.get("ownership") in (None, "OWN")]


def shared_out(parcels: list[dict]) -> list[dict]:
    """Active parcels of this account that are shared with somebody."""
    return [p for p in parcels or [] if p.get("shared_to")]


def shared_in(parcels: list[dict]) -> list[dict]:
    """Active parcels somebody else shared with this account."""
    return [p for p in parcels or [] if p.get("ownership") in ("FRIEND", "OBSERVED")]


def owner_label(
    parcel: dict, friends: list[dict], aliases: dict[str, str] | None = None
) -> str | None:
    """Who shared this parcel with us — best name available, else the number.

    The sharing account stays in the parcel's ``receiver``. An alias from another
    account configured here wins, because InPost's friend entry often carries no
    name at all and the app then shows bare digits. Otherwise fall back to the
    friend's name from InPost, and finally to the number itself.
    """
    phone = parcel.get("owner_phone")
    if not phone:
        return None
    phone = str(phone)
    if aliases and phone in aliases:
        return aliases[phone]
    for f in friends or []:
        if f.get("phone") and str(f["phone"]) == phone:
            return f.get("name") or phone
    return phone
