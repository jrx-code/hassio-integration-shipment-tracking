"""DPD Poland mobile-API client (phone + SMS auth).

Reimplemented from the observed DPD Mobile PL protocol (verified live 2026-08-06):
Keycloak realm ``DPD`` on ``dpdsso.dpd.com.pl`` for auth, ``mobapp.dpd.com.pl``
for the recipient package list. This is the *Polish* app backend — NOT the
GEOPOST myDPD / dpdgroup.com platform (which is email/password). stdlib urllib
only (blocking — callers run it in an executor). No third-party code copied.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .const import (
    DPD_API_URL,
    DPD_CLIENT_ID,
    DPD_MOBILE_PLATFORM,
    DPD_MOBILE_VERSION,
    DPD_REALM,
    DPD_SSO_URL,
    DPD_UA,
)


class DpdError(Exception):
    """Any DPD API failure."""


class DpdAuthError(DpdError):
    """Auth/token no longer valid — user must re-authenticate via SMS."""


def normalize_phone(phone: str) -> str:
    """Return a bare 9-digit Polish number (strip +48 / 0048 / spaces)."""
    clean = re.sub(r"\D", "", str(phone))
    if len(clean) > 9 and clean.startswith("48"):
        clean = clean[2:]
    elif len(clean) > 9 and clean.startswith("0048"):
        clean = clean[4:]
    return clean


class DpdApi:
    """Blocking DPD client. The access token is short-lived; the coordinator
    holds the refresh token and mints an access token per poll."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None

    @property
    def _token_url(self) -> str:
        return f"{DPD_SSO_URL}/auth/realms/{DPD_REALM}/protocol/openid-connect/token"

    # ---------------- HTTP ----------------
    def _do(self, req: urllib.request.Request):
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                body = r.read().decode() or "{}"
                return r.status, json.loads(body) if body.strip().startswith(("{", "[")) else {"raw": body}
        except urllib.error.HTTPError as e:
            body = e.read().decode() or "{}"
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, {"raw": body}

    def _req(self, method: str, url: str, *, token: str | None = None,
             json_body: dict | None = None, form: dict | None = None,
             extra_headers: dict | None = None):
        headers = {"Accept": "application/json", "User-Agent": DPD_UA}
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode()
        elif form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(form).encode()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        return self._do(urllib.request.Request(url, data=data, headers=headers, method=method))

    # ---------------- auth ----------------
    def send_sms(self, phone: str) -> bool:
        phone = normalize_phone(phone)
        st, _d = self._req("PUT", f"{DPD_SSO_URL}/api/phone-verifications/{phone}")
        return st in (200, 201, 204)

    def register(self, phone: str, code: str) -> tuple[str, str]:
        """Verify the SMS code and return (access_token, refresh_token)."""
        phone = normalize_phone(phone)
        params = urllib.parse.urlencode(
            {
                "redirect_uri": f"{DPD_SSO_URL}/landing-page?messageType=activeAccount",
                "client_id": DPD_CLIENT_ID,
            }
        )
        st, d = self._req(
            "POST",
            f"{DPD_SSO_URL}/api/users?{params}",
            json_body={
                "emailRegistration": None,
                "phoneRegistration": {"phone": phone, "code": str(code)},
                "type": "PhoneBasedUserRegistrationModel",
            },
        )
        auth_code = d.get("code")
        if not auth_code:
            raise DpdError(f"registration failed: HTTP {st} {d}")
        st2, tok = self._req(
            "POST",
            self._token_url,
            form={
                "code": auth_code,
                "grant_type": "authorization_code",
                "client_id": DPD_CLIENT_ID,
            },
        )
        if st2 == 200 and tok.get("access_token") and tok.get("refresh_token"):
            return tok["access_token"], tok["refresh_token"]
        raise DpdError(f"token exchange failed: HTTP {st2} {tok}")

    def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Mint an access token. Returns (access_token, refresh_token) — the
        refresh token may rotate, so callers must persist the returned one."""
        st, d = self._req(
            "POST",
            self._token_url,
            form={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "client_id": DPD_CLIENT_ID,
            },
        )
        if st == 200 and d.get("access_token"):
            return d["access_token"], d.get("refresh_token") or refresh_token
        raise DpdAuthError(f"refresh failed: HTTP {st} {d}")

    # ---------------- data ----------------
    def get_parcels(self, access_token: str) -> list[dict]:
        st, d = self._req(
            "POST",
            f"{DPD_API_URL}/mdupackageservices/api/v1/packages?userContext=RECEIVER",
            token=access_token,
            json_body={"alias": None, "sent": None},
            extra_headers={
                "X-Mobile-Platform": DPD_MOBILE_PLATFORM,
                "X-Mobile-Version": DPD_MOBILE_VERSION,
            },
        )
        if st == 200:
            return d.get("packages", []) or []
        if st in (401, 403):
            raise DpdAuthError(f"parcels unauthorized: HTTP {st}")
        raise DpdError(f"get_parcels failed: HTTP {st} {d}")
