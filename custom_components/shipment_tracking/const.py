"""Constants for the Shipment Tracking (Śledzenie przesyłek) integration.

Multi-carrier: InPost (lockers, QR, multiskrytka), DPD (to-address, status
history), FedEx (official REST API, track-by-number) and Pocztex (Keycloak
OAuth2, account auto-discovery). Each config entry carries a ``carrier``
discriminator; entries created before multi-carrier support default to
InPost.

v2.4.0 (2026-08-25): Pocztex's carrier module replaced — the first cut
(same-day v2.3.0) used Poczta Polska's official track-by-number SOAP service
because Pocztex Mobile's own app needs email/password + ToS registration
(heavier than InPost/DPD's SMS flow) to unlock its phone-based
auto-discovery. Then it turned out that gate is only for *creating* an
account — an *existing* one logs in fine over plain HTTP (Keycloak
authorization_code+PKCE, no browser needed), and its
/api/customer/tracking endpoint gives real account auto-discovery, same
shape as DPD/InPost. That's strictly better than track-by-number, so it
replaced it rather than living alongside it. GLS is the only
originally-planned carrier still untouched.

v2.2.0 (2026-08-25): FedEx added — architecturally the odd one out. InPost/DPD
are reverse-engineered consumer apps (phone+SMS, auto-discover "my parcels").
FedEx is developer.fedex.com's documented Track API (OAuth2 client_credentials,
one Client ID/Secret per FedEx developer org project) with no account-level
auto-discovery at all — recipients aren't tied to a phone number the way
InPost/DPD's consumer apps work, so the config entry holds a manually-maintained
tracking-number list (options, not auth data) instead. DHL Parcel Polska and
Allegro One were also scouted the same day: DHL got a full spike (see
HANDOVER-20260825-dhl-parcel-api-research.md) but hit a 24h account lockout
before a working handshake; Allegro turned out track-by-number only, same
shape as FedEx, deferred (no test waybill on hand). GLS + Pocztex still
untouched.

v2.0.0 (2026-08-25): version bumped from 1.x to signal a real scope change, not
an incremental fix — this stopped being "InPost with a DPD side-quest" the day
the InPost carrier module was brought to parity with prod (app-to-app sharing,
button/switch entities, carrier-prefixed identifiers so DPD/InPost never
collide under the shared domain). Framework target: InPost + DPD today, DHL +
GLS + Pocztex planned (zero existing protocol research for any of the three —
each needs its own reverse-engineering spike, same as DPD got 2026-08-06).

**Cutover to prod done 2026-08-25** (same day as the parity merge — Faza 4 of
the rework plan, no SMS re-onboarding needed): the three ``inpost``-domain
config entries (Jarek/Marian/Betacom) carried a non-rotating refresh_token, so
new ``shipment_tracking`` entries were created directly in
``core.config_entries`` reusing those tokens, verified live, then the old
``inpost`` entries were deleted and the 42 resulting entities (which had
landed on ``_2``/collision-suffixed entity_ids next to the still-live old
ones) were renamed back to their original entity_id via
``config/entity_registry/update`` over the WS API — so cards/automations
built against ``sensor.inpost_<alias>_*`` kept working unchanged. The old
``custom_components/inpost`` (v0.8.0) files are still on disk on prod
(orphaned, no config entry references them) — not yet cleaned up.

Gotcha hit during cutover: a first restart with 6 InPost-family config
entries loading at once took several minutes (still investigating whether
``_async_reload_peers_missing_us``'s peer-reload cascade was the cause) —
long enough that it looked hung from the outside. Do not assume a slow InPost
restart is stuck; check the container's own log timestamps for real silence
before intervening.
"""

from datetime import timedelta

DOMAIN = "shipment_tracking"

