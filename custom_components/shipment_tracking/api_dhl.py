"""DHL Parcel Polska ("Mój DHL", mojdhl.pl) API client — phone + SMS auth
gated by an Altcha proof-of-work captcha.

Reimplemented from the web app's own JS bundle (endpoints appear in
plaintext, no APK decompilation needed) and verified live 2026-08-26 against
a real account. stdlib only (urllib + http.cookiejar) — blocking, callers
run it in an executor. See const.py's DHL section for the session-mechanics
writeup (cookie-based refresh, not the opaque ``refresh`` string).
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .const import DHL_BASE, DHL_UA


class DhlError(Exception):
    """Any DHL API failure."""


class DhlAuthError(DhlError):
    """Session dead (cookies expired/rejected) — user must re-authenticate
    via SMS. There is no stored-password or long-lived-token fallback."""


def _solve_altcha(challenge: dict) -> str:
    """Brute-force n such that SHA-256(salt+n) == challenge, n in
    0..maxnumber (~100000 — a fraction of a second). Verified live: the
    server accepts this solved payload, not a theoretical implementation."""
    salt = challenge["salt"]
    target = challenge["challenge"]
    maxnumber = challenge.get("maxnumber", 100000)
    for n in range(maxnumber + 1):
        if hashlib.sha256(f"{salt}{n}".encode()).hexdigest() == target:
            payload = {
                "algorithm": challenge["algorithm"],
                "challenge": target,
                "number": n,
                "salt": salt,
                "signature": challenge["signature"],
            }
            return base64.b64encode(json.dumps(payload).encode()).decode()
    raise DhlError("altcha challenge not solved within maxnumber range")


class DhlApi:
    """Blocking DHL client. Keeps a persistent cookiejar across calls — the
    session lives in httpOnly cookies set during login, not in any token
    string this client holds. One instance per account, kept alive for the
    coordinator's lifetime (see coordinator_dhl.py); an instance's cookies
    do not survive process restart."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def export_cookies(self) -> list[dict]:
        """Snapshot the cookiejar as plain dicts — the config entry's only
        real handoff mechanism (config_flow's DhlApi login()s with its own
        jar; the coordinator's separate DhlApi instance needs those exact
        cookies, not a fresh empty jar, to refresh_session() successfully).
        Session cookies (no Max-Age/Expires) are exported too — how long
        they actually stay valid server-side is unverified, but their
        client-side "session-only" hint is just a browser convention, not
        proof they die with the process."""
        return [
            {
                "name": c.name, "value": c.value, "domain": c.domain,
                "path": c.path, "secure": c.secure,
            }
            for c in self.jar
        ]

    def import_cookies(self, cookies: list[dict]) -> None:
        for c in cookies or []:
            self.jar.set_cookie(
                http.cookiejar.Cookie(
                    version=0, name=c["name"], value=c["value"],
                    port=None, port_specified=False,
                    domain=c["domain"], domain_specified=True,
                    domain_initial_dot=c["domain"].startswith("."),
                    path=c.get("path", "/"), path_specified=True,
                    secure=c.get("secure", True), expires=None,
                    discard=True, comment=None, comment_url=None, rest={},
                )
            )

    # ---------------- HTTP ----------------
    def _get(self, path: str) -> dict:
        req = urllib.request.Request(
            f"{DHL_BASE}{path}",
            headers={"Accept": "application/json", "User-Agent": DHL_UA},
        )
        return self._do(req)

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{DHL_BASE}{path}",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DHL_UA,
                "Origin": "https://mojdhl.pl",
                "Referer": "https://mojdhl.pl/login",
            },
            method="POST",
        )
        return self._do_raw(req)

    def _do_raw(self, req: urllib.request.Request) -> tuple[int, dict]:
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        try:
            with self.opener.open(req, timeout=25) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"raw": raw}

    def _do(self, req: urllib.request.Request) -> dict:
        st, body = self._do_raw(req)
        if st != 200:
            raise DhlError(f"GET {req.full_url} failed: HTTP {st} {body}")
        return body

    def _captcha_payload(self) -> str:
        challenge = self._get("/auth/captcha/challenge")
        return _solve_altcha(challenge)

    # ---------------- auth ----------------
    def send_sms(self, phone: str) -> bool:
        """validate-account then generate-code. ``phone`` is bare 9 digits;
        prefix is always "48" (no "+" — confirmed live, "+48" is a 422)."""
        st, body = self._post(
            "/auth/validate-account",
            {"prefix": "48", "phoneNumber": phone, "captcha-payload": self._captcha_payload()},
        )
        if st != 200:
            raise DhlError(f"validate-account failed: HTTP {st} {body}")
        st, body = self._post(
            "/auth/generate-code",
            {
                "prefix": "48",
                "phoneNumber": phone,
                "isMobileDevice": False,
                "captcha-payload": self._captcha_payload(),
            },
        )
        if st != 200:
            raise DhlError(f"generate-code failed: HTTP {st} {body}")
        return body.get("responseCode") == 0

    def verify_sms(
        self, phone: str, sms_code: str, device_id: str, device_name: str
    ) -> str:
        """Verify the SMS code. Returns the access token (JWT) — the real
        credential to persist afterwards is this client's cookiejar, not
        the token string (it expires in 30 min and refresh_session() mints
        a new one from cookies, not from this value)."""
        st, body = self._post(
            "/auth/validate-code",
            {
                "prefix": "48",
                "phoneNumber": phone,
                "smsCode": str(sms_code),
                "deviceId": device_id,
                "deviceName": device_name,
                "rememberMe": True,
                "captcha-payload": self._captcha_payload(),
            },
        )
        if st != 200 or not body.get("success"):
            raise DhlAuthError(f"validate-code rejected: HTTP {st} {body}")
        return body["token"]["token"]

    def refresh_session(self, device_id: str, device_name: str) -> str:
        """Cookie-based session refresh — no token/refresh param, just the
        cookiejar this instance has been carrying since login(). Verified
        live to mint a token with iat = call time (real sliding window),
        not pinned to the original login like Pocztex's refresh_token."""
        path = "/auth/refresh?" + urllib.parse.urlencode(
            {"deviceId": device_id, "deviceName": device_name}
        )
        st, body = self._do_raw(
            urllib.request.Request(
                f"{DHL_BASE}{path}",
                headers={"Accept": "application/json", "User-Agent": DHL_UA},
            )
        )
        if st == 401:
            raise DhlAuthError("DHL session expired (cookies rejected)")
        if st != 200 or not body.get("token"):
            raise DhlError(f"auth/refresh failed: HTTP {st} {body}")
        return body["token"]

    # ---------------- data ----------------
    def get_parcels(self, access_token: str, page: int = 1) -> dict:
        """POST /user/shipment/v2.1/list/incoming/active/{page} — own
        shipments. Body is a filter object, empty filters = everything.
        Returns the raw response (shipments[] + hasNextPage) so the
        coordinator can paginate if needed — the research account only had
        one parcel, pagination itself is unverified."""
        req = urllib.request.Request(
            f"{DHL_BASE}/user/shipment/v2.1/list/incoming/active/{page}",
            data=json.dumps(
                {"shipmentFilterTypes": [], "shipmentFilterStatuses": [], "page": page}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DHL_UA,
                "Authorization": f"Bearer {access_token}",
            },
            method="POST",
        )
        st, body = self._do_raw(req)
        if st in (401, 403):
            raise DhlAuthError(f"parcel list unauthorized: HTTP {st}")
        if st != 200:
            raise DhlError(f"get_parcels failed: HTTP {st} {body}")
        return body

    def get_observed_parcels(self, access_token: str) -> list[dict]:
        """POST /user/shipment/observed/v1.0/list/incoming/active — parcels
        someone else shared to this account (analogue of InPost's
        sharedTo/FRIEND). Returns a bare list, unlike get_parcels()'s
        wrapped shape — confirmed live (empty list on the research
        account, no shared parcels to inspect the populated shape)."""
        req = urllib.request.Request(
            f"{DHL_BASE}/user/shipment/observed/v1.0/list/incoming/active",
            data=json.dumps({}).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DHL_UA,
                "Authorization": f"Bearer {access_token}",
            },
            method="POST",
        )
        st, body = self._do_raw(req)
        if st in (401, 403):
            raise DhlAuthError(f"observed list unauthorized: HTTP {st}")
        if st != 200:
            raise DhlError(f"get_observed_parcels failed: HTTP {st} {body}")
        return body if isinstance(body, list) else []
