"""Unit tests for the sharing calls in the InPost API client.

    python3 -m pytest tests/test_api_share.py -q

The request shapes here match the live API:
`GET /v2/friends` (NO trailing slash — with one InPost answers 404) and
`POST /v4/parcels/shared` with {"parcels":[{"shipmentNumber","friendUuids"}]}.
"""
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
_spec = importlib.util.spec_from_file_location(f"{_PKG}.api", _COMPONENT / "api.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
InPostApi = _mod.InPostApi
InPostError = _mod.InPostError
categorize_parcels = _mod.categorize_parcels

PEER_B_UUID = "00000000-0000-4000-8000-000555000001"


class _Api(InPostApi):
    """Client with the HTTP layer replaced by canned responses."""

    def __init__(self, get=None, post=None):
        super().__init__("https://example.invalid", "test-agent")
        self._get_resp = get or (200, {}, {})
        self._post_resp = post or (200, {}, {})
        self.calls = []

    def _get(self, path, token, etag=None):
        self.calls.append(("GET", path, None))
        return self._get_resp

    def _post(self, path, body, token=None):
        self.calls.append(("POST", path, body))
        return self._post_resp


FRIENDS_V2 = {
    "friends": [
        {
            "uuid": PEER_B_UUID,
            "phoneNumber": {"prefix": "+48", "value": "555000002"},
            "name": "Peer B",
        }
    ],
    "invitations": [],
}


def test_get_friends_hits_v2_without_trailing_slash():
    api = _Api(get=(200, {}, FRIENDS_V2))
    friends = api.get_friends("tok")
    assert api.calls == [("GET", "/v2/friends", None)]
    assert friends == [
        {
            "uuid": PEER_B_UUID,
            "name": "Peer B",
            "prefix": "+48",
            "phone": "555000002",
        }
    ]


def test_get_friends_raises_on_error():
    api = _Api(get=(404, {}, {}))
    with pytest.raises(InPostError):
        api.get_friends("tok")


def test_share_parcels_body_shape():
    api = _Api(post=(200, {}, {}))
    api.share_parcels("tok", ["111", "222"], [PEER_B_UUID])
    method, path, body = api.calls[0]
    assert (method, path) == ("POST", "/v4/parcels/shared")
    assert body == {
        "parcels": [
            {"shipmentNumber": "111", "friendUuids": [PEER_B_UUID]},
            {"shipmentNumber": "222", "friendUuids": [PEER_B_UUID]},
        ]
    }


def test_share_parcels_noop_without_targets():
    api = _Api()
    api.share_parcels("tok", [], [PEER_B_UUID])
    api.share_parcels("tok", ["111"], [])
    assert api.calls == []


def test_share_parcels_raises_on_error():
    api = _Api(post=(400, {}, {"error": "badRequest"}))
    with pytest.raises(InPostError):
        api.share_parcels("tok", ["111"], [PEER_B_UUID])


def test_map_parcel_exposes_sharing_state():
    raw = {
        "shipmentNumber": "111",
        "status": "READY_TO_PICKUP",
        "openCode": "107960",
        "ownershipStatus": "OWN",
        "operations": {"canShareParcel": True, "canShareOpenCode": False},
        "sharedTo": [
            {
                "uuid": PEER_B_UUID,
                "name": "Peer B",
                "phoneNumber": {"prefix": "+48", "value": "555000002"},
            }
        ],
    }
    p = categorize_parcels([raw])["ready"][0]
    assert p["ownership"] == "OWN"
    assert p["can_share"] is True
    assert p["shared_to"] == [
        {"uuid": PEER_B_UUID, "name": "Peer B", "phone": "555000002"}
    ]


def test_map_parcel_defaults_when_sharing_fields_absent():
    p = categorize_parcels([{"shipmentNumber": "111", "status": "DELIVERED"}])["archived"][0]
    assert p["ownership"] is None
    assert p["shared_to"] == []
    assert p["can_share"] is False


def test_get_parcels_dedupes_overlapping_pages():
    """ETag pages can overlap; a repeat must not inflate counts (seen live)."""
    pages = [
        (200, {"Etag": '"p1"'}, {"more": True, "parcels": [
            {"shipmentNumber": "111", "status": "SENT_FROM_SOURCE_BRANCH"},
            {"shipmentNumber": "222", "status": "CONFIRMED"},
        ]}),
        (200, {"Etag": '"p2"'}, {"more": False, "parcels": [
            {"shipmentNumber": "222", "status": "OUT_FOR_DELIVERY"},
            {"shipmentNumber": "333", "status": "READY_TO_PICKUP"},
        ]}),
    ]

    class _Paged(_Api):
        def _get(self, path, token, etag=None):
            return pages.pop(0)

    out = _Paged().get_parcels("tok")
    assert [p["shipmentNumber"] for p in out] == ["111", "222", "333"]
    # later page wins: the repeat carries the fresher status
    assert out[1]["status"] == "OUT_FOR_DELIVERY"


def test_map_parcel_extracts_owner_phone_from_receiver():
    raw = {
        "shipmentNumber": "111",
        "status": "READY_TO_PICKUP",
        "ownershipStatus": "FRIEND",
        "receiver": {"phoneNumber": {"prefix": "+48", "value": "555000001"}},
    }
    p = categorize_parcels([raw])["ready"][0]
    assert p["owner_phone"] == "555000001"