# ---- Carriers ----
CONF_CARRIER = "carrier"
CARRIER_INPOST = "inpost"
CARRIER_DPD = "dpd"
CARRIER_FEDEX = "fedex"
CARRIER_POCZTEX = "pocztex"
CARRIER_DHL = "dhl"
CARRIERS = [CARRIER_INPOST, CARRIER_DPD, CARRIER_FEDEX, CARRIER_POCZTEX, CARRIER_DHL]
CARRIER_LABELS = {
    CARRIER_INPOST: "InPost Paczkomaty",
    CARRIER_DPD: "DPD",
    CARRIER_FEDEX: "FedEx",
    CARRIER_POCZTEX: "Pocztex",
    CARRIER_DHL: "DHL",
}

# ---- Common config-entry data keys ----
CONF_ALIAS = "alias"
CONF_PREFIX = "prefix"
CONF_PHONE = "phone"
CONF_REFRESH_TOKEN = "refresh_token"

# ---- DHL config-entry data keys ----
CONF_DEVICE_ID = "device_id"
CONF_COOKIES = "cookies"

# ---- FedEx config-entry data keys ----
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ACCOUNT_NUMBER = "account_number"

# ---- Pocztex config-entry data keys ----
CONF_EMAIL = "email"

# ---- FedEx options ----
CONF_TRACKING_NUMBERS = "tracking_numbers"

# ---- InPost options ----
# A manual escape hatch for zombie records InPost's own /v4/parcels/tracked
# keeps returning after the app itself has stopped showing them (found live
# 2026-08-27: a parcel with operations.delete=true and an internally
# inconsistent eventLog — a DELIVERED entry sandwiched between two
# SENT_FROM_SOURCE_BRANCH ones — sat in "w drodze" for 10+ days while the
# user could no longer find it in InPost Mobile at all). There is no known
# API endpoint to delete/hide a tracked parcel (checked IFOSSA/inpost-python,
# the only public reverse-engineered client — operations.delete is a
# capability flag the app's own UI reads, its actual endpoint was never
# reverse-engineered by anyone), so this integration can't clean the record
# up server-side; it can only stop showing it locally.
CONF_IGNORED_SHIPMENTS = "ignored_shipments"

# ---- Options ----
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ARCHIVE_LIMIT = "archive_limit"
CONF_NOTIFY = "notify_ready"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)
DEFAULT_ARCHIVE_LIMIT = 20

# Fixed number of QR image slots per InPost account (see image.py).
QR_SLOTS = 6

# =========================== InPost ===========================
# Legacy SMS-auth backend (no captcha).
DEFAULT_BASE = "https://api-inmobile-pl.easypack24.net"
DEFAULT_UA = "InPost-Mobile/3.23.0(32300001) (Android 9; unknown; unknown unknown; en)"

READY = {
    "READY_TO_PICKUP",
    "READY_TO_PICKUP_FROM_POK",
    "READY_TO_PICKUP_FROM_BRANCH",
    "STACK_IN_BOX_MACHINE",
}
IN_TRANSIT = {
    "CONFIRMED",
    "ADOPTED_AT_SOURCE_BRANCH",
    "SENT_FROM_SOURCE_BRANCH",
    "COLLECTED_FROM_SENDER",
    "TAKEN_BY_COURIER",
    "ADOPTED_AT_SORTING_CENTER",
    "OUT_FOR_DELIVERY",
    "OUT_FOR_DELIVERY_TO_ADDRESS",
    "DISPATCHED_BY_SENDER",
    "REDIRECT_TO_BOX",
    "READDRESSED",
    "OFFERS_PREPARED",
    "OFFER_SELECTED",
    "CREATED",
}
ARCHIVED = {
    "DELIVERED",
    "PICKUP_TIME_EXPIRED",
    "CANCELED",
    "RETURNED_TO_SENDER",
    "AVIZO",
    "CLAIMED",
    "UNSTACK_FROM_BOX_MACHINE",
}

