"""Data update coordinator for Alexa Shopping List integration."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from .shopping_list_sync import ShoppingListSync
from .cdp_manager import CDPManager, CDPConnectionError

_LOGGER = logging.getLogger(__name__)


class AlexaShoppingListCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage Alexa shopping list updates.

    This coordinator handles periodic synchronization between Home Assistant
    and Alexa shopping lists using the DataUpdateCoordinator pattern.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        cdp_manager: CDPManager,
        sync_manager: ShoppingListSync,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            cdp_manager: CDP manager for browser connection
            sync_manager: Shopping list sync logic manager
            update_interval: How often to sync
        """
        super().__init__(
            hass,
            _LOGGER,
            name="Alexa Shopping List",
            update_interval=update_interval,
        )

        self.cdp = cdp_manager
        self.sync = sync_manager

        # Register cleanup on HA shutdown
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_shutdown)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Alexa and sync with Home Assistant.

        This is called automatically by the coordinator on the update_interval.

        Returns:
            Dict containing sync results and metadata

        Raises:
            UpdateFailed: If sync fails
        """
        try:
            _LOGGER.debug("Running scheduled sync")

            # Perform sync
            result = await self.sync.sync(force=False)

            if not result["success"]:
                error_msg = result.get("error", "Unknown error")

                # Don't raise UpdateFailed for concurrent sync attempts
                if "already in progress" in error_msg.lower():
                    _LOGGER.debug("Sync skipped: %s", error_msg)
                    return self.data or {}

                raise UpdateFailed(f"Sync failed: {error_msg}")

            # Fire event if list changed
            if result["changed"]:
                _LOGGER.info("Shopping list changed during sync")
                self.hass.bus.async_fire("alexa_shopping_list_changed", result)

            return {
                "last_sync": datetime.now(timezone.utc),
                "sync_result": result,
                "connected": True,
            }

        except CDPConnectionError as err:
            _LOGGER.error("CDP connection error: %s", err)
            await self._create_connection_notification()
            raise UpdateFailed(f"CDP connection failed: {err}") from err

        except Exception as err:
            _LOGGER.error("Unexpected error during sync: %s", err, exc_info=True)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_request_refresh_now(self) -> None:
        """Request an immediate refresh with force=True.

        This is useful for manual sync service calls.
        """
        try:
            _LOGGER.info("Manual sync requested")
            result = await self.sync.sync(force=True)

            if result["success"]:
                # Fire event if list changed
                if result["changed"]:
                    self.hass.bus.async_fire("alexa_shopping_list_changed", result)

                # Update coordinator data with current timestamp
                self.async_set_updated_data({
                    "last_sync": datetime.now(timezone.utc),
                    "sync_result": result,
                    "connected": True,
                })

                _LOGGER.info("Manual sync completed successfully")
            else:
                error = result.get("error", "Unknown error")
                _LOGGER.error("Manual sync failed: %s", error)
                raise UpdateFailed(f"Sync failed: {error}")

        except CDPConnectionError as err:
            _LOGGER.error("Manual sync failed - CDP connection error: %s", err)
            await self._create_connection_notification()
            raise UpdateFailed(f"CDP connection failed: {err}") from err

        except Exception as err:
            _LOGGER.error("Manual sync failed: %s", err, exc_info=True)
            raise UpdateFailed(f"Manual sync failed: {err}") from err

    async def _create_connection_notification(self) -> None:
        """Create a persistent notification about connection issues."""
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Alexa Shopping List - Connection Issue",
                    "message": (
                        "Cannot connect to Chromium browser via CDP.\n\n"
                        "Please ensure:\n"
                        "1. Chromium is running with --remote-debugging-port=9222\n"
                        "2. The browser is on the Amazon list page\n"
                        "3. The CDP endpoint is correctly configured\n\n"
                        "Restart Chromium if needed, then reload the integration."
                    ),
                    "notification_id": "alexa_shopping_list_cdp_connection",
                },
            )
            _LOGGER.info("Created connection notification")
        except Exception as err:
            _LOGGER.error("Failed to create notification: %s", err)

    async def _async_shutdown(self, _event) -> None:
        """Clean up resources on Home Assistant shutdown."""
        _LOGGER.info("Shutting down Alexa Shopping List coordinator")

        try:
            # Stop polling
            self.async_set_update_interval(None)

            # Clean up CDP (disconnect, don't close browser)
            await self.cdp.cleanup()

            _LOGGER.info("Coordinator shutdown complete")

        except Exception as err:
            _LOGGER.error("Error during shutdown: %s", err)

    async def async_check_connection(self) -> bool:
        """Check if CDP connection is alive.

        Returns:
            True if connected, False otherwise
        """
        try:
            return await self.cdp.check_connection()
        except Exception as err:
            _LOGGER.error("Error checking connection: %s", err, exc_info=True)
            return False

    def get_sync_stats(self) -> dict[str, Any]:
        """Get current sync statistics.

        Returns:
            Dict with sync stats (counts, last sync time, etc.)
        """
        if not self.data:
            return {
                "last_sync": None,
                "connected": False,
                "alexa_count": 0,
                "ha_count": 0,
            }

        sync_result = self.data.get("sync_result", {})

        return {
            "last_sync": self.last_update_success,
            "connected": self.data.get("connected", False),
            "alexa_count": sync_result.get("alexa_count", 0),
            "ha_count": sync_result.get("ha_count", 0),
            "last_added": sync_result.get("added", []),
            "last_removed": sync_result.get("removed", []),
        }
