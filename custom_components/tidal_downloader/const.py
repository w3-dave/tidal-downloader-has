"""Constants for Tidal Downloader integration."""
from enum import Enum

DOMAIN = "tidal_downloader"
PLATFORMS = ["sensor"]

# Configuration keys
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_TYPE = "token_type"
CONF_EXPIRY_TIME = "expiry_time"
CONF_DOWNLOAD_PATH = "download_path"
CONF_AUDIO_QUALITY = "audio_quality"
CONF_POLL_INTERVAL = "poll_interval"
CONF_FOLDER_TEMPLATE = "folder_template"
CONF_FILE_TEMPLATE = "file_template"
CONF_EXTRACT_FLAC = "extract_flac"
CONF_DOWNLOAD_LYRICS = "download_lyrics"
CONF_DOWNLOAD_COVER = "download_cover"
CONF_RATE_LIMIT_ALBUMS = "rate_limit_albums"
CONF_RATE_LIMIT_HOURS = "rate_limit_hours"

# SMB/NAS Configuration
CONF_SMB_ENABLED = "smb_enabled"
CONF_SMB_SERVER = "smb_server"
CONF_SMB_SHARE = "smb_share"
CONF_SMB_USERNAME = "smb_username"
CONF_SMB_PASSWORD = "smb_password"
CONF_SMB_PATH = "smb_path"
CONF_SMB_DELETE_AFTER_UPLOAD = "smb_delete_after_upload"

# Defaults
DEFAULT_POLL_INTERVAL = 5  # 5 minutes
DEFAULT_RATE_LIMIT_ALBUMS = 5  # Max albums per time period
DEFAULT_RATE_LIMIT_HOURS = 24  # Time period in hours
# tidal-dl-ng template variables:
# Folder: {album_artist}, {album_title}, {album_year}, {album_id}
# Track: {album_track_num}, {track_title}, {artist_name}, {track_volume_num}
DEFAULT_FOLDER_TEMPLATE = "{album_artist}/{album_title}"
DEFAULT_FILE_TEMPLATE = "{track_volume_num}-{album_track_num} - {track_title}"
DEFAULT_DOWNLOAD_PATH = "/config/media/tidal"


class AudioQuality(Enum):
    """Audio quality options matching tidal-dl-ng."""

    LOW = "LOW"  # 96 kbps AAC
    HIGH = "HIGH"  # 320 kbps AAC
    LOSSLESS = "LOSSLESS"  # 16-bit 44.1kHz FLAC
    HI_RES = "HI_RES_LOSSLESS"  # 24-bit up to 192kHz FLAC


AUDIO_QUALITY_OPTIONS = {
    AudioQuality.LOW.value: "Low (96 kbps)",
    AudioQuality.HIGH.value: "High (320 kbps)",
    AudioQuality.LOSSLESS.value: "Lossless (CD Quality)",
    AudioQuality.HI_RES.value: "HiRes Lossless (24-bit/192kHz)",
}

# Storage keys
STORAGE_KEY = f"{DOMAIN}_downloaded_albums"
STORAGE_VERSION = 1

# Service names
SERVICE_SYNC_NOW = "sync_now"
SERVICE_FORCE_DOWNLOAD = "force_download"
SERVICE_CLEAR_HISTORY = "clear_history"
SERVICE_FIX_PERMISSIONS = "fix_permissions"
SERVICE_CLEAR_LOCAL_FILES = "clear_local_files"
SERVICE_CLEAR_QUEUE = "clear_queue"

# Sensor attributes
ATTR_LAST_SYNC = "last_sync"
ATTR_QUEUE_COUNT = "queue_count"
ATTR_DOWNLOADED_COUNT = "downloaded_count"
ATTR_CURRENT_DOWNLOAD = "current_download"
ATTR_SYNC_STATUS = "sync_status"
ATTR_RATE_LIMIT_REMAINING = "rate_limit_remaining"
ATTR_RATE_LIMIT_RESETS_AT = "rate_limit_resets_at"
