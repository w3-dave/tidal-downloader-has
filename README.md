# 🎵 Tidal Album Downloader for Home Assistant

A Home Assistant custom integration that automatically downloads your Tidal favourite albums to a local directory or NAS.

## ✨ Features

- **Automatic Sync** - Monitors your Tidal favourites and automatically downloads new albums
- **High Quality Audio** - Supports all Tidal quality tiers up to HiRes Lossless (24-bit/192kHz)
- **FLAC Extraction** - Automatically extracts FLAC from M4A containers (requires FFmpeg)
- **SMB/NAS Upload** - Optional automatic upload to network shares with atomic staging
- **Resilient Transfers** - Automatic recovery from interrupted downloads and failed uploads
- **Rate Limiting** - Configurable download limits to avoid API throttling
- **Flexible Organization** - Customizable folder and filename templates
- **Kill Switch** - Enable/disable downloads instantly via UI toggle

## 📋 Requirements

- Home Assistant 2024.1 or newer
- Tidal subscription (HiFi Plus required for HiRes quality)
- FFmpeg (required for FLAC extraction, typically pre-installed on Home Assistant OS)

## 📥 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Click **Install**
5. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/tidal_downloader` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## ⚙️ Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Tidal Downloader**
3. Follow the OAuth flow to link your Tidal account
4. Configure your download settings

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| **Local Download Path** | Directory for downloaded albums | `/config/media/tidal` |
| **Audio Quality** | Quality level (Low/High/Lossless/HiRes) | Lossless |
| **Polling Interval** | How often to check for new favourites (minutes) | 5 |
| **Max Albums per Period** | Rate limit - max albums to download | 5 |
| **Rate Limit Period** | Rate limit time window (hours) | 24 |
| **Folder Template** | Album folder structure | `{album_artist}/{album_title}` |
| **File Template** | Track filename format | `{track_volume_num}-{album_track_num} - {track_title}` |
| **Extract FLAC** | Convert M4A to FLAC | Enabled |
| **Download Cover Art** | Include album artwork | Enabled |

### SMB/NAS Options

| Option | Description |
|--------|-------------|
| **Upload to SMB/NAS** | Enable network upload |
| **SMB Server** | NAS IP or hostname |
| **SMB Share** | Share name |
| **SMB Username** | Login username |
| **SMB Password** | Login password |
| **SMB Path** | Subfolder within share |
| **Delete Local After Upload** | Remove local files after successful upload |

### Template Variables

**Folder templates:**
- `{album_artist}` - Album artist name
- `{album_title}` - Album title
- `{album_year}` - Release year
- `{album_id}` - Tidal album ID

**File templates:**
- `{track_volume_num}` - Disc number
- `{album_track_num}` - Track number
- `{track_title}` - Track title
- `{artist_name}` - Track artist

## 🎛️ Entities

### Sensors

| Entity | Description |
|--------|-------------|
| **Sync Status** | Current state (idle/syncing/error) |
| **Download Queue** | Number of albums pending download |
| **Downloaded Albums** | Total albums downloaded |
| **Last Sync** | Timestamp of last sync |
| **Current Download** | Album currently downloading |
| **Rate Limit Remaining** | Downloads left in current period |
| **FFmpeg Status** | FFmpeg availability check |

### Switches

| Entity | Description |
|--------|-------------|
| **Download Enabled** | Kill switch to enable/disable all downloads |

### Buttons

| Entity | Description |
|--------|-------------|
| **Sync Now** | Trigger immediate sync |
| **Clear Download History** | Reset history (allows re-downloading all) |
| **Clear Download Queue** | Remove pending downloads |
| **Clear Local Files** | Delete all local downloads |
| **Fix File Permissions** | Set open permissions on downloaded files |

## 🔌 Services

| Service | Description |
|---------|-------------|
| `tidal_downloader.sync_now` | Trigger immediate sync |
| `tidal_downloader.force_download` | Download specific album by ID |
| `tidal_downloader.clear_history` | Reset download history |
| `tidal_downloader.clear_queue` | Clear pending downloads |
| `tidal_downloader.clear_local_files` | Delete local files |
| `tidal_downloader.fix_permissions` | Fix file permissions |

## 🛡️ Reliability & Recovery

The integration is designed to handle interruptions gracefully and ensure your NAS stays in sync with your Tidal collection.

### Startup Cleanup

On Home Assistant restart, the integration automatically:
- Clears any incomplete downloads from the local staging folder
- Removes any incomplete uploads from the SMB `.staging` folder
- Albums that weren't fully synced will automatically re-download on the next sync cycle

### SMB Staging Folder

To prevent partial albums appearing on your NAS, uploads use a staging approach:
1. Files are first uploaded to a `.staging` folder on the NAS
2. Only when the upload is 100% complete, the album is moved to its final location
3. If interrupted, the staging folder is cleaned up on next startup

### NAS Unavailable Handling

If the NAS is unavailable during upload:
- Local files are kept intact
- The album is **not** marked as downloaded (doesn't count against rate limit)
- On the next sync cycle (default: 5 minutes), the upload is automatically retried
- Retries continue each sync cycle until the NAS becomes available

| Scenario | Behavior |
|----------|----------|
| HA restart mid-download | Local files cleared, album re-downloads |
| HA restart mid-upload | Staging folder cleared, album re-downloads |
| Tidal fails mid-download | Partial files cleaned up, retry on next sync |
| NAS offline during upload | Local files kept, retry upload on next sync |
| NAS stays offline | Continues retrying upload each sync cycle |

## 🎧 Audio Quality Notes

| Setting | Quality | Requirements |
|---------|---------|--------------|
| Low | 96 kbps AAC | Any Tidal subscription |
| High | 320 kbps AAC | Any Tidal subscription |
| Lossless | 16-bit/44.1kHz FLAC | Tidal HiFi or HiFi Plus |
| HiRes Lossless | 24-bit/192kHz FLAC | Tidal HiFi Plus |

**Note:** Actual quality depends on what's available for each album. Not all albums have HiRes versions.

## 🔧 Troubleshooting

### Files downloading as M4A instead of FLAC
- Ensure FFmpeg is installed and working (check the FFmpeg Status sensor)
- Verify "Extract FLAC" is enabled in settings

### Downloads stuck at 320kbps
- Check your Tidal subscription tier supports your selected quality
- Verify the Audio Quality setting in the integration options
- Some albums may not have lossless/HiRes versions available

### SMB upload not working
- Verify server IP/hostname is correct
- Check credentials are valid
- Ensure the share name exists and is accessible
- Check Home Assistant logs for detailed error messages
- Look for files in the `.staging` folder on your NAS (indicates upload started but didn't complete)

### Albums stuck in local folder
- If SMB is enabled and albums remain in the local folder, the NAS upload likely failed
- Check NAS connectivity and credentials
- The integration will automatically retry uploads on each sync cycle
- Check logs for "SMB upload FAILED" messages

### Downloads failing / Tidal connection issues
- If Tidal is unavailable or a download fails, partial files are automatically cleaned up
- The album will be retried on the next sync cycle
- Check logs for "Failed to download" messages with specific error details
- Verify your Tidal session is still valid (may need to re-authenticate)

### Rate limit reached
- The integration respects configurable rate limits to avoid API issues
- Wait for the rate limit period to reset, or adjust settings

## 📦 Dependencies

- [tidalapi](https://github.com/tamland/python-tidal) (>=0.8.8) - Tidal API access
- [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng) (>=0.31.4) - Download engine
- [smbprotocol](https://github.com/jborean93/smbprotocol) (>=1.10.0) - SMB/NAS support

## ⚠️ Disclaimer

**This project is not affiliated with, endorsed by, or connected to Tidal or its parent companies in any way.** This is an independent, unofficial integration created for personal use.

### Legal Notice

- This software is provided for **personal, non-commercial use only**
- Users are solely responsible for ensuring their use complies with Tidal's [Terms of Service](https://tidal.com/terms)
- Downloaded content remains subject to Tidal's licensing agreements and copyright protections
- This tool is intended for users with valid, paid Tidal subscriptions to access content they are entitled to
- The authors do not condone or support piracy or unauthorized distribution of copyrighted material
- By using this software, you acknowledge that you have read and agree to Tidal's Terms of Service

### No Warranty

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### DMCA / Takedown

If you are a rights holder and believe this project infringes on your intellectual property, please open an issue to discuss.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgements

- [tidalapi](https://github.com/tamland/python-tidal) - Python API for Tidal
- [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng) - Tidal download engine

## ☕ Support

If you find this project useful and want to support its development, consider buying me a coffee!

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/w3dave)
