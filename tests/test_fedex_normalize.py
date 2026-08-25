"""Unit tests for FedEx status mapping + normalize_parcel() — pure, no HA.

The "IN"/"Initiated" case uses the actual FedEx sandbox response captured
live 2026-08-25 (mock waybill 449044304137821, FedEx's own published test
number — response carried a "VIRTUAL.RESPONSE" alert, i.e. their canned
sandbox reply). Other derived codes (PU/IT/OD/DL/DE/CA) are FedEx's
long-documented derived-status table, NOT individually verified live this
session — see the comment in const.py.

    python3 -m pytest tests/test_fedex_normalize.py -q
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
    src = src.replace("from .api_fedex import", "from api_fedex import")
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


def _load_coordinator_fedex():
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
    _load_flat("api_fedex", _PKG_DIR / "api_fedex.py")
    return _load_flat("coordinator_fedex", _PKG_DIR / "coordinator_fedex.py")


_coord = _load_coordinator_fedex()
_c = sys.modules["const"]

# Trimmed to the fields normalize_parcel() actually reads, from the real
# sandbox response body (POST /track/v1/trackingnumbers, mock waybill
# 449044304137821, captured live 2026-08-25).
_SANDBOX_RESULT = {
    "trackingNumber": "449044304137821",
    "trackResults": [
        {
            "trackingNumberInfo": {"trackingNumber": "449044304137821"},
            "latestStatusDetail": {
                "code": "OC",
                "derivedCode": "IN",
                "statusByLocale": "Initiated",
                "description": "Shipment information sent to FedEx",
            },
            "shipperInformation": {
                "address": {"city": "JEFFERSONVILLE", "countryCode": "US"}
            },
            "recipientInformation": {"address": {"city": "Miami", "countryCode": "US"}},
            "serviceDetail": {"type": "GROUND_HOME_DELIVERY", "description": "FedEx Home Delivery"},
            "scanEvents": [
                {
                    "date": "2013-12-30T13:24:00-05:00",
                    "eventDescription": "Shipment information sent to FedEx",
                    "scanLocation": {"city": ""},
                }
            ],
        }
    ],
}


def test_derived_codes_verified_and_documented():
    assert _c.fedex_canonical("IN") == "created"  # verified live
    assert _c.fedex_canonical("PU") == "in_transport"
    assert _c.fedex_canonical("IT") == "in_transport"
    assert _c.fedex_canonical("OD") == "handed_out_for_delivery"
    assert _c.fedex_canonical("DL") == "delivered"
    assert _c.fedex_canonical("DE") == "exception"
    assert _c.fedex_canonical("CA") == "cancelled"


def test_unknown_code_falls_back_to_text_keyword_scan():
    assert _c.fedex_canonical("ZZ", "Out for delivery") == "handed_out_for_delivery"
    assert _c.fedex_canonical("ZZ", "Package delivered") == "delivered"
    assert _c.fedex_canonical("", "") == "unknown"


def test_is_active_terminal_buckets():
    assert _c.fedex_is_active("IN")
    assert _c.fedex_is_active("IT")
    assert not _c.fedex_is_active("DL")
    assert not _c.fedex_is_active("CA")


def test_normalize_parcel_from_real_sandbox_response():
    row = _coord.normalize_parcel(_SANDBOX_RESULT)
    assert row["number"] == "449044304137821"
    assert row["derived_code"] == "IN"
    assert row["canonical"] == "created"
    assert row["active"] is True
    assert row["sender_city"] == "JEFFERSONVILLE"
    assert row["service"] == "FedEx Home Delivery"
    assert len(row["history"]) == 1


def test_normalize_parcel_missing_track_results_returns_none():
    assert _coord.normalize_parcel({"trackingNumber": "000", "trackResults": []}) is None
