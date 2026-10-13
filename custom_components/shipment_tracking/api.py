"""InPost mobile-API client.

Stdlib only (urllib) — blocking, so callers must run it in an executor. Key
gotchas kept intact: ETag pagination on /v4/parcels/tracked, 304 => NotModified.

Sign-in (since 2026-10-12): InPost retired the legacy SMS login
(`/v1/account`, `/v1/account/verification`, `/v1/authenticate` all answer 404).
InPost Mobile now signs in with OAuth2 + PKCE on account.inpost-group.com. That
page sits behind a Cloudflare captcha and accepts only InPost's own redirect URI,
so Home Assistant cannot sign in by itself: the user opens the authorize URL in a
browser and pastes back the callback URL carrying `?code=`. The code and every
later refresh go to `POST /global/oauth2/token` on the API host (form encoded).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .const import inpost_canonical

OAUTH_AUTHORIZE_URL = "https://account.inpost-group.com/oauth2/authorize"
OAUTH_REDIRECT_URI = "https://account.inpost-group.com/callback"
OAUTH_CLIENT_ID = "inpost-mobile"
OAUTH_TOKEN_PATH = "/global/oauth2/token"
APP_ID = "pl.inpost.inmobile"
# Refresh this many seconds before the access token runs out.
EXPIRY_MARGIN = 60

class NotModified(Exception):
    """InPost returned 304 (rate-limited / nothing changed) — keep prior state."""


class ReauthRequired(Exception):
    """The stored session cannot be refreshed — the user must sign in again."""


class InPostError(Exception):
    """Any other InPost API failure."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token_claims(token: str | None) -> dict:
    """Unverified payload of a JWT (empty dict when the value is not one)."""
    raw = str(token or "")
    if raw.lower().startswith("bearer "):
        raw = raw[7:]
    parts = raw.split(".")
    if len(parts) != 3:
        return {}
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def token_phone(token: str | None) -> str | None:
    """The 9-digit phone number an InPost access token was issued for, if any."""
    claims = token_claims(token)
    for key in ("phone", "phone_number", "phoneNumber"):
        raw = claims.get(key)
        if isinstance(raw, dict):
            raw = raw.get("value")
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if len(digits) >= 9:
            return digits[-9:]
    return None


def account_phone_from_parcels(parcels: list[dict]) -> str | None:
    """Phone number of the account, from the receiver of its own parcels.

    A fallback for tokens without a phone claim (sign-in with e-mail may give
    one). Own parcels (ownershipStatus OWN, or none on old records) are
    addressed to the account itself; parcels shared with us carry the friend's
    number, so they are left out. The most common number wins.
    """
    counts: dict[str, int] = {}
    for p in parcels:
        if p.get("ownershipStatus") not in (None, "OWN"):
            continue
        digits = "".join(
            ch for ch in str(_phone_value((p.get("receiver") or {}).get("phoneNumber")) or "")
            if ch.isdigit()
        )
        if len(digits) >= 9:
            counts[digits[-9:]] = counts.get(digits[-9:], 0) + 1
    return max(counts, key=counts.get) if counts else None


class PkceLogin:
    """One browser sign-in attempt: the authorize URL and its PKCE secret."""

    def __init__(self) -> None:
        self.verifier = _b64url(secrets.token_bytes(48))
        self.state = _b64url(secrets.token_bytes(24))
        self._nonce = _b64url(secrets.token_bytes(24))

    @property
    def url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid",
            "code_challenge": _b64url(hashlib.sha256(self.verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "state": self.state,
            "nonce": self._nonce,
            "response_mode": "query",
            "lang": "pl-PL",
            # Always show the form: a browser still signed in to InPost would
            # otherwise hand back the previous account's code.
            "prompt": "login",
        }
        return f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def extract_code(self, pasted: str) -> str:
        """Authorization code from the pasted callback URL.

        Raises ValueError with reason "sms" (digits pasted, the old flow),
        "state" (URL from another attempt) or "no_code".
        """
        value = str(pasted or "").strip()
        if "code=" not in value:
            raise ValueError("sms" if value.replace(" ", "").isdigit() else "no_code")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(value).query or value)
        code = (query.get("code") or [""])[0]
        if not code:
            raise ValueError("no_code")
        state = (query.get("state") or [None])[0]
        if state is not None and state != self.state:
            raise ValueError("state")
        return code


@dataclass
class Tokens:
    access: str
    refresh: str
    expires_at: float


def _state_of(status: str, status_group: str | None = None) -> str:
    return inpost_canonical(status, status_group)


