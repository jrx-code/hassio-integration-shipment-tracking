"""Session-keepalive tests for the DHL client — the cookie pair that carries
the session, and the jar rotation the coordinator persists.

Regression cover for the 2026-09-04 failure: the token minted by
/auth/refresh was never written back into the jar, so the access-token
cookie stayed the login-time one and the session died 30 minutes after the
SMS. The server named the cause itself, in a 401 to a dead jar:

    WWW-Authenticate: Bearer error="invalid_token",
      error_description="The token expired at '09/03/2026 09:30:14'"

matching the stored cookie's own exp to the second.

    python3 -m pytest tests/test_dhl_session.py -q
"""
import sys
import types
from pathlib import Path

import pytest

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"


def _load_api_dhl():
    sys.path.insert(0, str(_PKG_DIR))
    src = (_PKG_DIR / "api_dhl.py").read_text().replace("from .const import", "from const import")
    const_src = (_PKG_DIR / "const.py").read_text()
    const = types.ModuleType("const")
    sys.modules["const"] = const
    exec(compile(const_src, "const.py", "exec"), const.__dict__)
    mod = types.ModuleType("api_dhl")
    sys.modules["api_dhl"] = mod
    exec(compile(src, "api_dhl.py", "exec"), mod.__dict__)
    return mod


_api = _load_api_dhl()

# Shape taken from the live jars: header.payload in access-token (two
# segments), the 43-char HS256 signature alone in access-signature.
_HEAD = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
_PAYLOAD = "eyJzdWIiOiIxIiwiZXhwIjoxNzg4NDk0NjE0fQ"
_SIG = "Ql" + "T7oHctzmSD3T4aZxnD22uGrPdOxxxxxxxxxxxxxxxxx"[:41]
_TOKEN = f"{_HEAD}.{_PAYLOAD}.{_SIG}"


def _jar_dict(api):
    return {c["name"]: c["value"] for c in api.export_cookies()}


def test_minted_token_is_split_across_the_two_cookies():
    api = _api.DhlApi()
    api._adopt_access_token(_TOKEN)
    jar = _jar_dict(api)
    # NOT the whole JWT in access-token — that is what the server rejects.
    assert jar["access-token"] == f"{_HEAD}.{_PAYLOAD}"
    assert jar["access-signature"] == _SIG
    assert jar["access-token"].count(".") == 1


def test_adopting_replaces_the_login_time_pair_rather_than_duplicating():
    api = _api.DhlApi()
    api.import_cookies([
        {"name": "access-token", "value": "old.payload", "domain": "mojdhl.pl", "path": "/", "secure": True},
        {"name": "access-signature", "value": "oldsig", "domain": "mojdhl.pl", "path": "/", "secure": True},
        {"name": "TS012c8f70", "value": "keepme", "domain": "mojdhl.pl", "path": "/", "secure": True},
    ])
    api._adopt_access_token(_TOKEN)
    cookies = api.export_cookies()
    names = [c["name"] for c in cookies]
    assert names.count("access-token") == 1
    assert names.count("access-signature") == 1
    jar = _jar_dict(api)
    assert jar["access-token"] == f"{_HEAD}.{_PAYLOAD}"
    # The F5 cookie must survive — it is part of what the session rides on.
    assert jar["TS012c8f70"] == "keepme"


def test_jar_moves_after_adopting_so_the_coordinator_has_something_to_persist():
    """The coordinator only writes entry.data when export_cookies() differs
    from what is stored. Before the fix it never did — this asserts it does."""
    api = _api.DhlApi()
    api.import_cookies([
        {"name": "access-token", "value": "old.payload", "domain": "mojdhl.pl", "path": "/", "secure": True},
        {"name": "access-signature", "value": "oldsig", "domain": "mojdhl.pl", "path": "/", "secure": True},
    ])
    before = api.export_cookies()
    api._adopt_access_token(_TOKEN)
    assert api.export_cookies() != before


def test_non_jwt_is_refused_loudly():
    api = _api.DhlApi()
    with pytest.raises(_api.DhlError):
        api._adopt_access_token("not-a-jwt")
    with pytest.raises(_api.DhlError):
        api._adopt_access_token(f"{_HEAD}.{_PAYLOAD}")


def test_refresh_session_adopts_what_it_minted():
    api = _api.DhlApi()
    calls = []

    def _fake_do_raw(req):
        calls.append(req.full_url)
        return 200, {"token": _TOKEN}

    api._do_raw = _fake_do_raw
    assert api.refresh_session("dev-1", "Home Assistant") == _TOKEN
    assert _jar_dict(api)["access-token"] == f"{_HEAD}.{_PAYLOAD}"
    assert "deviceId=dev-1" in calls[0]


def test_refresh_session_401_still_raises_auth_error_before_touching_the_jar():
    api = _api.DhlApi()
    api._do_raw = lambda req: (401, {})
    with pytest.raises(_api.DhlAuthError):
        api.refresh_session("dev-1", "Home Assistant")
    assert "access-token" not in _jar_dict(api)


def test_constructor_does_not_build_an_ssl_context(monkeypatch):
    """DhlApi() runs on the event loop (config flow, coordinator); loading CAs
    there is what HA reports as a blocking call. The context must wait for the
    first request, which runs in an executor."""
    import http.client
    import ssl

    calls = []
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: calls.append("ssl"))
    monkeypatch.setattr(
        http.client, "_create_https_context", lambda *a, **k: calls.append("http")
    )
    _api.DhlApi()
    assert calls == []
