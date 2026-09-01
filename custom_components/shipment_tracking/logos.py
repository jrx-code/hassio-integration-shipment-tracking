"""Carrier logos: a static HTTP path plus the ``entity_picture`` URL per carrier.

Home Assistant has exactly ONE brand image per integration domain — the device
registry carries no icon or picture field (checked live on 2026-09-01: a device
entry has ``manufacturer``/``model``/``hw_version``… and nothing image-shaped),
and the frontend fetches ``/api/brands/integration/<domain>/icon.png``, keyed by
domain. So every carrier device under this hub shows the same parcel box, and no
device-level setting can change that.

What CAN differ per carrier is the entity: ``entity_picture`` replaces the icon
wherever an entity is drawn. That is what this module feeds — a real PNG per
carrier, served from the integration's own folder.

The pictures are round-safe: the frontend draws ``entity_picture`` as a circle
with ``background-size: cover``, so each file is a 256² badge in the carrier's
own colours with the mark inscribed in the circle. Built by
``scripts/build_badge_logos.py`` in the panel repo; sources are the carriers'
own press materials.

The static path is public — no auth, like any other frontend asset. These are
logos, nothing account-specific: the QR codes, which ARE account-specific, keep
going through the ``image`` platform with its signed paths.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = f"/{DOMAIN}/logo"
_DIR = Path(__file__).parent / "logos"
_REGISTERED = f"{DOMAIN}_logos_registered"

# Carriers whose badge ships with the integration. A carrier missing here simply
# keeps its mdi icon — never a broken image.
AVAILABLE = {"inpost", "dpd", "fedex", "pocztex", "dhl", "gls"}

# Cache buster. The static route is registered with month-long cache headers, so
# a redrawn badge under the same file name would keep showing the old picture in
# every browser that had already seen it. Bump this whenever the PNGs change.
VERSION = 1


def logo_url(carrier: str) -> str | None:
    """``entity_picture`` for a carrier, or None when we have no badge for it."""
    return f"{URL_BASE}/{carrier}.png?v={VERSION}" if carrier in AVAILABLE else None


async def async_register(hass: HomeAssistant) -> None:
    """Serve the badges under ``/shipment_tracking/logo/`` — once per HA run.

    Registering the same URL twice raises, and this runs from every config
    entry's setup (there are eight of them here), so the guard is not optional.
    It lives in ``hass.data`` rather than a module global: a module global would
    survive a reload of the integration while the aiohttp route would not, and
    the pictures would 404 until the next restart.
    """
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(_DIR), cache_headers=True)]
    )
    _LOGGER.debug("carrier logos served from %s at %s", _DIR, URL_BASE)
