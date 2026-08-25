"""FedEx Track API client (official REST API, OAuth2 client_credentials).

Unlike InPost/DPD this is NOT a reverse-engineered consumer app — it's the
documented developer.fedex.com Track API. No phone/SMS, no per-user session:
one Client ID/Secret pair (from a FedEx developer org's project) authenticates
the whole integration, and tracking is by number, not account-auto-discovery.
Verified live 2026-08-25: OAuth against production (apimode:"Live" in the
returned JWT) and a full Track API round-trip against the sandbox environment
(mock waybill 449044304137821 — FedEx's own published test number).
stdlib urllib only (blocking — callers run it in an executor).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .const import FEDEX_MAX_NUMBERS_PER_REQUEST, FEDEX_OAUTH_URL, FEDEX_TRACK_URL


class FedexError(Exception):
    """Any FedEx API failure."""


class FedexAuthError(FedexError):
    """Client ID/Secret rejected — not a per-user session, so no reauth flow;
    this means the credentials themselves are wrong or revoked."""


class FedexApi:
    """Blocking FedEx client. Client ID/Secret are static (no rotation, no
    per-user token to persist) — the coordinator re-authenticates each poll,
    same simplicity tradeoff as the DPD client."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._ctx: ssl.SSLContext | None = None

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

    def get_access_token(self) -> str:
        form = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        ).encode()
        req = urllib.request.Request(
            FEDEX_OAUTH_URL,
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        st, d = self._do(req)
        if st == 200 and d.get("access_token"):
            return d["access_token"]
        if st in (401, 403):
            raise FedexAuthError(f"OAuth rejected: HTTP {st} {d}")
        raise FedexError(f"OAuth failed: HTTP {st} {d}")

    def track(self, access_token: str, tracking_numbers: list[str]) -> list[dict]:
        """Track up to FEDEX_MAX_NUMBERS_PER_REQUEST numbers in one call.
        Returns the raw ``completeTrackResults`` list from the API."""
        if not tracking_numbers:
            return []
        if len(tracking_numbers) > FEDEX_MAX_NUMBERS_PER_REQUEST:
            raise FedexError(
                f"{len(tracking_numbers)} tracking numbers > "
                f"{FEDEX_MAX_NUMBERS_PER_REQUEST}-per-request FedEx limit"
            )
        body = json.dumps(
            {
                "includeDetailedScans": True,
                "trackingInfo": [
                    {"trackingNumberInfo": {"trackingNumber": n}} for n in tracking_numbers
                ],
            }
        ).encode()
        req = urllib.request.Request(
            FEDEX_TRACK_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-locale": "pl_PL",
            },
            method="POST",
        )
        st, d = self._do(req)
        if st in (401, 403):
            raise FedexAuthError(f"track unauthorized: HTTP {st}")
        if st != 200:
            raise FedexError(f"track failed: HTTP {st} {d}")
        return (d.get("output") or {}).get("completeTrackResults", []) or []
