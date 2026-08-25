"""FedEx sensors: active-tracking-number count with details in attributes.

Mirrors the DPD "W drodze" pattern — one sensor whose state is the active
count and whose attributes carry the parcel details, so a card/automation
has everything on one entity. There is no "Do odbioru"/archive split like
InPost: FedEx numbers are user-added and stay tracked until removed from
options, delivered or not.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ALIAS, CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT, DOMAIN
from .coordinator_fedex import FedexCoordinator


async def async_setup_fedex_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FedexActiveSensor(entry.runtime_data)])


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "status": p.get("status"),
        "nadawca_miasto": p.get("sender_city"),
        "nadawca_kraj": p.get("sender_country"),
        "usluga": p.get("service"),
    }


class FedexActiveSensor(CoordinatorEntity[FedexCoordinator], SensorEntity):
    """Active FedEx tracking numbers, with details in attributes."""

    _attr_has_entity_name = True
    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: FedexCoordinator) -> None:
        super().__init__(coordinator)
        alias = coordinator.entry.data.get(CONF_ALIAS) or coordinator.entry.entry_id
        self._attr_unique_id = f"fedex_{coordinator.entry.entry_id}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"fedex_{coordinator.entry.entry_id}")},
            name=f"FedEx — {alias}",
            manufacturer="FedEx",
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
