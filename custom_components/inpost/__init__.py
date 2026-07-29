"""The InPost Paczkomaty integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import InPostCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type InPostConfigEntry = ConfigEntry[InPostCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: InPostConfigEntry) -> bool:
    """Set up InPost from a config entry."""
    coordinator = InPostCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InPostConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: InPostConfigEntry) -> None:
    """Reload the entry when options (interval / archive limit) change."""
    await hass.config_entries.async_reload(entry.entry_id)
