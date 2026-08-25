"""DPD sensors: active-parcel count with full parcel lists in attributes.

Mirrors the InPost "do odbioru" pattern — one sensor per account whose state is
the active-parcel count and whose attributes carry the parcel details (active +
recent delivered), so a card / automation has everything on one entity.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ALIAS,
    CONF_ARCHIVE_LIMIT,
    CONF_PHONE,
    DEFAULT_ARCHIVE_LIMIT,
    DOMAIN,
)
from .coordinator_dpd import DpdCoordinator


async def async_setup_dpd_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DpdActiveSensor(entry.runtime_data)])


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "nadawca": p.get("sender"),
        "status": p.get("status"),
        "aktualizacja": p.get("updated"),
    }


def _active_row(p: dict) -> dict:
    """Like _row(), plus the detail-endpoint fields (GPS/courier/mps) that the
    coordinator only fetches for active parcels."""
    row = _row(p)
    row.update(
        {
            "adres_nadawcy": p.get("sender_address"),
            "gps_doreczenia": p.get("delivery_gps"),
            "kurier": p.get("courier_name"),
            "telefon_kuriera": p.get("courier_phone"),
        }
    )
    if p.get("mps_count"):
        row["czesc_przesylki"] = f"{p.get('mps_part')}/{p.get('mps_count')}"
        row["pozostale_paczki"] = p.get("mps_siblings")
    return row


class DpdActiveSensor(CoordinatorEntity[DpdCoordinator], SensorEntity):
    """Active DPD parcels for one account, with parcel lists in attributes."""

    _attr_has_entity_name = True
    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: DpdCoordinator) -> None:
        super().__init__(coordinator)
        phone = coordinator.entry.data[CONF_PHONE]
        alias = coordinator.entry.data.get(CONF_ALIAS, phone)
        self._attr_unique_id = f"dpd_{phone}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"dpd_{phone}")},
            name=f"DPD — {alias}",
            manufacturer="DPD",
            model="Przesyłki",
        )

    @property
    def native_value(self) -> int:
        return (self.coordinator.data or {}).get("counts", {}).get("active", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        counts = data.get("counts", {})
        limit = int(
            self.coordinator.entry.options.get(CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT)
        )
        return {
            "active_count": counts.get("active", 0),
            "delivered_count": counts.get("delivered", 0),
            "w_drodze": [_active_row(p) for p in data.get("active", [])],
            "dostarczone": [_row(p) for p in data.get("delivered", [])[:limit]],
        }