def _newest_event(p: dict) -> dict:
    """Return the newest events[] entry, or {} when the parcel has none.

    InPost lists events newest-first in live payloads (issue #3); fall back to
    the last element if the list is somehow ordered the other way and only one
    end carries title/description.
    """
    events = p.get("events") or []
    if not events:
        return {}
    first = events[0] if isinstance(events[0], dict) else {}
    if first.get("eventTitle") or first.get("eventDescription"):
        return first
    last = events[-1] if isinstance(events[-1], dict) else {}
    return last


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
    event = _newest_event(p)
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
        # Newest events[] entry — the only place some human-readable explanations
        # exist (e.g. expired locker storage window). Surfaced on sensor attrs.
        "event_title": event.get("eventTitle"),
        "event_description": event.get("eventDescription"),
    }


def categorize_parcels(parcels: list[dict]) -> dict[str, list[dict]]:
    """Split all parcels into ready / in_transit / archived, keeping full history."""
    out: dict[str, list[dict]] = {"ready": [], "in_transit": [], "archived": []}
    for p in parcels:
        state = _state_of(p.get("status", "UNKNOWN"), p.get("statusGroup"))
        out[state].append(_map_parcel(p, state))
    return out


def filter_ignored(cat: dict[str, list[dict]], ignored: set[str]) -> dict[str, list[dict]]:
    """Drop shipment numbers in ``ignored`` from every bucket.

    User-side hide for InPost records that ``/v4/parcels/tracked`` keeps
    returning after the app itself stopped showing them — see
    CONF_IGNORED_SHIPMENTS in const.py. A no-op (same dict, not copied) when
    ``ignored`` is empty, since that's the overwhelmingly common case and
    copying three lists on every poll for nothing would be wasteful."""
    if not ignored:
        return cat
    return {
        bucket: [p for p in rows if p.get("shipment") not in ignored]
        for bucket, rows in cat.items()
    }


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

    def _post_form(self, path: str, form: dict):
        h = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": self._ua,
            "X-App-Id": APP_ID,
        }
        return self._do(urllib.request.Request(
            self._base + path, data=urllib.parse.urlencode(form).encode(),
            headers=h, method="POST"))

    def _post(self, path: str, body: dict, token: str | None = None):
        h = {"Content-Type": "application/json; charset=UTF-8", "User-Agent": self._ua}
        if token:
            h["Authorization"] = token
        return self._do(urllib.request.Request(
            self._base + path, data=json.dumps(body).encode(), headers=h, method="POST"))

    def _get(self, path: str, token: str, etag: str | None = None):
        h = {"User-Agent": self._ua, "Authorization": token, "X-App-Id": APP_ID}
        if etag:
            h["If-None-Match"] = etag
        return self._do(urllib.request.Request(self._base + path, headers=h, method="GET"))

    # ---------------- auth (OAuth2 + PKCE) ----------------
    def _token_request(self, form: dict) -> Tokens:
        st, _h, d = self._post_form(OAUTH_TOKEN_PATH, form)
        if st in (400, 401, 403, 404):
            # invalid_grant: code or refresh token used up, expired or revoked.
            raise ReauthRequired(f"token endpoint HTTP {st} {d}")
        if st != 200:
            raise InPostError(f"token endpoint HTTP {st} {d}")
        if not d.get("access_token") or not d.get("refresh_token"):
            raise ReauthRequired(f"token response without tokens: {sorted(d)}")
        return Tokens(
            access=d["access_token"],
            refresh=d["refresh_token"],
            expires_at=time.time() + float(d.get("expires_in") or 0),
        )

    def exchange_code(self, code: str, verifier: str) -> Tokens:
        """Trade the authorization code from the callback URL for tokens."""
        return self._token_request({
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "authorization_code",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "code_verifier": verifier,
            "code": code,
        })

    def refresh(self, refresh_token: str) -> Tokens:
        return self._token_request({
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

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


class InPostSession:
    """Access token cache for one account; refreshes and tracks rotation.

    Thread-safe: the coordinator calls it from executor threads (poll and share
    can overlap). `refresh_token` always holds the newest refresh token; the
    owner persists it when `rotated` is set (single-use tokens would otherwise
    be lost on restart).
    """

    def __init__(self, api: InPostApi, refresh_token: str) -> None:
        self._api = api
        self.refresh_token = refresh_token
        self._access: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()
        self.rotated = False

    def authorization(self, force: bool = False) -> str:
        """`Authorization` header value, refreshing when due (or forced)."""
        with self._lock:
            if force or not self._access or time.time() > self._expires_at - EXPIRY_MARGIN:
                tokens = self._api.refresh(self.refresh_token)
                self._access, self._expires_at = tokens.access, tokens.expires_at
                if tokens.refresh != self.refresh_token:
                    self.refresh_token = tokens.refresh
                    self.rotated = True
            return f"Bearer {self._access}"

    def adopt(self, tokens: Tokens) -> None:
        """Start from tokens just obtained in the config flow."""
        with self._lock:
            self._access, self._expires_at = tokens.access, tokens.expires_at
            self.refresh_token = tokens.refresh
