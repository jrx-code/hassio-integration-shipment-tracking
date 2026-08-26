"""DHL sensors: active-parcel count with full parcel lists in attributes.

Mirrors the DPD sensor shape — one sensor whose state is the active-parcel
count and whose attributes carry the parcel details (active + recent
delivered), so a card / automation has everything on one entity.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ALIAS, CONF_ARCHIVE_LIMIT, DEFAULT_ARCHIVE_LIMIT, DOMAIN
from .coordinator_dhl import DhlCoordinator


async def async_setup_dhl_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DhlActiveSensor(entry.runtime_data)])


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "nadawca": p.get("sender"),
        "status": p.get("status"),
        "aktualizacja": p.get("updated"),
        "udostepniona": p.get("shared"),
    }


class DhlActiveSensor(CoordinatorEntity[DhlCoordinator], SensorEntity):
    """Active DHL parcels for one account, with parcel lists in attributes."""

    _attr_has_entity_name = True
    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: DhlCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.entry.entry_id
        alias = coordinator.entry.data.get(CONF_ALIAS, "DHL")
        self._attr_unique_id = f"dhl_{entry_id}_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"dhl_{entry_id}")},
            name=f"DHL — {alias}",
            manufacturer="DHL",
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