STATUS_PL = {
    "READY_TO_PICKUP": "Gotowa do odbioru",
    "READY_TO_PICKUP_FROM_POK": "Gotowa (punkt)",
    "READY_TO_PICKUP_FROM_BRANCH": "Gotowa (oddział)",
    "STACK_IN_BOX_MACHINE": "W skrytce",
    "CONFIRMED": "Potwierdzona",
    "ADOPTED_AT_SOURCE_BRANCH": "Przyjęta (oddział nadania)",
    "SENT_FROM_SOURCE_BRANCH": "Wysłana z oddziału",
    "COLLECTED_FROM_SENDER": "Odebrana od nadawcy",
    "TAKEN_BY_COURIER": "U kuriera",
    "ADOPTED_AT_SORTING_CENTER": "W sortowni",
    "OUT_FOR_DELIVERY": "W doręczeniu",
    "OUT_FOR_DELIVERY_TO_ADDRESS": "W doręczeniu (adres)",
    "DISPATCHED_BY_SENDER": "Nadana przez nadawcę",
    "REDIRECT_TO_BOX": "Przekierowana do paczkomatu",
    "READDRESSED": "Przeadresowana",
    "OFFERS_PREPARED": "Oferta przygotowana",
    "OFFER_SELECTED": "Oferta wybrana",
    "CREATED": "Utworzona",
    "DELIVERED": "Odebrana",
    "PICKUP_TIME_EXPIRED": "Czas odbioru minął",
    "CANCELED": "Anulowana",
    "RETURNED_TO_SENDER": "Zwrócona do nadawcy",
    "AVIZO": "Awizowana",
    "CLAIMED": "Reklamacja",
    "UNSTACK_FROM_BOX_MACHINE": "Wyjęta ze skrytki",
}


def status_pl(status: str) -> str:
    return STATUS_PL.get(status or "", status or "—")


# InPost's own canonical buckets don't collapse onto DPD/FedEx's shared
# vocabulary (created/in_transport/handed_out_for_delivery/delivered/...) —
# "ready" means "sitting in a locker with a pickup code/QR", a locker-specific
# concept the other carriers don't have (DPD's closest analogue,
# waiting_for_pickup, is a courier pickup point, not a coded locker). So
# InPost keeps its own three buckets rather than being forced into the
# others' shape; only the *pattern* (raw -> canonical -> label/is_active) is
# shared, same as dpd_canonical()/fedex_canonical() below.
INPOST_TERMINAL = {"archived"}


def inpost_canonical(raw: str) -> str:
    """Map a raw InPost status to its canonical bucket (ready/in_transit/archived)."""
    if raw in READY:
        return "ready"
    if raw in IN_TRANSIT:
        return "in_transit"
    return "archived"


def inpost_is_active(raw: str) -> bool:
    return inpost_canonical(raw) not in INPOST_TERMINAL


# ============================ DPD =============================
# Polish DPD mobile-app backend (dpdsso Keycloak realm DPD + mobapp packages).
# NOTE: NOT the GEOPOST myDPD/dpdgroup.com platform (email/password) — DPD Poland
# recipients authenticate by phone number + SMS. Verified live 2026-08-06 against
# a real account. Reimplemented from the observed protocol; no code copied.
DPD_SSO_URL = "https://dpdsso.dpd.com.pl"
DPD_API_URL = "https://mobapp.dpd.com.pl"
DPD_REALM = "DPD"
DPD_CLIENT_ID = "DPDClientMDU"
DPD_UA = "DPD Mobile"
DPD_MOBILE_PLATFORM = "android"
DPD_MOBILE_VERSION = "2.10.2"

# Canonical status buckets -> Polish labels. Raw DPD statuses verified live:
# READY_TO_SEND, RECEIVED_FROM_SENDER, IN_TRANSPORT, RECEIVED_IN_DEPOT,
# HANDED_OVER_FOR_DELIVERY, DELIVERED. Others mapped by keyword in dpd_canonical().
DPD_CANONICAL_PL = {
    "created": "Utworzona",
    "in_transport": "W transporcie",
    "handed_out_for_delivery": "W doręczeniu",
    "waiting_for_pickup": "Do odbioru",
    "delivered": "Dostarczona",
    "returned": "Zwrócona do nadawcy",
    "cancelled": "Anulowana",
    "exception": "Problem",
    "unknown": "—",
}

