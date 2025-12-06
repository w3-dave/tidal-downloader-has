"""Tidal Downloader integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_SYNC_NOW,
    SERVICE_FORCE_DOWNLOAD,
    SERVICE_CLEAR_HISTORY,
    SERVICE_FIX_PERMISSIONS,
    SERVICE_CLEAR_LOCAL_FILES,
    SERVICE_CLEAR_QUEUE,
)
from .coordinator import TidalDownloaderCoordinator
from .download_manager import DownloadManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]

# Service schemas
SERVICE_FORCE_DOWNLOAD_SCHEMA = vol.Schema(
    {
        vol.Required("album_id"): cv.positive_int,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tidal Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize coordinator
    coordinator = TidalDownloaderCoordinator(
        hass=hass,
        entry_data=dict(entry.data),
        entry_options=dict(entry.options),
    )

    # Initialize coordinator (load storage, connect to Tidal)
    await coordinator.async_initialize()

    # Initialize download manager with coordinator's session
    download_manager = DownloadManager(
        hass=hass,
        session=coordinator.session,
        options=dict(entry.options),
        coordinator=coordinator,
        on_download_complete=coordinator.mark_downloaded,
    )

    # Connect download manager to coordinator
    coordinator.set_download_manager(download_manager)

    # Store coordinator and download manager
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "download_manager": download_manager,
    }

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await _async_setup_services(hass, entry)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))

    return True


async def _async_setup_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up integration services."""

    async def handle_sync_now(call: ServiceCall) -> None:
        """Handle sync_now service call."""
        _LOGGER.warning("sync_now service called")
        found = False
        for entry_id, data in hass.data[DOMAIN].items():
            _LOGGER.warning("Checking entry %s: %s", entry_id, type(data))
            if isinstance(data, dict) and "coordinator" in data:
                found = True
                coordinator = data["coordinator"]
                _LOGGER.warning("Found coordinator, calling force_sync")
                await coordinator.force_sync()
        if not found:
            _LOGGER.error("No coordinator found in hass.data[%s]", DOMAIN)

    async def handle_force_download(call: ServiceCall) -> None:
        """Handle force_download service call."""
        album_id = call.data["album_id"]
        _LOGGER.warning("force_download service called for album %s", album_id)
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and "download_manager" in data:
                download_manager = data["download_manager"]
                await download_manager.force_download(album_id)

    async def handle_clear_history(call: ServiceCall) -> None:
        """Handle clear_history service call."""
        _LOGGER.warning("clear_history service called")
        found = False
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and "coordinator" in data:
                found = True
                coordinator = data["coordinator"]
                _LOGGER.warning("Found coordinator, calling clear_history")
                await coordinator.clear_history()
        if not found:
            _LOGGER.error("No coordinator found in hass.data[%s]", DOMAIN)

    async def handle_fix_permissions(call: ServiceCall) -> None:
        """Handle fix_permissions service call."""
        _LOGGER.warning("fix_permissions service called")
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and "download_manager" in data:
                download_manager = data["download_manager"]
                count = await download_manager.fix_permissions()
                _LOGGER.warning("Fixed permissions on %d files/directories", count)

    async def handle_clear_local_files(call: ServiceCall) -> None:
        """Handle clear_local_files service call."""
        _LOGGER.warning("clear_local_files service called")
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and "download_manager" in data:
                download_manager = data["download_manager"]
                count = await download_manager.clear_local_files()
                _LOGGER.warning("Deleted %d files/directories from local folder", count)

    async def handle_clear_queue(call: ServiceCall) -> None:
        """Handle clear_queue service call."""
        _LOGGER.warning("clear_queue service called")
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and "download_manager" in data:
                download_manager = data["download_manager"]
                count = download_manager.clear_queue()
                _LOGGER.warning("Cleared %d items from download queue", count)

    # Register services (only if not already registered)
    if not hass.services.has_service(DOMAIN, SERVICE_SYNC_NOW):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SYNC_NOW,
            handle_sync_now,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_DOWNLOAD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_DOWNLOAD,
            handle_force_download,
            schema=SERVICE_FORCE_DOWNLOAD_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HISTORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HISTORY,
            handle_clear_history,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FIX_PERMISSIONS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FIX_PERMISSIONS,
            handle_fix_permissions,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_LOCAL_FILES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_LOCAL_FILES,
            handle_clear_local_files,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_QUEUE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_QUEUE,
            handle_clear_queue,
        )


async def async_options_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
