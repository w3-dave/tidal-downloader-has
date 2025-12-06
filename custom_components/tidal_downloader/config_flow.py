"""Config flow for Tidal Downloader integration."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import voluptuous as vol
import tidalapi

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_TYPE,
    CONF_EXPIRY_TIME,
    CONF_DOWNLOAD_PATH,
    CONF_AUDIO_QUALITY,
    CONF_POLL_INTERVAL,
    CONF_FOLDER_TEMPLATE,
    CONF_FILE_TEMPLATE,
    CONF_EXTRACT_FLAC,
    CONF_DOWNLOAD_LYRICS,
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
    DEFAULT_POLL_INTERVAL,
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_DOWNLOAD_PATH,
    DEFAULT_RATE_LIMIT_ALBUMS,
    DEFAULT_RATE_LIMIT_HOURS,
    AUDIO_QUALITY_OPTIONS,
    AudioQuality,
)

_LOGGER = logging.getLogger(__name__)


class TidalDownloaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tidal Downloader."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._session: tidalapi.Session | None = None
        self._login_future: asyncio.Future | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step - start OAuth device code flow."""
        errors = {}

        if self._session is None:
            # Start OAuth device code flow
            self._session = tidalapi.Session()

            # Run OAuth login in executor (blocking call)
            login_data, self._login_future = await self.hass.async_add_executor_job(
                self._session.login_oauth
            )

            # Store login data for display
            self._verification_url = login_data.verification_uri_complete
            self._user_code = login_data.user_code
            self._expires_in = login_data.expires_in

        if user_input is not None:
            # User clicked submit - check if auth completed
            try:
                # Wait briefly for the future to complete
                await asyncio.wait_for(
                    self.hass.async_add_executor_job(
                        lambda: self._login_future.result(timeout=1)
                    ),
                    timeout=5,
                )
            except (asyncio.TimeoutError, Exception):
                pass

            # Check if login was successful
            if await self.hass.async_add_executor_job(self._session.check_login):
                # Proceed to options step
                return await self.async_step_options()
            else:
                errors["base"] = "auth_pending"

        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "url": self._verification_url,
                "code": self._user_code,
                "expires": str(self._expires_in // 60),
            },
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle options configuration after successful auth."""
        errors = {}

        if user_input is not None:
            # Validate download path
            download_path = user_input[CONF_DOWNLOAD_PATH]
            path_valid = await self.hass.async_add_executor_job(
                self._validate_path, download_path
            )
            if not path_valid:
                errors[CONF_DOWNLOAD_PATH] = "invalid_path"
            else:
                # Get user info for title
                user_email = "Unknown"
                try:
                    user_email = await self.hass.async_add_executor_job(
                        lambda: self._session.user.email
                    )
                except Exception:
                    pass

                # Create config entry with auth + options
                return self.async_create_entry(
                    title=f"Tidal ({user_email})",
                    data={
                        CONF_ACCESS_TOKEN: self._session.access_token,
                        CONF_REFRESH_TOKEN: self._session.refresh_token,
                        CONF_TOKEN_TYPE: self._session.token_type,
                        CONF_EXPIRY_TIME: self._session.expiry_time.isoformat()
                        if self._session.expiry_time
                        else None,
                    },
                    options={
                        CONF_DOWNLOAD_PATH: user_input[CONF_DOWNLOAD_PATH],
                        CONF_AUDIO_QUALITY: user_input[CONF_AUDIO_QUALITY],
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                        CONF_RATE_LIMIT_ALBUMS: user_input.get(
                            CONF_RATE_LIMIT_ALBUMS, DEFAULT_RATE_LIMIT_ALBUMS
                        ),
                        CONF_RATE_LIMIT_HOURS: user_input.get(
                            CONF_RATE_LIMIT_HOURS, DEFAULT_RATE_LIMIT_HOURS
                        ),
                        CONF_FOLDER_TEMPLATE: user_input.get(
                            CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
                        ),
                        CONF_FILE_TEMPLATE: user_input.get(
                            CONF_FILE_TEMPLATE, DEFAULT_FILE_TEMPLATE
                        ),
                        CONF_EXTRACT_FLAC: user_input.get(CONF_EXTRACT_FLAC, True),
                        CONF_DOWNLOAD_LYRICS: user_input.get(CONF_DOWNLOAD_LYRICS, True),
                        CONF_DOWNLOAD_COVER: user_input.get(CONF_DOWNLOAD_COVER, True),
                        # SMB/NAS settings
                        CONF_SMB_ENABLED: user_input.get(CONF_SMB_ENABLED, False),
                        CONF_SMB_SERVER: user_input.get(CONF_SMB_SERVER, ""),
                        CONF_SMB_SHARE: user_input.get(CONF_SMB_SHARE, ""),
                        CONF_SMB_USERNAME: user_input.get(CONF_SMB_USERNAME, ""),
                        CONF_SMB_PASSWORD: user_input.get(CONF_SMB_PASSWORD, ""),
                        CONF_SMB_PATH: user_input.get(CONF_SMB_PATH, ""),
                        CONF_SMB_DELETE_AFTER_UPLOAD: user_input.get(CONF_SMB_DELETE_AFTER_UPLOAD, False),
                    },
                )

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DOWNLOAD_PATH, default=DEFAULT_DOWNLOAD_PATH
                ): cv.string,
                vol.Required(
                    CONF_AUDIO_QUALITY, default=AudioQuality.LOSSLESS.value
                ): vol.In(AUDIO_QUALITY_OPTIONS),
                vol.Required(
                    CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                vol.Required(
                    CONF_RATE_LIMIT_ALBUMS, default=DEFAULT_RATE_LIMIT_ALBUMS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Required(
                    CONF_RATE_LIMIT_HOURS, default=DEFAULT_RATE_LIMIT_HOURS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Optional(
                    CONF_FOLDER_TEMPLATE, default=DEFAULT_FOLDER_TEMPLATE
                ): cv.string,
                vol.Optional(
                    CONF_FILE_TEMPLATE, default=DEFAULT_FILE_TEMPLATE
                ): cv.string,
                vol.Optional(CONF_EXTRACT_FLAC, default=True): cv.boolean,
                vol.Optional(CONF_DOWNLOAD_LYRICS, default=True): cv.boolean,
                vol.Optional(CONF_DOWNLOAD_COVER, default=True): cv.boolean,
                # SMB/NAS settings
                vol.Optional(CONF_SMB_ENABLED, default=False): cv.boolean,
                vol.Optional(CONF_SMB_SERVER, default=""): cv.string,
                vol.Optional(CONF_SMB_SHARE, default=""): cv.string,
                vol.Optional(CONF_SMB_USERNAME, default=""): cv.string,
                vol.Optional(CONF_SMB_PASSWORD, default=""): cv.string,
                vol.Optional(CONF_SMB_PATH, default=""): cv.string,
                vol.Optional(CONF_SMB_DELETE_AFTER_UPLOAD, default=False): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="options",
            data_schema=options_schema,
            errors=errors,
        )

    def _validate_path(self, path: str) -> bool:
        """Validate that the download path exists or can be created."""
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            return os.path.isdir(path) and os.access(path, os.W_OK)
        except Exception:
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return TidalDownloaderOptionsFlowHandler()


class TidalDownloaderOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Tidal Downloader."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        errors = {}

        if user_input is not None:
            # Validate path
            path_valid = await self.hass.async_add_executor_job(
                self._validate_path, user_input[CONF_DOWNLOAD_PATH]
            )
            if not path_valid:
                errors[CONF_DOWNLOAD_PATH] = "invalid_path"
            else:
                return self.async_create_entry(title="", data=user_input)

        current_options = self.config_entry.options

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DOWNLOAD_PATH,
                    default=current_options.get(CONF_DOWNLOAD_PATH, DEFAULT_DOWNLOAD_PATH),
                ): cv.string,
                vol.Required(
                    CONF_AUDIO_QUALITY,
                    default=current_options.get(
                        CONF_AUDIO_QUALITY, AudioQuality.LOSSLESS.value
                    ),
                ): vol.In(AUDIO_QUALITY_OPTIONS),
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=current_options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                vol.Required(
                    CONF_RATE_LIMIT_ALBUMS,
                    default=current_options.get(
                        CONF_RATE_LIMIT_ALBUMS, DEFAULT_RATE_LIMIT_ALBUMS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Required(
                    CONF_RATE_LIMIT_HOURS,
                    default=current_options.get(
                        CONF_RATE_LIMIT_HOURS, DEFAULT_RATE_LIMIT_HOURS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Optional(
                    CONF_FOLDER_TEMPLATE,
                    default=current_options.get(
                        CONF_FOLDER_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
                    ),
                ): cv.string,
                vol.Optional(
                    CONF_FILE_TEMPLATE,
                    default=current_options.get(CONF_FILE_TEMPLATE, DEFAULT_FILE_TEMPLATE),
                ): cv.string,
                vol.Optional(
                    CONF_EXTRACT_FLAC,
                    default=current_options.get(CONF_EXTRACT_FLAC, True),
                ): cv.boolean,
                vol.Optional(
                    CONF_DOWNLOAD_LYRICS,
                    default=current_options.get(CONF_DOWNLOAD_LYRICS, True),
                ): cv.boolean,
                vol.Optional(
                    CONF_DOWNLOAD_COVER,
                    default=current_options.get(CONF_DOWNLOAD_COVER, True),
                ): cv.boolean,
                # SMB/NAS settings
                vol.Optional(
                    CONF_SMB_ENABLED,
                    default=current_options.get(CONF_SMB_ENABLED, False),
                ): cv.boolean,
                vol.Optional(
                    CONF_SMB_SERVER,
                    default=current_options.get(CONF_SMB_SERVER, ""),
                ): cv.string,
                vol.Optional(
                    CONF_SMB_SHARE,
                    default=current_options.get(CONF_SMB_SHARE, ""),
                ): cv.string,
                vol.Optional(
                    CONF_SMB_USERNAME,
                    default=current_options.get(CONF_SMB_USERNAME, ""),
                ): cv.string,
                vol.Optional(
                    CONF_SMB_PASSWORD,
                    default=current_options.get(CONF_SMB_PASSWORD, ""),
                ): cv.string,
                vol.Optional(
                    CONF_SMB_PATH,
                    default=current_options.get(CONF_SMB_PATH, ""),
                ): cv.string,
                vol.Optional(
                    CONF_SMB_DELETE_AFTER_UPLOAD,
                    default=current_options.get(CONF_SMB_DELETE_AFTER_UPLOAD, False),
                ): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )

    def _validate_path(self, path: str) -> bool:
        """Validate download path."""
        try:
            return os.path.isdir(path) and os.access(path, os.W_OK)
        except Exception:
            return False
