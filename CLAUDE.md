# Tidal Album Downloader - Home Assistant Integration

## Project Overview
A Home Assistant custom integration that monitors Tidal Favourite Albums and automatically downloads complete albums to a configurable location, with optional upload to SMB/NAS shares.

## Tech Stack
- **Python** - Home Assistant integration
- **tidalapi** (>=0.8.8) - Tidal API access, OAuth authentication
- **tidal-dl-ng** (>=0.31.4) - Album downloading with quality selection
- **smbprotocol** (>=1.10.0) - SMB/NAS upload support
- **Home Assistant** - Custom component architecture

## Directory Structure
```
custom_components/
└── tidal_downloader/
    ├── __init__.py           # Integration setup, service registration
    ├── manifest.json         # Metadata and dependencies
    ├── config_flow.py        # OAuth device code flow + options UI
    ├── const.py              # Constants and configuration keys
    ├── strings.json          # UI strings
    ├── translations/en.json  # English translations
    ├── coordinator.py        # DataUpdateCoordinator for polling
    ├── sensor.py             # Status sensors
    ├── switch.py             # Download enabled kill switch
    ├── download_manager.py   # Download queue, execution, SMB upload
    └── services.yaml         # Service definitions
```

## Key Features

### Authentication
- OAuth 2.1 device code flow (user visits link.tidal.com)
- Automatic token refresh

### Download Management
- Monitors favourite albums, downloads new additions automatically
- Configurable audio quality: Low (96kbps) / High (320kbps) / Lossless (CD) / HiRes (24-bit/192kHz)
- FLAC extraction from M4A containers (requires FFmpeg)
- **Rate limiting**: Configurable max albums (X) per time period (Y hours)
- **Kill switch**: Toggle to immediately stop/start downloads

### File Organization
- Configurable folder template: `{album_artist}/{album_title}` etc.
- Configurable track filename template: `{album_track_num} - {track_title}` etc.
- Available template variables:
  - Folder: `{album_artist}`, `{album_title}`, `{album_year}`, `{album_id}`
  - Track: `{album_track_num}`, `{track_title}`, `{artist_name}`, `{track_volume_num}`, `{track_id}`

### SMB/NAS Support
- Optional upload to SMB shares after download
- Configurable: server, share, username, password, path
- Downloads locally first, then copies to NAS

### File Permissions
- Automatic open permissions (777/666) on downloaded files
- Service to fix permissions on existing files

## Services
| Service | Description |
|---------|-------------|
| `tidal_downloader.sync_now` | Trigger immediate sync of favourites |
| `tidal_downloader.force_download` | Download specific album by ID |
| `tidal_downloader.clear_history` | Reset download history (re-download all) |
| `tidal_downloader.fix_permissions` | Set open permissions on all downloaded files |

## Entities
### Sensors
- **Sync Status** - idle/syncing/error
- **Download Queue** - albums pending download
- **Downloaded Albums** - total downloaded count
- **Last Sync** - timestamp of last sync
- **Current Download** - album currently downloading
- **Rate Limit Remaining** - downloads left in current period

### Switches
- **Download Enabled** - Kill switch to enable/disable downloads

## Configuration Options
| Option | Description | Default |
|--------|-------------|---------|
| Download Path | Local temp directory | `/config/media/tidal` |
| Audio Quality | Quality level | Lossless |
| Polling Interval | Sync frequency (seconds) | 300 |
| Rate Limit Albums | Max albums per period | 5 |
| Rate Limit Hours | Period duration | 24 |
| Folder Template | Album folder structure | `{album_artist}/{album_title}` |
| File Template | Track filename format | `{track_volume_num}-{track_num} - {track_title}` |
| Extract FLAC | Convert to FLAC | true |
| Download Cover | Include cover art | true |
| SMB Enabled | Upload to NAS | false |
| SMB Server | NAS IP/hostname | - |
| SMB Share | Share name | - |
| SMB Username | Login user | - |
| SMB Password | Login password | - |
| SMB Path | Subfolder in share | - |

## Development Notes
- All blocking I/O must use `hass.async_add_executor_job()`
- Use DataUpdateCoordinator pattern for polling
- Store downloaded album IDs in HA's `.storage/` directory
- OAuth tokens stored in ConfigEntry data (encrypted)
- tidal-dl-ng requires Python 3.12+ and specific initialization:
  - Must provide `Progress` objects (Rich library) - use `disable=True`
  - Must provide `threading.Event` objects for abort/run control
  - Session wrapper needs `stream_lock`, `switch_to_atmos_session()`, `restore_normal_session()`

## Dependencies
- tidalapi >= 0.8.8
- tidal-dl-ng >= 0.31.4
- smbprotocol >= 1.10.0
- FFmpeg (required for FLAC extraction, typically at `/usr/bin/ffmpeg`)
