"""Unit tests for the ORLEN Paczka account carrier — status map + normalize.

Pure functions, no Home Assistant. The account shipments list was empty when
the API was reverse-engineered (2026-10-01), so the per-parcel field names are
best-effort: these tests pin the numeric status map (official spec v1.26.005,
7.3) and the defensive multi-key normalize_parcel(). Update the field fixtures
once a real parcel is captured.

    python3 -m pytest tests/test_orlen_account_normalize.py -q
"""
import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _load_flat(modname: str, path: Path):
    src = path.read_text().replace(
        "from .carriers_orlen_account import", "from carriers_orlen_account import"
    )
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


sys.path.insert(0, str(_PKG_DIR))
_cc = _load_flat("carriers_orlen_account", _PKG_DIR / "carriers_orlen_account.py")
_api = _load_flat("api_orlen_account", _PKG_DIR / "api_orlen_account.py")


def test_numeric_codes_map_to_expected_buckets():
    assert _cc.orlen_account_canonical("200") == "created"
    assert _cc.orlen_account_canonical("300") == "in_transit"
    assert _cc.orlen_account_canonical("610") == "out_for_delivery"
    assert _cc.orlen_account_canonical("620") == "ready_for_pickup"
    assert _cc.orlen_account_canonical("1000") == "delivered"
    assert _cc.orlen_account_canonical("750") == "returned"
    assert _cc.orlen_account_canonical("999") == "exception"


def test_int_code_matches_string_code():
    assert _cc.orlen_account_canonical(620) == _cc.orlen_account_canonical("620")


def test_unknown_code_falls_back_to_text_keywords():
    # No code, only text -> keyword scan keeps it meaningful, not "unknown".
    assert _cc.orlen_account_canonical(None, "Gotowa do odbioru w punkcie") == "ready_for_pickup"
    assert _cc.orlen_account_canonical(None, "Przesyłka w sortowni centralnej") == "in_transit"
    assert _cc.orlen_account_canonical("77777", "Zwrot do nadawcy") == "returned"


def test_empty_status_is_unknown():
    assert _cc.orlen_account_canonical(None, "") == "unknown"
    assert _cc.orlen_account_canonical("", "") == "unknown"


def test_is_active_terminal_states():
    assert _cc.orlen_account_is_active("300") is True          # in transit
    assert _cc.orlen_account_is_active("620") is True          # ready for pickup
    assert _cc.orlen_account_is_active("1000") is False        # delivered
    assert _cc.orlen_account_is_active("750") is False         # returned


def test_status_pl_prefers_carrier_text():
    assert _cc.orlen_account_status_pl("300", "Niestandardowy opis") == "Niestandardowy opis"
    # No text -> bucket label.
    assert _cc.orlen_account_status_pl("620", "") == "Gotowa do odbioru"


def test_normalize_reads_several_key_spellings():
    # camelCase spelling
    row = _api.normalize_parcel(
        {"shipmentNumber": "2100064143434", "statusId": "620", "statusName": "Gotowa do odbioru", "senderName": "Allegro"}
    )
    assert row["number"] == "2100064143434"
    assert row["canonical"] == "ready_for_pickup"
    assert row["active"] is True
    assert row["sender"] == "Allegro"
    # lowercase spelling (as the customer record used)
    row2 = _api.normalize_parcel(
        {"packnumber": "2100000000001", "statusid": "1000", "statusname": "Odebrana przez klienta"}
    )
    assert row2["number"] == "2100000000001"
    assert row2["canonical"] == "delivered"
    assert row2["active"] is False


def test_normalize_survives_missing_fields():
    row = _api.normalize_parcel({})
    assert row["number"] is None
    assert row["canonical"] == "unknown"
    assert row["active"] is True  # unknown is not terminal


# --- app client secret: entered by the user, never shipped -----------------

def test_no_secret_in_package():
    assert not hasattr(_cc, "ORLEN_CLIENT_SECRET")


def test_missing_secret_raises_before_any_request(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("token request sent without a secret")

    monkeypatch.setattr(_api.urllib.request, "urlopen", boom)
    api = _api.OrlenAccountApi("  ")
    try:
        api._token_value()
    except _api.OrlenAccountClientSecretError:
        pass
    else:
        raise AssertionError("expected OrlenAccountClientSecretError")


def test_rejected_secret_maps_to_client_secret_error(monkeypatch):
    import io
    import urllib.error

    def unauthorized(req, timeout=30):
        assert b"client_secret=wrong" in req.data
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"invalid_client"}')
        )

    monkeypatch.setattr(_api.urllib.request, "urlopen", unauthorized)
    try:
        _api.OrlenAccountApi("wrong")._token_value()
    except _api.OrlenAccountClientSecretError:
        pass
    else:
        raise AssertionError("expected OrlenAccountClientSecretError")
