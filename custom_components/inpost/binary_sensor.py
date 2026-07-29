"""InPost binary sensor: ON when at least one parcel is ready for pickup."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InPostConfigEntry
from .entity import InPostEntity, ready_attrs, transit_attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InPostConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([InPostReadyBinarySensor(entry.runtime_data)])


class InPostReadyBinarySensor(InPostEntity, BinarySensorEntity):
    """Aggregated 'do odbioru' sensor with full parcel lists in attributes."""

    _attr_translation_key = "do_odbioru"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "do_odbioru")

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return data.get("counts", {}).get("ready", 0) > 0

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        counts = data.get("counts", {})
        return {
            "do_odbioru_count": counts.get("ready", 0),
            "w_drodze_count": counts.get("in_transit", 0),
            "do_odbioru": ready_attrs(data.get("ready", [])),
            "w_drodze": transit_attrs(data.get("in_transit", [])),
        }
