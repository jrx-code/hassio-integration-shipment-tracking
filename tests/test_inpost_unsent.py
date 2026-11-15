"""Unit tests for api.split_unsent() and the ShipX lookup (issue #4).

Pure logic, no Home Assistant:
    python3 -m pytest tests/test_inpost_unsent.py -q
"""
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _load_flat(modname: str, path: Path):
    src = path.read_text()
    src = src.replace("from .const import", "from const import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


sys.path.insert(0, str(_PKG_DIR))
_const = _load_flat("const", _PKG_DIR / "const.py")
_api = _load_flat("inpost_api_unsent", _PKG_DIR / "api.py")

NOW = datetime(2026, 11, 15, 21, 0, tzinfo=timezone.utc)
# Real shapes: ShipX created_at as returned live on 2026-11-15.
CREATED = {
    "OLD": "2026-10-13T16:33:18.506+02:00",   # 33 days
    "MID": "2026-11-08T20:00:00.000+01:00",   # exactly 7 days
    "NEW": "2026-11-12T19:35:09.772+01:00",   # 3 days
    "SENT": "2026-10-01T10:00:00.000+02:00",
}


def _row(num, status="CONFIRMED", state="in_transit"):
    return {"shipment": num, "status": status, "state": state}


def _cat():
    return {
        "ready": [_row("R1", "READY_TO_PICKUP", "ready")],
        "in_transit": [_row("OLD"), _row("MID"), _row("NEW"), _row("SENT", "ADOPTED_AT_SORTING_CENTER"),
                       _row("NODATE")],
        "archived": [],
    }


def test_old_unsent_labels_move_and_carry_their_age():
    cat = _api.split_unsent(_cat(), CREATED, 7, NOW)
    assert [r["shipment"] for r in cat["unsent"]] == ["OLD", "MID"]
    assert cat["unsent"][0]["unsent_days"] == 33
    assert cat["unsent"][0]["created"] == CREATED["OLD"]
    assert [r["shipment"] for r in cat["in_transit"]] == ["NEW", "SENT", "NODATE"]
    assert [r["shipment"] for r in cat["ready"]] == ["R1"]


def test_a_sent_parcel_never_moves_however_old():
    cat = _api.split_unsent(_cat(), CREATED, 1, NOW)
    assert "SENT" not in [r["shipment"] for r in cat["unsent"]]


def test_unknown_creation_date_stays_in_transit():
    cat = _api.split_unsent(_cat(), {"NODATE": None}, 1, NOW)
    assert cat["unsent"] == []
    assert len(cat["in_transit"]) == 5


def test_zero_days_turns_it_off_but_keeps_the_bucket():
    cat = _api.split_unsent(_cat(), CREATED, 0, NOW)
    assert cat["unsent"] == []
    assert len(cat["in_transit"]) == 5


def test_other_pre_send_statuses_count_as_unsent():
    for status in ("CREATED", "OFFERS_PREPARED", "OFFER_SELECTED"):
        cat = {"ready": [], "in_transit": [_row("OLD", status)], "archived": []}
        assert len(_api.split_unsent(cat, CREATED, 7, NOW)["unsent"]) == 1


def test_bad_date_is_ignored():
    cat = {"ready": [], "in_transit": [_row("X")], "archived": []}
    assert _api.split_unsent(cat, {"X": "not a date"}, 1, NOW)["unsent"] == []


def test_shipx_lookup_reads_created_at_and_fails_soft():
    api = _api.InPostApi("https://example.invalid", "ua")
    seen = {}

    def ok(req):
        seen["url"] = req.full_url
        return 200, {}, {"status": "confirmed", "created_at": CREATED["OLD"]}

    api._do = ok
    assert api.shipx_created_at("620999") == CREATED["OLD"]
    assert seen["url"] == "https://api-shipx-pl.easypack24.net/v1/tracking/620999"
    api._do = lambda req: (404, {}, {"error": "resource_not_found"})
    assert api.shipx_created_at("1") is None

    def boom(req):
        raise _api.InPostError("network down")

    api._do = boom
    assert api.shipx_created_at("1") is None
