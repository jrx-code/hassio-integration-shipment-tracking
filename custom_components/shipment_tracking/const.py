"""Constants for the Shipment Tracking (Śledzenie przesyłek) integration.

Multi-carrier: InPost (lockers, QR, multiskrytka) and DPD (to-address, status
history). Each config entry carries a ``carrier`` discriminator; entries created
before multi-carrier support default to InPost.

v2.0.0 (2026-08-25): version bumped from 1.x to signal a real scope change, not
an incremental fix — this stopped being "InPost with a DPD side-quest" the day
the InPost carrier module was brought to parity with prod (app-to-app sharing,
button/switch entities, carrier-prefixed identifiers so DPD/InPost never
collide under the shared domain). Framework target: InPost + DPD today, DHL +
GLS + Pocztex planned (zero existing protocol research for any of the three —
each needs its own reverse-engineering spike, same as DPD got 2026-08-06).

**Cutover to prod done 2026-08-25** (same day as the parity merge — Faza 4 of
the rework plan, no SMS re-onboarding needed): the three ``inpost``-domain
config entries (three) carried a non-rotating refresh_token, so
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
CARRIERS = [CARRIER_INPOST, CARRIER_DPD]
CARRIER_LABELS = {CARRIER_INPOST: "InPost Paczkomaty", CARRIER_DPD: "DPD"}

# ---- Common config-entry data keys ----
CONF_ALIAS = "alias"
CONF_PREFIX = "prefix"
CONF_PHONE = "phone"
CONF_REFRESH_TOKEN = "refresh_token"

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
    "READY_TO_PICKUP", "READY_TO_PICKUP_FROM_POK",
    "READY_TO_PICKUP_FROM_BRANCH", "STACK_IN_BOX_MACHINE",
}
IN_TRANSIT = {
    "CONFIRMED", "ADOPTED_AT_SOURCE_BRANCH", "SENT_FROM_SOURCE_BRANCH",
    "COLLECTED_FROM_SENDER", "TAKEN_BY_COURIER", "ADOPTED_AT_SORTING_CENTER",
    "OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY_TO_ADDRESS", "DISPATCHED_BY_SENDER",
    "REDIRECT_TO_BOX", "READDRESSED", "OFFERS_PREPARED", "OFFER_SELECTED",
    "CREATED",
}
ARCHIVED = {
    "DELIVERED", "PICKUP_TIME_EXPIRED", "CANCELED",
    "RETURNED_TO_SENDER", "AVIZO", "CLAIMED", "UNSTACK_FROM_BOX_MACHINE",
}

STATUS_PL = {
    "READY_TO_PICKUP": "Gotowa do odbioru", "READY_TO_PICKUP_FROM_POK": "Gotowa (punkt)",
    "READY_TO_PICKUP_FROM_BRANCH": "Gotowa (oddział)", "STACK_IN_BOX_MACHINE": "W skrytce",
    "CONFIRMED": "Potwierdzona", "ADOPTED_AT_SOURCE_BRANCH": "Przyjęta (oddział nadania)",
    "SENT_FROM_SOURCE_BRANCH": "Wysłana z oddziału", "COLLECTED_FROM_SENDER": "Odebrana od nadawcy",
    "TAKEN_BY_COURIER": "U kuriera", "ADOPTED_AT_SORTING_CENTER": "W sortowni",
    "OUT_FOR_DELIVERY": "W doręczeniu", "OUT_FOR_DELIVERY_TO_ADDRESS": "W doręczeniu (adres)",
    "DISPATCHED_BY_SENDER": "Nadana przez nadawcę", "REDIRECT_TO_BOX": "Przekierowana do paczkomatu",
    "READDRESSED": "Przeadresowana", "OFFERS_PREPARED": "Oferta przygotowana",
    "OFFER_SELECTED": "Oferta wybrana", "CREATED": "Utworzona",
    "DELIVERED": "Odebrana", "PICKUP_TIME_EXPIRED": "Czas odbioru minął",
    "CANCELED": "Anulowana", "RETURNED_TO_SENDER": "Zwrócona do nadawcy",
    "AVIZO": "Awizowana", "CLAIMED": "Reklamacja", "UNSTACK_FROM_BOX_MACHINE": "Wyjęta ze skrytki",
}


def status_pl(status: str) -> str:
    return STATUS_PL.get(status or "", status or "—")


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
    if any(x in s for x in ("transport", "transit", "depot", "sorting", "received", "sent", "adopted", "arrived", "departed")):
        return "in_transport"
    if any(x in s for x in ("created", "label", "confirmed")):
        return "created"
    return "unknown"


def dpd_status_pl(raw: str) -> str:
    return DPD_CANONICAL_PL.get(dpd_canonical(raw), raw or "—")


def dpd_is_active(raw: str) -> bool:
    """A DPD parcel is active until it is delivered / returned / cancelled."""
    return dpd_canonical(raw) not in DPD_TERMINAL
