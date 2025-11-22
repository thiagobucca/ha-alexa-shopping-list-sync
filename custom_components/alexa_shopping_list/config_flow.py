"""Config flow for Alexa Shopping List integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import selector

from .cdp_manager import CDPManager, CDPConnectionError

_LOGGER = logging.getLogger(__name__)

# Domain must be defined here to avoid circular import
DOMAIN = "alexa_shopping_list"

# Configuration keys
CONF_AMAZON_URL = "amazon_url"
CONF_CDP_ENDPOINT = "cdp_endpoint"
CONF_SYNC_MINS = "sync_mins"

# Default values
DEFAULT_SYNC_MINS = 60
DEFAULT_CDP_ENDPOINT = "http://localhost:9222"


class AlexaShoppingListConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Alexa Shopping List."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize config flow."""
        self._config_data: dict[str, Any] = {}
        self._cdp_manager: CDPManager | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step - CDP endpoint configuration."""
        # Skip domain selection, go directly to CDP
        return await self.async_step_cdp()

    async def async_step_cdp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle CDP endpoint configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cdp_endpoint = user_input.get(CONF_CDP_ENDPOINT, DEFAULT_CDP_ENDPOINT).strip()

            # If empty, use default
            if not cdp_endpoint:
                cdp_endpoint = DEFAULT_CDP_ENDPOINT

            # Basic URL validation
            if not cdp_endpoint.startswith(("http://", "https://")):
                errors["base"] = "invalid_cdp_endpoint"
            else:
                self._config_data[CONF_CDP_ENDPOINT] = cdp_endpoint
                return await self.async_step_test_connection()

        data_schema = vol.Schema({
            vol.Optional(
                CONF_CDP_ENDPOINT,
                default=self._config_data.get(CONF_CDP_ENDPOINT, DEFAULT_CDP_ENDPOINT)
            ): cv.string,
        })

        return self.async_show_form(
            step_id="cdp",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_test_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Test CDP connection to Chromium browser."""
        errors: dict[str, str] = {}

        # This step doesn't show a form initially, just tests connection
        if user_input is None:
            try:
                # Get CDP endpoint
                cdp_endpoint = self._config_data[CONF_CDP_ENDPOINT]

                # First, detect Amazon domain from browser
                _LOGGER.info("Detecting Amazon domain from browser at %s", cdp_endpoint)

                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{cdp_endpoint}/json", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status != 200:
                            raise Exception(f"CDP endpoint returned status {resp.status}")
                        pages = await resp.json()

                # Find Amazon page and extract domain
                amazon_url = None
                for page in pages:
                    if page.get("type") == "page":
                        url = page.get("url", "")
                        if "amazon." in url and "alexaquantum" in url:
                            # Extract domain from URL (e.g., "amazon.com.br" from "https://www.amazon.com.br/...")
                            import re
                            match = re.search(r'amazon\.([a-z.]+)', url)
                            if match:
                                amazon_url = f"amazon.{match.group(1)}"
                                _LOGGER.info("Detected Amazon domain: %s", amazon_url)
                                break

                if not amazon_url:
                    # Default to amazon.com if not found
                    amazon_url = "amazon.com"
                    _LOGGER.warning("Could not detect Amazon domain, using default: %s", amazon_url)

                self._config_data[CONF_AMAZON_URL] = amazon_url

                # Create CDP manager and test connection
                _LOGGER.info("Testing CDP connection to %s", cdp_endpoint)

                self._cdp_manager = CDPManager(
                    self.hass,
                    amazon_url,
                    cdp_endpoint
                )

                await self._cdp_manager.initialize()

                # Test reading the list
                items = await self._cdp_manager.get_shopping_list_items()
                _LOGGER.info("Successfully connected! Found %d items in list", len(items))

                # Cleanup (disconnect but don't close browser)
                await self._cdp_manager.cleanup()

                # Connection successful, proceed to sync settings
                return await self.async_step_sync_settings()

            except CDPConnectionError as err:
                _LOGGER.error("CDP connection failed: %s", err)
                errors["base"] = "cdp_connection_failed"
            except Exception as err:
                _LOGGER.error("Unexpected error during connection test: %s", err, exc_info=True)
                errors["base"] = "unknown"

        # If we got here, connection failed - show error and allow retry
        if errors:
            return self.async_show_form(
                step_id="test_connection",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders={
                    "cdp_endpoint": self._config_data.get(CONF_CDP_ENDPOINT, "http://localhost:9222"),
                    "instructions": (
                        "Ensure Chromium is running with CDP enabled:\n\n"
                        "chromium-browser --remote-debugging-port=9222 "
                        "--user-data-dir=/home/pi/.config/chromium-ha "
                        '"https://www.amazon.YOUR-DOMAIN/alexaquantum/sp/alexaShoppingList" &\n\n'
                        "Replace YOUR-DOMAIN with your Amazon domain (e.g., com.br, co.uk, com)"
                    )
                }
            )

        # This shouldn't happen, but just in case
        return await self.async_step_sync_settings()

    async def async_step_sync_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Configure sync interval."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sync_mins = user_input.get(CONF_SYNC_MINS, DEFAULT_SYNC_MINS)

            # Validate sync interval
            try:
                sync_mins = int(sync_mins)
                if sync_mins < 1:
                    errors["base"] = "invalid_sync_mins"
                elif sync_mins > 1440:  # Max 24 hours
                    errors["base"] = "sync_mins_too_high"
                else:
                    self._config_data[CONF_SYNC_MINS] = sync_mins

                    # Create entry with detected Amazon domain
                    amazon_domain = self._config_data.get(CONF_AMAZON_URL, "amazon.com")
                    return self.async_create_entry(
                        title=f"Alexa Shopping List ({amazon_domain})",
                        data=self._config_data,
                    )

            except ValueError:
                errors["base"] = "invalid_sync_mins"

        data_schema = vol.Schema({
            vol.Required(
                CONF_SYNC_MINS,
                default=self._config_data.get(CONF_SYNC_MINS, DEFAULT_SYNC_MINS)
            ): cv.positive_int,
        })

        return self.async_show_form(
            step_id="sync_settings",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AlexaShoppingListOptionsFlow:
        """Get the options flow for this handler."""
        return AlexaShoppingListOptionsFlow(config_entry)


class AlexaShoppingListOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Alexa Shopping List."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sync_mins = user_input.get(CONF_SYNC_MINS)
            cdp_endpoint = user_input.get(CONF_CDP_ENDPOINT, "").strip()

            try:
                sync_mins = int(sync_mins)
                if sync_mins < 1:
                    errors["base"] = "invalid_sync_mins"
                elif sync_mins > 1440:
                    errors["base"] = "sync_mins_too_high"

                # Validate CDP endpoint if provided
                if cdp_endpoint and not errors:
                    if not cdp_endpoint.startswith(("http://", "https://")):
                        errors["base"] = "invalid_cdp_endpoint"

                if not errors:
                    # Update config entry with both values
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={
                            **self.config_entry.data,
                            CONF_SYNC_MINS: sync_mins,
                            CONF_CDP_ENDPOINT: cdp_endpoint or DEFAULT_CDP_ENDPOINT,
                        }
                    )
                    return self.async_create_entry(title="", data={})

            except ValueError:
                errors["base"] = "invalid_sync_mins"

        current_sync_mins = self.config_entry.data.get(CONF_SYNC_MINS, DEFAULT_SYNC_MINS)
        current_cdp_endpoint = self.config_entry.data.get(CONF_CDP_ENDPOINT, DEFAULT_CDP_ENDPOINT)

        data_schema = vol.Schema({
            vol.Required(CONF_SYNC_MINS, default=current_sync_mins): cv.positive_int,
            vol.Optional(CONF_CDP_ENDPOINT, default=current_cdp_endpoint): cv.string,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )
