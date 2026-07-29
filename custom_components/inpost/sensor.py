"""InPost sensors: parcel counts per bucket (do odbioru / w drodze / archiwum)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InPostConfigEntry
from .entity import InPostEntity, archive_attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InPostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            InPostCountSensor(coordinator, "do_odbioru", "ready", "mdi:package-check"),
            InPostCountSensor(coordinator, "w_drodze", "in_transit", "mdi:truck-delivery"),
            InPostArchiveSensor(coordinator),
        ]
    )


class InPostCountSensor(InPostEntity, SensorEntity):
    """Count of parcels in one bucket."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(self, coordinator, key: str, bucket: str, icon: str) -> None:
        super().__init__(coordinator, key)
        self._bucket = bucket
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return data.get("counts", {}).get(self._bucket, 0)


class InPostArchiveSensor(InPostEntity, SensorEntity):
    """Archived parcel count + latest N in attributes (capped by option)."""

    _attr_translation_key = "archiwum"
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
