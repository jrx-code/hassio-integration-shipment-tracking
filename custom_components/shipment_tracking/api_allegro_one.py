"""Allegro One public track-by-number client.

Uses Allegro's edge tracking endpoint
https://edge.allegro.pl/ad/tracking?packageNo=...
with Accept: application/vnd.allegro.internal.v1+json — no OAuth token required
for this public track-by-number path (verified live 2026-09-18 against a
historical Allegro One waybill). Official api.allegro.pl carrier tracking
still requires OAuth and is NOT used here.

Waybill format is Allegro's internal number (A / AD + alphanumerics),
not the subcontractor UPS/DPD/Orlen number. stdlib urllib only (blocking —
callers run it in an executor).
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote

from .carriers_orlen_allegro import ALLEGRO_ONE_API_URL, ALLEGRO_ONE_UA


class AllegroOneError(Exception):
    """Any Allegro One tracking failure."""


class AllegroOneApi:
    """Blocking Allegro One client — one GET per tracking number."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None

    def _do(self, req: urllib.request.Request) -> tuple[int, dict | list]:
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

    def track(self, tracking_number: str) -> dict | None:
        """Track one Allegro One parcel. Returns decoded JSON, or None when
        the endpoint has no status history for the number."""
        number = re.sub(r"\s+", "", str(tracking_number or "")).upper()
        if not number:
            return None
        url = f"{ALLEGRO_ONE_API_URL}?packageNo={quote(number, safe='')}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.allegro.internal.v1+json",
                "Accept-Language": "pl-PL",
                "User-Agent": ALLEGRO_ONE_UA,
            },
            method="GET",
        )
        st, data = self._do(req)
        if st == 404:
            return None
        if st != 200:
            raise AllegroOneError(f"track failed: HTTP {st} {data}")
        if not isinstance(data, dict):
            raise AllegroOneError(f"unexpected payload type: {type(data).__name__}")
        statuses = data.get("status") or []
        if not statuses:
            return None
        data = dict(data)
        data["number"] = number
        return data
