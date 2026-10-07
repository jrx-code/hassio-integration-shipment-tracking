"""Unit tests for app-to-app sharing selection logic — shipment_tracking copy.

Mirrors test_share.py but loads `custom_components/shipment_tracking/share.py`
(the multi-carrier merge target, 2026-08-25) instead of the original
`custom_components/inpost/share.py`. Two differences from that file are
intentional and asserted explicitly here, not accidental drift:

  * share_unique_id() is prefixed with "inpost_" — DOMAIN is shared with other
    carriers (DPD, ...) under the multi-carrier umbrella, and the same phone
    number is commonly used for more than one carrier's account.
  * peer_entries() / entry_by_phone() / configured_aliases() filter entries by
    CONF_CARRIER == CARRIER_INPOST, so a DPD account under the same DOMAIN is
    never picked up as an InPost peer.

Run: python3 -m pytest tests/test_share_shipment_tracking.py -q
"""
import importlib.util
import sys
import types
from pathlib import Path

# share.py uses a relative import (`from .const import ...`), so give it a stub
# package rooted at the component directory. Both modules are stdlib-only, which
# keeps this test free of the Home Assistant runtime.
_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"
_PKG = "shipment_tracking_share_stub"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_COMPONENT)]
    sys.modules[_PKG] = pkg
    # const.py is imported by share.py; load it into the stub package first.
    _const_spec = importlib.util.spec_from_file_location(f"{_PKG}.const", _COMPONENT / "const.py")
    _const_mod = importlib.util.module_from_spec(_const_spec)
    sys.modules[_const_spec.name] = _const_mod
    _const_spec.loader.exec_module(_const_mod)
