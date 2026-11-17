"""DPD parcel management calls used by the App Hub DPD app.

Paths and bodies come from DPD Mobile 2.10.18 (docs/DPD_MOBILE_API.md); the
read calls were checked live on 2026-11-15. The validation token travels in
the allowed-operations response header and goes back on every write.

    python3 -m pytest tests/test_dpd_management.py -q
"""
import sys
import types
from pathlib import Path

import pytest

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _load_api_dpd():
    sys.path.insert(0, str(_PKG_DIR))
    src = (_PKG_DIR / "api_dpd.py").read_text().replace("from .const import", "from const import")
    const = types.ModuleType("const")
    sys.modules["const"] = const
    exec(compile((_PKG_DIR / "const.py").read_text(), "const.py", "exec"), const.__dict__)
    mod = types.ModuleType("api_dpd")
    sys.modules["api_dpd"] = mod
    exec(compile(src, "api_dpd.py", "exec"), mod.__dict__)
    return mod


_api = _load_api_dpd()


class _Recorder(_api.DpdApi):
    def __init__(self, answers, headers=None):
        super().__init__()
        self.answers = list(answers)
        self.calls = []
        self._headers = headers or {}

    def _req(self, method, url, **kw):
        self.calls.append((method, url, kw))
        self.last_headers = self._headers
        return self.answers.pop(0)


_OPS = {"enabledOperations": [{"code": "DIRECT_TO_PARCEL_SHOP"}, {"code": "REFUSE_PARCEL"}]}


def test_allowed_operations_returns_codes_and_header_token():
    api = _Recorder([(200, _OPS)], headers={"X-Validation-Token": "vt"})
    codes, token = api.allowed_operations("acc", "WB1")
    assert codes == ["DIRECT_TO_PARCEL_SHOP", "REFUSE_PARCEL"]
    assert token == "vt"
    method, url, kw = api.calls[0]
    assert method == "GET" and url.endswith("/parcels/WB1/allowed-operations?userContext=RECEIVER")
    assert kw["token"] == "acc"


def test_writes_carry_the_validation_token():
    api = _Recorder([(204, {})])
    api.change_delivery_date("acc", "WB1", "vt", "2026-11-17")
    method, url, kw = api.calls[0]
    assert method == "POST" and url.endswith("/parcels/WB1/delivery-dates")
    assert kw["json_body"] == {"deliveryDate": {"date": "2026-11-17"}}
    assert kw["extra_headers"]["X-Validation-Token"] == "vt"


def test_redirect_sends_the_point_and_the_requirements():
    api = _Recorder([(204, {})])
    req = {"rkRegion": "A1209", "udRegion": None, "depotNumber": "1308"}
    api.redirect_to_point("acc", "WB1", "vt", "PL81900", req)
    _m, url, kw = api.calls[0]
    assert url.endswith("/parcels/WB1/parcel-shop-redirects")
    assert kw["json_body"] == {"pudoId": "PL81900", "rkRegion": "A1209", "udRegion": None, "depotNumber": "1308"}


def test_address_change_and_refusal_bodies():
    api = _Recorder([(204, {}), (204, {})])
    api.change_delivery_address("acc", "WB1", "vt", "Szczecińska 19", "Tanowo", "72-004", "brama")
    api.refuse_parcel("acc", "WB1", "vt", "not ordered")
    assert api.calls[0][2]["json_body"] == {
        "address": "Szczecińska 19", "city": "Tanowo", "postalCode": "72-004", "deliveryNote": "brama"
    }
    assert api.calls[1][2]["json_body"] == {"refuseReason": "not ordered"}


def test_pin_is_none_before_the_parcel_waits_somewhere():
    assert _Recorder([(404, {})]).get_pin("acc", "WB1") is None
    pin = _Recorder([(200, {"shipmentPin": "123456", "pinExpiryDate": "2026-11-20"})]).get_pin("acc", "WB1")
    assert pin == {"pin": "123456", "expires": "2026-11-20"}


def test_nearest_points_are_flattened():
    raw = {"results": [{
        "pudoId": "PL81900", "name": "Automat DPD Pickup", "pudoTypeGroup": "LOCKER",
        "address": {"address": "Szczecińska 19", "postalCode": "72004", "city": "Tanowo"},
        "latitude": 53.5, "longitude": 14.4, "services": ["PINPAD", "PUDO_TO_SEND"],
        "depotNumber": "1308", "rkRegion": "A1209",
    }]}
    pts = _Recorder([(200, raw)]).nearest_points("acc", 53.5, 14.4, 3, 3)
    assert pts == [{
        "id": "PL81900", "name": "Automat DPD Pickup", "kind": "LOCKER",
        "address": "Szczecińska 19, 72004, Tanowo", "lat": 53.5, "lon": 14.4, "hint": None,
        "pinpad": True, "send": True, "depot": "1308", "rk_region": "A1209",
    }]


def test_rejections_raise_typed_errors():
    with pytest.raises(_api.DpdAuthError):
        _Recorder([(401, {})]).allowed_operations("acc", "WB1")
    with pytest.raises(_api.DpdError):
        _Recorder([(400, {"errors": [{"subcode": "X"}]})]).refuse_parcel("acc", "WB1", "vt", "r")
