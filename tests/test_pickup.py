"""Unit tests for pickup grouping (multiskrytka + n singles).

Pure-logic tests — no Home Assistant runtime needed:
    python3 -m pytest tests/test_pickup.py -q
Parcel dicts use the api._map_parcel shape and mirror real API data verified
live on 2026-08-03 (multiskrytka members share multi_uuid; the leader carries
the shipmentNumbers list, surfaced as multi_count).
"""
import importlib.util
from pathlib import Path

# Load pickup.py directly by path — importing the `inpost` package would pull in
# `inpost/__init__.py`, which needs the Home Assistant runtime. pickup.py is
# stdlib-only by design, so this keeps the test HA-free.
_PICKUP = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking" / "pickup.py"
_spec = importlib.util.spec_from_file_location("inpost_pickup", _PICKUP)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
group_qr_payload = _mod.group_qr_payload
group_qr_data_url = _mod.group_qr_data_url
pickup_groups = _mod.pickup_groups


def _parcel(shipment, code, uuid=None, multi_count=None):
    return {
        "shipment": shipment,
        "status": "READY_TO_PICKUP",
        "state": "ready",
        "open_code": code,
        "qr": f"P|+48555000001|{code}",
        "locker": "WAW01A",
        "address": "ul. Testowa 1 Warszawa",
        "sender": "Allegro",
        "expiry": "2026-08-05T12:00:00Z",
        "stored": None,
        "multi_uuid": uuid,
        "multi_count": multi_count,
    }


def test_n_singles_stay_separate():
    ready = [_parcel("A", "111"), _parcel("B", "222"), _parcel("C", "333")]
    groups = pickup_groups(ready)
    assert len(groups) == 3
    assert [g["count"] for g in groups] == [1, 1, 1]
    assert [group_qr_payload(g) for g in groups] == [
        "P|+48555000001|111",
        "P|+48555000001|222",
        "P|+48555000001|333",
    ]


def test_multiskrytka_collapses_to_one_group_with_leader_qr():
    u = "00000000-0000-4000-8000-000000000009"
    # Two plain members + the leader (multi_count set) last, as the API returns.
    ready = [
        _parcel("M1", "204171", uuid=u),
        _parcel("M2", "196695", uuid=u),
        _parcel("LEADER", "792113", uuid=u, multi_count=3),
    ]
    groups = pickup_groups(ready)
    assert len(groups) == 1
    g = groups[0]
    assert g["count"] == 3
    assert g["key"] == u
    assert g["rep"]["shipment"] == "LEADER"  # leader picked despite arriving last
    assert group_qr_payload(g) == "P|+48555000001|792113"
    assert [m["shipment"] for m in g["members"]] == ["M1", "M2", "LEADER"]


def test_multiskrytka_without_leader_falls_back_to_first_member():
    u = "no-leader-uuid"
    ready = [_parcel("X", "555", uuid=u), _parcel("Y", "666", uuid=u)]
    groups = pickup_groups(ready)
    assert len(groups) == 1
    assert groups[0]["rep"]["shipment"] == "X"
    assert groups[0]["count"] == 2


def test_mixed_order_preserved_by_first_appearance():
    u = "grp"
    ready = [
        _parcel("S1", "100"),
        _parcel("M1", "200", uuid=u),
        _parcel("S2", "300"),
        _parcel("M2", "400", uuid=u, multi_count=2),
    ]
    groups = pickup_groups(ready)
    # S1, then multiskrytka (first seen at M1), then S2
    assert [g["key"] for g in groups] == ["S1", u, "S2"]
    assert [g["count"] for g in groups] == [1, 2, 1]
    assert groups[1]["rep"]["shipment"] == "M2"  # leader


def test_empty():
    assert pickup_groups([]) == []


def test_qr_payload_none_when_leader_has_no_qr():
    p = _parcel("Z", "999")
    p["qr"] = None
    assert group_qr_payload(pickup_groups([p])[0]) is None


def test_qr_data_url_none_without_payload_skips_segno():
    # No payload -> returns None before importing segno (segno not installed here).
    p = _parcel("Z", "999")
    p["qr"] = None
    assert group_qr_data_url(pickup_groups([p])[0]) is None
