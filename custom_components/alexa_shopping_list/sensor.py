"""Sensor platform for Alexa Shopping List integration."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import AlexaShoppingListCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Alexa Shopping List sensor from a config entry."""
    coordinator: AlexaShoppingListCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Add sensors
    async_add_entities([
        AlexaShoppingListSyncSensor(coordinator, entry),
    ])


class AlexaShoppingListSyncSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing last sync time for Alexa Shopping List."""

    def __init__(
        self,
        coordinator: AlexaShoppingListCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor.

        Args:
            coordinator: Data update coordinator
            entry: Config entry
        """
        super().__init__(coordinator)

        self._attr_name = "Alexa Shopping List Sync"
        self._attr_unique_id = f"{entry.entry_id}_sync"
        self._attr_icon = "mdi:sync"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

        # Device info for grouping in UI
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Alexa Shopping List",
            "manufacturer": "Amazon",
            "model": "Shopping List Sync",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor.

        Returns the timestamp of the last successful sync.
        """
        # Try to get timestamp from coordinator data first
        if self.coordinator.data and "last_sync" in self.coordinator.data:
            timestamp = self.coordinator.data["last_sync"]
            if timestamp and isinstance(timestamp, datetime):
                return timestamp

        # Fallback to coordinator's last_update_success
        timestamp = self.coordinator.last_update_success
        if timestamp and isinstance(timestamp, datetime):
            return timestamp

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes.

        Provides detailed sync statistics and status information.
        """
        if not self.coordinator.data:
            return {
                "connected": False,
                "alexa_items": 0,
                "ha_items": 0,
                "last_sync_status": "Unknown",
            }

        sync_result = self.coordinator.data.get("sync_result", {})

        attributes = {
            "connected": self.coordinator.data.get("connected", False),
            "alexa_items": sync_result.get("alexa_count", 0),
            "ha_items": sync_result.get("ha_count", 0),
            "last_sync_status": "Success" if sync_result.get("success") else "Failed",
        }

        # Include last operation details if available
        if sync_result.get("added"):
            attributes["last_added"] = sync_result["added"]

        if sync_result.get("removed"):
            attributes["last_removed"] = sync_result["removed"]

        if sync_result.get("error"):
            attributes["last_error"] = sync_result["error"]

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available.

        The sensor is available as long as the coordinator is running,
        even if the last sync failed.
        """
        return True  # Always show sensor, even if sync fails

    @property
    def icon(self) -> str:
        """Return the icon based on sync status."""
        if not self.coordinator.data:
            return "mdi:sync-off"

        sync_result = self.coordinator.data.get("sync_result", {})

        if not sync_result.get("success"):
            return "mdi:sync-alert"

        if not self.coordinator.data.get("connected"):
            return "mdi:sync-off"

        return "mdi:sync"