# Buckets meaning the parcel is no longer active (not counted / archived).
DPD_TERMINAL = {"delivered", "returned", "cancelled"}


def dpd_canonical(raw: str) -> str:
    """Map a raw DPD status to a canonical bucket (keyword heuristic).

    Reimplemented from the observed DPD status vocabulary; unknown strings fall
    back to a keyword scan, then ``unknown``.
    """
    s = (raw or "").strip().lower()
    if not s:
        return "unknown"
    exact = {
        "ready_to_send": "created",
        "received_from_sender": "in_transport",
        "in_transport": "in_transport",
        "received_in_depot": "in_transport",
        "handed_over_for_delivery": "handed_out_for_delivery",
        "delivered": "delivered",
    }
    if s in exact:
        return exact[s]
    if any(x in s for x in ("out_for_delivery", "handed_over")):
        return "handed_out_for_delivery"
    if any(x in s for x in ("ready_to_pick", "ready_for_pick", "pickup", "collection", "locker", "awizo")):
        return "waiting_for_pickup"
    if any(x in s for x in ("delivered", "picked_up", "collected")):
        return "delivered"
    if "return" in s:
        return "returned"
    if "cancel" in s:
        return "cancelled"
    if any(x in s for x in ("fail", "problem", "undeliver", "reject", "exception")):
        return "exception"
    if any(
        x in s
        for x in ("transport", "transit", "depot", "sorting", "received", "sent", "adopted", "arrived", "departed")
    ):
        return "in_transport"
    if any(x in s for x in ("created", "label", "confirmed")):
        return "created"
    return "unknown"


def dpd_status_pl(raw: str) -> str:
    return DPD_CANONICAL_PL.get(dpd_canonical(raw), raw or "—")


def dpd_is_active(raw: str) -> bool:
    """A DPD parcel is active until it is delivered / returned / cancelled."""
    return dpd_canonical(raw) not in DPD_TERMINAL


# ============================ FedEx ============================
# Official FedEx REST API (developer.fedex.com) — OAuth2 client_credentials,
# not a reverse-engineered consumer app like InPost/DPD. No phone/SMS,
# no auto-discovery of "my parcels": FedEx's Track API is track-by-number
# only, so this carrier's config entry holds a manually-maintained list of
# tracking numbers (CONF_TRACKING_NUMBERS in options) instead of an account.
# Verified live 2026-08-25 against the sandbox environment (mock waybill
# 449044304137821, a FedEx-published test number — "VIRTUAL.RESPONSE" alert
# confirms it's their canned sandbox reply, not a real parcel) and against a
# real production OAuth token (JWT apimode:"Live"). Track-by-number itself
# not yet exercised against a real production waybill.
FEDEX_OAUTH_URL = "https://apis.fedex.com/oauth/token"
FEDEX_TRACK_URL = "https://apis.fedex.com/track/v1/trackingnumbers"
# Up to 30 tracking numbers per request — documented FedEx Track API limit.
FEDEX_MAX_NUMBERS_PER_REQUEST = 30

# Canonical status buckets -> Polish labels.
FEDEX_CANONICAL_PL = {
    "created": "Utworzona",
    "in_transport": "W transporcie",
    "handed_out_for_delivery": "W doręczeniu",
    "delivered": "Dostarczona",
    "exception": "Problem",
    "cancelled": "Anulowana",
    "unknown": "—",
}

FEDEX_TERMINAL = {"delivered", "cancelled"}

