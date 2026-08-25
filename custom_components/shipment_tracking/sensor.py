"""InPost sensors: parcel counts per bucket (do odbioru / w drodze / archiwum).

"Do odbioru" is the primary sensor: its state is the number of parcels ready for
pickup and it carries the full parcel details (ready + in-transit) in attributes,
so a Lovelace card / automation has everything on one entity.

This module is the SENSOR platform for the whole shipment_tracking domain, not
just InPost — HA forwards every carrier's config entry to whatever platforms
PLATFORMS_BY_CARRIER lists, and both CARRIER_INPOST and CARRIER_DPD include
Platform.SENSOR. async_setup_entry MUST dispatch on carrier: an un-dispatched
version crashed here 2026-08-25 for DPD entries (InPostSharedSensor calls
coordinator.active(), which only InPostCoordinator has — AttributeError on
DpdCoordinator) before any DPD account had actually been onboarded to catch it.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShipmentConfigEntry, carrier_of
from .const import CARRIER_DPD
from .entity import (
    InPostEntity,
    archive_attrs,
    ready_attrs,
    shared_in_attrs,
    shared_out_attrs,
    transit_attrs,
)
from .sensor_dpd import async_setup_dpd_sensors
from .share import own_only, shared_in, shared_out


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShipmentConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if carrier_of(entry) == CARRIER_DPD:
        await async_setup_dpd_sensors(hass, entry, async_add_entities)
        return
    coordinator = entry.runtime_data
    async_add_entities(
        [
            InPostReadySensor(coordinator),
            InPostCountSensor(
                coordinator, "w_drodze", "W drodze", "in_transit",
                "mdi:truck-delivery", own=True,
            ),
            InPostSharedSensor(coordinator),
            InPostArchiveSensor(coordinator),
        ]
    )


class InPostReadySensor(InPostEntity, SensorEntity):
    """Parcels ready for pickup — **ours plus the ones shared with us**.

    This is the "what can I collect right now" number, so it deliberately spans
    both: with mirroring on, either household member can open the locker. The
    in-transit counter next door is the opposite — own parcels only.
    """

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
        transit = own_only(data.get("in_transit", []))
        return {
            "do_odbioru_count": counts.get("ready", 0),
            "grupy_count": len(groups),
            # Own parcels only, matching sensor "W drodze".
            "w_drodze_count": len(transit),
            "do_odbioru": ready_attrs(groups),
            "w_drodze": transit_attrs(transit),
        }


class InPostCountSensor(InPostEntity, SensorEntity):
    """Count of parcels in one bucket, optionally restricted to our own.

    "W drodze" counts own parcels only: a parcel a friend shared with us is
    already reported by the "Udostępnione" sensor, and counting it here too would
    show six parcels on both accounts when the household really has six in total.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."

    def __init__(
        self, coordinator, key: str, name: str, bucket: str, icon: str, own: bool = False
    ) -> None:
        super().__init__(coordinator, key)
        self._bucket = bucket
        self._own = own
        self._attr_name = name
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        if not self._own:
            return data.get("counts", {}).get(self._bucket, 0)
        return len(own_only(data.get(self._bucket, [])))


class InPostSharedSensor(InPostEntity, SensorEntity):
    """Parcels **shared with this account** by somebody else.

    State counts what this person gained through sharing — parcels they do not
    own but may collect. That makes the three counters add up without overlap:

        Do odbioru = own ready + shared-with-me ready
        W drodze   = own, in transit
        Udostępnione = shared with me, active

    The opposite direction (our parcels handed to somebody) never enters the
    state — those are still our parcels, already counted by the other sensors —
    but it is kept in ``moje_udostepnione[]`` so a card can show both.
    """

    _attr_name = "Udostępnione"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "szt."
    _attr_icon = "mdi:share-variant"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "udostepnione")

    @property
    def native_value(self) -> int:
        return len(shared_in(self.coordinator.active()))

    @property
    def extra_state_attributes(self) -> dict:
        active = self.coordinator.active()
        incoming = shared_in(active)
        outgoing = shared_out(active)
        return {
            "udostepnione_count": len(incoming),
            "moje_udostepnione_count": len(outgoing),
            "udostepnione": shared_in_attrs(
                incoming, self.coordinator.friends, self.coordinator.aliases
            ),
            "moje_udostepnione": shared_out_attrs(outgoing),
        }


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
