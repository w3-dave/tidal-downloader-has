"""Download manager for Tidal albums."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any, Callable, Awaitable, TYPE_CHECKING

import tidalapi

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import TidalDownloaderCoordinator

from .const import (
    CONF_DOWNLOAD_PATH,
    CONF_AUDIO_QUALITY,
    CONF_FOLDER_TEMPLATE,
    CONF_FILE_TEMPLATE,
    CONF_EXTRACT_FLAC,
    CONF_DOWNLOAD_COVER,
    CONF_RATE_LIMIT_ALBUMS,
    CONF_RATE_LIMIT_HOURS,
    CONF_SMB_ENABLED,
    CONF_SMB_SERVER,
    CONF_SMB_SHARE,
    CONF_SMB_USERNAME,
    CONF_SMB_PASSWORD,
    CONF_SMB_PATH,
    CONF_SMB_DELETE_AFTER_UPLOAD,
    DEFAULT_DOWNLOAD_PATH,
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_RATE_LIMIT_ALBUMS,
    DEFAULT_RATE_LIMIT_HOURS,
    AudioQuality,
)

_LOGGER = logging.getLogger(__name__)


FFMPEG_PATHS = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/config/bin/ffmpeg"]


def check_ffmpeg_available() -> tuple[bool, str | None]:
    """Check if FFmpeg is available. Returns (available, path)."""
    import shutil
    import os

    # Check common paths
    for path in FFMPEG_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return True, path

    # Check if in PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return True, ffmpeg_path

    return False, None


def test_ffmpeg_execution() -> tuple[bool, str]:
    """Test FFmpeg by actually executing it. Returns (success, output/error)."""
    import subprocess

    available, ffmpeg_path = check_ffmpeg_available()
    if not available:
        return False, "FFmpeg not found in any known location"

    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Get first line of version info
            version_line = result.stdout.split('\n')[0] if result.stdout else "No version output"
            _LOGGER.warning("FFmpeg test SUCCESS: %s", version_line)
            return True, version_line
        else:
            error = result.stderr or "Unknown error"
            _LOGGER.error("FFmpeg test FAILED (exit code %d): %s", result.returncode, error)
            return False, f"Exit code {result.returncode}: {error}"
    except subprocess.TimeoutExpired:
        _LOGGER.error("FFmpeg test FAILED: Timeout after 10 seconds")
        return False, "Timeout after 10 seconds"
    except Exception as e:
        _LOGGER.error("FFmpeg test FAILED: %s", str(e))
        return False, str(e)


class TidalSessionWrapper:
    """Wrapper to make tidalapi.Session compatible with tidal-dl-ng.

    tidal-dl-ng's Download class expects a Tidal object with:
    - session: tidalapi.Session
    - stream_lock: threading.Lock for thread-safe stream fetching
    - switch_to_atmos_session(): for Dolby Atmos downloads
    - restore_normal_session(): to restore after Atmos
    """

    def __init__(self, session: tidalapi.Session) -> None:
        """Initialize wrapper."""
        import threading

        self.session = session
        self.stream_lock = threading.Lock()
        self.is_atmos_session = False
        self._original_client_id = None
        self._original_client_secret = None

    def switch_to_atmos_session(self) -> bool:
        """Switch to Atmos credentials (stub - not implemented).

        Real implementation would switch client_id/secret for Atmos streams.
        For now, just return False to indicate Atmos not available.
        """
        _LOGGER.debug("switch_to_atmos_session called (stub - Atmos not supported)")
        self.is_atmos_session = False
        return False

    def restore_normal_session(self, force: bool = False) -> bool:
        """Restore normal session (stub - returns True to indicate success)."""
        _LOGGER.debug("restore_normal_session called (stub)")
        self.is_atmos_session = False
        return True  # Return True to indicate "success" even though we didn't switch


@dataclass
class DownloadTask:
    """Represents a pending album download."""

    album: tidalapi.Album
    queued_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"  # pending, downloading, completed, failed
    error: str | None = None
    progress: int = 0  # Track count progress


class DownloadManager:
    """Manages download queue and execution."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: tidalapi.Session,
        options: dict[str, Any],
        coordinator: TidalDownloaderCoordinator | None = None,
        on_download_complete: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize download manager."""
        self.hass = hass
        self._session = session
        self._options = options
        self._coordinator = coordinator
        self._on_download_complete = on_download_complete

        # Download queue
        self._queue: deque[DownloadTask] = deque()
        self._current_task: DownloadTask | None = None
        self._is_processing = False
        self._download_lock = asyncio.Lock()

        # Rate limiting - track timestamps of completed downloads
        self._download_timestamps: list[datetime] = []

        # tidal-dl-ng components (initialized lazily)
        self._download_engine = None
        self._settings = None
        self._media_type_enum = None

        # Kill switch - initialize from coordinator if available
        self._downloads_enabled = coordinator.downloads_enabled if coordinator else True

    def update_session(self, session: tidalapi.Session) -> None:
        """Update the Tidal session reference."""
        self._session = session
        # Reset download engine to use new session
        self._download_engine = None

    def update_options(self, options: dict[str, Any]) -> None:
        """Update options and reset download engine."""
        self._options = options
        self._download_engine = None
        self._settings = None
        self._media_type_enum = None

    def _get_rate_limit_albums(self) -> int:
        """Get the max albums per period setting."""
        return self._options.get(CONF_RATE_LIMIT_ALBUMS, DEFAULT_RATE_LIMIT_ALBUMS)

    def _get_rate_limit_hours(self) -> int:
        """Get the rate limit period in hours."""
        return self._options.get(CONF_RATE_LIMIT_HOURS, DEFAULT_RATE_LIMIT_HOURS)

    def _clean_old_timestamps(self) -> None:
        """Remove timestamps older than the rate limit period."""
        cutoff = datetime.now() - timedelta(hours=self._get_rate_limit_hours())
        self._download_timestamps = [
            ts for ts in self._download_timestamps if ts > cutoff
        ]

    def _can_download(self) -> bool:
        """Check if we can download based on rate limit."""
        self._clean_old_timestamps()
        return len(self._download_timestamps) < self._get_rate_limit_albums()

    def _get_rate_limit_remaining(self) -> int:
        """Get the number of downloads remaining in the current period."""
        self._clean_old_timestamps()
        return max(0, self._get_rate_limit_albums() - len(self._download_timestamps))

    def _get_rate_limit_reset_time(self) -> datetime | None:
        """Get when the rate limit will reset (oldest timestamp + period)."""
        self._clean_old_timestamps()
        if not self._download_timestamps:
            return None
        # The rate limit resets when the oldest download falls outside the window
        oldest = min(self._download_timestamps)
        return oldest + timedelta(hours=self._get_rate_limit_hours())

    def _record_download(self) -> None:
        """Record a download timestamp for rate limiting."""
        self._download_timestamps.append(datetime.now())

    async def _ensure_download_engine(self) -> None:
        """Initialize tidal-dl-ng download engine if needed."""
        if self._download_engine is not None:
            _LOGGER.warning("Download engine already initialized")
            return

        _LOGGER.warning("Initializing tidal-dl-ng download engine")

        def _init_engine():
            # Import tidal-dl-ng components
            from tidal_dl_ng.download import Download
            from tidal_dl_ng.config import Settings
            from tidal_dl_ng.constants import MediaType
            from rich.progress import Progress

            # Create a dummy progress bar (tidal-dl-ng requires one)
            # We use transient=True so it doesn't leave output
            # Start the progress context so add_task() works
            progress = Progress(transient=True, disable=True)
            progress.start()  # Must be started for add_task() to work

            # Configure tidal-dl-ng settings
            settings = Settings()

            # Map our quality setting to tidal-dl-ng format
            quality_map = {
                AudioQuality.LOW.value: "LOW",
                AudioQuality.HIGH.value: "HIGH",
                AudioQuality.LOSSLESS.value: "LOSSLESS",
                AudioQuality.HI_RES.value: "HI_RES_LOSSLESS",
            }

            settings.data.quality_audio = quality_map.get(
                self._options.get(CONF_AUDIO_QUALITY, AudioQuality.LOSSLESS.value),
                "LOSSLESS",
            )
            settings.data.download_base_path = self._options.get(
                CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH
            )
            # FLAC extraction - converts M4A to FLAC (requires FFmpeg)
            settings.data.extract_flac = self._options.get(CONF_EXTRACT_FLAC, True)
            settings.data.skip_existing = True

            # Set FFmpeg path (standard location in Home Assistant OS)
            settings.data.path_binary_ffmpeg = "/usr/bin/ffmpeg"

            # Folder template from config
            # Available vars: {album_artist}, {album_title}, {album_year}, {album_id}
            settings.data.fn_template_album = self._options.get(
                CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
            )

            # Track filename template from config
            # Available vars: {track_volume_num}, {track_num}, {track_title}, {artist_name}, {track_id}
            # Note: tidal-dl-ng adds the file extension automatically
            settings.data.fn_template_track = self._options.get(
                CONF_FILE_TEMPLATE, DEFAULT_FILE_TEMPLATE
            )

            # Download cover art
            settings.data.download_cover = self._options.get(CONF_DOWNLOAD_COVER, True)

            # Wrap session for tidal-dl-ng compatibility
            session_wrapper = TidalSessionWrapper(self._session)

            # Create a second progress bar for overall progress
            progress_overall = Progress(transient=True, disable=True)
            progress_overall.start()

            # Create threading events for abort/run control
            import threading
            event_abort = threading.Event()  # Not set = don't abort
            event_run = threading.Event()
            event_run.set()  # Set = running

            # Initialize download engine with correct parameters
            # Signature: __init__(tidal_obj, path_base, fn_logger, skip_existing, progress_gui, progress, progress_overall, event_abort, event_run)
            download = Download(
                tidal_obj=session_wrapper,
                path_base=settings.data.download_base_path,
                fn_logger=_LOGGER,
                skip_existing=settings.data.skip_existing,
                progress=progress,
                progress_overall=progress_overall,
                event_abort=event_abort,
                event_run=event_run,
            )

            # Override the internal settings created by Download.__init__
            # since it doesn't accept settings as a parameter
            ffmpeg_available, ffmpeg_path = check_ffmpeg_available()

            # Actually test FFmpeg execution
            ffmpeg_works, ffmpeg_test_result = test_ffmpeg_execution()
            _LOGGER.warning("FFmpeg execution test: works=%s, result=%s", ffmpeg_works, ffmpeg_test_result)

            extract_flac = self._options.get(CONF_EXTRACT_FLAC, True) and ffmpeg_works

            download.settings.data.extract_flac = extract_flac
            download.settings.data.path_binary_ffmpeg = ffmpeg_path or "/usr/bin/ffmpeg"
            download.settings.data.quality_audio = quality_map.get(
                self._options.get(CONF_AUDIO_QUALITY, AudioQuality.LOSSLESS.value),
                "LOSSLESS",
            )
            # tidal-dl-ng uses format_* not fn_template_*
            download.settings.data.format_album = self._options.get(
                CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
            )
            download.settings.data.format_track = self._options.get(
                CONF_FILE_TEMPLATE, DEFAULT_FILE_TEMPLATE
            )
            download.settings.data.download_cover_album = self._options.get(CONF_DOWNLOAD_COVER, True)

            # Save the settings to disk so tidal-dl-ng uses them
            download.settings.save()

            _LOGGER.warning(
                "tidal-dl-ng config file: %s",
                download.settings.file_path,
            )
            _LOGGER.warning(
                "tidal-dl-ng settings applied and saved: extract_flac=%s, ffmpeg_path=%s, quality=%s, format_track=%s",
                download.settings.data.extract_flac,
                download.settings.data.path_binary_ffmpeg,
                download.settings.data.quality_audio,
                download.settings.data.format_track,
            )

            # Verify by reading the file back
            try:
                import json
                with open(download.settings.file_path, 'r') as f:
                    saved_config = json.load(f)
                _LOGGER.warning(
                    "Verified saved config - extract_flac=%s, path_binary_ffmpeg=%s",
                    saved_config.get('extract_flac'),
                    saved_config.get('path_binary_ffmpeg'),
                )
            except Exception as e:
                _LOGGER.error("Failed to verify config file: %s", e)

            if not ffmpeg_available and self._options.get(CONF_EXTRACT_FLAC, True):
                _LOGGER.warning("FFmpeg not found - FLAC extraction disabled. Files will be saved as M4A.")

            return download, settings, MediaType

        try:
            self._download_engine, self._settings, self._media_type_enum = await self.hass.async_add_executor_job(
                _init_engine
            )
            _LOGGER.warning("tidal-dl-ng engine initialized successfully")
        except Exception as e:
            _LOGGER.error("Failed to initialize tidal-dl-ng engine: %s", e, exc_info=True)
            raise

    async def queue_download(self, album: tidalapi.Album) -> None:
        """Add an album to the download queue."""
        task = DownloadTask(album=album)
        self._queue.append(task)

        artist_name = "Unknown Artist"
        try:
            if album.artist:
                artist_name = album.artist.name
        except Exception:
            pass

        _LOGGER.warning(
            "Queued album: %s - %s (queue size: %d, is_processing: %s)",
            artist_name,
            album.name,
            len(self._queue),
            self._is_processing,
        )

        # Start processing if not already running
        if not self._is_processing:
            _LOGGER.warning("Creating queue processing task")
            self.hass.async_create_task(self._process_queue())

    async def _process_queue(self) -> None:
        """Process download queue."""
        _LOGGER.warning("_process_queue called, attempting to acquire lock")
        async with self._download_lock:
            if self._is_processing:
                _LOGGER.warning("Already processing, exiting")
                return
            self._is_processing = True
            _LOGGER.warning("Lock acquired, starting processing")

        try:
            # Check kill switch before starting
            if not self._downloads_enabled:
                _LOGGER.warning("Downloads DISABLED - not starting queue processing")
                return

            _LOGGER.warning("Starting download queue processing, %d albums in queue", len(self._queue))
            await self._ensure_download_engine()
            _LOGGER.warning("Download engine initialized")

            while self._queue:
                # Check kill switch before each download
                if not self._downloads_enabled:
                    _LOGGER.warning(
                        "Downloads DISABLED - stopping queue processing. %d albums remain queued.",
                        len(self._queue),
                    )
                    break

                # Check rate limit before processing
                if not self._can_download():
                    reset_time = self._get_rate_limit_reset_time()
                    _LOGGER.warning(
                        "Rate limit reached (%d albums in %d hours). "
                        "Next download available at %s. %d albums queued.",
                        self._get_rate_limit_albums(),
                        self._get_rate_limit_hours(),
                        reset_time.isoformat() if reset_time else "unknown",
                        len(self._queue),
                    )
                    # Stop processing - will resume on next sync
                    break

                task = self._queue.popleft()
                self._current_task = task
                task.status = "downloading"

                artist_name = "Unknown Artist"
                try:
                    if task.album.artist:
                        artist_name = task.album.artist.name
                except Exception:
                    pass

                _LOGGER.warning(
                    "Starting download: %s - %s (album_id: %s)",
                    artist_name,
                    task.album.name,
                    task.album.id,
                )

                try:
                    await self._download_album(task)
                    task.status = "completed"

                    # Set open permissions on downloaded files
                    folder_template = self._options.get(
                        CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
                    )
                    album_folder = folder_template.replace(
                        "{album_artist}", artist_name
                    ).replace("{album_title}", task.album.name).replace(
                        "{album_year}", str(task.album.year) if task.album.year else ""
                    ).replace("{album_id}", str(task.album.id))
                    local_album_path = f"{self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)}/{album_folder}"

                    _LOGGER.warning(
                        "Post-download processing: local_album_path=%s, album_folder=%s",
                        local_album_path,
                        album_folder,
                    )

                    await self.hass.async_add_executor_job(
                        self._set_open_permissions, local_album_path
                    )

                    # Upload to SMB if enabled
                    _LOGGER.warning("Checking SMB upload... calling _is_smb_enabled()")
                    if self._is_smb_enabled():
                        _LOGGER.warning("SMB is enabled, calling _upload_to_smb")
                        smb_success = await self._upload_to_smb(local_album_path, album_folder)

                        # Delete local files after successful SMB upload if option enabled
                        if smb_success and self._options.get(CONF_SMB_DELETE_AFTER_UPLOAD, False):
                            _LOGGER.warning("SMB upload successful, deleting local files: %s", local_album_path)
                            await self.hass.async_add_executor_job(
                                self._delete_local_album, local_album_path
                            )
                    else:
                        _LOGGER.warning("SMB upload NOT enabled, skipping")

                    # Record download for rate limiting
                    self._record_download()

                    # Notify coordinator
                    if self._on_download_complete:
                        await self._on_download_complete(task.album.id)

                    _LOGGER.warning(
                        "Downloaded album: %s - %s (Rate limit: %d/%d remaining)",
                        artist_name,
                        task.album.name,
                        self._get_rate_limit_remaining(),
                        self._get_rate_limit_albums(),
                    )

                except Exception as e:
                    task.status = "failed"
                    task.error = str(e)
                    _LOGGER.error(
                        "Failed to download %s - %s: %s",
                        artist_name,
                        task.album.name,
                        e,
                    )

                self._current_task = None

        finally:
            self._is_processing = False
            _LOGGER.warning("Download queue processing finished")

            # Clean up empty folders if delete after SMB upload is enabled
            if self._options.get(CONF_SMB_DELETE_AFTER_UPLOAD, False):
                download_path = self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)
                _LOGGER.warning("Cleaning up empty folders in: %s", download_path)
                await self.hass.async_add_executor_job(
                    self._cleanup_empty_folders, download_path
                )

    async def _download_album(self, task: DownloadTask) -> None:
        """Download a single album using tidal-dl-ng."""
        album = task.album
        _LOGGER.warning(
            "Calling tidal-dl-ng to download album %s to %s",
            album.id,
            self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH),
        )

        # Run download in executor (blocking I/O)
        # items() signature: items(file_template, media=None, media_id=None, media_type=None, ...)
        try:
            # Combine folder template and file template into full path
            folder_template = self._options.get(CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE)
            track_template = self._options.get(CONF_FILE_TEMPLATE, DEFAULT_FILE_TEMPLATE)
            file_template = f"{folder_template}/{track_template}"

            # Pre-create album directory to avoid tidal-dl-ng errors
            download_path = self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)
            artist_name = album.artist.name if album.artist else "Unknown Artist"
            album_folder = folder_template.replace("{album_artist}", artist_name).replace("{album_title}", album.name)
            album_folder = album_folder.replace("{album_year}", str(album.year) if album.year else "").replace("{album_id}", str(album.id))
            full_album_path = f"{download_path}/{album_folder}"

            import os
            os.makedirs(full_album_path, exist_ok=True)
            _LOGGER.warning("Pre-created album directory: %s", full_album_path)

            _LOGGER.warning(
                "Executing tidal-dl-ng download.items(file_template='%s', media_id='%s', media_type=ALBUM, extract_flac=%s)",
                file_template,
                album.id,
                self._download_engine.settings.data.extract_flac,
            )

            def _do_download():
                # Log all relevant settings before download
                _LOGGER.warning(
                    "tidal-dl-ng settings check before download: extract_flac=%s, ffmpeg=%s, quality=%s",
                    self._download_engine.settings.data.extract_flac,
                    self._download_engine.settings.data.path_binary_ffmpeg,
                    self._download_engine.settings.data.quality_audio,
                )
                return self._download_engine.items(
                    file_template=file_template,
                    media_id=str(album.id),
                    media_type=self._media_type_enum.ALBUM,
                )

            result = await self.hass.async_add_executor_job(_do_download)
            _LOGGER.warning("tidal-dl-ng download call completed for album %s, result: %s", album.id, result)
        except Exception as e:
            _LOGGER.error("tidal-dl-ng download failed for album %s: %s", album.id, e, exc_info=True)
            raise

    async def force_download(self, album_id: int) -> None:
        """Force download a specific album (even if already downloaded)."""
        # Get album info from Tidal
        album = await self.hass.async_add_executor_job(self._session.album, album_id)

        if album:
            await self.queue_download(album)
        else:
            raise ValueError(f"Album {album_id} not found")

    @property
    def queue_size(self) -> int:
        """Return number of items in queue."""
        return len(self._queue)

    @property
    def queued_album_ids(self) -> set[int]:
        """Return set of album IDs currently in queue (including current download)."""
        ids = {task.album.id for task in self._queue}
        if self._current_task:
            ids.add(self._current_task.album.id)
        return ids

    def clear_queue(self) -> int:
        """Clear the download queue. Returns number of items cleared."""
        count = len(self._queue)
        self._queue.clear()
        _LOGGER.warning("Download queue cleared (%d items removed)", count)
        return count

    @property
    def current_download(self) -> str | None:
        """Return currently downloading album name."""
        if self._current_task:
            album = self._current_task.album
            artist_name = "Unknown Artist"
            try:
                if album.artist:
                    artist_name = album.artist.name
            except Exception:
                pass
            return f"{artist_name} - {album.name}"
        return None

    @property
    def is_downloading(self) -> bool:
        """Return whether downloads are in progress."""
        return self._is_processing

    @property
    def rate_limit_remaining(self) -> int:
        """Return number of downloads remaining in current period."""
        return self._get_rate_limit_remaining()

    @property
    def rate_limit_reset_time(self) -> datetime | None:
        """Return when the rate limit will reset."""
        return self._get_rate_limit_reset_time()

    @property
    def is_rate_limited(self) -> bool:
        """Return whether rate limit has been reached."""
        return not self._can_download()

    @property
    def ffmpeg_available(self) -> bool:
        """Return whether FFmpeg is available for FLAC extraction."""
        available, _ = check_ffmpeg_available()
        return available

    @property
    def ffmpeg_path(self) -> str | None:
        """Return the path to FFmpeg if available."""
        _, path = check_ffmpeg_available()
        return path

    _ffmpeg_test_cache: tuple[bool, str] | None = None

    @property
    def ffmpeg_test_result(self) -> tuple[bool, str]:
        """Test FFmpeg execution and return cached (success, message)."""
        if DownloadManager._ffmpeg_test_cache is None:
            DownloadManager._ffmpeg_test_cache = test_ffmpeg_execution()
        return DownloadManager._ffmpeg_test_cache

    @property
    def downloads_enabled(self) -> bool:
        """Return whether downloads are enabled (kill switch)."""
        return self._downloads_enabled

    @downloads_enabled.setter
    def downloads_enabled(self, value: bool) -> None:
        """Set whether downloads are enabled (local state only, use async_set_downloads_enabled for persistence)."""
        self._downloads_enabled = value
        if not value:
            _LOGGER.warning("Downloads DISABLED via kill switch")
        else:
            _LOGGER.warning("Downloads ENABLED")

    async def async_set_downloads_enabled(self, value: bool) -> None:
        """Set whether downloads are enabled and persist to storage."""
        self._downloads_enabled = value
        if self._coordinator:
            await self._coordinator.set_downloads_enabled(value)
        if not value:
            _LOGGER.warning("Downloads DISABLED via kill switch (persisted)")
        else:
            _LOGGER.warning("Downloads ENABLED (persisted)")

    def get_queue_status(self) -> list[dict[str, Any]]:
        """Return status of all queued items."""
        items = []

        if self._current_task:
            album = self._current_task.album
            artist_name = "Unknown Artist"
            try:
                if album.artist:
                    artist_name = album.artist.name
            except Exception:
                pass

            items.append(
                {
                    "album_id": album.id,
                    "name": f"{artist_name} - {album.name}",
                    "status": self._current_task.status,
                    "queued_at": self._current_task.queued_at.isoformat(),
                }
            )

        for task in self._queue:
            album = task.album
            artist_name = "Unknown Artist"
            try:
                if album.artist:
                    artist_name = album.artist.name
            except Exception:
                pass

            items.append(
                {
                    "album_id": album.id,
                    "name": f"{artist_name} - {album.name}",
                    "status": task.status,
                    "queued_at": task.queued_at.isoformat(),
                }
            )

        return items

    def _is_smb_enabled(self) -> bool:
        """Check if SMB upload is enabled."""
        enabled = self._options.get(CONF_SMB_ENABLED, False)
        _LOGGER.warning("SMB enabled check: %s (from options: %s)", enabled, CONF_SMB_ENABLED in self._options)
        return enabled

    def _get_smb_config(self) -> dict[str, str]:
        """Get SMB configuration."""
        return {
            "server": self._options.get(CONF_SMB_SERVER, ""),
            "share": self._options.get(CONF_SMB_SHARE, ""),
            "username": self._options.get(CONF_SMB_USERNAME, ""),
            "password": self._options.get(CONF_SMB_PASSWORD, ""),
            "path": self._options.get(CONF_SMB_PATH, ""),
        }

    async def _upload_to_smb(self, local_path: str, album_folder: str) -> bool:
        """Upload downloaded album to SMB share. Returns True if successful."""
        import os

        _LOGGER.warning("_upload_to_smb called with local_path=%s, album_folder=%s", local_path, album_folder)

        if not self._is_smb_enabled():
            _LOGGER.warning("SMB upload skipped - not enabled")
            return False

        smb_config = self._get_smb_config()
        _LOGGER.warning(
            "SMB config: server=%s, share=%s, path=%s, username=%s",
            smb_config["server"],
            smb_config["share"],
            smb_config["path"],
            smb_config["username"],
        )

        if not smb_config["server"] or not smb_config["share"]:
            _LOGGER.warning("SMB enabled but server/share not configured")
            return False

        # Check if local path exists and has files
        if not os.path.exists(local_path):
            _LOGGER.error("SMB upload failed - local path does not exist: %s", local_path)
            return False

        local_files = []
        for root, dirs, files in os.walk(local_path):
            local_files.extend(files)
        _LOGGER.warning("Local path contains %d files to upload: %s", len(local_files), local_files[:5])

        _LOGGER.warning(
            "Starting SMB upload: %s -> //%s/%s/%s/%s",
            local_path,
            smb_config["server"],
            smb_config["share"],
            smb_config["path"],
            album_folder,
        )

        success = await self.hass.async_add_executor_job(
            self._smb_upload_directory,
            local_path,
            album_folder,
            smb_config,
        )
        return success

    def _smb_upload_directory(
        self, local_path: str, album_folder: str, smb_config: dict[str, str]
    ) -> bool:
        """Upload a directory to SMB share (blocking). Returns True if successful."""
        import os
        from pathlib import Path

        _LOGGER.warning("_smb_upload_directory called (blocking) - local_path=%s", local_path)

        try:
            from smbclient import register_session, makedirs, open_file
            import smbclient
            _LOGGER.warning("smbclient imported successfully")

            # Register SMB session
            _LOGGER.warning("Registering SMB session to server: %s", smb_config["server"])
            register_session(
                smb_config["server"],
                username=smb_config["username"],
                password=smb_config["password"],
            )
            _LOGGER.warning("SMB session registered successfully")

            # Build remote path including album folder structure
            base_path = smb_config["path"].strip("/") if smb_config["path"] else ""
            # Convert album_folder from forward slashes to backslashes for SMB path
            album_folder_smb = album_folder.replace("/", "\\")
            if base_path:
                remote_base = f"\\\\{smb_config['server']}\\{smb_config['share']}\\{base_path}\\{album_folder_smb}"
            else:
                remote_base = f"\\\\{smb_config['server']}\\{smb_config['share']}\\{album_folder_smb}"

            _LOGGER.warning("SMB remote base path (with album folder): %s", remote_base)

            # Walk local directory and upload files
            local_base = Path(local_path)
            files_uploaded = 0
            files_failed = 0

            _LOGGER.warning("Walking local directory: %s", local_path)
            for root, dirs, files in os.walk(local_path):
                _LOGGER.warning("Processing dir: %s (files: %s)", root, files)
                root_path = Path(root)
                relative_path = root_path.relative_to(local_base)

                # Create remote directory
                remote_dir = f"{remote_base}\\{str(relative_path).replace('/', '\\')}"
                _LOGGER.warning("Creating remote directory: %s", remote_dir)
                try:
                    makedirs(remote_dir, exist_ok=True)
                    _LOGGER.warning("Remote directory created/verified: %s", remote_dir)
                except Exception as e:
                    _LOGGER.warning("Directory creation issue (may already exist): %s - %s", remote_dir, e)

                # Upload files
                for filename in files:
                    local_file = root_path / filename
                    remote_file = f"{remote_dir}\\{filename}"

                    _LOGGER.warning("Uploading file: %s -> %s", local_file, remote_file)
                    try:
                        with open(local_file, "rb") as src:
                            file_data = src.read()
                            _LOGGER.warning("Read %d bytes from local file", len(file_data))
                            with open_file(remote_file, mode="wb") as dst:
                                dst.write(file_data)
                        files_uploaded += 1
                        _LOGGER.warning("Successfully uploaded: %s", remote_file)
                    except Exception as e:
                        files_failed += 1
                        _LOGGER.error("Failed to upload %s: %s", filename, e, exc_info=True)

            _LOGGER.warning("SMB upload complete: %d files uploaded, %d failed", files_uploaded, files_failed)
            # Consider success if at least some files uploaded and no failures
            return files_uploaded > 0 and files_failed == 0

        except ImportError:
            _LOGGER.error("smbprotocol not installed - cannot upload to SMB")
            return False
        except Exception as e:
            _LOGGER.error("SMB upload failed: %s", e, exc_info=True)
            return False

    def _delete_local_album(self, path: str) -> None:
        """Delete local album folder after successful SMB upload (blocking)."""
        import os
        import shutil
        import stat

        try:
            if not os.path.exists(path):
                _LOGGER.warning("Local album path does not exist, nothing to delete: %s", path)
                return

            # First set open permissions to ensure we can delete everything
            for root, dirs, files in os.walk(path):
                for d in dirs:
                    dir_path = os.path.join(root, d)
                    try:
                        os.chmod(dir_path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                    except Exception as e:
                        _LOGGER.debug("Could not chmod dir %s: %s", dir_path, e)

                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                    except Exception as e:
                        _LOGGER.debug("Could not chmod file %s: %s", file_path, e)

            # Now delete the directory
            shutil.rmtree(path)
            _LOGGER.warning("Deleted local album folder: %s", path)

        except Exception as e:
            _LOGGER.error("Failed to delete local album folder %s: %s", path, e)

    def _cleanup_empty_folders(self, path: str) -> int:
        """Remove empty folders recursively from bottom up (blocking). Returns count removed."""
        import os

        removed_count = 0
        try:
            if not os.path.exists(path):
                return 0

            # Walk bottom-up so we can remove empty child dirs before checking parent
            for root, dirs, files in os.walk(path, topdown=False):
                # Don't delete the root download path itself
                if root == path:
                    continue

                # Check if directory is empty (no files and no subdirs)
                try:
                    if not os.listdir(root):
                        os.rmdir(root)
                        removed_count += 1
                        _LOGGER.debug("Removed empty folder: %s", root)
                except Exception as e:
                    _LOGGER.debug("Could not remove folder %s: %s", root, e)

            if removed_count > 0:
                _LOGGER.warning("Cleaned up %d empty folders", removed_count)

        except Exception as e:
            _LOGGER.error("Failed to cleanup empty folders: %s", e)

        return removed_count

    def _set_open_permissions(self, path: str) -> None:
        """Set open permissions (777) on all files and directories recursively."""
        import os
        import stat

        try:
            # Set permissions: rwxrwxrwx (777) for dirs, rw-rw-rw- (666) for files
            for root, dirs, files in os.walk(path):
                # Set directory permissions to 777
                try:
                    os.chmod(root, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                except Exception as e:
                    _LOGGER.debug("Could not chmod dir %s: %s", root, e)

                # Set file permissions to 666
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                    except Exception as e:
                        _LOGGER.debug("Could not chmod file %s: %s", filepath, e)

            _LOGGER.debug("Set open permissions on: %s", path)
        except Exception as e:
            _LOGGER.error("Failed to set permissions on %s: %s", path, e)

    async def fix_permissions(self) -> int:
        """Fix permissions on all files in download directory. Returns count of files fixed."""
        download_path = self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)
        _LOGGER.warning("Fixing permissions on: %s", download_path)

        count = await self.hass.async_add_executor_job(
            self._fix_all_permissions, download_path
        )
        _LOGGER.warning("Fixed permissions on %d files/directories", count)
        return count

    def _fix_all_permissions(self, path: str) -> int:
        """Fix permissions on all files (blocking). Returns count."""
        import os
        import stat

        count = 0
        try:
            for root, dirs, files in os.walk(path):
                # Fix directory permissions
                try:
                    os.chmod(root, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                    count += 1
                except Exception as e:
                    _LOGGER.debug("Could not chmod dir %s: %s", root, e)

                # Fix file permissions
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                        count += 1
                    except Exception as e:
                        _LOGGER.debug("Could not chmod file %s: %s", filepath, e)
        except Exception as e:
            _LOGGER.error("Failed to fix permissions: %s", e)

        return count

    async def clear_local_files(self) -> int:
        """Delete all files in the local download directory. Returns count of items deleted."""
        download_path = self._options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH)
        _LOGGER.warning("Clearing all files in local download folder: %s", download_path)

        count = await self.hass.async_add_executor_job(
            self._clear_directory_contents, download_path
        )
        _LOGGER.warning("Deleted %d files/directories from local folder", count)
        return count

    def _clear_directory_contents(self, path: str) -> int:
        """Delete all contents of a directory (blocking). Returns count of items deleted."""
        import os
        import shutil
        import stat

        count = 0
        try:
            if not os.path.exists(path):
                _LOGGER.warning("Download path does not exist: %s", path)
                return 0

            # First pass: set open permissions on everything recursively
            for root, dirs, files in os.walk(path):
                # Set directory permissions to 777
                for d in dirs:
                    dir_path = os.path.join(root, d)
                    try:
                        os.chmod(dir_path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
                    except Exception as e:
                        _LOGGER.debug("Could not chmod dir %s: %s", dir_path, e)

                # Set file permissions to 666
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
                    except Exception as e:
                        _LOGGER.debug("Could not chmod file %s: %s", file_path, e)

            # Second pass: delete everything
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        _LOGGER.debug("Deleted directory: %s", item_path)
                    else:
                        os.remove(item_path)
                        _LOGGER.debug("Deleted file: %s", item_path)
                    count += 1
                except Exception as e:
                    _LOGGER.error("Failed to delete %s: %s", item_path, e)
        except Exception as e:
            _LOGGER.error("Failed to clear directory contents: %s", e)

        return count