_spec = importlib.util.spec_from_file_location(f"{_PKG}.share", _COMPONENT / "share.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
friend_uuid = _mod.friend_uuid
shareable = _mod.shareable

PEER_B_UUID = "00000000-0000-4000-8000-000555000001"
PEER_C_UUID = "00000000-0000-4000-8000-000555000002"

FRIENDS = [
    {"uuid": PEER_C_UUID, "name": "Peer C", "prefix": "+48", "phone": "555000003"},
    {"uuid": PEER_B_UUID, "name": "Peer B", "prefix": "+48", "phone": "555000002"},
]


def _parcel(shipment, *, can_share=True, shared_to=(), ownership="OWN"):
    return {
        "shipment": shipment,
        "status": "READY_TO_PICKUP",
        "state": "ready",
        "open_code": "107960",
        "ownership": ownership,
        "shared_to": list(shared_to),
        "can_share": can_share,
    }


def test_friend_uuid_matches_by_phone():
    assert friend_uuid(FRIENDS, "555000002") == PEER_B_UUID


def test_shareable_picks_ready_parcels():
    parcels = [_parcel("111"), _parcel("222")]
    assert shareable(parcels, PEER_B_UUID) == ["111", "222"]


def test_shareable_skips_already_shared_with_that_friend():
    parcels = [
        _parcel("111", shared_to=[{"uuid": PEER_B_UUID, "name": "Peer B"}]),
        _parcel("222"),
    ]
    assert shareable(parcels, PEER_B_UUID) == ["222"]


def test_shareable_skips_when_inpost_forbids_sharing():
    parcels = [_parcel("111", can_share=False), _parcel("222")]
    assert shareable(parcels, PEER_B_UUID) == ["222"]


PEER_B = {"uuid": PEER_B_UUID, "name": "Peer B", "prefix": "+48", "phone": "555000002"}
shared_out = _mod.shared_out
shared_in = _mod.shared_in
owner_label = _mod.owner_label
own_only = _mod.own_only


def test_shared_out_lists_only_parcels_with_recipients():
    parcels = [
        _parcel("111", shared_to=[{"uuid": PEER_B_UUID, "name": "Peer B"}]),
        _parcel("222"),
    ]
    assert [p["shipment"] for p in shared_out(parcels)] == ["111"]


def test_shared_in_covers_friend_and_observed():
    parcels = [
        _parcel("111", ownership="FRIEND"),
        _parcel("222", ownership="OBSERVED"),
        _parcel("333", ownership="OWN"),
    ]
    assert [p["shipment"] for p in shared_in(parcels)] == ["111", "222"]


def test_owner_label_resolves_phone_to_friend_name():
    p = dict(_parcel("111", ownership="FRIEND"), owner_phone="555000002")
    assert owner_label(p, [PEER_B]) == "Peer B"


def test_own_only_keeps_our_parcels_including_shared_out():
    parcels = [
        _parcel("111", shared_to=[{"uuid": PEER_B_UUID, "name": "Peer B"}]),
        _parcel("222", ownership="FRIEND"),
        _parcel("333", ownership="OBSERVED"),
        _parcel("444"),
    ]
    assert [p["shipment"] for p in own_only(parcels)] == ["111", "444"]


def test_counters_do_not_overlap():
    parcels = [
        _parcel("111", shared_to=[{"uuid": PEER_B_UUID, "name": "Peer B"}]),
        _parcel("222"),
        _parcel("333", ownership="FRIEND"),
    ]
    mine = {p["shipment"] for p in own_only(parcels)}
    theirs = {p["shipment"] for p in shared_in(parcels)}
    assert mine == {"111", "222"}
    assert theirs == {"333"}
    assert not mine & theirs


share_unique_id = _mod.share_unique_id


def test_share_unique_id_is_carrier_prefixed():
    """DELIBERATE DIFFERENCE from custom_components/inpost/share.py: the id is
    prefixed with "inpost_" because DOMAIN is shared with DPD (and future
    carriers) here, and the bare phone number alone could collide between two
    carriers' accounts for the same person."""
    own, peer = "555000001", "555000002"
    assert share_unique_id(own, peer) == f"inpost_{own}_share_{peer}"
    assert share_unique_id(own, peer) != share_unique_id(peer, own)


auto_share_unique_id = _mod.auto_share_unique_id


def test_auto_share_unique_id_matches_switch_key_scheme():
    """InPostEntity builds "inpost_<own phone>_<key>" and the switch's key is
    "auto_share_<peer phone>" (switch.py) — mirrors test_share_unique_id_
    matches_entity_scheme for the button. Used by __init__.py's
    async_remove_entry to find and drop a peer's stale auto-share switch when
    the account it targets is removed."""
    own, peer = "555000001", "555000002"
    assert auto_share_unique_id(own, peer) == f"inpost_{own}_auto_share_{peer}"
    assert auto_share_unique_id(own, peer) != share_unique_id(own, peer)


def test_owner_label_prefers_configured_alias_over_bare_digits():
    p = dict(_parcel("111", ownership="FRIEND"), owner_phone="555000001")
    friends = [{"uuid": "x", "name": "555000001", "phone": "555000001"}]
    assert owner_label(p, friends) == "555000001"
    assert owner_label(p, friends, {"555000001": "Jarek"}) == "Jarek"


# ------------------- carrier filtering (new in the merge) -------------------
# peer_entries / entry_by_phone / configured_aliases need `hass.config_entries.
# async_entries(DOMAIN)`, so these use minimal fakes rather than the real HA
# ConfigEntry/HomeAssistant classes (kept HA-runtime-free like the rest of the
# suite).

CARRIER_INPOST = _mod.CARRIER_INPOST
CONF_CARRIER = _mod.CONF_CARRIER


class _FakeEntry:
    def __init__(self, entry_id, phone, carrier=CARRIER_INPOST, alias=None,
                 disabled_by=None, source="user"):
        self.entry_id = entry_id
        self.data = {"phone": phone, "carrier": carrier}
        if alias is not None:
            self.data["alias"] = alias
        self.disabled_by = disabled_by
        self.source = source


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return list(self._entries)


class _FakeHass:
    def __init__(self, entries):
        self.config_entries = _FakeConfigEntries(entries)


def test_peer_entries_excludes_dpd_accounts():
    """A DPD account with the same phone as an InPost one is not a peer."""
    us = _FakeEntry("e1", "886108986", carrier=CARRIER_INPOST)
    other_inpost = _FakeEntry("e2", "576516300", carrier=CARRIER_INPOST)
    dpd_same_phone = _FakeEntry("e3", "886108986", carrier="dpd")
    hass = _FakeHass([us, other_inpost, dpd_same_phone])
    peers = _mod.peer_entries(hass, us)
    assert [p.entry_id for p in peers] == ["e2"]


def test_entry_by_phone_ignores_dpd_entry_for_same_number():
    dpd_only = _FakeEntry("e1", "886108986", carrier="dpd")
    hass = _FakeHass([dpd_only])
    assert _mod.entry_by_phone(hass, "886108986") is None


def test_configured_aliases_only_covers_inpost_entries():
    inpost = _FakeEntry("e1", "886108986", carrier=CARRIER_INPOST, alias="Jarek")
    dpd = _FakeEntry("e2", "576516300", carrier="dpd", alias="Marian DPD")
    hass = _FakeHass([inpost, dpd])
    assert _mod.configured_aliases(hass) == {"886108986": "Jarek"}
