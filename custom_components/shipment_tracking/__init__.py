"""Śledzenie przesyłek — multi-carrier parcel tracking (InPost, DPD, FedEx, Pocztex, DHL, Orlen, Allegro One)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .carriers_orlen_allegro import CARRIER_ALLEGRO_ONE, CARRIER_ORLEN
from .const import (
    CARRIER_DHL,
    CARRIER_DPD,
    CARRIER_FEDEX,
    CARRIER_INPOST,
    CARRIER_POCZTEX,
    CONF_CARRIER,
    CONF_PHONE,
    DOMAIN,
)
from .coordinator import InPostCoordinator
from .coordinator_allegro_one import AllegroOneCoordinator
from .coordinator_dhl import DhlCoordinator
from .coordinator_dpd import DpdCoordinator
from .coordinator_fedex import FedexCoordinator
from .coordinator_orlen import OrlenCoordinator
from .coordinator_pocztex import PocztexCoordinator
from .logos import async_register as async_register_logos
from .share import auto_share_unique_id, peer_entries, share_unique_id

_LOGGER = logging.getLogger(__name__)

type ShipmentConfigEntry = ConfigEntry

# Platforms per carrier — only InPost exposes QR images and app-to-app sharing
# (button/switch); DPD, FedEx and Pocztex have neither.
PLATFORMS_BY_CARRIER: dict[str, list[Platform]] = {
    CARRIER_INPOST: [Platform.SENSOR, Platform.IMAGE, Platform.BUTTON, Platform.SWITCH],
    CARRIER_DPD: [Platform.SENSOR],
    CARRIER_FEDEX: [Platform.SENSOR],
    CARRIER_POCZTEX: [Platform.SENSOR],
    CARRIER_DHL: [Platform.SENSOR],
    CARRIER_ORLEN: [Platform.SENSOR],
    CARRIER_ALLEGRO_ONE: [Platform.SENSOR],
}


def carrier_of(entry: ConfigEntry) -> str:
    """Carrier for an entry; pre-multi-carrier entries default to InPost."""
    return entry.data.get(CONF_CARRIER, CARRIER_INPOST)


async def async_setup_entry(hass: HomeAssistant, entry: ShipmentConfigEntry) -> bool:
    """Set up one carrier account from a config entry."""
    carrier = carrier_of(entry)
    # Carrier badges are served over HTTP and pointed at by entity_picture, so
    # the route has to exist before the platforms build their entities.
    await async_register_logos(hass)
    coordinator: (
        InPostCoordinator
        | DpdCoordinator
        | FedexCoordinator
        | PocztexCoordinator
        | DhlCoordinator
        | OrlenCoordinator
        | AllegroOneCoordinator
    )
    if carrier == CARRIER_DPD:
        coordinator = DpdCoordinator(hass, entry)
    elif carrier == CARRIER_FEDEX:
        coordinator = FedexCoordinator(hass, entry)
    elif carrier == CARRIER_POCZTEX:
        coordinator = PocztexCoordinator(hass, entry)
    elif carrier == CARRIER_DHL:
        coordinator = DhlCoordinator(hass, entry)
    elif carrier == CARRIER_ORLEN:
        coordinator = OrlenCoordinator(hass, entry)
    elif carrier == CARRIER_ALLEGRO_ONE:
        coordinator = AllegroOneCoordinator(hass, entry)
    else:
        coordinator = InPostCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Snapshot of the options this setup ran with — _async_reload_on_update
    # compares against it to tell an options edit from a credential write.
    coordinator.setup_options = dict(entry.options)
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS_BY_CARRIER[carrier]
    )
    if carrier == CARRIER_INPOST:
        _async_reload_peers_missing_us(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShipmentConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS_BY_CARRIER[carrier_of(entry)]
    )


async def async_remove_entry(hass: HomeAssistant, entry: ShipmentConfigEntry) -> None:
    """Drop sharing entities other InPost accounts hold pointing at this one.

    Mirror of _async_reload_peers_missing_us: adding an account gives every
    already-running peer a button/switch aimed at it; removing one must take
    those back, or a surviving account keeps a permanently-broken "Udostępnij →
    <removed alias>" button with no coordinator behind it (found live 2026-08-25
    — deleting the "Betacom" account left four orphaned button/switch entities
    on Jarek's and Marian's devices).

    InPost-only, like the add-side reload — DPD has no sharing feature. Runs
    even though this entry itself is already gone; peer_entries() filtering out
    our own entry_id is then a no-op, not a requirement.
    """
    if carrier_of(entry) != CARRIER_INPOST:
        return
    my_phone = str(entry.data.get(CONF_PHONE, ""))
    if not my_phone:
        return
    registry = er.async_get(hass)
    for peer in peer_entries(hass, entry):
        peer_phone = str(peer.data[CONF_PHONE])
        for unique_id, platform in (
            (share_unique_id(peer_phone, my_phone), Platform.BUTTON),
            (auto_share_unique_id(peer_phone, my_phone), Platform.SWITCH),
        ):
            entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
            if entity_id:
                _LOGGER.debug(
                    "removing %s — %s account was removed", entity_id, my_phone
                )
                registry.async_remove(entity_id)


async def _async_reload_on_update(hass: HomeAssistant, entry: ShipmentConfigEntry) -> None:
    """Reload the entry when its OPTIONS change.

    The listener fires on every ``async_update_entry``, and entry.data moves on
    its own now: DHL's session lives in cookies the server rotates on each
    refresh, so its coordinator writes the current jar back to entry.data every
    poll (see coordinator_dhl.py). Reloading on those would restart the
    integration every ~15 minutes, which is the reload storm this file's
    carriers have already been bitten by twice.

    Reauth does not depend on this path — the flow ends in
    ``async_update_reload_and_abort``, which reloads explicitly.
    """
    # runtime_data itself raises AttributeError on an entry whose setup failed
    # (both DHL entries sat in setup_error the day this was written), so reach
    # for it defensively — an unknown baseline means "reload", the old default.
    previous = getattr(getattr(entry, "runtime_data", None), "setup_options", None)
    if previous is not None and previous == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_reload_peers_missing_us(hass: HomeAssistant, entry: ShipmentConfigEntry) -> None:
    """Give already-running InPost accounts their sharing entities for this one.

    Sharing entities are created while an account sets up, one per InPost account
    that existed at that moment. So a freshly added account immediately gets
    entities aimed at the older ones, but the older ones know nothing about it
    until they are reloaded — mirroring would work one way only. InPost-only:
    `peer_entries` already excludes DPD accounts under the shared domain.

    Home Assistant does dispatch SIGNAL_CONFIG_ENTRY_CHANGED / ConfigEntryChange
    .ADDED, but it is sent through `async_dispatcher_send_internal`, documented as
    core-internal and explicitly not for integrations, so this reconciles through
    the entity registry instead: reload every loaded peer that has no button
    pointing back at us.

    Terminates by construction. The reload recreates the peer's entities with us
    in view, so its own pass finds our button already registered and reloads
    nobody.
    """
    registry = er.async_get(hass)
    my_phone = str(entry.data[CONF_PHONE])
    for peer in peer_entries(hass, entry):
        if peer.state is not ConfigEntryState.LOADED:
            # Not set up yet — it will see us on its own setup.
            continue
        unique_id = share_unique_id(str(peer.data[CONF_PHONE]), my_phone)
        if registry.async_get_entity_id(Platform.BUTTON, DOMAIN, unique_id):
            continue
        _LOGGER.debug(
            "reloading %s so it gains sharing entities for %s", peer.title, my_phone
        )
        hass.config_entries.async_schedule_reload(peer.entry_id)
