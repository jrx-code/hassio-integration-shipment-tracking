"""Shared entity base + parcel->attribute mapping for InPost."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ALIAS, CONF_PHONE, DOMAIN, status_pl
from .coordinator import InPostCoordinator


class InPostEntity(CoordinatorEntity[InPostCoordinator]):
    """Base entity: one HA device per InPost account (config entry)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InPostCoordinator, key: str) -> None:
        super().__init__(coordinator)
        phone = coordinator.entry.data[CONF_PHONE]
        alias = coordinator.entry.data.get(CONF_ALIAS, phone)
        self._attr_unique_id = f"{phone}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, phone)},
            name=f"InPost — {alias}",
            manufacturer="InPost",
            model="Paczkomaty",
        )


def ready_attrs(parcels: list[dict]) -> list[dict]:
    """Mirror of the MQTT `do_odbioru[]` attribute shape (Polish keys)."""
    return [
        {
            "nadawca": p.get("sender"),
            "kod_odbioru": p.get("open_code"),
            "paczkomat": p.get("locker"),
            "adres": p.get("address"),
            "termin_odbioru": p.get("expiry"),
            "qr": p.get("qr"),
            "multiskrytka": p.get("multi_count"),
        }
        for p in parcels
    ]


def transit_attrs(parcels: list[dict]) -> list[dict]:
    return [
        {
            "nadawca": p.get("sender"),
            "paczkomat": p.get("locker"),
            "status": status_pl(p.get("status")),
        }
        for p in parcels
    ]


def archive_attrs(parcels: list[dict], limit: int) -> list[dict]:
    return [
        {
            "nadawca": p.get("sender"),
            "paczkomat": p.get("locker"),
            "status": status_pl(p.get("status")),
            "data": p.get("stored") or p.get("expiry"),
        }
        for p in parcels[:limit]
    ]
