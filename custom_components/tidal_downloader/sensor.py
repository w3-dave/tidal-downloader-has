"""Sensor platform for Tidal Downloader."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TidalDownloaderCoordinator
from .download_manager import DownloadManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tidal Downloader sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    download_manager = hass.data[DOMAIN][entry.entry_id]["download_manager"]

    sensors = [
        TidalSyncStatusSensor(coordinator, entry),
        TidalQueueCountSensor(coordinator, download_manager, entry),
        TidalDownloadedCountSensor(coordinator, entry),
        TidalLastSyncSensor(coordinator, entry),
        TidalCurrentDownloadSensor(coordinator, download_manager, entry),
        TidalRateLimitSensor(coordinator, download_manager, entry),
        TidalFFmpegStatusSensor(coordinator, download_manager, entry),
    ]

    async_add_entities(sensors)


class TidalBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Tidal sensors."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Tidal Downloader",
            "manufacturer": "Tidal",
            "model": "Album Downloader",
        }


class TidalSyncStatusSensor(TidalBaseSensor):
    """Sensor for sync status."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "sync_status")
        self._attr_name = "Sync Status"
        self._attr_icon = "mdi:sync"

    @property
    def native_value(self) -> str:
        """Return the sync status."""
        return self.coordinator.sync_status


class TidalQueueCountSensor(TidalBaseSensor):
    """Sensor for download queue count."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "queue_count")
        self._download_manager = download_manager
        self._attr_name = "Download Queue"
        self._attr_icon = "mdi:playlist-music"
        self._attr_native_unit_of_measurement = "albums"

    @property
    def native_value(self) -> int:
        """Return the queue count."""
        return self._download_manager.queue_size

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        # Limit queue items to prevent exceeding HA's 16KB attribute limit
        queue_status = self._download_manager.get_queue_status()
        max_items = 10
        return {
            "queue_items": queue_status[:max_items],
            "queue_items_truncated": len(queue_status) > max_items,
            "total_in_queue": len(queue_status),
            "is_downloading": self._download_manager.is_downloading,
        }


class TidalDownloadedCountSensor(TidalBaseSensor):
    """Sensor for total downloaded albums."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "downloaded_count")
        self._attr_name = "Downloaded Albums"
        self._attr_icon = "mdi:download-circle"
        self._attr_native_unit_of_measurement = "albums"

    @property
    def native_value(self) -> int:
        """Return downloaded count."""
        return self.coordinator.downloaded_count


class TidalLastSyncSensor(TidalBaseSensor):
    """Sensor for last sync time."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "last_sync")
        self._attr_name = "Last Sync"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return last sync time."""
        return self.coordinator.last_sync


class TidalCurrentDownloadSensor(TidalBaseSensor):
    """Sensor for currently downloading album."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "current_download")
        self._download_manager = download_manager
        self._attr_name = "Current Download"
        self._attr_icon = "mdi:download"

    @property
    def native_value(self) -> str:
        """Return currently downloading album."""
        return self._download_manager.current_download or "None"


class TidalRateLimitSensor(TidalBaseSensor):
    """Sensor for rate limit status."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "rate_limit")
        self._download_manager = download_manager
        self._attr_name = "Rate Limit Remaining"
        self._attr_icon = "mdi:speedometer"
        self._attr_native_unit_of_measurement = "albums"

    @property
    def native_value(self) -> int:
        """Return remaining downloads in current period."""
        return self._download_manager.rate_limit_remaining

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        reset_time = self._download_manager.rate_limit_reset_time
        return {
            "is_rate_limited": self._download_manager.is_rate_limited,
            "reset_time": reset_time.isoformat() if reset_time else None,
        }


class TidalFFmpegStatusSensor(TidalBaseSensor):
    """Sensor for FFmpeg availability status."""

    def __init__(
        self,
        coordinator: TidalDownloaderCoordinator,
        download_manager: DownloadManager,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "ffmpeg_status")
        self._download_manager = download_manager
        self._attr_name = "FFmpeg Status"
        self._attr_icon = "mdi:video-check"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        """Return FFmpeg status."""
        works, _ = self._download_manager.ffmpeg_test_result
        if works:
            return "Working"
        elif self._download_manager.ffmpeg_available:
            return "Found but not working"
        return "Not Found"

    @property
    def icon(self) -> str:
        """Return icon based on status."""
        works, _ = self._download_manager.ffmpeg_test_result
        if works:
            return "mdi:check-circle"
        return "mdi:alert-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        works, test_output = self._download_manager.ffmpeg_test_result
        return {
            "ffmpeg_path": self._download_manager.ffmpeg_path,
            "ffmpeg_works": works,
            "ffmpeg_version": test_output if works else None,
            "ffmpeg_error": None if works else test_output,
            "flac_extraction_enabled": works,
        }
