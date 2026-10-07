"""ORLEN Paczka account sensors: auto-discovered parcels, split by state.

State of the main sensor is the active-parcel count; attributes carry the
ready-for-pickup and delivered lists. Unlike the public-track Orlen carrier
there is no manual number list — parcels come from the account itself.
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
    DEFAULT_ARCHIVE_LIMIT,
    DOMAIN,
)
from .coordinator_orlen_account import OrlenAccountCoordinator


async def async_setup_orlen_account_sensors(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            OrlenAccountActiveSensor(entry.runtime_data),
            OrlenAccountReadySensor(entry.runtime_data),
        ]
    )


def _row(p: dict) -> dict:
    return {
        "numer": p.get("number"),
        "status": p.get("status"),
        "nadawca": p.get("sender"),
        "punkt": p.get("point"),
    }


class _OrlenAccountBase(CoordinatorEntity[OrlenAccountCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator: OrlenAccountCoordinator) -> None:
        super().__init__(coordinator)
        alias = coordinator.entry.data.get(CONF_ALIAS) or coordinator.entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"orlen_account_{coordinator.entry.entry_id}")},
            name=f"Orlen Paczka (konto) — {alias}",
            manufacturer="Orlen Paczka",
            model="Konto",
        )


class OrlenAccountActiveSensor(_OrlenAccountBase):
    """Active (in-transit) parcels on the account, details in attributes."""

    _attr_name = "W drodze"
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: OrlenAccountCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"orlen_account_{coordinator.entry.entry_id}_active"

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
            "ready_count": counts.get("ready", 0),
            "delivered_count": counts.get("delivered", 0),
            "w_drodze": [_row(p) for p in data.get("active", [])],
            "dostarczone": [_row(p) for p in data.get("delivered", [])[:limit]],
        }


class OrlenAccountReadySensor(_OrlenAccountBase):
    """Parcels ready for pickup, details in attributes."""

    _attr_name = "Do odbioru"
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator: OrlenAccountCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"orlen_account_{coordinator.entry.entry_id}_ready"

    @property
    def native_value(self) -> int:
        return (self.coordinator.data or {}).get("counts", {}).get("ready", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {"do_odbioru": [_row(p) for p in data.get("ready", [])]}
