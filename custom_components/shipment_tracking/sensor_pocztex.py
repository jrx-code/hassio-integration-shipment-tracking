"""Pocztex sensors: active-parcel count with full parcel lists in attributes.

Mirrors the DPD "W drodze" pattern — one sensor per account whose state is
the active-parcel count and whose attributes carry the parcel details.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CARRIER_POCZTEX,
    CONF_ALIAS,
    CONF_ARCHIVE_LIMIT,
    CONF_EMAIL,
    DEFAULT_ARCHIVE_LIMIT,
    DOMAIN,
)
from .logos import logo_url
from .coordinator_pocztex import PocztexCoordinator


async def async_setup_pocztex_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PocztexActiveSensor(entry.runtime_data)])


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "status": p.get("status"),
        "postep": p.get("progress"),
        "aktualizacja": p.get("updated"),
    }


class PocztexActiveSensor(CoordinatorEntity[PocztexCoordinator], SensorEntity):
    """Active Pocztex parcels for one account, with parcel lists in attributes."""

    _attr_has_entity_name = True
    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"
    _attr_entity_picture = logo_url(CARRIER_POCZTEX)
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: PocztexCoordinator) -> None:
        super().__init__(coordinator)
        email = coordinator.entry.data.get(CONF_EMAIL, coordinator.entry.entry_id)
        alias = coordinator.entry.data.get(CONF_ALIAS) or email
        self._attr_unique_id = f"pocztex_{email}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"pocztex_{email}")},
            name=f"Pocztex — {alias}",
            manufacturer="Poczta Polska",
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
            "w_drodze": [_row(p) for p in data.get("active", [])],
            "dostarczone": [_row(p) for p in data.get("delivered", [])[:limit]],
        }
