"""Constants and status mapping for the ORLEN Paczka *account* carrier.

Unlike ``carriers_orlen_allegro`` (public track-by-number via the consumer
JSONP surface), this carrier logs into the ORLEN Paczka mobile app backend with
the owner's phone number + SMS and lists every parcel addressed to that number
— the auto-discovery the user actually wants.

Backend reverse-engineered from the ``pl.orlen.paczka`` Android app 3.7.0
(React Native / Hermes bundle, decompiled 2026-10-01):

* Azure API Management: ``https://orlenapm.azure-api.net/CustomerAPP2026/v1``
* Bearer token: Entra ID client_credentials flow, app-level (TTL ~1h,
  re-fetched automatically). The tenant, client_id and scope below identify the
  app. The client secret is NOT shipped with this integration: the user enters
  it in the config flow (``CONF_CLIENT_SECRET`` on the entry).
* Durable per-user credentials: the phone number (== ``customerId``) plus a
  self-generated ``deviceId`` (the app uses the Android unique id; any stable
  string works). Established once via SMS; no refresh token, no re-login unless
  the account is deactivated server-side.

Flow verified live 2026-10-01 against a real account (token OK, SMS delivered,
verify → account "Aktywny", GET .../shipments → HTTP 200). The shipments list
was empty at the time, so the per-parcel JSON field names below are best-effort
(read defensively, several key spellings tried) and the numeric status map is
taken from the official ORLEN Paczka API spec v1.26.005 (section 7.3). Lock the
exact field names when the first real parcel appears — the coordinator logs the
raw keys at debug level for exactly that.
"""
from __future__ import annotations

# --- Entra ID (Azure AD) app auth; the client secret comes from the config entry ---
ORLEN_TENANT = "65ea349c-0ecd-4648-96e0-9ff6f64b0880"
ORLEN_CLIENT_ID = "113ecb3c-caa8-44b7-a45f-abdcb72011d7"
ORLEN_SCOPE = "api://9c103a1b-25d8-4aff-bf1c-2496bc00a1bf/.default"
ORLEN_TOKEN_URL = (
    f"https://login.microsoftonline.com/{ORLEN_TENANT}/oauth2/v2.0/token"
)

# --- Customer app API ---
ORLEN_ACCOUNT_API_URL = "https://orlenapm.azure-api.net/CustomerAPP2026/v1"
ORLEN_APP_VERSION = "3.7.0"

CARRIER_ORLEN_ACCOUNT = "orlen_account"
CARRIER_LABEL_ORLEN_ACCOUNT = "Orlen Paczka (konto)"

# Canonical buckets -> Polish labels (shared vocabulary with the other carriers).
ORLEN_ACCOUNT_CANONICAL_PL = {
    "created": "Zaawizowana",
    "in_transit": "W transporcie",
    "out_for_delivery": "W doręczeniu",
    "ready_for_pickup": "Gotowa do odbioru",
    "delivered": "Odebrana",
    "returned": "Zwrot do nadawcy",
    "exception": "Problem",
    "unknown": "—",
}

# Official ORLEN Paczka status codes (spec v1.26.005, 7.3) -> canonical bucket.
# Codes are returned in the SOAP <Trans> field; the app backend is expected to
# reuse the same vocabulary. Keyed as strings so an int or str code both match
# after str().
ORLEN_CODE_BUCKET = {
    "100": "in_transit",       # W sortowni regionalnej
    "110": "in_transit",       # W transporcie do SC z ekspedycji
    "120": "in_transit",       # W transporcie do DP z ekspedycji
    "193": "in_transit",       # Przekierowanie do APM
    "195": "in_transit",       # Przekierowanie do punktu
    "200": "created",          # Zaawizowana do PwR
    "201": "returned",         # Anulowane awizo
    "210": "in_transit",       # Nadana w kiosku
    "230": "in_transit",       # W transporcie do ekspedycji z kiosku
    "240": "in_transit",       # W transporcie do ekspedycji u kuriera
    "241": "in_transit",       # W transporcie po magazynowaniu
    "300": "in_transit",       # W sortowni centralnej
    "400": "in_transit",
    "401": "in_transit",
    "450": "in_transit",       # W transporcie do ekspedycji z SC
    "610": "out_for_delivery",  # Wydana kurierowi DP do doręczenia
    "620": "ready_for_pickup",  # Gotowa do odbioru
    "653": "in_transit",       # W ekspedycji
    "711": "exception",        # Przesyłka w weryfikacji
    "712": "exception",        # Zatrzymana
    "714": "exception",        # Nieczynny POK
    "729": "returned",         # Powrót – niepoprawny kiosk
    "739": "returned",         # Nie przekazano do kiosku
    "749": "exception",        # Reklamacja
    "750": "returned",         # Zwrot do nadawcy
    "780": "exception",        # Brak możliwości doręczenia DP
    "790": "returned",         # Zwrot do ekspedycji
    "800": "returned",         # Zwrot do sortowni
    "888": "delivered",        # Archiwizacja (terminal — treated as closed)
    "900": "returned",         # Zwrot do nadawcy
    "999": "exception",        # Zniszczona – zagubiona
    "1000": "delivered",       # Odebrana przez klienta
    "1100": "returned",        # Odebrana (powrót)
    "1200": "returned",        # Odebrana – zwrot
    "1220": "returned",        # Zwrot do nadawcy
    "2000": "exception",       # Likwidacja
}

# Buckets meaning the parcel is no longer active (archived, not counted).
ORLEN_ACCOUNT_TERMINAL = {"delivered", "returned"}


def orlen_account_canonical(status_code: str | int | None, status_text: str = "") -> str:
    """Map an ORLEN account status to a canonical bucket.

    Prefers the numeric code (official table); falls back to a keyword scan of
    the human status text so an unknown code still lands somewhere sensible
    instead of vanishing.
    """
    code = str(status_code).strip() if status_code is not None else ""
    if code in ORLEN_CODE_BUCKET:
        return ORLEN_CODE_BUCKET[code]
    s = (status_text or "").strip().lower()
    if not s:
        return "unknown"
    if any(x in s for x in ("odebran", "doręczon", "doreczon", "wydana klientowi")):
        return "delivered"
    if any(x in s for x in ("gotowa do odbioru", "oczekuje na odbiór", "do odbioru")):
        return "ready_for_pickup"
    if any(x in s for x in ("doręczen", "doreczen", "kurierowi")):
        return "out_for_delivery"
    if any(x in s for x in ("zwrot", "powrót", "powrot", "anulow")):
        return "returned"
    if any(x in s for x in ("zaawizowan", "awizo", "zarejestrow")):
        return "created"
    if any(x in s for x in ("reklamacj", "zatrzyman", "weryfikacj", "nieczynny", "zniszczon", "zagubion", "likwidacj")):
        return "exception"
    if any(x in s for x in ("sortown", "transporc", "transport", "ekspedycj", "magazyn", "kiosk", "przekierowan")):
        return "in_transit"
    return "unknown"


def orlen_account_status_pl(status_code: str | int | None, status_text: str = "") -> str:
    """Human label: the carrier's own text if present, else the bucket label."""
    text = (status_text or "").strip()
    if text:
        return text
    bucket = orlen_account_canonical(status_code, status_text)
    return ORLEN_ACCOUNT_CANONICAL_PL.get(bucket, "—")


def orlen_account_is_active(status_code: str | int | None, status_text: str = "") -> bool:
    """Active until the parcel is delivered or returned."""
    return orlen_account_canonical(status_code, status_text) not in ORLEN_ACCOUNT_TERMINAL
