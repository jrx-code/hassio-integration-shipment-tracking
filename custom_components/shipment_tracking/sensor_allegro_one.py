"""Allegro One sensors: active-tracking-number count with details in attributes."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CARRIER_ALLEGRO_ONE,
    CONF_ALIAS,
    CONF_ARCHIVE_LIMIT,
    DEFAULT_ARCHIVE_LIMIT,
    DOMAIN,
)
from .coordinator_allegro_one import AllegroOneCoordinator
from .logos import logo_url


async def async_setup_allegro_one_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([AllegroOneActiveSensor(entry.runtime_data)])


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "status": p.get("status"),
        "aktualizacja": p.get("updated"),
    }


class AllegroOneActiveSensor(CoordinatorEntity[AllegroOneCoordinator], SensorEntity):
    """Active Allegro One tracking numbers, with details in attributes."""

    _attr_has_entity_name = True
    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"
    _attr_entity_picture = logo_url(CARRIER_ALLEGRO_ONE)
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: AllegroOneCoordinator) -> None:
        super().__init__(coordinator)
        alias = coordinator.entry.data.get(CONF_ALIAS) or coordinator.entry.entry_id
        self._attr_unique_id = f"allegro_one_{coordinator.entry.entry_id}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"allegro_one_{coordinator.entry.entry_id}")},
            name=f"Allegro One — {alias}",
            manufacturer="Allegro",
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
