"""Orlen Paczka + Allegro One constants and status mapping.

Split out of const.py so the wiring commit stays reviewable; imported
into const for a single import site used by coordinators/tests.
"""
# ============================ Orlen Paczka ============================
# Public JSONP track-by-number endpoint used by orlenpaczka.pl / jwilk/pacz —
# NOT the partner SOAP API (which needs PartnerID/PartnerKey). No account,
# no OAuth: the config entry holds a manually maintained tracking-number list
# in options, same shape as FedEx/Allegro One.
# Verified live 2026-09-18: unknown id -> {"err":1003}; schema matches pacz.
ORLEN_API_URL = "https://nadaj.orlenpaczka.pl/parcel/api-status"
ORLEN_UA = "HomeAssistant-ShipmentTracking/2.10"

ORLEN_CANONICAL_PL = {
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

ORLEN_TERMINAL = {"delivered", "returned", "cancelled"}


def orlen_canonical(status_text: str) -> str:
    """Map Orlen status/label text to a canonical bucket (keyword heuristic).

    The public JSONP endpoint returns free-text Polish labels, not stable
    codes — same fallback pattern as FedEx's statusByLocale scan.
    """
    s = (status_text or "").strip().lower()
    if not s:
        return "unknown"
    if any(x in s for x in ("anulow", "cancel", "canceled", "cancelled")):
        return "cancelled"
    if any(x in s for x in ("zwrot", "zwróc", "zwroc", "return")):
        return "returned"
    if any(x in s for x in ("odebra", "doręczon", "doreczon", "wydan odbior", "delivered")):
        return "delivered"
    if any(x in s for x in ("oczekuje na odbiór", "oczekuje na odbior", "do odbioru", "w punkcie", "pickup", "awaiting pick")):
        return "waiting_for_pickup"
    if any(x in s for x in ("wydan do doręczenia", "wydana do doręczenia", "w doręczeniu", "out for delivery")):
        return "handed_out_for_delivery"
    if any(x in s for x in ("problem", "błąd", "blad", "exception", "fail")):
        return "exception"
    if any(x in s for x in ("przygotow", "utworzon", "created", "label")):
        return "created"
    if any(x in s for x in ("w drodze", "transpor", "sortown", "przyjęt", "przyjet", "nadan", "kurier", "depot", "transit")):
        return "in_transport"
    return "unknown"


def orlen_status_pl(status_text: str) -> str:
    bucket = orlen_canonical(status_text)
    if bucket == "unknown":
        return (status_text or "").strip() or "—"
    # Prefer the carrier's own wording when we have it.
    return (status_text or "").strip() or ORLEN_CANONICAL_PL.get(bucket, "—")


def orlen_is_active(status_text: str) -> bool:
    return orlen_canonical(status_text) not in ORLEN_TERMINAL


# ============================ Allegro One ============================
# Public edge tracking endpoint (no OAuth) used by Allegro's own tracking
# page / jwilk/pacz — NOT api.allegro.pl/order/carriers/... which requires
# a seller OAuth token. Waybills are Allegro-internal (A… / AD…), not the
# subcontractor number. Track-by-number list in options, like FedEx/Orlen.
# Verified live 2026-09-18 against A000YR4D27 (full Polish status history).
# Risk: undocumented internal Accept media type; may change without notice.
ALLEGRO_ONE_API_URL = "https://edge.allegro.pl/ad/tracking"
ALLEGRO_ONE_UA = "HomeAssistant-ShipmentTracking/2.10"

ALLEGRO_ONE_CANONICAL_PL = {
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

ALLEGRO_ONE_TERMINAL = {"delivered", "returned", "cancelled"}


def allegro_one_canonical(status_text: str) -> str:
    """Map Allegro One status description to a canonical bucket.

    Descriptions are free text (PL with Accept-Language: pl-PL, else EN).
    Captured live 2026-09-18 sample included: przygotowana przez nadawcę,
    odebrana przez kuriera, przyjęta w oddziale, wydana do doręczenia,
    oczekuje na odbiór, została doręczona.
    """
    s = (status_text or "").strip().lower()
    if not s:
        return "unknown"
    if any(x in s for x in ("anulow", "cancel")):
        return "cancelled"
    if any(x in s for x in ("zwrot", "zwróc", "zwroc", "return")):
        return "returned"
    if any(x in s for x in ("doręczon", "doreczon", "delivered", "has been delivered")):
        return "delivered"
    if any(x in s for x in ("oczekuje na odbiór", "oczekuje na odbior", "awaiting pick", "do odbioru")):
        return "waiting_for_pickup"
    if any(x in s for x in ("wydan", "doręczenia", "doreczenia", "out for delivery", "released for delivery")):
        return "handed_out_for_delivery"
    if any(x in s for x in ("problem", "exception", "fail")):
        return "exception"
    if any(x in s for x in ("przygotow", "prepared by the sender", "utworzon")):
        return "created"
    if any(x in s for x in ("kurier", "oddział", "oddzial", "przyjęt", "przyjet", "accepted", "picked up", "branch", "transit", "w drodze")):
        return "in_transport"
    return "unknown"


def allegro_one_status_pl(status_text: str) -> str:
    bucket = allegro_one_canonical(status_text)
    if bucket == "unknown":
        return (status_text or "").strip() or "—"
    return (status_text or "").strip() or ALLEGRO_ONE_CANONICAL_PL.get(bucket, "—")


def allegro_one_is_active(status_text: str) -> bool:
    return allegro_one_canonical(status_text) not in ALLEGRO_ONE_TERMINAL
