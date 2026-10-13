"""InPost OAuth2 + PKCE sign-in (since InPost retired the SMS login, 2026-10-12).

    python3 -m pytest tests/test_inpost_oauth.py -q

Live facts these tests pin (checked 2026-10-13): the legacy `/v1/account`,
`/v1/account/verification` and `/v1/authenticate` answer 404; the token endpoint
`POST /global/oauth2/token` on the API host answers 400 `invalid_grant` to a bad
refresh token; `/v4/parcels/tracked` is still the data endpoint.
"""
import base64
import hashlib
import importlib.util
import json
import sys
import types
import urllib.parse
from pathlib import Path

import pytest

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"
_PKG = "inpost_api_stub"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_COMPONENT)]
    sys.modules[_PKG] = pkg
_spec = importlib.util.spec_from_file_location(f"{_PKG}.api", _COMPONENT / "api.py")
api = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = api
_spec.loader.exec_module(api)


def _jwt(claims: dict) -> str:
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


class _Api(api.InPostApi):
    """Token endpoint replaced by a queue of canned (status, body) answers."""

    def __init__(self, *answers):
        super().__init__("https://example.invalid", "test-agent")
        self.answers = list(answers)
        self.forms = []

    def _post_form(self, path, form):
        assert path == api.OAUTH_TOKEN_PATH
        self.forms.append(dict(form))
        st, body = self.answers.pop(0)
        return st, {}, body


def _ok(access="a1", refresh="r1", expires_in=7200):
    return 200, {"access_token": access, "refresh_token": refresh, "expires_in": expires_in}


# ---------------- PKCE login ----------------
def test_authorize_url_carries_pkce_s256_challenge_of_the_verifier():
    login = api.PkceLogin()
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(login.url).query)
    assert login.url.startswith(api.OAUTH_AUTHORIZE_URL + "?")
    assert q["client_id"] == ["inpost-mobile"]
    assert q["redirect_uri"] == [api.OAUTH_REDIRECT_URI]
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(login.verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert q["code_challenge"] == [expected]
    assert q["state"] == [login.state]
    assert q["prompt"] == ["login"]


def test_extract_code_from_callback_url():
    login = api.PkceLogin()
    url = f"{api.OAUTH_REDIRECT_URI}?code=abc123&state={login.state}"
    assert login.extract_code(f"  {url}\n") == "abc123"


def test_extract_code_without_state_is_accepted():
    assert api.PkceLogin().extract_code(f"{api.OAUTH_REDIRECT_URI}?code=xyz") == "xyz"


@pytest.mark.parametrize(
    ("pasted", "reason"),
    [
        ("123 456", "sms"),
        ("https://account.inpost-group.com/callback", "no_code"),
        ("https://account.inpost-group.com/callback?code=", "no_code"),
        ("https://account.inpost-group.com/callback?code=c&state=other", "state"),
    ],
)
def test_extract_code_rejects(pasted, reason):
    with pytest.raises(ValueError, match=reason):
        api.PkceLogin().extract_code(pasted)


# ---------------- token endpoint ----------------
def test_exchange_code_posts_authorization_code_grant_with_verifier():
    client = _Api(_ok("acc", "ref", 7200))
    tokens = client.exchange_code("the-code", "the-verifier")
    assert (tokens.access, tokens.refresh) == ("acc", "ref")
    assert client.forms == [{
        "client_id": "inpost-mobile",
        "grant_type": "authorization_code",
        "redirect_uri": api.OAUTH_REDIRECT_URI,
        "code_verifier": "the-verifier",
        "code": "the-code",
    }]


def test_refresh_posts_refresh_token_grant():
    client = _Api(_ok())
    client.refresh("old-refresh")
    assert client.forms[0] == {
        "client_id": "inpost-mobile",
        "grant_type": "refresh_token",
        "refresh_token": "old-refresh",
    }


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_rejected_grant_means_reauth(status):
    client = _Api((status, {"error": "invalid_grant"}))
    with pytest.raises(api.ReauthRequired):
        client.refresh("dead")


def test_server_error_is_not_reauth():
    client = _Api((503, {"raw": "maintenance"}))
    with pytest.raises(api.InPostError):
        client.refresh("r")


def test_answer_without_tokens_means_reauth():
    client = _Api((200, {"access_token": "a"}))
    with pytest.raises(api.ReauthRequired):
        client.refresh("r")


# ---------------- session ----------------
def test_session_reuses_access_token_until_shortly_before_expiry(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api.time, "time", lambda: now[0])
    client = _Api(_ok("a1", "r1", 7200), _ok("a2", "r1", 7200))
    session = api.InPostSession(client, "r1")
    assert session.authorization() == "Bearer a1"
    now[0] += 7200 - api.EXPIRY_MARGIN - 1
    assert session.authorization() == "Bearer a1"
    assert len(client.forms) == 1
    now[0] += 2
    assert session.authorization() == "Bearer a2"
    assert len(client.forms) == 2
    assert session.rotated is False


def test_session_tracks_rotated_refresh_token():
    client = _Api(_ok("a1", "r2"), _ok("a2", "r3"))
    session = api.InPostSession(client, "r1")
    session.authorization()
    assert (session.refresh_token, session.rotated) == ("r2", True)
    session.authorization(force=True)
    assert client.forms[1]["refresh_token"] == "r2"
    assert session.refresh_token == "r3"


def test_session_refresh_failure_propagates_reauth():
    session = api.InPostSession(_Api((400, {"error": "invalid_grant"})), "r1")
    with pytest.raises(api.ReauthRequired):
        session.authorization()


def test_session_adopts_tokens_from_the_flow(monkeypatch):
    monkeypatch.setattr(api.time, "time", lambda: 0.0)
    client = _Api()
    session = api.InPostSession(client, "")
    session.adopt(api.Tokens("acc", "ref", 3600))
    assert session.authorization() == "Bearer acc"
    assert client.forms == []


# ---------------- token claims ----------------
@pytest.mark.parametrize(
    "claims",
    [
        {"phone": "555000001"},
        {"phone": "+48555000001"},
        {"phone_number": "48555000001"},
        {"phoneNumber": {"prefix": "+48", "value": "555000001"}},
    ],
)
def test_token_phone_reads_known_claim_shapes(claims):
    assert api.token_phone(_jwt(claims)) == "555000001"
    assert api.token_phone("Bearer " + _jwt(claims)) == "555000001"


@pytest.mark.parametrize("token", [None, "", "not-a-jwt", _jwt({"sub": "x"})])
def test_token_phone_none_when_missing(token):
    assert api.token_phone(token) is None
