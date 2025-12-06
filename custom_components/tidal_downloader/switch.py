"""Switch platform for Tidal Downloader."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tidal Downloader switches."""
    download_manager = hass.data[DOMAIN][entry.entry_id]["download_manager"]

    switches = [
        TidalDownloadEnabledSwitch(entry, download_manager),
    ]

    async_add_entities(switches)


class TidalDownloadEnabledSwitch(SwitchEntity):
    """Switch to enable/disable downloading."""

    def __init__(self, entry: ConfigEntry, download_manager) -> None:
        """Initialize the switch."""
        self._entry = entry
        self._download_manager = download_manager
        self._attr_unique_id = f"{entry.entry_id}_download_enabled"
        self._attr_has_entity_name = True
        self._attr_name = "Download Enabled"
        self._attr_icon = "mdi:download"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Tidal Downloader",
            "manufacturer": "Tidal",
            "model": "Album Downloader",
        }

    @property
    def is_on(self) -> bool:
        """Return true if downloads are enabled."""
        return self._download_manager.downloads_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable downloads."""
        await self._download_manager.async_set_downloads_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable downloads (kill switch)."""
        await self._download_manager.async_set_downloads_enabled(False)
        self.async_write_ha_state()
