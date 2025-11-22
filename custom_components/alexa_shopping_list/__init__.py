"""Alexa Shopping List integration for Home Assistant."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .cdp_manager import CDPManager, CDPConnectionError
from .shopping_list_sync import ShoppingListSync
from .coordinator import AlexaShoppingListCoordinator
from .config_flow import CONF_AMAZON_URL, CONF_SYNC_MINS, CONF_CDP_ENDPOINT

_LOGGER = logging.getLogger(__name__)

DOMAIN = "alexa_shopping_list"
PLATFORMS = [Platform.SENSOR]

# Services
SERVICE_SYNC = "sync_alexa_shopping_list"

# Legacy config keys (for backwards compatibility)
CONF_IP = "server_ip"
CONF_PORT = "server_port"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alexa Shopping List from a config entry."""
    _LOGGER.info("Setting up Alexa Shopping List integration")

    # Initialize storage
    hass.data.setdefault(DOMAIN, {})

    # Get configuration
    amazon_url = entry.data.get(CONF_AMAZON_URL)
    sync_mins = entry.data.get(CONF_SYNC_MINS, 60)
    cdp_endpoint = entry.data.get(CONF_CDP_ENDPOINT, "http://localhost:9222")
    update_interval = timedelta(minutes=sync_mins)

    # Validate required configuration
    if not amazon_url:
        _LOGGER.error("Amazon URL not found in configuration. Please reconfigure the integration.")
        raise ConfigEntryNotReady("Amazon URL not configured. Please remove and re-add the integration.")

    try:
        # Initialize CDP manager
        cdp_manager = CDPManager(hass, amazon_url, cdp_endpoint)

        # Connect to browser via CDP
        _LOGGER.info("Initializing CDP connection...")
        await cdp_manager.initialize()
        _LOGGER.info("CDP connection initialized successfully")

        # Initialize sync manager
        sync_manager = ShoppingListSync(hass, cdp_manager)

        # Initialize coordinator
        coordinator = AlexaShoppingListCoordinator(
            hass,
            cdp_manager,
            sync_manager,
            update_interval,
        )

        # Perform first refresh
        await coordinator.async_config_entry_first_refresh()

        # Store coordinator and managers
        hass.data[DOMAIN][entry.entry_id] = {
            "coordinator": coordinator,
            "cdp": cdp_manager,
            "sync": sync_manager,
        }

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register services
        async def handle_sync_service(call: ServiceCall) -> None:
            """Handle the sync service call."""
            _LOGGER.info("Manual sync service called")

            try:
                await coordinator.async_request_refresh_now()
                _LOGGER.info("Manual sync completed successfully")

            except Exception as err:
                _LOGGER.error("Manual sync failed: %s", err, exc_info=True)

        # Register service (only once, not per entry)
        if not hass.services.has_service(DOMAIN, SERVICE_SYNC):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SYNC,
                handle_sync_service,
            )

        _LOGGER.info("Alexa Shopping List integration setup complete")
        return True

    except CDPConnectionError as err:
        _LOGGER.error("CDP connection failed: %s", err)
        raise ConfigEntryNotReady(f"CDP connection failed: {err}") from err

    except ConfigEntryNotReady:
        raise

    except Exception as err:
        _LOGGER.error("Failed to set up Alexa Shopping List: %s", err, exc_info=True)
        raise ConfigEntryNotReady(f"Setup failed: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Alexa Shopping List integration")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up resources
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)

        # Clean up CDP connection
        try:
            cdp_manager: CDPManager = entry_data["cdp"]
            await cdp_manager.cleanup()
        except Exception as err:
            _LOGGER.warning("Error cleaning up CDP: %s", err)

        # Unregister service if this was the last entry
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SYNC)
            _LOGGER.debug("Unregistered services")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("Reloading Alexa Shopping List integration")
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
