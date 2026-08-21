"""InPost QR images: one scannable code per pickup group.

A fixed set of ``QR_SLOTS`` image entities is created per account; slot *k*
renders the k-th pickup group (multiskrytka collapsed to a single group — see
``pickup.pickup_groups``), so several ready parcels each get their own QR while a
multiskrytka shows one leader QR. Slots with no group go unavailable.

Slot 0 keeps the legacy unique_id (``<phone>_qr``) and name ("QR do odbioru") so
existing dashboards keep working unchanged.

Notification-agnostic: any card can show the entity picture; the parcel details
(number, code, multiskrytka members) live on the slot's attributes and on the
``sensor.*_do_odbioru`` entity.
"""
from __future__ import annotations

import io

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import InPostConfigEntry
from .const import CONF_ALIAS, CONF_PHONE, DOMAIN, QR_SLOTS
from .coordinator import InPostCoordinator
from .pickup import group_qr_payload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InPostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        InPostQrImage(hass, coordinator, slot) for slot in range(QR_SLOTS)
    )


class InPostQrImage(CoordinatorEntity[InPostCoordinator], ImageEntity):
    """QR of one pickup group's open payload (regenerated when it changes)."""

    _attr_has_entity_name = True
    _attr_content_type = "image/png"

    def __init__(
        self, hass: HomeAssistant, coordinator: InPostCoordinator, slot: int
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._slot = slot
        phone = coordinator.entry.data[CONF_PHONE]
        alias = coordinator.entry.data.get(CONF_ALIAS, phone)
        if slot == 0:
            self._attr_unique_id = f"{phone}_qr"
            self._attr_name = "QR do odbioru"
        else:
            self._attr_unique_id = f"{phone}_qr_{slot + 1}"
            self._attr_name = f"QR do odbioru #{slot + 1}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, phone)},
            name=f"InPost — {alias}",
            manufacturer="InPost",
            model="Paczkomaty",
        )
        self._last_payload: str | None = None
        self._png: bytes | None = None

    @property
    def _group(self) -> dict | None:
        groups = (self.coordinator.data or {}).get("pickup_groups") or []
        return groups[self._slot] if self._slot < len(groups) else None

    @property
    def available(self) -> bool:
        return super().available and self._group is not None

    def _handle_coordinator_update(self) -> None:
        payload = group_qr_payload(self._group) if self._group else None
        if payload != self._last_payload:
            self._last_payload = payload
            self._png = None  # invalidate cached render
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        payload = group_qr_payload(self._group) if self._group else None
        if not payload:
            return None
        if self._png is None:
            self._png = await self.hass.async_add_executor_job(self._render, payload)
        return self._png

    @property
    def extra_state_attributes(self) -> dict:
        g = self._group
        if not g:
            return {}
        rep = g.get("rep") or {}
        multi = g.get("count", 1) > 1
        members = g.get("members") or [rep]
        return {
            "numer": rep.get("shipment"),
            "kod_odbioru": rep.get("open_code"),
            "paczkomat": rep.get("locker"),
            "nadawca": rep.get("sender"),
            "termin_odbioru": rep.get("expiry"),
            "multiskrytka": g.get("count") if multi else None,
            "paczki": [m.get("shipment") for m in members] if multi else None,
            "kody_fallback": [m.get("open_code") for m in members] if multi else None,
        }

    def _render(self, payload: str) -> bytes:
        import segno

        buf = io.BytesIO()
        segno.make(payload, error="m").save(buf, kind="png", scale=6, border=2)
        return buf.getvalue()
