"""Shopping list synchronization logic between Home Assistant and Alexa."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .cdp_manager import CDPManager, CDPConnectionError

_LOGGER = logging.getLogger(__name__)


class SyncError(HomeAssistantError):
    """Base exception for synchronization errors."""


class ShoppingListSync:
    """Manages synchronization between Home Assistant and Alexa shopping lists.

    This class implements bidirectional sync logic:
    - Items completed in HA are removed from Alexa
    - Items in HA (not completed) are added to Alexa
    - Items in Alexa are reflected back to HA
    """

    def __init__(
        self,
        hass: HomeAssistant,
        cdp_manager: CDPManager,
    ) -> None:
        """Initialize the sync manager.

        Args:
            hass: Home Assistant instance
            cdp_manager: CDP manager for browser operations
        """
        self.hass = hass
        self.cdp = cdp_manager
        self._is_syncing = False
        self._sync_lock = asyncio.Lock()

        # Path to HA shopping list file
        self._ha_list_path = Path(hass.config.config_dir) / ".shopping_list.json"

    @property
    def is_syncing(self) -> bool:
        """Return whether a sync is currently in progress."""
        return self._is_syncing

    async def _read_ha_shopping_list(self) -> list[dict[str, Any]]:
        """Read the Home Assistant shopping list from disk.

        Returns:
            List of shopping list items (dicts with 'name', 'complete', etc.)
        """
        if not self._ha_list_path.exists():
            _LOGGER.warning("HA shopping list file not found at %s", self._ha_list_path)
            return []

        try:

            def _read():
                with open(self._ha_list_path, 'r', encoding='utf-8') as file:
                    return json.load(file)

            items = await self.hass.async_add_executor_job(_read)
            return items if items else []

        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse HA shopping list: %s", err)
            return []
        except Exception as err:
            _LOGGER.error("Error reading HA shopping list: %s", err, exc_info=True)
            return []

    async def _write_ha_shopping_list(self, items: list[str]) -> bool:
        """Write items to the Home Assistant shopping list.

        Args:
            items: List of item names to write

        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert item names to HA shopping list format
            ha_items = []
            for item_name in items:
                ha_items.append({
                    "id": item_name.replace(" ", "_").lower(),
                    "name": item_name,
                    "complete": False
                })

            def _write():
                with open(self._ha_list_path, 'w', encoding='utf-8') as file:
                    json.dump(ha_items, file, indent=4)

            await self.hass.async_add_executor_job(_write)

            _LOGGER.debug("Wrote %d items to HA shopping list", len(ha_items))
            return True

        except Exception as err:
            _LOGGER.error("Error writing HA shopping list: %s", err, exc_info=True)
            return False

    def _calculate_list_hash(self, items: list[dict[str, Any]]) -> str:
        """Calculate MD5 hash of shopping list for change detection.

        Args:
            items: List of shopping list items

        Returns:
            MD5 hash as hex string
        """
        serialized = json.dumps(items, sort_keys=True)
        return hashlib.md5(serialized.encode('utf-8')).hexdigest()

    async def sync(self, force: bool = False) -> dict[str, Any]:
        """Synchronize Home Assistant and Alexa shopping lists.

        Sync logic:
        1. Read HA shopping list
        2. Get Alexa shopping list
        3. For items in HA:
           - If complete: remove from Alexa
           - If not in Alexa: add to Alexa
        4. Update HA list with current Alexa state
        5. Reload HA shopping list component

        Args:
            force: If True, sync even if already syncing

        Returns:
            Dict with sync results:
            {
                "success": bool,
                "changed": bool,
                "error": str | None,
                "added": list[str],
                "removed": list[str],
                "alexa_count": int,
                "ha_count": int
            }

        Raises:
            CDPConnectionError: If CDP connection fails
            SyncError: On other sync errors
        """
        # Prevent concurrent syncs
        if not force and self._is_syncing:
            _LOGGER.debug("Sync already in progress, skipping")
            return {
                "success": False,
                "changed": False,
                "error": "Sync already in progress",
                "added": [],
                "removed": [],
                "alexa_count": 0,
                "ha_count": 0,
            }

        async with self._sync_lock:
            self._is_syncing = True

            try:
                _LOGGER.info("Starting shopping list sync")

                # Check if HA shopping list exists
                if not self._ha_list_path.exists():
                    _LOGGER.error("HA shopping list not found - is shopping_list component enabled?")
                    raise SyncError("Home Assistant shopping list not configured")

                # Read current HA list
                ha_list = await self._read_ha_shopping_list()
                original_hash = self._calculate_list_hash(ha_list)
                _LOGGER.debug("HA list has %d items (hash: %s)", len(ha_list), original_hash[:8])

                # Get current Alexa list
                _LOGGER.debug("Fetching Alexa shopping list")
                alexa_items = await self.cdp.get_shopping_list_items()
                _LOGGER.debug("Alexa list has %d items", len(alexa_items))

                # Create dict for easy lookup by name
                alexa_dict = {item["name"]: item for item in alexa_items}
                alexa_names = set(alexa_dict.keys())

                # Create set of all HA item names (both completed and not)
                ha_all_items = {item.get("name", "") for item in ha_list}
                ha_active_items = {item.get("name", "") for item in ha_list if not item.get("complete", False)}

                # Determine what needs to be synced
                to_add = []
                to_remove = []  # Will store (name, id) tuples

                # Check HA items
                for ha_item in ha_list:
                    item_name = ha_item.get("name", "")
                    is_complete = ha_item.get("complete", False)

                    if is_complete and item_name in alexa_names:
                        # Item completed in HA - remove from Alexa
                        item_id = alexa_dict[item_name]["id"]
                        to_remove.append((item_name, item_id))
                        _LOGGER.debug("Item '%s' completed in HA - will remove from Alexa", item_name)
                    elif not is_complete and item_name not in alexa_names and force:
                        # Item in HA but not in Alexa - only add during manual sync
                        # This prevents re-adding items that were intentionally removed from Alexa
                        _LOGGER.debug("Item '%s' in HA but not in Alexa - will add (manual sync)", item_name)
                        to_add.append(item_name)
                    elif not is_complete and item_name not in alexa_names and not force:
                        _LOGGER.debug("Item '%s' in HA but not in Alexa - skipping add (auto sync)", item_name)

                # Note: We do NOT remove items from Alexa just because they were deleted from HA
                # This prevents issues where:
                # - New items added to Alexa haven't synced to HA yet
                # - Accidental deletions in HA would remove from Alexa
                # Instead, users should mark items as "complete" in HA to remove from Alexa

                # Execute sync operations
                _LOGGER.info("Sync plan: adding %d, removing %d items (force=%s)", len(to_add), len(to_remove), force)

                # Add items to Alexa
                for item_name in to_add:
                    try:
                        _LOGGER.debug("Adding to Alexa: %s", item_name)
                        await self.cdp.add_item(item_name)
                    except Exception as err:
                        _LOGGER.error("Failed to add item '%s': %s", item_name, err)
                        # Continue with other items

                # Remove items from Alexa
                for item_name, item_id in to_remove:
                    try:
                        _LOGGER.debug("Removing from Alexa: %s (ID: %s)", item_name, item_id)
                        await self.cdp.remove_item(item_id)
                    except Exception as err:
                        _LOGGER.error("Failed to remove item '%s': %s", item_name, err)
                        # Continue with other items

                # Get updated Alexa list
                refreshed_alexa_items = await self.cdp.get_shopping_list_items()
                _LOGGER.debug("Refreshed Alexa list has %d items", len(refreshed_alexa_items))

                # Extract just the names for HA
                refreshed_alexa_names = [item["name"] for item in refreshed_alexa_items if not item.get("completed", False)]

                # Update HA list to match Alexa
                await self._write_ha_shopping_list(refreshed_alexa_names)

                # Reload HA shopping list component to reflect changes
                try:
                    if "shopping_list" in self.hass.data:
                        await self.hass.data["shopping_list"].async_load()
                        _LOGGER.debug("Reloaded HA shopping list component")
                except Exception as err:
                    _LOGGER.warning("Could not reload shopping list component: %s", err)

                # Calculate new hash to detect changes
                updated_ha_list = await self._read_ha_shopping_list()
                new_hash = self._calculate_list_hash(updated_ha_list)
                changed = original_hash != new_hash

                _LOGGER.info(
                    "Sync completed: changed=%s, added=%d, removed=%d",
                    changed,
                    len(to_add),
                    len(to_remove)
                )

                return {
                    "success": True,
                    "changed": changed,
                    "error": None,
                    "added": to_add,
                    "removed": [name for name, _ in to_remove],  # Just names for reporting
                    "alexa_count": len(refreshed_alexa_items),
                    "ha_count": len(updated_ha_list),
                }

            except CDPConnectionError as err:
                _LOGGER.error("CDP connection error: %s", err)
                # Re-raise to be handled by coordinator
                raise

            except Exception as err:
                _LOGGER.error("Sync failed: %s", err, exc_info=True)
                return {
                    "success": False,
                    "changed": False,
                    "error": str(err),
                    "added": [],
                    "removed": [],
                    "alexa_count": 0,
                    "ha_count": 0,
                }

            finally:
                self._is_syncing = False

    async def get_alexa_items(self) -> list[str]:
        """Get current items from Alexa shopping list.

        Returns:
            List of item names

        Raises:
            CDPConnectionError: If CDP connection fails
            SyncError: On other errors
        """
        try:
            items = await self.cdp.get_shopping_list_items()
            # Return just names of non-completed items
            return [item["name"] for item in items if not item.get("completed", False)]
        except CDPConnectionError:
            raise
        except Exception as err:
            raise SyncError(f"Failed to get Alexa items: {err}") from err

    async def get_ha_items(self) -> list[dict[str, Any]]:
        """Get current items from Home Assistant shopping list.

        Returns:
            List of item dicts with 'name', 'complete', etc.
        """
        return await self._read_ha_shopping_list()

    async def add_to_alexa(self, item_name: str) -> bool:
        """Add a single item to Alexa shopping list.

        Args:
            item_name: Name of item to add

        Returns:
            True if successful

        Raises:
            CDPConnectionError: If CDP connection fails
        """
        try:
            await self.cdp.add_item(item_name)
            _LOGGER.info("Added item to Alexa: %s", item_name)
            return True
        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to add item '%s': %s", item_name, err, exc_info=True)
            return False

    async def remove_from_alexa(self, item_name: str) -> bool:
        """Remove a single item from Alexa shopping list.

        Args:
            item_name: Name of item to remove

        Returns:
            True if successful

        Raises:
            CDPConnectionError: If CDP connection fails
        """
        try:
            # Need to find the item ID first
            items = await self.cdp.get_shopping_list_items()
            for item in items:
                if item["name"] == item_name:
                    await self.cdp.remove_item(item["id"])
                    _LOGGER.info("Removed item from Alexa: %s", item_name)
                    return True

            _LOGGER.warning("Item not found in Alexa list: %s", item_name)
            return False
        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to remove item '%s': %s", item_name, err, exc_info=True)
            return False
