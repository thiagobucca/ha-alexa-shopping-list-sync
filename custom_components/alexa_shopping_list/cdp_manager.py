"""Chrome DevTools Protocol Manager for Alexa Shopping List Integration."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
import websockets

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# Default CDP endpoint
DEFAULT_CDP_ENDPOINT = "http://localhost:9222"

# Amazon URLs
AMAZON_LIST_PATH = "/alexaquantum/sp/alexaShoppingList"


class CDPConnectionError(HomeAssistantError):
    """Raised when CDP connection fails."""


class CDPManager:
    """Manages Chrome DevTools Protocol connection to existing Chromium browser."""

    def __init__(self, hass: HomeAssistant, amazon_url: str, cdp_endpoint: str = DEFAULT_CDP_ENDPOINT) -> None:
        """Initialize CDP manager.

        Args:
            hass: Home Assistant instance
            amazon_url: Amazon domain (e.g., 'amazon.com', 'amazon.co.uk')
            cdp_endpoint: CDP endpoint URL (default: http://localhost:9222)
        """
        self.hass = hass
        self.amazon_url = amazon_url.replace("https://", "").replace("http://", "").replace("www.", "")
        self.cdp_endpoint = cdp_endpoint

        self._ws_url: str | None = None
        self._websocket: websockets.WebSocketClientProtocol | None = None
        self._message_id = 0
        self._list_url = f"https://{self.amazon_url}{AMAZON_LIST_PATH}"

    async def initialize(self) -> None:
        """Connect to existing browser via CDP."""
        try:
            _LOGGER.info("Connecting to Chrome via CDP at %s", self.cdp_endpoint)

            # Get list of pages from CDP
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.cdp_endpoint}/json", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        raise CDPConnectionError(f"CDP endpoint returned status {resp.status}")

                    pages = await resp.json()

            _LOGGER.debug("Found %d pages in browser", len(pages) if pages else 0)

            if not pages:
                raise CDPConnectionError("No pages found in browser. Make sure Chromium is running with a tab open.")

            # Find page with Amazon list or use first page
            target_page = None
            for page in pages:
                if page.get("type") != "page":
                    continue

                url = page.get("url", "")
                if AMAZON_LIST_PATH in url:
                    target_page = page
                    _LOGGER.info("Found existing Amazon list page: %s", url)
                    break

            # If no Amazon page found, use first available page
            if not target_page:
                for page in pages:
                    if page.get("type") == "page":
                        target_page = page
                        _LOGGER.info("Using page: %s", page.get("url", "unknown"))
                        break

            if not target_page:
                raise CDPConnectionError("No suitable page found in browser")

            # Get WebSocket URL
            ws_url = target_page.get("webSocketDebuggerUrl")
            if not ws_url:
                _LOGGER.error("Target page has no WebSocket URL. Page info: %s", target_page)
                raise CDPConnectionError("No WebSocket URL in page info")

            self._ws_url = ws_url
            _LOGGER.info("CDP WebSocket URL: %s", self._ws_url)

            # Connect to WebSocket
            _LOGGER.debug("Connecting to WebSocket...")
            await self._connect_websocket()
            _LOGGER.debug("WebSocket connected successfully")

            # Navigate to list page if needed
            current_url = target_page.get("url", "")
            if AMAZON_LIST_PATH not in current_url:
                _LOGGER.info("Navigating to Amazon list page: %s", self._list_url)
                await self._navigate(self._list_url)
            else:
                _LOGGER.info("Already on Amazon list page: %s", current_url)

            _LOGGER.info("CDP connection established successfully")

        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to connect to CDP endpoint: %s", err, exc_info=True)
            raise CDPConnectionError(f"CDP endpoint unreachable: {err}") from err
        except Exception as err:
            _LOGGER.error("Unexpected error during CDP initialization: %s", err, exc_info=True)
            await self.cleanup()
            raise CDPConnectionError(f"CDP initialization failed: {err}") from err

    async def _connect_websocket(self) -> None:
        """Connect to CDP WebSocket."""
        if not self._ws_url:
            raise CDPConnectionError("No WebSocket URL available")

        try:
            self._websocket = await websockets.connect(
                self._ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )
            _LOGGER.debug("WebSocket connected")
        except Exception as err:
            raise CDPConnectionError(f"WebSocket connection failed: {err}") from err

    async def _send_cdp_command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a CDP command and wait for response.

        Args:
            method: CDP method name (e.g., "Runtime.evaluate")
            params: Method parameters

        Returns:
            Response result

        Raises:
            CDPConnectionError: If command fails
        """
        if not self._websocket:
            await self._connect_websocket()

        self._message_id += 1
        message = {
            "id": self._message_id,
            "method": method,
            "params": params or {}
        }

        try:
            # Send command
            await self._websocket.send(json.dumps(message))

            # Wait for response
            while True:
                response_str = await asyncio.wait_for(self._websocket.recv(), timeout=10.0)
                response = json.loads(response_str)

                # Check if this is our response
                if response.get("id") == self._message_id:
                    if "error" in response:
                        error = response["error"]
                        raise CDPConnectionError(f"CDP command failed: {error.get('message', error)}")

                    return response.get("result", {})

        except asyncio.TimeoutError as err:
            raise CDPConnectionError("CDP command timeout") from err
        except websockets.exceptions.WebSocketException as err:
            raise CDPConnectionError(f"WebSocket error: {err}") from err
        except Exception as err:
            raise CDPConnectionError(f"CDP command failed: {err}") from err

    async def _evaluate_js(self, expression: str) -> Any:
        """Evaluate JavaScript expression in browser.

        Args:
            expression: JavaScript code to evaluate

        Returns:
            Evaluation result
        """
        result = await self._send_cdp_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True
            }
        )

        if result.get("exceptionDetails"):
            error = result["exceptionDetails"]
            raise CDPConnectionError(f"JavaScript error: {error}")

        return result.get("result", {}).get("value")

    async def _navigate(self, url: str) -> None:
        """Navigate to URL.

        Args:
            url: URL to navigate to
        """
        await self._send_cdp_command("Page.navigate", {"url": url})
        # Wait a bit for page to load
        await asyncio.sleep(2)

    async def cleanup(self) -> None:
        """Disconnect from browser (does not close the browser)."""
        try:
            if self._websocket:
                try:
                    await self._websocket.close()
                except Exception:
                    pass  # Already closed
                self._websocket = None
                _LOGGER.info("Disconnected from browser")

            self._ws_url = None

        except Exception as err:
            _LOGGER.error("Error during cleanup: %s", err, exc_info=True)

    async def get_shopping_list_items(self) -> list[dict[str, Any]]:
        """Read shopping list items from the Amazon page.

        Returns:
            List of items with structure: [{"id": "...", "name": "...", "completed": bool}, ...]
        """
        try:
            # JavaScript to extract list items from Amazon virtual-list structure
            js_code = """
            (function() {
                const items = [];

                console.log('=== Reading Amazon Shopping List ===');

                // Find the virtual list container
                const virtualList = document.querySelector('.virtual-list');
                if (!virtualList) {
                    console.error('Virtual list container not found');
                    return items;
                }

                console.log('Found virtual list container');

                // Get all items - each item has class .inner
                const itemElements = virtualList.querySelectorAll('div.inner');
                console.log('Found', itemElements.length, 'items in list');

                itemElements.forEach((el, idx) => {
                    try {
                        // Get item name from .item-title
                        const titleElement = el.querySelector('.item-title') ||
                                           el.querySelector('p.sc-dAbbOL') ||
                                           el.querySelector('.item-name p');

                        if (!titleElement) {
                            console.warn('Item', idx, ': No title element found');
                            return;
                        }

                        const name = titleElement.textContent.trim();

                        // Get checkbox ID as item ID
                        const checkbox = el.querySelector('.checkBox input[type="checkbox"]');
                        const itemId = checkbox ? checkbox.id : 'item_' + idx;

                        // Check if item is completed (checkbox checked)
                        const isCompleted = checkbox ? checkbox.checked : false;

                        console.log('Item', idx, ':', {
                            id: itemId,
                            name: name,
                            completed: isCompleted
                        });

                        if (name && name.length > 0) {
                            items.push({
                                id: itemId,
                                name: name,
                                completed: isCompleted
                            });
                        }
                    } catch (err) {
                        console.error('Error processing item', idx, ':', err);
                    }
                });

                console.log('Successfully extracted', items.length, 'items');
                return items;
            })();
            """

            items = await self._evaluate_js(js_code)
            _LOGGER.info("Retrieved %d items from shopping list", len(items) if items else 0)
            if items:
                _LOGGER.debug("Items: %s", items)
            return items or []

        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to read shopping list: %s", err, exc_info=True)
            return []

    async def _debug_page_structure(self) -> None:
        """Debug helper to inspect page structure."""
        js_code = """
        (function() {
            const inputs = document.querySelectorAll('input');
            const buttons = document.querySelectorAll('button');
            const forms = document.querySelectorAll('form');

            const inputDetails = [];
            inputs.forEach((el, i) => {
                const details = {
                    index: i,
                    type: el.type,
                    name: el.name,
                    id: el.id,
                    placeholder: el.placeholder,
                    className: el.className,
                    ariaLabel: el.ariaLabel,
                    visible: el.offsetWidth > 0 && el.offsetHeight > 0
                };
                inputDetails.push(details);
                console.log(`Input ${i}:`, details);
            });

            const buttonDetails = [];
            buttons.forEach((el, i) => {
                const details = {
                    index: i,
                    type: el.type,
                    text: el.textContent.trim().substring(0, 50),
                    className: el.className,
                    ariaLabel: el.ariaLabel,
                    visible: el.offsetWidth > 0 && el.offsetHeight > 0
                };
                buttonDetails.push(details);
                console.log(`Button ${i}:`, details);
            });

            return {
                inputCount: inputs.length,
                buttonCount: buttons.length,
                formCount: forms.length,
                visibleInputs: inputDetails.filter(i => i.visible).length,
                visibleButtons: buttonDetails.filter(b => b.visible).length,
                firstVisibleInput: inputDetails.find(i => i.visible),
                addButtons: buttonDetails.filter(b =>
                    b.visible && (
                        b.text.toLowerCase().includes('add') ||
                        b.text.toLowerCase().includes('adicionar')
                    )
                )
            };
        })();
        """
        result = await self._evaluate_js(js_code)
        _LOGGER.info("Page structure debug: %s", result)

    async def add_item(self, item_name: str) -> bool:
        """Add an item to the shopping list.

        Args:
            item_name: Name of the item to add

        Returns:
            True if successful, False otherwise
        """
        try:
            # Debug page structure on first call
            if not hasattr(self, '_debug_done'):
                await self._debug_page_structure()
                self._debug_done = True
            # Escape quotes in item name
            escaped_name = item_name.replace("'", "\\'").replace('"', '\\"')

            js_code = f"""
            (async function() {{
                // Find input using specific selectors for Amazon shopping list page
                const input = document.querySelector('.input-box input[type="text"]') ||
                             document.querySelector('input.sc-dhKdcB') ||
                             document.querySelector('input.gsiayx') ||
                             document.querySelector('input[type="text"]') ||
                             document.querySelector('input[name="item-name"]') ||
                             document.querySelector('#item-name');

                if (!input) {{
                    console.error('Could not find input field');
                    console.error('Available inputs:', document.querySelectorAll('input').length);
                    return {{ success: false, error: 'Input field not found' }};
                }}

                console.log('Found input:', input.className, 'parent:', input.parentElement.className);

                // Focus and click the input first
                input.focus();
                input.click();

                // For React/modern frameworks, we need to use the native setter
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    'value'
                ).set;
                nativeInputValueSetter.call(input, '{escaped_name}');

                // Dispatch input event immediately after setting value (React expects this)
                input.dispatchEvent(new Event('input', {{ bubbles: true, cancelable: true }}));

                // Simulate pressing Tab to trigger onChange
                input.dispatchEvent(new KeyboardEvent('keydown', {{
                    bubbles: true,
                    cancelable: true,
                    key: 'Tab',
                    code: 'Tab',
                    keyCode: 9
                }}));

                input.dispatchEvent(new KeyboardEvent('keyup', {{
                    bubbles: true,
                    cancelable: true,
                    key: 'Tab',
                    code: 'Tab',
                    keyCode: 9
                }}));

                // Trigger blur/focus cycle (helps with onChange)
                input.blur();
                await new Promise(resolve => setTimeout(resolve, 50));
                input.focus();

                // Final change event
                input.dispatchEvent(new Event('change', {{ bubbles: true, cancelable: true }}));

                console.log('Input value set to:', input.value);

                // Find button using specific selectors for Amazon shopping list page
                const button = document.querySelector('.add-to-list button') ||
                              document.querySelector('button.sc-kpDqfm') ||
                              document.querySelector('.sc-kpDqfm.sc-jlZhew') ||
                              Array.from(document.querySelectorAll('button')).find(btn =>
                                  btn.textContent.trim().toLowerCase().includes('add to list') ||
                                  btn.textContent.trim().toLowerCase().includes('adicionar')
                              ) ||
                              document.querySelector('button[type="submit"]');

                if (!button) {{
                    console.error('Could not find add button');
                    console.error('Available buttons:', document.querySelectorAll('button').length);
                    return {{ success: false, error: 'Add button not found' }};
                }}

                console.log('Found button:', button.textContent.trim(), 'disabled:', button.disabled);

                // Wait for button to be enabled (important!)
                let attempts = 0;
                while (button.disabled && attempts < 20) {{
                    await new Promise(resolve => setTimeout(resolve, 100));
                    attempts++;
                }}

                if (button.disabled) {{
                    console.error('Button is still disabled after waiting');
                    return {{ success: false, error: 'Button remained disabled' }};
                }}

                console.log('Button enabled after', attempts * 100, 'ms');

                // Click the button
                button.focus();
                button.click();

                // Also dispatch mouse events for better compatibility
                button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true }}));
                button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true }}));
                button.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true }}));

                console.log('Button clicked');

                // Wait for item to be added to the list
                await new Promise(resolve => setTimeout(resolve, 1000));

                // Verify the input was cleared (indicates success)
                const inputCleared = input.value === '';
                console.log('Input cleared:', inputCleared, 'current value:', input.value);

                return {{ success: true, inputCleared: inputCleared, attempts: attempts }};
            }})();
            """

            result = await self._evaluate_js(js_code)

            if result and (result is True or (isinstance(result, dict) and result.get("success"))):
                _LOGGER.info("Added item to shopping list: %s", item_name)
                return True
            else:
                error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else "Unknown error"
                _LOGGER.warning("Could not add item '%s': %s", item_name, error_msg)
                return False

        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to add item '%s': %s", item_name, err, exc_info=True)
            return False

    async def remove_item(self, item_id: str) -> bool:
        """Remove an item from the shopping list.

        Args:
            item_id: ID of the item to remove (checkbox ID)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Escape item ID
            escaped_id = item_id.replace("'", "\\'").replace('"', '\\"')

            js_code = f"""
            (function() {{
                console.log('Attempting to remove item with ID:', '{escaped_id}');

                // Find checkbox with this ID
                const checkbox = document.getElementById('{escaped_id}');
                if (!checkbox) {{
                    console.error('Checkbox not found for ID:', '{escaped_id}');
                    return false;
                }}

                // Navigate up to the .inner container
                const innerContainer = checkbox.closest('div.inner');
                if (!innerContainer) {{
                    console.error('Could not find .inner container');
                    return false;
                }}

                // Find the Delete button
                const deleteButton = innerContainer.querySelector('.item-actions button[aria-label*="Delete"]') ||
                                   innerContainer.querySelector('.item-actions-2 button') ||
                                   Array.from(innerContainer.querySelectorAll('button')).find(btn =>
                                       btn.textContent.toLowerCase().includes('delete')
                                   );

                if (!deleteButton) {{
                    console.error('Delete button not found');
                    return false;
                }}

                console.log('Found delete button, clicking...');
                deleteButton.click();
                return true;
            }})();
            """

            success = await self._evaluate_js(js_code)

            if success:
                _LOGGER.info("Removed item from shopping list: %s", item_id)
            else:
                _LOGGER.warning("Could not find item to remove: %s", item_id)

            return bool(success)

        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to remove item '%s': %s", item_id, err, exc_info=True)
            return False

    async def complete_item(self, item_id: str) -> bool:
        """Mark an item as completed.

        Args:
            item_id: ID of the item to complete (checkbox ID)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Escape item ID
            escaped_id = item_id.replace("'", "\\'").replace('"', '\\"')

            js_code = f"""
            (function() {{
                console.log('Attempting to complete item with ID:', '{escaped_id}');

                // Find checkbox with this ID
                const checkbox = document.getElementById('{escaped_id}');
                if (!checkbox) {{
                    console.error('Checkbox not found for ID:', '{escaped_id}');
                    return false;
                }}

                if (checkbox.checked) {{
                    console.log('Item already completed');
                    return false;
                }}

                console.log('Clicking checkbox to mark as completed');
                checkbox.click();
                return true;
            }})();
            """

            success = await self._evaluate_js(js_code)

            if success:
                _LOGGER.info("Completed item: %s", item_id)
            else:
                _LOGGER.warning("Could not find item to complete: %s", item_id)

            return bool(success)

        except CDPConnectionError:
            raise
        except Exception as err:
            _LOGGER.error("Failed to complete item '%s': %s", item_id, err, exc_info=True)
            return False

    async def check_connection(self) -> bool:
        """Check if CDP connection is alive.

        Returns:
            True if connected and responsive, False otherwise
        """
        try:
            if not self._websocket:
                return False

            # Simple check - get page title
            title = await self._evaluate_js("document.title")
            _LOGGER.debug("CDP connection check: page title = '%s'", title)
            return True

        except Exception as err:
            _LOGGER.debug("CDP connection check failed: %s", err)
            return False
