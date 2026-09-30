"""Unit tests for InPost statusGroup fallback + events[] mapping (issue #3).

Pure-logic tests — no Home Assistant runtime needed:
    python3 -m pytest tests/test_inpost_statusgroup_events.py -q
"""
from __future__ import annotations

import sys
import types
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
_api = _load_flat("inpost_api", _PKG_DIR / "api.py")

inpost_canonical = _const.inpost_canonical
status_pl = _const.status_pl
categorize_parcels = _api.categorize_parcels


def test_known_ready_unchanged():
    assert inpost_canonical("READY_TO_PICKUP") == "ready"
    assert inpost_canonical("STACK_IN_BOX_MACHINE") == "ready"


def test_known_archived_unchanged():
    assert inpost_canonical("DELIVERED") == "archived"
    assert inpost_canonical("PICKUP_TIME_EXPIRED") == "archived"


def test_stack_parcel_expired_is_ready():
    """The live issue #3 status must land in ready, not archive."""
    assert (
        inpost_canonical("STACK_PARCEL_IN_BOX_MACHINE_PICKUP_TIME_EXPIRED")
        == "ready"
    )


def test_pickup_reminder_is_ready():
    assert inpost_canonical("PICKUP_REMINDER_SENT") == "ready"


def test_unknown_with_to_pickup_group_is_ready():
    assert inpost_canonical("BRAND_NEW_UNKNOWN_STATUS", "TO_PICKUP") == "ready"
    assert inpost_canonical("BRAND_NEW_UNKNOWN_STATUS", "to_pickup") == "ready"


def test_unknown_without_group_defaults_to_in_transit():
    """DHL-style safer default — never silently archive unknowns."""
    assert inpost_canonical("BRAND_NEW_UNKNOWN_STATUS") == "in_transit"
    assert inpost_canonical("BRAND_NEW_UNKNOWN_STATUS", "IN_TRANSIT") == "in_transit"
    assert inpost_canonical("BRAND_NEW_UNKNOWN_STATUS", "") == "in_transit"


def test_status_pl_for_new_statuses():
    assert "skrytce" in status_pl("STACK_PARCEL_IN_BOX_MACHINE_PICKUP_TIME_EXPIRED").lower()
    assert status_pl("PICKUP_REMINDER_SENT") == "Przypomnienie o odbiorze"


def _expired_locker_parcel(**extra):
    body = {
        "shipmentNumber": "620000000000000000000000",
        "status": "STACK_PARCEL_IN_BOX_MACHINE_PICKUP_TIME_EXPIRED",
        "statusGroup": "TO_PICKUP",
        "openCode": "123456",
        "qrCode": "P|+48111111111|123456",
        "operations": {"collect": True, "canShareParcel": False},
        "pickUpPoint": {
            "name": "KRA01A",
            "addressDetails": {
                "street": "Testowa", "buildingNumber": "1", "city": "Kraków",
            },
        },
        "sender": {"name": "Sklep"},
        "events": [
            {
                "eventTitle": "Upłynął termin magazynowania",
                "eventDescription": (
                    "Upłynął termin odebrania paczki z miejsca magazynowania. "
                    "Wkrótce paczka wyruszy w drogę do pierwotnie wybranego miejsca."
                ),
            }
        ],
    }
    body.update(extra)
    return body


def test_categorize_expired_locker_goes_to_ready_with_events():
    cat = categorize_parcels([_expired_locker_parcel()])
    assert cat["archived"] == []
    assert len(cat["ready"]) == 1
    assert cat["in_transit"] == []
    row = cat["ready"][0]
    assert row["shipment"] == "620000000000000000000000"
    assert row["state"] == "ready"
    assert row["open_code"] == "123456"
    assert row["event_title"] == "Upłynął termin magazynowania"
    assert "magazynowania" in (row["event_description"] or "")


def test_categorize_unknown_status_group_to_pickup():
    cat = categorize_parcels([{
        "shipmentNumber": "1",
        "status": "SOME_FUTURE_STATUS",
        "statusGroup": "TO_PICKUP",
        "events": [],
    }])
    assert [p["shipment"] for p in cat["ready"]] == ["1"]
    assert cat["archived"] == []


def test_categorize_delivered_still_archived():
    cat = categorize_parcels([{
        "shipmentNumber": "2",
        "status": "DELIVERED",
        "statusGroup": "DELIVERED",
    }])
    assert [p["shipment"] for p in cat["archived"]] == ["2"]
