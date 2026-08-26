"""Unit tests for DhlCoordinator.normalize_parcel() and const.py's DHL
canonical mapping — pure, no HA.

_REAL_SHIPMENT is the actual body of one entry from a live POST
/user/shipment/v2.1/list/incoming/active/1 call, captured 2026-08-26
against a real account (1 delivered parcel — no in-transit example was
available, so only the TT_DOR/"delivered" branch of dhl_canonical() is
exercised against real data; everything else falls back to "unknown" by
design, see the caveat in const.py).

    python3 -m pytest tests/test_dhl_normalize.py -q
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
    src = path.read_text()
    src = src.replace("from .const import", "from const import")
    src = src.replace("from .api_dhl import", "from api_dhl import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_dhl():
    sys.path.insert(0, str(_PKG_DIR))

    class _DUC:
        def __class_getitem__(cls, item):
            return cls

    _stub("homeassistant")
    _stub("homeassistant.config_entries", ConfigEntry=object)
    _stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC, UpdateFailed=Exception)

    _load_flat("const", _PKG_DIR / "const.py")
    _load_flat("api_dhl", _PKG_DIR / "api_dhl.py")
    return _load_flat("coordinator_dhl", _PKG_DIR / "coordinator_dhl.py")


_coord = _load_coordinator_dhl()

# Real POST /user/shipment/v2.1/list/incoming/active/1 entry, captured live 2026-08-26.
_REAL_SHIPMENT = {
    "shipmentNumber": "30413196282",
    "customTitle": None,
    "sender": "Amazon EU SARL",
    "receiver": None,
    "status": "TT_DOR",
    "packageType": "Courier",
    "parcelExpirationDate": None,
    "cod": {"packagePaymentStatus": None},
    "permissions": {
        "canArchiveShipment": True, "canRemoveShipment": True,
        "canRedirectShipment": False, "showResignedFromShipment": False,
        "showLostShipment": False, "showDisposedhipment": False,
        "canCreateReturn": True,
    },
    "menuTimelineLabel": {
        "status": "Delivered", "label": "ReceiptDate", "dateText": None,
        "dateUtc": "2026-08-26T09:54:29Z", "dateToUtc": None, "showHour": True,
    },
    "inAppPaymentStatus": None,
    "returnInfo": {"isReturn": False},
    "returnAuthorizationInfo": None,
    "isShippingCache": False,
    "hasActiveIntervention": False,
    "hasClosedIntervention": False,
    "isHeartActionShipment": False,
}


def test_normalize_parcel_maps_known_status():
    row = _coord.normalize_parcel(_REAL_SHIPMENT)
    assert row["number"] == "30413196282"
    assert row["sender"] == "Amazon EU SARL"
    assert row["status_raw"] == "TT_DOR"
    assert row["status"] == "Dostarczona"
    assert row["canonical"] == "delivered"
    assert row["active"] is False
    assert row["updated"] == "2026-08-26T09:54:29Z"
    assert row["package_type"] == "Courier"
    assert row["shared"] is False


def test_normalize_parcel_shared_flag():
    row = _coord.normalize_parcel(_REAL_SHIPMENT, shared=True)
    assert row["shared"] is True


def test_unknown_status_falls_back_to_raw_not_a_guess():
    const = sys.modules["const"]
    assert const.dhl_canonical("TT_SOMETHING_NEW") == "unknown"
    assert const.dhl_status_pl("TT_SOMETHING_NEW") == "TT_SOMETHING_NEW"
    assert const.dhl_is_active("TT_SOMETHING_NEW") is True


def test_prefix_has_no_plus_sign():
    """Confirmed live 2026-08-26: "+48" gets HTTP 422 "Prefix is incorrect",
    only bare "48" is accepted. Regression guard against reintroducing the
    "+" that cost the first live attempt."""
    src = (_PKG_DIR / "api_dhl.py").read_text()
    assert '"prefix": "48"' in src
    assert '"prefix": "+48"' not in src
