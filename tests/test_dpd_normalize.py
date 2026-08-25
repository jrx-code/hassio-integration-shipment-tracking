"""Unit tests for DpdCoordinator.normalize_parcel() — pure, no Home Assistant.

Verified live 2026-08-25 against a real DPD account: the ``/packages/{waybill}``
detail endpoint returns sender.address / delivery_point GPS / delivery.courier_*
and (for multi-parcel shipments) mps.parcels[] — all absent/empty on the list
endpoint (list-level mps only carries the count, not the sibling waybills).

    python3 -m pytest tests/test_dpd_normalize.py -q
"""
import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _load_flat(modname: str, path: Path):
    """Exec a component module as a standalone flat module (rewriting its
    relative ``from .x import`` to plain ``from x import``) so it can run
    without a real package context or Home Assistant installed."""
    src = path.read_text()
    src = src.replace("from .const import", "from const import")
    src = src.replace("from .api_dpd import", "from api_dpd import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_dpd():
    sys.path.insert(0, str(_PKG_DIR))

    class _DUC:
        def __class_getitem__(cls, item):
            return cls

    _stub("homeassistant")
    _stub("homeassistant.config_entries", ConfigEntry=object)
    _stub("homeassistant.core", HomeAssistant=object)
    _stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC, UpdateFailed=Exception)

    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_dpd", _PKG_DIR / "api_dpd.py")
    return _load_flat("coordinator_dpd", _PKG_DIR / "coordinator_dpd.py")


_coord = _load_coordinator_dpd()

_RAW = {
    "waybill": "X1",
    "sender": {"name": "Sender"},
    "main_status": {"status": "IN_TRANSPORT", "date": "2026-08-25"},
    "statuses": [],
}

_DETAIL = {
    "sender": {"address": {"address": "ul. Test 1", "postal_code": "00-001", "city": "Warszawa"}},
    "delivery_point": {"latitude": "53.5", "longitude": "14.4"},
    "delivery": {"courier_name": "Jan", "courier_phone": "123456789", "delivered_datetime": None},
    "mps": {
        "current_parcel_number": 1,
        "parcels_count": 2,
        "parcels": [{"waybill": "X2", "current_parcel_number": 2, "main_status": {"status": "DELIVERED"}}],
    },
}


def test_normalize_without_detail_has_no_enrichment_fields():
    row = _coord.normalize_parcel(_RAW)
    assert row["number"] == "X1"
    assert "sender_address" not in row


def test_normalize_with_detail_adds_enrichment_fields():
    row = _coord.normalize_parcel(_RAW, _DETAIL)
    assert row["sender_address"] == "ul. Test 1, 00-001, Warszawa"
    assert row["delivery_gps"] == {"lat": "53.5", "lon": "14.4"}
    assert row["courier_name"] == "Jan"
    assert row["courier_phone"] == "123456789"


def test_normalize_mps_group_pulls_sibling_waybills():
    row = _coord.normalize_parcel(_RAW, _DETAIL)
    assert row["mps_part"] == 1
    assert row["mps_count"] == 2
    assert row["mps_siblings"] == [{"number": "X2", "status": "Dostarczona", "part": 2}]


def test_normalize_single_parcel_detail_has_no_mps_fields():
    detail = dict(_DETAIL)
    detail["mps"] = {"current_parcel_number": 1, "parcels_count": 1, "parcels": []}
    row = _coord.normalize_parcel(_RAW, detail)
    assert row["mps_part"] is None
    assert row["mps_count"] is None
    assert row["mps_siblings"] is None
