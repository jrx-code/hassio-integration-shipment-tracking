"""ORLEN Paczka account client — app-backend login by phone + SMS.

Reverse-engineered from pl.orlen.paczka 3.7.0; see ``carriers_orlen_account``
for the backend description and the live-verification note. stdlib urllib only
(blocking — callers run it in an executor).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from .carriers_orlen_account import (
    ORLEN_ACCOUNT_API_URL,
    ORLEN_APP_VERSION,
    ORLEN_CLIENT_ID,
    ORLEN_SCOPE,
    ORLEN_TOKEN_URL,
    orlen_account_canonical,
    orlen_account_is_active,
    orlen_account_status_pl,
)

_LOGGER = logging.getLogger(__name__)

# Fields the parcel object may use (locked when the first real parcel lands;
# read defensively until then).
_NUMBER_KEYS = ("shipmentnumber", "shipmentNumber", "packnumber", "packNumber", "number", "shipmentid", "id")
_STATUS_CODE_KEYS = ("statusid", "statusId", "trans", "statusCode", "status_code", "code")
_STATUS_TEXT_KEYS = ("statusname", "statusName", "statusText", "statusdescription", "status")
_SENDER_KEYS = ("sender", "senderName", "sendername", "shipper")
_POINT_KEYS = ("pointname", "pointName", "machinename", "parcelpoint", "pointid", "pointId")
_EVENTS_KEYS = ("events", "history", "statuses", "trace")


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


class OrlenAccountError(Exception):
    """Any ORLEN account API failure."""


class OrlenAccountReauthRequired(OrlenAccountError):
    """Account no longer valid (deactivated / unknown device) — re-run SMS."""


class OrlenAccountClientSecretError(OrlenAccountError):
    """The app client secret is missing or Entra ID rejected it."""


def normalize_parcel(raw: dict) -> dict:
    """Flatten one account shipment object into the entity row shape."""
    code = _first(raw, _STATUS_CODE_KEYS)
    text = _first(raw, _STATUS_TEXT_KEYS) or ""
    text = str(text).strip()
    return {
        "number": _first(raw, _NUMBER_KEYS),
        "status": orlen_account_status_pl(code, text),
        "status_raw": text or (str(code) if code is not None else None),
        "canonical": orlen_account_canonical(code, text),
        "active": orlen_account_is_active(code, text),
        "sender": _first(raw, _SENDER_KEYS),
        "point": _first(raw, _POINT_KEYS),
    }


class OrlenAccountApi:
    """Blocking ORLEN Paczka account client. One instance per entry."""

    def __init__(self, client_secret: str) -> None:
        self._client_secret = (client_secret or "").strip()
        self._token: str | None = None
        self._token_exp: float = 0.0

    # --- transport ---------------------------------------------------------
    def _token_value(self) -> str:
        """App-level bearer token, cached until ~60s before expiry."""
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        if not self._client_secret:
            raise OrlenAccountClientSecretError("no client secret configured")
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": ORLEN_CLIENT_ID,
                "client_secret": self._client_secret,
                "scope": ORLEN_SCOPE,
            }
        ).encode()
        req = urllib.request.Request(
            ORLEN_TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            if err.code in (400, 401):
                # Entra ID answers a wrong client secret with 401 invalid_client
                # (400 for some malformed values).
                raise OrlenAccountClientSecretError(
                    f"token rejected: HTTP {err.code}"
                ) from err
            raise OrlenAccountError(f"token request failed: {err}") from err
        except urllib.error.URLError as err:
            raise OrlenAccountError(f"token request failed: {err}") from err
        tok = d.get("access_token")
        if not tok:
            raise OrlenAccountError("no access_token in token response")
        self._token = tok
        self._token_exp = now + int(d.get("expires_in", 3600))
        return tok

    def _req(self, method: str, path: str, payload: dict | None = None):
        url = f"{ORLEN_ACCOUNT_API_URL}/{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token_value()}",
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode() or "{}"
                return r.status, json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as err:
            raw = err.read().decode() or ""
            if err.code in (401, 403, 404):
                raise OrlenAccountReauthRequired(f"HTTP {err.code}: {raw[:200]}") from err
            raise OrlenAccountError(f"HTTP {err.code}: {raw[:200]}") from err
        except urllib.error.URLError as err:
            raise OrlenAccountError(f"request failed: {err}") from err

    # --- auth --------------------------------------------------------------
    def send_sms(self, phone: str, device_id: str) -> bool:
        """POST customers — registers the device and triggers the SMS code."""
        body = {
            "phone": phone,
            "deviceid": device_id,
            "versionapp": ORLEN_APP_VERSION,
            "ostype": "android",
            "pushtoken": "",
            "appconfiguration": [{"type": "languages", "value": "pl-PL"}],
            "sms": 1,
        }
        st, _d = self._req("POST", "customers", body)
        return st == 200

    def verify_sms(self, phone: str, device_id: str, code: str) -> bool:
        """PATCH customers/{phone}/{deviceId} — confirms the SMS code.

        Returns True when the account comes back Active.
        """
        st, d = self._req(
            "PATCH",
            f"customers/{phone}/{device_id}",
            {"validationtoken": code, "versionapp": ORLEN_APP_VERSION},
        )
        if st != 200:
            return False
        inner = (d or {}).get("data", {}).get("data", {}) if isinstance(d, dict) else {}
        status = str(inner.get("statusid") or inner.get("statusId") or "").lower()
        # No status field -> treat 200 as success; a wrong code returns an error.
        return status in ("", "active", "aktywny") or "activ" in status

    # --- data --------------------------------------------------------------
    def get_shipments(self, phone: str, device_id: str) -> list[dict]:
        """GET customers/{phone}/{deviceId}/shipments — all parcels for the number."""
        st, d = self._req("GET", f"customers/{phone}/{device_id}/shipments")
        if st != 200:
            raise OrlenAccountError(f"unexpected status {st}")
        items = d.get("data") if isinstance(d, dict) else d
        if not isinstance(items, list):
            raise OrlenAccountError("shipments payload is not a list")
        if items:
            # First populated fetch: log the real key set so the field map can be
            # locked without guessing. One line, debug only.
            _LOGGER.debug("Orlen account shipment keys: %s", sorted(items[0].keys()))
        return [normalize_parcel(p) for p in items if isinstance(p, dict)]