# derivedCode -> canonical bucket. Only "IN" verified live this session
# (sandbox mock response). The rest are FedEx's long-standing, widely
# documented derived-status codes (used across third-party FedEx tracking
# integrations for years) but NOT individually verified live — treat as
# well-attested, not confirmed. Unknown codes fall back to a keyword scan
# over statusByLocale/description, then "unknown", same pattern as DPD.
_FEDEX_DERIVED_EXACT = {
    "IN": "created",  # Initiated — verified live 2026-08-25
    "PU": "in_transport",  # Picked up
    "IT": "in_transport",  # In transit
    "OD": "handed_out_for_delivery",  # Out for delivery
    "DL": "delivered",  # Delivered
    "DE": "exception",  # Delivery exception
    "CA": "cancelled",  # Shipment canceled
}


def fedex_canonical(derived_code: str, status_text: str = "") -> str:
    """Map a FedEx ``latestStatusDetail.derivedCode`` (+ fallback text) to a
    canonical bucket. Reimplemented from the documented derived-code table;
    unknown codes fall back to a keyword scan of the status text."""
    code = (derived_code or "").strip().upper()
    if code in _FEDEX_DERIVED_EXACT:
        return _FEDEX_DERIVED_EXACT[code]
    s = (status_text or "").strip().lower()
    if not s:
        return "unknown"
    if "deliver" in s and "exception" not in s and "out for" not in s:
        return "delivered"
    if "out for delivery" in s:
        return "handed_out_for_delivery"
    if any(x in s for x in ("cancel",)):
        return "cancelled"
    if any(x in s for x in ("exception", "delay", "problem", "fail")):
        return "exception"
    if any(x in s for x in ("transit", "picked up", "departed", "arrived", "shipment information")):
        return "in_transport"
    if any(x in s for x in ("initiated", "created", "label")):
        return "created"
    return "unknown"


def fedex_status_pl(derived_code: str, status_text: str = "") -> str:
    return FEDEX_CANONICAL_PL.get(fedex_canonical(derived_code, status_text), status_text or "—")


def fedex_is_active(derived_code: str, status_text: str = "") -> bool:
    return fedex_canonical(derived_code, status_text) not in FEDEX_TERMINAL


# =========================== Pocztex ===========================
# Pocztex Mobile's own backend — Keycloak OAuth2 authorization_code+PKCE
# (idm.pocztex.pl, realm "ppsa") for auth, aplikacja.pocztex.pl/api/customer/
# tracking for the recipient parcel list. Superseded an earlier SOAP
# track-by-number implementation (Poczta Polska's official tt.poczta-polska.pl
# tracking web service) once this proved auto-discovery — like DPD/InPost —
# actually works and isn't gated behind self-service signup (registration is
# app-only, but an existing account logs in fine over plain HTTP with no
# browser). Reimplemented from the observed protocol; no code copied.
#
# Verified live 2026-08-25 against a real account: full login (email+password
# -> PKCE code -> token exchange, zero browser involved), GET .../tracking
# with a real Bearer token returning real parcels (2 delivered, numbers
# PX-prefixed — matches third-party docs on Pocztex's number format).
# direct password grant is explicitly disabled for this client
# ("Client not allowed for direct access grants") and offline_access scope
# is rejected ("Invalid scopes") — both confirmed by the server's own error,
# not assumed — hence the full PKCE login() dance instead of a one-shot
# password grant.
#
# SESSION LIFETIME (corrected 2026-08-26, live, twice — see
# coordinator_pocztex.py for the full story): this client's Keycloak
# session has a hard, non-extendable 30-minute cap. refresh() mints a
# genuinely new token (fresh jti) each call, but the decoded JWT's iat/exp
# stay pinned to the ORIGINAL login instant regardless — "refresh often
# enough to never let the session idle out" doesn't apply, there is no
# idle timer to reset. The only way to stay authenticated past 30 minutes
# is a fresh login(), which is why the config entry stores the account
# password (config_flow.py) and the coordinator re-logs-in every poll
# instead of refreshing.
POCZTEX_IDM_URL = "https://idm.pocztex.pl"
POCZTEX_REALM = "ppsa"
POCZTEX_CLIENT_ID = "customer-front"
POCZTEX_APP_URL = "https://aplikacja.pocztex.pl"
POCZTEX_REDIRECT_URI = f"{POCZTEX_APP_URL}/app/"
POCZTEX_TRACKING_URL = f"{POCZTEX_APP_URL}/api/customer/tracking"


