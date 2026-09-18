"""Orlen Paczka public track-by-number client.

Uses the same unofficial JSONP status endpoint the public tracking page
backs onto (nadaj.orlenpaczka.pl/parcel/api-status) — no PartnerID /
PartnerKey, no SOAP, no account. Verified live 2026-09-18: a known-bad
number returns err 1003; a numeric id with no history returns an
empty history list. Response shape matches what jwilk/pacz scrapes.
stdlib urllib only (blocking — callers run it in an executor).
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from .const import ORLEN_API_URL, ORLEN_UA


class OrlenError(Exception):
    """Any Orlen Paczka API failure."""


class OrlenApi:
    """Blocking Orlen Paczka client — one GET per tracking number."""

    def __init__(self) -> None:
        self._ctx: ssl.SSLContext | None = None

    def _do(self, req: urllib.request.Request) -> tuple[int, str]:
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                return r.status, r.read().decode() or ""
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode() or ""

    @staticmethod
    def _unwrap_jsonp(body: str) -> dict:
        """Strip callback(...); wrapper; tolerate bare JSON too."""
        text = (body or "").strip()
        if text.startswith("callback(") and text.endswith(");"):
            text = text[len("callback("):-2]
        elif text.startswith("callback(") and text.endswith(")"):
            text = text[len("callback("):-1]
        data = json.loads(text or "{}")
        if not isinstance(data, dict):
            raise OrlenError(f"unexpected JSONP payload type: {type(data).__name__}")
        return data

    def track(self, tracking_number: str) -> dict | None:
        """Track one parcel. Returns the decoded JSON body, or None when the
        endpoint reports the number as unknown (err 1003)."""
        number = re.sub(r"\s+", "", str(tracking_number or ""))
        if not number:
            return None
        ts = int(time.time() * 1000)
        url = f"{ORLEN_API_URL}?id={quote(number, safe='')}&jsonp=callback&_={ts}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "*/*", "User-Agent": ORLEN_UA},
            method="GET",
        )
        st, body = self._do(req)
        if st != 200:
            raise OrlenError(f"track failed: HTTP {st} {body[:200]}")
        try:
            data = self._unwrap_jsonp(body)
        except json.JSONDecodeError as err:
            raise OrlenError(f"invalid JSONP: {err}") from err
        if data.get("err") in (1003, "1003"):
            return None
        data.setdefault("number", number)
        return data
