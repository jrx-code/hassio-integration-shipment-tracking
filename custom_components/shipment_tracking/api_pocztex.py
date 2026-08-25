"""Pocztex Mobile API client (Keycloak OAuth2 authorization_code + PKCE).

Reverse-engineered from the observed protocol (verified live 2026-08-25
against a real account): ``idm.pocztex.pl`` realm ``ppsa`` (Keycloak) for
auth, ``aplikacja.pocztex.pl/api/customer/tracking`` for the recipient
parcel list. Direct password grant is disabled for this client
(``unauthorized_client: Client not allowed for direct access grants`` —
confirmed live) and ``offline_access`` scope is rejected
(``invalid_scope`` — confirmed live), so this drives the same
authorization_code+PKCE dance a browser would: GET the Keycloak login page,
POST credentials to its form action, capture the code from the 302
redirect's fragment, exchange it for tokens.

The refresh token's own idle timeout is short (``refresh_expires_in``
observed as 1800s = 30 min) — but each refresh call resets that timer, so
polling faster than ~25 min (this integration's default is 15 min) keeps
the session alive indefinitely without re-entering the password. The token
itself is NOT single-use (verified live: the same refresh_token succeeded
on three separate calls), so — like DPD — the coordinator doesn't need to
persist the rotated one each poll. If HA is down longer than the idle
timeout, refresh fails and the entry needs reauth (password re-entry —
there's no SMS-resend equivalent here).

stdlib urllib only (blocking — callers run it in an executor). No
third-party OAuth/OIDC library, no code copied.
"""
from __future__ import annotations

import base64
import hashlib
import html
import http.cookiejar
import json
import re
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .const import (
    POCZTEX_APP_URL,
    POCZTEX_CLIENT_ID,
    POCZTEX_IDM_URL,
    POCZTEX_REALM,
    POCZTEX_REDIRECT_URI,
    POCZTEX_TRACKING_URL,
)

_ACTION_RE = re.compile(r'action="([^"]*login-actions/authenticate[^"]*)"')


class PocztexError(Exception):
    """Any Pocztex API failure."""


class PocztexAuthError(PocztexError):
    """Login/refresh rejected — user must re-authenticate with a password."""


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class PocztexApi:
    """Blocking Keycloak client. No per-request session state is kept here —
    each call builds its own cookie jar, matching the DPD/InPost clients'
    "mint fresh, don't hold state" style."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None

    def _opener(self, jar: http.cookiejar.CookieJar) -> urllib.request.OpenerDirector:
        """An opener that does NOT auto-follow redirects — the Keycloak login
        POST's 302 carries the authorization code in its Location header
        (fragment-mode), which we need to read ourselves, not chase."""
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        no_redirect = type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {
            "redirect_request": lambda self, *a, **kw: None
        })
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=self._ctx),
            no_redirect(),
        )

    def login(self, email: str, password: str) -> tuple[str, str]:
        """Full authorization_code+PKCE login. Returns (access_token,
        refresh_token). Raises PocztexAuthError on bad credentials."""
        jar = http.cookiejar.CookieJar()
        opener = self._opener(jar)
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        nonce = secrets.token_urlsafe(16)

        auth_url = (
            f"{POCZTEX_IDM_URL}/realms/{POCZTEX_REALM}/protocol/openid-connect/auth?"
            + urllib.parse.urlencode(
                {
                    "client_id": POCZTEX_CLIENT_ID,
                    "redirect_uri": POCZTEX_REDIRECT_URI,
                    "state": state,
                    "response_mode": "fragment",
                    "response_type": "code",
                    "scope": "openid",
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        try:
            with opener.open(auth_url, timeout=25) as r:
                page = r.read().decode()
        except urllib.error.HTTPError as e:
            raise PocztexError(f"auth page fetch failed: HTTP {e.code}") from e

        m = _ACTION_RE.search(page)
        if not m:
            raise PocztexError("login form action not found in Keycloak page")
        action = html.unescape(m.group(1))

        form = urllib.parse.urlencode(
            {"username": email, "password": password, "credentialId": ""}
        ).encode()
        req = urllib.request.Request(
            action,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            opener.open(req, timeout=25)
            # A successful login always 302s (caught as URLError by the
            # no-redirect handler below); reaching here means no redirect
            # happened, i.e. the credentials were rejected and Keycloak
            # re-rendered the login form with an error instead.
            raise PocztexAuthError("login rejected (no redirect — bad credentials)")
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303):
                raise PocztexError(f"login POST failed: HTTP {e.code}") from e
            location = e.headers.get("Location", "")

        code_match = re.search(r"[#&]code=([^&]+)", location)
        if not code_match:
            if "error=" in location:
                err = re.search(r"error_description=([^&]+)", location)
                msg = urllib.parse.unquote_plus(err.group(1)) if err else location
                raise PocztexAuthError(f"login rejected: {msg}")
            raise PocztexError(f"no code in redirect: {location}")
        code = urllib.parse.unquote(code_match.group(1))

        return self._exchange(code=code, code_verifier=verifier)

    def _exchange(
        self, *, code: str | None = None, refresh_token: str | None = None,
        code_verifier: str | None = None,
    ) -> tuple[str, str]:
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        if code is not None:
            form = {
                "grant_type": "authorization_code",
                "client_id": POCZTEX_CLIENT_ID,
                "code": code,
                "redirect_uri": POCZTEX_REDIRECT_URI,
                "code_verifier": code_verifier,
            }
        else:
            form = {
                "grant_type": "refresh_token",
                "client_id": POCZTEX_CLIENT_ID,
                "refresh_token": refresh_token,
            }
        req = urllib.request.Request(
            f"{POCZTEX_IDM_URL}/realms/{POCZTEX_REALM}/protocol/openid-connect/token",
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code in (400, 401):
                raise PocztexAuthError(f"token exchange rejected: {body}") from e
            raise PocztexError(f"token exchange failed: HTTP {e.code} {body}") from e
        if not (d.get("access_token") and d.get("refresh_token")):
            raise PocztexError(f"token response missing tokens: {d}")
        return d["access_token"], d["refresh_token"]

    def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Mint a new access token. Returns (access_token, refresh_token) —
        Keycloak issues a new refresh_token each call, but the old one keeps
        working too (verified live), so callers may discard it, same as
        DPD's client."""
        return self._exchange(refresh_token=refresh_token)

    def get_parcels(self, access_token: str) -> list[dict]:
        req = urllib.request.Request(
            POCZTEX_TRACKING_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                # Required — omitting it gets a 400, confirmed live.
                "language": "PL",
            },
            method="GET",
        )
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                return json.loads(r.read().decode()) or []
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PocztexAuthError(f"tracking unauthorized: HTTP {e.code}") from e
            raise PocztexError(f"get_parcels failed: HTTP {e.code}") from e