def pocztex_is_active(progress_percentage) -> bool:
    """Only ``progressPercentage`` (0-100) was seen live, and only at 100
    (both test parcels were already delivered) — no in-transit example to
    confirm intermediate values behave as expected. Treating <100 as active
    is the obvious reading of a progress percentage, not verified beyond
    the terminal case."""
    try:
        return float(progress_percentage or 0) < 100
    except (TypeError, ValueError):
        return True


# ============================= DHL ==============================
# "Mój DHL" (pl.mojdhl.app), DHL eCommerce/Parcel Polska — a Next.js web app
# (mojdhl.pl) reverse-engineered by reading its own JS bundle, no APK
# decompilation needed (endpoints appear as plaintext in the shipped chunks).
#
# Auth: phone + SMS, same shape as InPost/DPD, but gated by an Altcha
# proof-of-work captcha (solved by brute-forcing SHA-256(salt+n)==challenge
# for n in 0..maxnumber, ~100000 — a fraction of a second) on every auth
# call. ``prefix`` must be sent WITHOUT a leading "+" ("48", not "+48") —
# confirmed live, "+48" gets a 422 "Prefix is incorrect".
#
# SESSION MECHANICS (verified live 2026-08-26, in-browser AND from a plain
# stdlib http.cookiejar client — deliberately checked both, because Pocztex
# looked fine in-browser-adjacent testing too and wasn't): GET /auth/refresh
# (no body, no token param — just ?deviceId=&deviceName=) mints a token with
# a genuinely fresh ``iat`` = the call's own timestamp (decoded JWT,
# cross-checked against wall-clock `date -u`), a real sliding 30-minute
# window, NOT pinned to the original login like Pocztex's. What carries the
# session is the httpOnly cookies set during login (BIGipServer.../TS...,
# Secure, no Max-Age — session-scoped, not readable from JS) — not the
# opaque ``refresh`` string the login response also returns (that field's
# actual consumer, if any, wasn't identified; refresh_session() works
# without ever sending it). So the DHL carrier module persists cookies,
# not a token string, across polls (api_dhl.py/coordinator_dhl.py).
#
# PARTLY ANSWERED 2026-08-28. What is PROVEN: a login-time jar that is ~30
# HOURS old is rejected. Both accounts came up "DHL session expired" after
# the first restart, the stored ``access-token`` was a JWT whose ``exp`` sat
# at login + 30 min (long past), and replaying that stored set against
# /auth/refresh returned 401 — with AND without the expired access-token
# alongside it, so ``access-remember`` alone did not carry it either.
#
# What is NOT proven, and was briefly written here as if it were: WHY. The
# 401 is equally consistent with (a) the set rotating and the old one being
# spent, and (b) it simply having aged out. Evidence for (b) arrived the same
# evening: after a fresh SMS reauth at 18:54/18:58 the entries survived a
# 19:05 HA restart on the still-login-time jar, ~11 minutes old. So "spent by
# the first refresh" is wrong as stated — an hours-old jar dies, a
# minutes-old one does not, and the boundary is unmeasured.
#
# Either way the fix is the same and is what matters: keep the STORED jar
# fresh, so a restart restores a jar that is minutes old rather than hours.
# The coordinator writes it back to entry.data on every poll.
#
# ANSWERED 2026-09-04, and the 28.08 conclusion above was only half right.
# The sliding window is real but was never being used: the token minted by
# /auth/refresh went to get_parcels() and nowhere else, so the jar kept the
# LOGIN-TIME credential and the session died 30 minutes after the SMS —
# restart or no restart, poll frequency irrelevant. "Keep the stored jar
# fresh" could not work, because the jar never moved: both entries'
# modified_at stayed pinned to the SMS login (09:00:15 / 08:57:39 on 09-03),
# the stored access-token's exp sat at exactly login+30 min, and the reauth
# was raised on the first poll past that (09:45 / 09:43).
#
# The server states the mechanism itself. Replaying a dead jar against
# /auth/refresh returns:
#     HTTP/1.1 401 Unauthorized
#     WWW-Authenticate: Bearer error="invalid_token",
#       error_description="The token expired at '09/03/2026 09:30:14'"
# — the stored cookie's own exp, to the second. So /auth/refresh
# authenticates with the access-token cookie AS a bearer token, and the only
# cookie it re-issues is F5's TS…; it never sets a new access-token.
#
# The credential is SPLIT ACROSS TWO COOKIES: access-token holds
# header.payload (2 segments, 560 chars live) and access-signature holds the
# 43-char HS256 signature. api_dhl._adopt_access_token() re-splits each
# minted token the same way and puts it back in the jar, which is what makes
# the window slide — and, as a side effect, finally gives the coordinator a
# changed jar to persist. The poll interval is therefore also the keepalive;
# coordinator_dhl clamps it to 20 min (DHL_MAX_INTERVAL).
DHL_BASE = "https://mojdhl.pl/api/dhl/public"
DHL_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

