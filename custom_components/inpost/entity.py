"""Shared entity base + parcel->attribute mapping for InPost."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ALIAS, CONF_PHONE, DOMAIN, status_pl
from .coordinator import InPostCoordinator
from .share import owner_label


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


def ready_attrs(groups: list[dict]) -> list[dict]:
    """`do_odbioru[]` attribute list — ONE row per pickup group.

    A multiskrytka collapses to a single row (its leader) with ``multiskrytka``
    set to the parcel count and every member's number/code kept as a fallback.
    Standalone parcels stay 1-element groups (``multiskrytka`` = None). Keys stay
    backward-compatible with the previous per-parcel shape.
    """
    rows: list[dict] = []
    for g in groups:
        rep = g.get("rep") or {}
        multi = g.get("count", 1) > 1
        members = g.get("members") or [rep]
        rows.append(
            {
                "numer": rep.get("shipment"),
                "nadawca": rep.get("sender"),
                "kod_odbioru": rep.get("open_code"),
                "paczkomat": rep.get("locker"),
                "adres": rep.get("address"),
                "termin_odbioru": rep.get("expiry"),
                "qr": rep.get("qr"),
                "qr_url": g.get("qr_url"),
                "multiskrytka": g.get("count") if multi else None,
                "paczki": [m.get("shipment") for m in members] if multi else None,
                "kody_fallback": [m.get("open_code") for m in members] if multi else None,
                # App-to-app sharing state, per group leader.
                "wlasciciel": rep.get("ownership"),
                "udostepniona_do": [
                    s.get("name") for s in rep.get("shared_to") or []
                ],
                "mozna_udostepnic": bool(rep.get("can_share")),
            }
        )
    return rows


def transit_attrs(parcels: list[dict]) -> list[dict]:
    return [
        {
            "nadawca": p.get("sender"),
            "paczkomat": p.get("locker"),
            "status": status_pl(p.get("status")),
        }
        for p in parcels
    ]


def shared_out_attrs(parcels: list[dict]) -> list[dict]:
    """`udostepnione[]` — our parcels handed to somebody else."""
    return [
        {
            "numer": p.get("shipment"),
            "nadawca": p.get("sender"),
            "status": status_pl(p.get("status")),
            "dla": [s.get("name") for s in p.get("shared_to") or []],
            "kod_odbioru": p.get("open_code"),
            "paczkomat": p.get("locker"),
        }
        for p in parcels
    ]


def shared_in_attrs(
    parcels: list[dict], friends: list[dict], aliases: dict[str, str] | None = None
) -> list[dict]:
    """`otrzymane[]` — parcels somebody shared with us.

    ``podglad`` marks an OBSERVED share, where InPost withholds the pickup code.
    """
    return [
        {
            "numer": p.get("shipment"),
            "nadawca": p.get("sender"),
            "status": status_pl(p.get("status")),
            "od": owner_label(p, friends, aliases),
            "kod_odbioru": p.get("open_code"),
            "paczkomat": p.get("locker"),
            "podglad": p.get("ownership") == "OBSERVED",
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
