"""The InPost Paczkomaty integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_PHONE, DOMAIN
from .coordinator import InPostCoordinator
from .share import peer_entries, share_unique_id

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.IMAGE,
    Platform.BUTTON,
    Platform.SWITCH,
]

type InPostConfigEntry = ConfigEntry[InPostCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: InPostConfigEntry) -> bool:
    """Set up InPost from a config entry."""
    coordinator = InPostCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_reload_peers_missing_us(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InPostConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: InPostConfigEntry) -> None:
    """Reload the entry when options (interval / archive limit) change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_reload_peers_missing_us(hass: HomeAssistant, entry: InPostConfigEntry) -> None:
    """Give already-running accounts their sharing entities for this one.

    Sharing entities are created while an account sets up, one per account that
    existed at that moment. So a freshly added account immediately gets entities
    aimed at the older ones, but the older ones know nothing about it until they
    are reloaded — mirroring would work one way only.

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