# STATUS VOCABULARY, sourced 2026-08-28 — read out of the Mój DHL web app's
# own shipped bundle, not guessed and not translated by hand.
#
# The shipment object carries TWO status fields, and the useful one is not
# the obvious one:
#   * ``status`` — an internal code, ``TT_DOR`` / ``TT_LK`` / ``TT_MAG`` …
#     21 of them exist. Downloading every chunk the Next.js build manifest
#     lists (20 files, buildId Yj46M5Uq4I-kB_e3pWByW) and grepping all of
#     them shows these codes appear ONLY as a bare TypeScript enum
#     (``et.TT_DOR="TT_DOR"``). Nothing anywhere maps them to text — DHL's
#     own front end never translates them, so neither can we.
#   * ``menuTimelineLabel.status`` — a semantic key, ``"Delivered"``,
#     ``"DeliveredToLocker"``, ``"Route"`` … and THAT one has a full Polish
#     dictionary in the bundle (chunk 5820). This is what the app renders.
#
# So the label comes from the timeline key, and the raw TT_ code is kept only
# for diagnostics. Every Polish string below is copied verbatim from that
# dictionary — DHL's own wording, so the entity says what the app says.
# ``menuTimelineLabel.label`` is a different vocabulary (date captions:
# ReceiptDate, EstimatedDeliveryDate …) — deliberately not mixed in here.
DHL_CANONICAL_PL = {
    "created": "W przygotowaniu",
    "in_transport": "W transporcie",
    "handed_out_for_delivery": "W doręczeniu",
    "waiting_for_pickup": "Do odbioru",
    "delivered": "Doręczona",
    "returned": "Zwrócona do nadawcy",
    "cancelled": "Anulowana",
    "exception": "Problem",
    "unknown": "—",
}

DHL_TERMINAL = {"delivered", "returned", "cancelled"}

