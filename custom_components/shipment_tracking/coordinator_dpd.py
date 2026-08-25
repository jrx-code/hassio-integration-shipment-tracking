"""DataUpdateCoordinator for the DPD carrier."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_dpd import DpdApi, DpdAuthError, DpdError
from .const import (
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    dpd_canonical,
    dpd_is_active,
    dpd_status_pl,
)

_LOGGER = logging.getLogger(__name__)


def normalize_parcel(p: dict, detail: dict | None = None) -> dict:
    """Flatten a raw DPD package into the shape used by entities.

    ``detail`` is the optional richer ``/packages/{waybill}`` response — fetched
    by the coordinator only for active (non-terminal) parcels, since delivered
    ones don't change and it costs one extra HTTP call per parcel. When present
    it adds GPS/courier/mps-group fields not on the list endpoint."""
    ms = p.get("main_status") or {}
    raw = ms.get("status") or ""
    history = [
        {"status": dpd_status_pl(s.get("status")), "raw": s.get("status"), "date": s.get("date")}
        for s in (p.get("statuses") or [])
    ]
    row = {
        "number": p.get("waybill"),
        "sender": (p.get("sender") or {}).get("name"),
        "status": dpd_status_pl(raw),
        "status_raw": raw,
        "canonical": dpd_canonical(raw),
        "updated": ms.get("date"),
        "active": dpd_is_active(raw),
        "history": history,
    }
    if detail:
        sender_addr = (detail.get("sender") or {}).get("address") or {}
        point = (detail.get("delivery_point") or {})
        delivery = detail.get("delivery") or {}
        mps = detail.get("mps") or {}
        siblings = [
            {
                "number": s.get("waybill"),
                "status": dpd_status_pl((s.get("main_status") or {}).get("status")),
                "part": s.get("current_parcel_number"),
            }
            for s in (mps.get("parcels") or [])
        ]
        row.update(
            {
                "sender_address": ", ".join(
                    x for x in (sender_addr.get("address"), sender_addr.get("postal_code"),
                                sender_addr.get("city")) if x
                ) or None,
                "delivery_gps": (
                    {"lat": point.get("latitude"), "lon": point.get("longitude")}
                    if point.get("latitude") and point.get("longitude") else None
                ),
                "courier_name": delivery.get("courier_name"),
                "courier_phone": delivery.get("courier_phone"),
                "delivered_datetime": delivery.get("delivered_datetime"),
                "mps_part": mps.get("current_parcel_number") if mps.get("parcels_count", 1) > 1 else None,
                "mps_count": mps.get("parcels_count") if mps.get("parcels_count", 1) > 1 else None,
                "mps_siblings": siblings or None,
            }
        )
    return row


class DpdCoordinator(DataUpdateCoordinator[dict]):
    """Poll one DPD account (phone) and expose active / delivered parcels.

    The DPD refresh token is not single-use (verified 2026-08-06) — the stored
    one keeps working across polls even after Keycloak issues a rotated one — so
    we deliberately do NOT persist the rotated token. (Persisting via
    async_update_entry during the first refresh interfered with entry setup and
    left the coordinator empty until a reload.) If the stored token eventually
    expires, refresh raises DpdAuthError -> reauth.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL)
        update_interval = (
            timedelta(minutes=int(interval)) if interval else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_dpd_{entry.data.get(CONF_PHONE, entry.entry_id)}",
            update_interval=update_interval,
        )
        self.entry = entry
        self._api = DpdApi()

    def _fetch(self) -> dict:
        """Blocking fetch — runs in the executor."""
        access, _new_refresh = self._api.refresh(self.entry.data[CONF_REFRESH_TOKEN])
        raw_parcels = self._api.get_parcels(access)
        parcels = []
        for p in raw_parcels:
            raw_status = (p.get("main_status") or {}).get("status") or ""
            detail = None
            if dpd_is_active(raw_status):
                # Only active parcels get the extra per-waybill call — delivered
                # ones are terminal and won't change, not worth the API cost.
                try:
                    detail = self._api.get_parcel_detail(access, p.get("waybill"))
                except DpdAuthError:
                    raise  # token died mid-poll -> propagate to trigger reauth
                except DpdError as err:
                    _LOGGER.debug("DPD detail fetch failed for %s: %s", p.get("waybill"), err)
            parcels.append(normalize_parcel(p, detail))
        active = [p for p in parcels if p["active"]]
        delivered = [p for p in parcels if not p["active"]]
        return {
            "active": active,
            "delivered": delivered,
            "all": parcels,
            "counts": {"active": len(active), "delivered": len(delivered)},
        }

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except DpdAuthError as err:
            raise ConfigEntryAuthFailed("DPD token expired") from err
        except DpdError as err:
            raise UpdateFailed(str(err)) from err
