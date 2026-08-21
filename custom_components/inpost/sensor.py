"""InPost sensors: parcel counts per bucket (do odbioru / w drodze / archiwum).

"Do odbioru" is the primary sensor: its state is the number of parcels ready for
pickup and it carries the full parcel details (ready + in-transit) in attributes,
so a Lovelace card / automation has everything on one entity.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InPostConfigEntry
from .entity import InPostEntity, archive_attrs, ready_attrs, transit_attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InPostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            InPostReadySensor(coordinator),
            InPostCountSensor(coordinator, "w_drodze", "W drodze", "in_transit", "mdi:truck-delivery"),
            InPostArchiveSensor(coordinator),
        ]
    )


class InPostReadySensor(InPostEntity, SensorEntity):
    """Number of parcels ready for pickup, with full parcel lists in attributes."""

    _attr_name = "Do odbioru"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "do_odbioru")

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return data.get("counts", {}).get("ready", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        counts = data.get("counts", {})
        groups = data.get("pickup_groups", [])
        return {
            "do_odbioru_count": counts.get("ready", 0),
            "grupy_count": len(groups),
            "w_drodze_count": counts.get("in_transit", 0),
            "do_odbioru": ready_attrs(groups),
            "w_drodze": transit_attrs(data.get("in_transit", [])),
        }


class InPostCountSensor(InPostEntity, SensorEntity):
    """Count of parcels in one bucket."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator, key: str, name: str, bucket: str, icon: str) -> None:
        super().__init__(coordinator, key)
        self._bucket = bucket
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return data.get("counts", {}).get(self._bucket, 0)


class InPostArchiveSensor(InPostEntity, SensorEntity):
    """Archived parcel count + latest N in attributes (capped by option)."""

    _attr_name = "Archiwum"
    _attr_native_unit_of_measurement = "szt."
    _attr_icon = "mdi:archive"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "archiwum")

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return data.get("counts", {}).get("archived", 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {"archiwum": archive_attrs(data.get("archived", []), self.coordinator.archive_limit)}