# menuTimelineLabel.status -> (canonical bucket, DHL's own Polish label).
_DHL_TIMELINE = {
    "ShipmentInPreparation": ("created", "Przesyłka w przygotowaniu"),
    "WaitingForCourierPickup": ("created", "Przesyłka czeka na odbiór kuriera"),
    "PostedAtPoint": ("in_transport", "Nadana w punkcie"),
    "PickedUpByCourier": ("in_transport", "Odebrana przez kuriera"),
    "Route": ("in_transport", "W drodze"),
    "DeliveryToPoint": ("in_transport", "W drodze do POP"),
    "DeliveryToLocker": ("in_transport", "W drodze do automatu"),
    "Redirected": ("in_transport", "Przesyłka przekierowana"),
    "RedirectedToPoint": ("in_transport", "Przekierowana do punktu"),
    "Delivery": ("handed_out_for_delivery", "Doręczenie"),
    # Handed over to a locker/point is NOT the end of the road for whoever is
    # waiting for it — it is exactly the "go and collect it" state, same
    # bucket InPost's READY_TO_PICKUP lands in.
    "DeliveredToPoint": ("waiting_for_pickup", "Doręczona do punktu"),
    "DeliveredToLocker": ("waiting_for_pickup", "Doręczona do automatu"),
    "Delivered": ("delivered", "Doręczona"),
    "RetrievedFromPoint": ("delivered", "Odebrana z punktu"),
    "RetrievedFromLocker": ("delivered", "Odebrana z automatu"),
    "Refusal": ("returned", "Odmowa przyjęcia"),
    "ParcelReturnsToSender": ("returned", "Paczka wraca do Nadawcy"),
    "ParcelReturnedToSender": ("returned", "Paczka wróciła do Nadawcy"),
    "Resignated": ("cancelled", "Wycofanie przesyłki przez Nadawcę"),
    "Disposed": ("cancelled", "Przesyłka zutylizowana"),
    # Trouble states stay ACTIVE on purpose — a parcel that is late, refused
    # at the door or lost is precisely the one that must not quietly vanish
    # from the panel into the archive.
    "UnsuccessfulAttemptAtDelivery": ("exception", "Nieudana próba doręczenia"),
    "SecondUnsuccessfulAttemptAtDelivery": ("exception", "Druga nieudana próba doręczenia"),
    "DeliveryDelay": ("exception", "Opóźnienie dostawy"),
    "DeliveryProblem": ("exception", "Mamy problem z doręczeniem Twojej przesyłki"),
    "WaitingForShipperDecision": ("exception", "Oczekujemy na decyzje nadawcy"),
    "ContactDHL": ("exception", "Skontaktuj się z DHL"),
    "Lost": ("exception", "Przesyłka zaginęła"),
}

# Fallback for a shipment with no menuTimelineLabel at all. TT_DOR is the one
# code confirmed live (2026-08-26, "Doręczona" in the UI); the rest have no
# known meaning, so they stay "unknown" rather than become a guess.
_DHL_STATUS_EXACT = {
    "TT_DOR": "delivered",
}


def dhl_canonical(raw: str, timeline_status: str | None = None) -> str:
    """Canonical bucket for one shipment.

    ``timeline_status`` is ``menuTimelineLabel.status`` and wins when known —
    it is the field DHL's own app renders. ``raw`` is the internal TT_ code,
    used only as a fallback and only for the single code confirmed live.
    """
    if timeline_status:
        znane = _DHL_TIMELINE.get(timeline_status.strip())
        if znane:
            return znane[0]
    return _DHL_STATUS_EXACT.get((raw or "").strip().upper(), "unknown")


def dhl_status_pl(raw: str, timeline_status: str | None = None) -> str:
    """Polish label, in DHL's own wording where we have it.

    An unknown timeline key falls back to showing that key, and an unknown
    TT_ code to showing the code — a visible "I do not know this one" beats a
    plausible-looking wrong translation.
    """
    if timeline_status:
        znane = _DHL_TIMELINE.get(timeline_status.strip())
        if znane:
            return znane[1]
        return timeline_status.strip()
    bucket = dhl_canonical(raw)
    if bucket == "unknown":
        return raw or "—"
    return DHL_CANONICAL_PL.get(bucket, raw or "—")


def dhl_is_active(raw: str, timeline_status: str | None = None) -> bool:
    """Unknown statuses default to "active" (not terminal) — safer to show an
    unrecognized parcel as still-tracked than to silently drop it into
    archive on a status this integration has never seen."""
    return dhl_canonical(raw, timeline_status) not in DHL_TERMINAL
