"""Request shapes of the InPost Mobile functions (docs/INPOST_MOBILE_API.md)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"
_PKG = "inpost_api_stub"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_COMPONENT)]
    sys.modules[_PKG] = pkg
for _name in ("api", "inpost_management"):
    if f"{_PKG}.{_name}" not in sys.modules:
        _spec = importlib.util.spec_from_file_location(f"{_PKG}.{_name}", _COMPONENT / f"{_name}.py")
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_spec.name] = _mod
        _spec.loader.exec_module(_mod)
m = sys.modules[f"{_PKG}.inpost_management"]


class FakeApi:
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def request(self, method, path, token, body=None, query=None):
        self.calls.append((method, path, body, query))
        return self.answers.get(path, {})


def test_every_query_and_action_is_buildable():
    api = FakeApi()
    full = {
        "shipment_number": "6200", "uuid": "u", "name": "n", "search": "Szczecin",
        "latitude": 53.4, "longitude": 14.5,
    }
    for what in m.QUERY_FIELDS:
        m.query(api, "Bearer t", what, dict(full))
    assert len(api.calls) == len(m.QUERY_FIELDS)
    assert all(c[0] == "GET" for c in api.calls)


def test_missing_fields_are_named():
    with pytest.raises(m.Missing) as err:
        m.query(FakeApi(), "t", "parcel", {})
    assert err.value.fields == ["shipment_number"]
    with pytest.raises(m.Missing):
        m.build_action("friend_invite", {"phone": "500"})


def test_points_by_position_and_by_text():
    api = FakeApi()
    m.query(api, "t", "points", {"latitude": 53.4, "longitude": 14.5, "max_distance": 2000})
    assert api.calls[-1][3]["relativePoint"] == "53.4,14.5"
    m.query(api, "t", "points", {"search": "Tanowo"})
    assert api.calls[-1][3]["query"] == "Tanowo"
    with pytest.raises(m.Missing):
        m.query(api, "t", "points", {})


def test_path_segments_are_escaped():
    api = FakeApi()
    m.query(api, "t", "parcel", {"shipment_number": "../v2/friends"})
    assert api.calls[-1][1] == "/v4/parcels/tracked/..%2Fv2%2Ffriends"


def test_track_share_friend_bodies():
    assert m.build_action("track", {"shipment_number": "1"}) == (
        "POST", "/v4/parcels/observed", {"shipmentNumber": "1", "parcelType": "TRACKED"})
    assert m.build_action("untrack", {"shipment_number": "1"})[:2] == ("DELETE", "/v4/parcels/observed/1")
    assert m.build_action("easy_access", {"shipment_number": "1"})[2]["propertyKey"] == "EASY_ACCESS_ZONE_PREFERRED"
    assert m.build_action("share", {"shipment_numbers": ["1", "2"], "friend_uuids": ["f"]})[2] == {
        "parcels": [{"shipmentNumber": "1", "friendUuids": ["f"]}, {"shipmentNumber": "2", "friendUuids": ["f"]}]}
    assert m.build_action("friend_invite", {"phone": "500 600 700", "name": "A"})[2] == {
        "phoneNumber": {"prefix": "+48", "value": "500600700"}, "name": "A"}
    assert m.build_action("friend_rename", {"uuid": "u", "name": "B"})[:2] == ("PATCH", "/v2/friends/u")
    assert m.build_action("friend_remove", {"uuid": "u"})[:2] == ("DELETE", "/v2/friends/u")
    assert m.build_action("invitation_accept", {"invitation_code": "c", "name": "N"})[2] == {
        "invitationCode": "c", "friendName": "N"}
    assert m.build_action("notifications_read", {"notification_ids": ["a"]})[2] == {"notificationIds": ["a"]}
    assert m.build_action("notifications_read_all", {"date": "2026-11-16T00:00:00Z"})[2] == {"date": "2026-11-16T00:00:00Z"}


def test_return_tickets():
    base = {"organization_uuid": "o", "reason_uuid": "r", "parcel_size": "A",
            "sender_name": "J", "sender_email": "j@example.com"}
    method, path, body = m.build_action("return_parcel", {**base, "shipment_number": "9"})
    assert (method, path, body["shipmentNumber"]) == ("POST", "/v1/returns/parcels/tickets", "9")
    method, path, body = m.build_action("return_organization", {**base, "order_number": "ZAM1"})
    assert path == "/v1/returns/tickets" and "shipmentNumber" not in body


def test_send_parcel_body():
    p = {"parcel_size": "A", "delivery_point": "TAN01M", "receiver_first_name": "A",
         "receiver_last_name": "B", "receiver_email": "a@example.com", "receiver_phone": "500600700",
         "sender_first_name": "C", "sender_last_name": "D", "sender_email": "c@example.com",
         "sender_street": "Ulica", "sender_building": "1", "sender_post_code": "72-004", "sender_city": "Tanowo"}
    method, path, body = m.build_action("send_parcel", p)
    assert (method, path) == ("POST", "/v4/parcels")
    assert body["deliveryPoint"] == {"boxMachineName": "TAN01M"}
    assert body["receiver"]["phoneNumber"] == {"prefix": "+48", "value": "500600700"}
    assert body["sender"]["address"]["postCode"] == "72-004"


def test_collect_open_validates_first_then_opens():
    api = FakeApi({"/v2/collect/validate": {"sessionUuid": "S1", "sessionExpirationTime": 5}})
    out = m.locker(api, "t", "collect", "open", {
        "shipment_number": "6200", "open_code": "123456", "phone": "500600700",
        "latitude": 53.4, "longitude": 14.5})
    assert [c[1] for c in api.calls] == ["/v2/collect/validate", "/v1/collect/compartment/open"]
    assert api.calls[0][2]["parcel"] == {
        "shipmentNumber": "6200", "openCode": "123456",
        "receiverPhoneNumber": {"prefix": "+48", "value": "500600700"}}
    assert api.calls[0][2]["geoPoint"]["latitude"] == 53.4
    assert api.calls[1][2] == {"sessionUuid": "S1"}
    assert out["session"] == "S1"


def test_locker_paths_per_flow():
    for flow, terminate in (("collect", "/v1/collect/terminate"), ("send", "/v1/send/cancel"), ("return", "/v1/return/cancel")):
        assert m.build_locker(flow, "terminate", {"session": "S"})[1] == terminate
        assert m.build_locker(flow, "closed", {"session": "S"})[1] == f"/v1/{flow}/compartment/closed"
        assert m.build_locker(flow, "reopen", {"session": "S"})[1] == f"/v1/{flow}/compartment/reopen"
        assert m.build_locker(flow, "confirm", {"session": "S"})[1] == f"/v1/{flow}/confirm"
    assert m.build_locker("collect", "status", {"session": "S", "expected": "OPENED"})[2] == {
        "sessionUuid": "S", "expectedStatus": "OPENED"}
    assert m.build_locker("return", "open", {"session": "S", "parcel_size": "A"})[2] == {
        "sessionUuid": "S", "parcelSize": "A"}
    assert m.build_locker("collect", "claim", {"session": "S", "shipment_numbers": ["1"]})[2] == {
        "sessionUuid": "S", "shipmentNumbers": ["1"]}


def test_locker_needs_position_and_session():
    with pytest.raises(m.Missing) as err:
        m.build_locker("collect", "validate", {"shipment_number": "1", "open_code": "1", "phone": "5"})
    assert err.value.fields == ["latitude", "longitude"]
    with pytest.raises(m.Missing):
        m.build_locker("collect", "closed", {})
    with pytest.raises(m.Missing):
        m.build_locker("send", "validate", {"shipment_number": "1", "latitude": 1, "longitude": 1})
