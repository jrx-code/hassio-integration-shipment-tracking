"""InPost mobile-API client (legacy SMS auth track).

Reverse-engineered from the InPost mobile app and verified against the live API.
stdlib only (urllib) — blocking, so callers must run it in an executor. Key
gotchas: ETag pagination on /v4/parcels/tracked, legacy SMS backend (no captcha),
304 => NotModified.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from .const import ARCHIVED, IN_TRANSIT, READY


class NotModified(Exception):
    """InPost returned 304 (rate-limited / nothing changed) — keep prior state."""


class ReauthRequired(Exception):
    """Refresh token no longer valid — user must re-authenticate via SMS."""


class InPostError(Exception):
    """Any other InPost API failure."""


def _state_of(status: str) -> str:
    if status in READY:
        return "ready"
    if status in IN_TRANSIT:
        return "in_transit"
    return "archived"


def _phone_value(raw) -> str | None:
    """Phone numbers come as a bare string on /v1 and as {prefix,value} on /v2."""
    if isinstance(raw, dict):
        return raw.get("value")
    return raw or None


def _shared_to(p: dict) -> list[dict]:
    return [
        {
            "uuid": f.get("uuid"),
            "name": f.get("name"),
            "phone": _phone_value(f.get("phoneNumber")),
        }
        for f in (p.get("sharedTo") or [])
    ]


def _dedupe(parcels: list[dict]) -> list[dict]:
    """Drop repeated shipment numbers, keeping first position and last payload."""
    order: list[str] = []
    by_num: dict[str, dict] = {}
    for p in parcels:
        num = p.get("shipmentNumber")
        if num is None:
            continue
        if num not in by_num:
            order.append(num)
        by_num[num] = p
    return [by_num[n] for n in order]


def _map_parcel(p: dict, state: str) -> dict:
    """Flatten one raw InPost parcel into the shape used by entities/attributes."""
    point = p.get("pickUpPoint") or {}
    addr = point.get("addressDetails") or {}
    mc = p.get("multiCompartment") or {}
    ops = p.get("operations") or {}
    return {
        "shipment": p.get("shipmentNumber"),
        "status": p.get("status", "UNKNOWN"),
        "state": state,
        "open_code": p.get("openCode"),
        "qr": p.get("qrCode"),
        "locker": point.get("name"),
        "address": " ".join(x for x in [
            addr.get("street"), addr.get("buildingNumber"), addr.get("city"),
        ] if x) or point.get("locationDescription"),
        "sender": (p.get("sender") or {}).get("name"),
        "expiry": p.get("expiryDate"),
        "stored": p.get("storedDate"),
        "multi_uuid": mc.get("uuid"),
        "multi_count": len(mc.get("shipmentNumbers", [])) or None,
        # App-to-app sharing. `ownership` is OWN for our own parcels, FRIEND for
        # ones someone shared with us (those carry openCode/qrCode too) and
        # OBSERVED for view-only shares (openCode/qrCode are null there).
        "ownership": p.get("ownershipStatus"),
        "shared_to": _shared_to(p),
        "can_share": bool(ops.get("canShareParcel")),
        # Owner of a parcel shared *with* us: InPost keeps the original
        # recipient in `receiver`, so this is how a FRIEND/OBSERVED parcel can be
        # attributed back to the account that shared it.
        "owner_phone": _phone_value((p.get("receiver") or {}).get("phoneNumber")),
    }


def categorize_parcels(parcels: list[dict]) -> dict[str, list[dict]]:
    """Split all parcels into ready / in_transit / archived, keeping full history."""
    out: dict[str, list[dict]] = {"ready": [], "in_transit": [], "archived": []}
    for p in parcels:
        state = _state_of(p.get("status", "UNKNOWN"))
        out[state].append(_map_parcel(p, state))
    return out


class InPostApi:
    """Blocking InPost client. One instance per account is fine but stateless
    except for base/UA; the auth token is passed per call by the coordinator."""

    def __init__(self, base: str, user_agent: str) -> None:
        self._base = base.rstrip("/")
        self._ua = user_agent
        # SSLContext is created lazily on first request: create_default_context()
        # is blocking (loads system CAs), and the client is only ever driven from
        # an executor thread, so this keeps it off the event loop.
        self._ctx: ssl.SSLContext | None = None

    # ---------------- HTTP ----------------
    def _do(self, req: urllib.request.Request):
        if self._ctx is None:
            self._ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=25, context=self._ctx) as r:
                return r.status, dict(r.headers), json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode() or "{}"
            try:
                return e.code, dict(e.headers), json.loads(body)
            except json.JSONDecodeError:
                return e.code, dict(e.headers), {"raw": body}

    def _post(self, path: str, body: dict, token: str | None = None):
        h = {"Content-Type": "application/json; charset=UTF-8", "User-Agent": self._ua}
        if token:
            h["Authorization"] = token
        return self._do(urllib.request.Request(
            self._base + path, data=json.dumps(body).encode(), headers=h, method="POST"))

    def _get(self, path: str, token: str, etag: str | None = None):
        h = {"User-Agent": self._ua, "Authorization": token}
        if etag:
            h["If-None-Match"] = etag
        return self._do(urllib.request.Request(self._base + path, headers=h, method="GET"))

    # ---------------- auth ----------------
    def send_sms(self, prefix: str, value: str) -> bool:
        st, _h, _d = self._post("/v1/account", {"phoneNumber": {"prefix": prefix, "value": value}})
        return st == 200

    def verify_sms(self, code: str, prefix: str, value: str) -> tuple[str, str]:
        st, _h, d = self._post("/v1/account/verification", {
            "smsCode": str(code), "devicePlatform": "Android",
            "phoneNumber": {"prefix": prefix, "value": value}})
        if st == 200 and "authToken" in d:
            return d["authToken"], d["refreshToken"]
        raise InPostError(f"verify failed: HTTP {st} {d}")

    def refresh(self, refresh_token: str) -> str:
        st, _h, d = self._post("/v1/authenticate",
                               {"refreshToken": refresh_token, "phoneOS": "Android"})
        if st == 200 and "authToken" in d:
            if d.get("reauthenticationRequired"):
                raise ReauthRequired()
            return d["authToken"]
        raise InPostError(f"refresh failed: HTTP {st} {d}")

    # ---------------- data ----------------
    def get_parcels(self, auth_token: str) -> list[dict]:
        """Fetch ALL parcels across pages, de-duplicated by shipment number.

        InPost paginates via ETag: send the response ETag back as If-None-Match to
        get the next page. A single GET only sees the oldest page and misses recent
        (incl. ready-to-pickup) parcels.

        Pages can OVERLAP — the same parcel was observed on two consecutive pages
        of a live account (2026-08-21), which inflated the in-transit count by one
        and would have sent a parcel twice in a single share request. Later pages
        are newer, so a repeat replaces the earlier copy while keeping the parcel
        at its first position.
        """
        parcels: list[dict] = []
        etag: str | None = None
        seen: set[str] = set()
        for _ in range(20):  # hard cap; typical account 1-3 pages
            st, headers, d = self._get("/v4/parcels/tracked", auth_token, etag)
            if st == 304:
                if not parcels:
                    raise NotModified()
                break
            if st != 200:
                raise InPostError(f"get_parcels failed: HTTP {st} {d}")
            parcels.extend(d.get("parcels", []))
            new_etag = headers.get("Etag")
            if not d.get("more") or new_etag in seen or not new_etag:
                break
            seen.add(new_etag)
            etag = new_etag
        return _dedupe(parcels)

    # ---------------- app-to-app sharing ----------------
    def get_friends(self, auth_token: str) -> list[dict]:
        """Paired InPost users ("znajomi") of this account.

        GOTCHA: the path must NOT carry a trailing slash — `/v2/friends/` answers
        404 with an empty body (same shape an unknown route returns), while
        `/v2/friends` answers 200. `/v1/friends` works too but returns the phone
        number as a bare string; v2 returns {prefix,value}, so v2 it is.
        """
        st, _h, d = self._get("/v2/friends", auth_token)
        if st != 200:
            raise InPostError(f"get_friends failed: HTTP {st} {d}")
        out: list[dict] = []
        for f in d.get("friends", []):
            phone = f.get("phoneNumber") or {}
            out.append({
                "uuid": f.get("uuid"),
                "name": f.get("name"),
                "prefix": phone.get("prefix") if isinstance(phone, dict) else None,
                "phone": _phone_value(phone),
            })
        return out

    def share_parcels(
        self, auth_token: str, shipments: list[str], friend_uuids: list[str]
    ) -> None:
        """Share parcels app-to-app with already-paired friends.

        The recipient then sees each parcel in their own /v4/parcels/tracked with
        ownershipStatus=FRIEND, including openCode and qrCode — i.e. a second HA
        account running this integration picks it up on its next poll with no
        extra wiring. Sharing is not undone by this client; InPost's unshare
        endpoint (if any) is unverified.
        """
        if not shipments or not friend_uuids:
            return
        body = {
            "parcels": [
                {"shipmentNumber": str(s), "friendUuids": list(friend_uuids)}
                for s in shipments
            ]
        }
        st, _h, d = self._post("/v4/parcels/shared", body, auth_token)
        if st != 200:
            raise InPostError(f"share_parcels failed: HTTP {st} {d}")
