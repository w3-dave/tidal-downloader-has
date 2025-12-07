"""DataUpdateCoordinator for Tidal Downloader."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
import shutil
from typing import Any, TYPE_CHECKING

import tidalapi

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_TYPE,
    CONF_EXPIRY_TIME,
    CONF_POLL_INTERVAL,
    CONF_AUDIO_QUALITY,
    CONF_DOWNLOAD_PATH,
    CONF_SMB_ENABLED,
    DEFAULT_DOWNLOAD_PATH,
    DEFAULT_POLL_INTERVAL,
    AudioQuality,
)

if TYPE_CHECKING:
    from .download_manager import DownloadManager

_LOGGER = logging.getLogger(__name__)


class TidalDownloaderCoordinator(DataUpdateCoordinator):
    """Coordinator to manage Tidal favorites polling and downloads."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: dict[str, Any],
        entry_options: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry_data = entry_data
        self.entry_options = entry_options
        self.download_manager: DownloadManager | None = None

        # Tidal session
        self._session: tidalapi.Session | None = None

        # Persistent storage for downloaded album IDs
        self._store = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
        )
        self._downloaded_albums: set[int] = set()

        # Coordinator state
        self._last_sync: datetime | None = None
        self._sync_status = "idle"

        poll_interval_minutes = entry_options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=poll_interval_minutes),
        )

    def set_download_manager(self, download_manager: DownloadManager) -> None:
        """Set the download manager reference."""
        self.download_manager = download_manager

    async def async_initialize(self) -> None:
        """Initialize the coordinator - load stored data and connect to Tidal."""
        # Load downloaded albums and settings from storage
        stored_data = await self._store.async_load()
        if stored_data:
            self._downloaded_albums = set(stored_data.get("downloaded_albums", []))
            self._downloads_enabled = stored_data.get("downloads_enabled", True)
            _LOGGER.debug(
                "Loaded %d previously downloaded albums, downloads_enabled=%s",
                len(self._downloaded_albums),
                self._downloads_enabled,
            )
        else:
            self._downloads_enabled = True

        # Perform startup cleanup - delete incomplete downloads/uploads
        await self._startup_cleanup()

        # Initialize Tidal session
        await self._initialize_session()

    async def _startup_cleanup(self) -> None:
        """Clean up incomplete downloads from previous session (local folder only).

        On startup:
        - Delete all contents of local download folder (it's temporary)
        - Albums not in downloaded_albums will re-download on next sync

        Note: SMB staging cleanup is done separately via async_cleanup_smb_staging()
        after download_manager is initialized.
        """
        _LOGGER.warning("Performing startup cleanup (local folder)...")

        # Clean up local download folder
        download_path = self.entry_options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)
        local_cleanup_count = await self.hass.async_add_executor_job(
            self._cleanup_local_folder, download_path
        )
        if local_cleanup_count > 0:
            _LOGGER.warning(
                "Startup cleanup: Deleted %d items from local download folder",
                local_cleanup_count,
            )

        _LOGGER.warning("Startup cleanup (local) complete")

    async def async_cleanup_smb_staging(self) -> None:
        """Clean up SMB staging folder (must be called after download_manager is set)."""
        if not self.entry_options.get(CONF_SMB_ENABLED, False):
            return

        smb_cleanup_count = await self._cleanup_smb_staging()
        if smb_cleanup_count > 0:
            _LOGGER.warning(
                "Startup cleanup: Deleted %d items from SMB staging folder",
                smb_cleanup_count,
            )

    def _cleanup_local_folder(self, path: str) -> int:
        """Delete all contents of local download folder (blocking). Returns count deleted."""
        import stat

        count = 0
        try:
            if not os.path.exists(path):
                _LOGGER.debug("Local download path does not exist: %s", path)
                return 0

            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    # Set permissions first to ensure we can delete
                    if os.path.isdir(item_path):
                        for root, dirs, files in os.walk(item_path):
                            for d in dirs:
                                try:
                                    os.chmod(os.path.join(root, d), stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                                except Exception:
                                    pass
                            for f in files:
                                try:
                                    os.chmod(os.path.join(root, f), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                                except Exception:
                                    pass
                        shutil.rmtree(item_path)
                    else:
                        os.chmod(item_path, stat.S_IRUSR | stat.S_IWUSR)
                        os.remove(item_path)
                    count += 1
                    _LOGGER.debug("Startup cleanup: Deleted %s", item_path)
                except Exception as e:
                    _LOGGER.error("Failed to delete %s during startup cleanup: %s", item_path, e)
        except Exception as e:
            _LOGGER.error("Failed to clean up local folder: %s", e)

        return count

    async def _cleanup_smb_staging(self) -> int:
        """Clean up SMB staging folder (incomplete uploads). Returns count deleted."""
        if not self.download_manager:
            _LOGGER.debug("Download manager not set, skipping SMB staging cleanup")
            return 0

        try:
            count = await self.hass.async_add_executor_job(
                self.download_manager.cleanup_smb_staging
            )
            return count
        except Exception as e:
            _LOGGER.error("Failed to clean up SMB staging folder: %s", e)
            return 0

    async def _initialize_session(self) -> None:
        """Initialize or restore Tidal session."""
        self._session = tidalapi.Session()

        # Parse expiry time
        expiry_time = None
        if self.entry_data.get(CONF_EXPIRY_TIME):
            try:
                expiry_time = datetime.fromisoformat(self.entry_data[CONF_EXPIRY_TIME])
            except (ValueError, TypeError):
                pass

        # Load saved OAuth tokens
        await self.hass.async_add_executor_job(
            self._session.load_oauth_session,
            self.entry_data.get(CONF_TOKEN_TYPE, "Bearer"),
            self.entry_data[CONF_ACCESS_TOKEN],
            self.entry_data.get(CONF_REFRESH_TOKEN),
            expiry_time,
        )

        # Set audio quality on the session based on user config
        # tidalapi defaults to Quality.low_320k (HIGH/320kbps) if not set!
        quality_setting = self.entry_options.get(CONF_AUDIO_QUALITY, AudioQuality.LOSSLESS.value)
        quality_map = {
            AudioQuality.LOW.value: tidalapi.Quality.low_96k,
            AudioQuality.HIGH.value: tidalapi.Quality.low_320k,
            AudioQuality.LOSSLESS.value: tidalapi.Quality.high_lossless,
            AudioQuality.HI_RES.value: tidalapi.Quality.hi_res_lossless,
        }
        self._session.audio_quality = quality_map.get(quality_setting, tidalapi.Quality.high_lossless)
        _LOGGER.warning(
            "Tidal session audio_quality set to: %s (from config: %s)",
            self._session.audio_quality,
            quality_setting,
        )

        # Verify session is valid
        is_valid = await self.hass.async_add_executor_job(self._session.check_login)
        if not is_valid:
            # Attempt token refresh
            try:
                await self.hass.async_add_executor_job(self._session.token_refresh)
                _LOGGER.info("Tidal token refreshed successfully")
            except Exception as e:
                _LOGGER.error("Failed to refresh Tidal token: %s", e)
                raise ConfigEntryAuthFailed("Tidal authentication expired") from e

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch favorite albums and queue new downloads."""
        self._sync_status = "syncing"

        try:
            # Get current favorite albums
            albums = await self._get_favorite_albums()
            _LOGGER.warning(
                "Sync: Found %d favorite albums, %d already downloaded",
                len(albums),
                len(self._downloaded_albums),
            )

            # Get already queued album IDs to avoid duplicates
            queued_ids = self.download_manager.queued_album_ids if self.download_manager else set()

            _LOGGER.warning(
                "Sync filter: %d favorites, %d downloaded, %d in queue",
                len(albums),
                len(self._downloaded_albums),
                len(queued_ids),
            )

            # Find new albums (not downloaded AND not already in queue)
            new_albums = [
                album for album in albums
                if album.id not in self._downloaded_albums and album.id not in queued_ids
            ]

            # Queue new albums for download
            if new_albums:
                if self.download_manager:
                    _LOGGER.warning("Queueing %d new albums for download", len(new_albums))
                    for album in new_albums:
                        await self.download_manager.queue_download(album)
                else:
                    _LOGGER.error("Download manager not set - cannot queue downloads")
            else:
                _LOGGER.warning("No new albums to download (all %d are downloaded or queued)", len(albums))

            # Always try to resume queue processing in case items are waiting
            # (e.g., from a previous rate limit that has now reset)
            if self.download_manager:
                await self.download_manager.resume_queue()

            self._last_sync = dt_util.now()
            self._sync_status = "idle"

            return {
                "total_favorites": len(albums),
                "new_albums": len(new_albums),
                "downloaded_count": len(self._downloaded_albums),
                "queue_count": self.download_manager.queue_size
                if self.download_manager
                else 0,
                "last_sync": self._last_sync.isoformat(),
                "sync_status": self._sync_status,
            }

        except tidalapi.exceptions.AuthenticationError as e:
            self._sync_status = "auth_error"
            # Try to refresh token
            try:
                await self.hass.async_add_executor_job(self._session.token_refresh)
                _LOGGER.info("Token refreshed, retrying sync")
                # Retry after refresh
                return await self._async_update_data()
            except Exception:
                raise ConfigEntryAuthFailed("Tidal authentication failed") from e

        except Exception as e:
            self._sync_status = "error"
            _LOGGER.error("Error syncing Tidal favorites: %s", e)
            raise UpdateFailed(f"Error syncing favorites: {e}") from e

    async def _get_favorite_albums(self) -> list[tidalapi.Album]:
        """Get list of favorite albums from Tidal."""
        return await self.hass.async_add_executor_job(
            self._session.user.favorites.albums
        )

    async def mark_downloaded(self, album_id: int) -> None:
        """Mark an album as downloaded and persist to storage."""
        self._downloaded_albums.add(album_id)
        await self._save_downloaded_albums()
        _LOGGER.debug("Marked album %d as downloaded", album_id)

    async def _save_state(self) -> None:
        """Persist state (downloaded albums and settings) to storage."""
        await self._store.async_save({
            "downloaded_albums": list(self._downloaded_albums),
            "downloads_enabled": self._downloads_enabled,
        })

    async def _save_downloaded_albums(self) -> None:
        """Persist downloaded album IDs to storage (legacy wrapper)."""
        await self._save_state()

    async def force_sync(self) -> None:
        """Force an immediate sync."""
        _LOGGER.warning("force_sync called, triggering refresh")
        await self.async_refresh()

    async def clear_history(self) -> None:
        """Clear download history (allows re-downloading all favorites)."""
        count = len(self._downloaded_albums)
        self._downloaded_albums.clear()
        await self._save_downloaded_albums()
        _LOGGER.warning("Download history cleared (%d albums removed)", count)
        # Force refresh to update sensors and trigger new downloads
        await self.async_refresh()

    @property
    def session(self) -> tidalapi.Session | None:
        """Return the Tidal session."""
        return self._session

    @property
    def last_sync(self) -> datetime | None:
        """Return last sync time."""
        return self._last_sync

    @property
    def sync_status(self) -> str:
        """Return current sync status."""
        return self._sync_status

    @property
    def downloaded_count(self) -> int:
        """Return count of downloaded albums."""
        return len(self._downloaded_albums)

    @property
    def downloads_enabled(self) -> bool:
        """Return whether downloads are enabled."""
        return self._downloads_enabled

    async def set_downloads_enabled(self, enabled: bool) -> None:
        """Set downloads enabled state and persist to storage."""
        self._downloads_enabled = enabled
        await self._save_state()
        _LOGGER.warning("Downloads %s (persisted)", "ENABLED" if enabled else "DISABLED")
