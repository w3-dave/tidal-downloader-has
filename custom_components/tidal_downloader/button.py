"""Button platform for Tidal Downloader."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TidalDownloaderCoordinator
from .download_manager import DownloadManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tidal Downloader buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    download_manager = hass.data[DOMAIN][entry.entry_id]["download_manager"]

    buttons = [
        TidalSyncNowButton(coordinator, entry),
        TidalClearHistoryButton(coordinator, entry),
        TidalClearQueueButton(download_manager, entry),
        TidalClearLocalFilesButton(download_manager, entry),
        TidalFixPermissionsButton(download_manager, entry),
    ]

    async_add_entities(buttons)


class TidalBaseButton(ButtonEntity):
    """Base class for Tidal buttons."""

    def __init__(
        self,
        entry: ConfigEntry,
        button_type: str,
    ) -> None:
        """Initialize the button."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{button_type}"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Tidal Downloader",
            "manufacturer": "Tidal",
            "model": "Album Downloader",
        }


class TidalSyncNowButton(TidalBaseButton):
    """Button to trigger immediate sync."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, "sync_now_button")
        self._coordinator = coordinator
        self._attr_name = "Sync Now"
        self._attr_icon = "mdi:sync"

    async def async_press(self) -> None:
        """Handle button press."""
        await self._coordinator.force_sync()


class TidalClearHistoryButton(TidalBaseButton):
    """Button to clear download history."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, "clear_history_button")
        self._coordinator = coordinator
        self._attr_name = "Clear Download History"
        self._attr_icon = "mdi:history"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press."""
        await self._coordinator.clear_history()


class TidalClearQueueButton(TidalBaseButton):
    """Button to clear download queue."""

    def __init__(
        self,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, "clear_queue_button")
        self._download_manager = download_manager
        self._attr_name = "Clear Download Queue"
        self._attr_icon = "mdi:playlist-remove"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press."""
        self._download_manager.clear_queue()


class TidalClearLocalFilesButton(TidalBaseButton):
    """Button to clear local download folder."""

    def __init__(
        self,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, "clear_local_files_button")
        self._download_manager = download_manager
        self._attr_name = "Clear Local Files"
        self._attr_icon = "mdi:folder-remove"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press."""
        await self._download_manager.clear_local_files()


class TidalFixPermissionsButton(TidalBaseButton):
    """Button to fix file permissions."""

    def __init__(
        self,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(entry, "fix_permissions_button")
        self._download_manager = download_manager
        self._attr_name = "Fix File Permissions"
        self._attr_icon = "mdi:lock-open"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press."""
        await self._download_manager.fix_permissions()
