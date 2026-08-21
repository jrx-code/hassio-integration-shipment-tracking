"""Constants for the InPost integration."""
from datetime import timedelta

DOMAIN = "inpost"

# Config-entry data keys
CONF_ALIAS = "alias"
CONF_PREFIX = "prefix"
CONF_PHONE = "phone"
CONF_REFRESH_TOKEN = "refresh_token"

# Options
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ARCHIVE_LIMIT = "archive_limit"
CONF_NOTIFY = "notify_ready"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)
DEFAULT_ARCHIVE_LIMIT = 20

# Fixed number of QR image slots per account. Each slot renders the k-th pickup
# group (multiskrytka collapsed to one group), so this caps *distinct pickups*
# shown simultaneously, not physical parcels. Slot 0 keeps the legacy unique_id
# (`<phone>_qr`) for backward-compatible dashboards.
QR_SLOTS = 6

# Legacy SMS-auth backend (no captcha). The OAuth backend (account.inpost-group.com)
# is gatekept by Cloudflare Turnstile, so this legacy endpoint is used instead.
# Overridable if InPost starts gatekeeping the app version.
DEFAULT_BASE = "https://api-inmobile-pl.easypack24.net"
DEFAULT_UA = "InPost-Mobile/3.23.0(32300001) (Android 9; unknown; unknown unknown; en)"

# InPost status -> logical bucket
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

# Human-readable Polish status labels (UI / attributes).
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
