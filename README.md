# Alexa Default Shopping List Sync with Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License](https://img.shields.io/github/license/thiagobucca/ha-alexa-shopping-list-sync)](LICENSE)
![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)

This project provides a reliable and lightweight synchronization between the **default Alexa shopping list** (the same list used natively on an Echo Show 15 widget) and Home Assistant.

---

## Why not use existing solutions?

Before building this integration, two popular alternatives were evaluated. They were not adopted for the reasons explained below.

### 1. ha-echo-command-center

**Repository:** https://github.com/mmstano/ha-echo-command-center

This project relies on **custom Alexa skills**. However, custom skills cannot access Alexa's default built-in shopping list. Because of this limitation, **the list displayed in the native Echo Show 15 shopping widget cannot be used**.

Since the goal of this project was to keep using Alexa's default list — ensuring full compatibility with the Echo Show interface — this approach was not viable.

### 2. home-assistant-alexa-shopping-list (v1.x - v2.x)

**Repository:** https://github.com/madmachinations/home-assistant-alexa-shopping-list

Previous versions of this project used:
- Browser-based authentication with cookies
- Interaction with Amazon's list interface through **Selenium**
- A **multi-container architecture** (one server container + one client container)

Although functional at first, this approach proved **unreliable in long-term use**:
- ❌ Cookies frequently expired or became invalid
- ❌ After some time, synchronization silently stopped
- ❌ Selenium interactions were heavy and resource-intensive
- ❌ The two-container setup added unnecessary complexity to the system

For these reasons, it was not suitable for a stable, always-on home automation environment.

---

## About This Project (v3.0)

This integration was created to provide a **simpler, stable, and lightweight solution** that:

✅ Works directly with the default Alexa shopping list
✅ Maintains compatibility with the Echo Show 15 native widget
✅ Requires minimal dependencies
✅ Ensures long-term reliability without Selenium or fragile cookies

### How It Works

This integration uses the **Chrome DevTools Protocol (CDP)** to interact directly with Amazon's web interface:

```
┌─────────────┐         ┌──────────────┐         ┌──────────────┐
│   Alexa     │ ◄─────► │   Amazon     │ ◄─────► │  Chromium    │
│  (Voice)    │         │  (Cloud)     │         │  (Browser)   │
└─────────────┘         └──────────────┘         └──────┬───────┘
                                                         │ CDP
                                                         │ (WebSocket)
                                                  ┌──────▼───────┐
                                                  │     Home     │
                                                  │  Assistant   │
                                                  └──────────────┘
```

1. **Chromium Browser**: Runs with remote debugging mode and your Amazon session logged in
2. **CDP Connection**: Home Assistant connects via WebSocket to control the browser
3. **JavaScript Execution**: Reads and manipulates the shopping list directly on the page
4. **Bidirectional Sync**: Keeps Home Assistant and Alexa lists synchronized

**Key Advantages:**
- 🔒 **Secure**: Uses your existing Amazon session (manual login, no stored credentials)
- 🚀 **Lightweight**: No Selenium, no cookies management, no complex architecture (~1MB vs ~100MB)
- 🔄 **Reliable**: Direct DOM manipulation via CDP - if the page loads, it works
- 🎯 **Simple**: One integration, one browser, one connection
- ⚡ **Fast**: WebSocket communication with minimal overhead

---

## Requirements

- **Home Assistant** 2021.3.0 or newer
- **Chromium/Chrome browser** running with remote debugging enabled
- **Amazon account** with access to Alexa shopping lists
- **Network access** between Home Assistant and Chromium (localhost if on same machine)

### Supported Platforms

- ✅ Raspberry Pi 4/5 (ARM64)
- ✅ Linux (x86_64, ARM64)
- ✅ Windows (with Chrome/Chromium)
- ✅ macOS
- ✅ Home Assistant Container (host network mode)
- ✅ Home Assistant Core
- ✅ Home Assistant OS (with separate Chromium instance)

---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Go to **Integrations**
3. Click the **⋮** menu → **Custom repositories**
4. Add this repository URL: `https://github.com/thiagobucca/ha-alexa-shopping-list-sync`
5. Category: **Integration**
6. Click **Download**
7. **Restart Home Assistant**

### Method 2: Manual Installation

1. Download or clone this repository
2. Copy the `custom_components/alexa_shopping_list` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

---

## Setup Guide

### Step 1: Install Chromium

#### On Raspberry Pi / Debian / Ubuntu:

```bash
sudo apt-get update
sudo apt-get install chromium-browser
```

#### On Arch Linux:

```bash
sudo pacman -S chromium
```

#### On macOS:

```bash
brew install --cask chromium
```

#### On Windows:

Download Chromium from: https://www.chromium.org/getting-involved/download-chromium

### Step 2: Start Chromium with Remote Debugging

Run Chromium with the `--remote-debugging-port` flag:

```bash
chromium-browser \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.config/chromium-ha \
  --no-first-run \
  --no-default-browser-check \
  "https://www.amazon.com/alexaquantum/sp/alexaShoppingList"
```

**Adjust the Amazon domain for your region:**
- 🇺🇸 US: `amazon.com`
- 🇬🇧 UK: `amazon.co.uk`
- 🇧🇷 Brazil: `amazon.com.br`
- 🇩🇪 Germany: `amazon.de`
- 🇫🇷 France: `amazon.fr`
- 🇮🇹 Italy: `amazon.it`
- 🇪🇸 Spain: `amazon.es`
- 🇨🇦 Canada: `amazon.ca`
- 🇯🇵 Japan: `amazon.co.jp`

> **💡 Important**: The `--user-data-dir` flag creates a separate Chrome profile, keeping your session isolated and persistent.

### Step 3: Log in to Amazon

When Chromium opens:

1. **Manually log in** to your Amazon account
2. Complete **two-factor authentication** if prompted
3. Solve any CAPTCHAs if requested
4. ✅ **Keep this browser window open** and logged in

> **💡 Tip**: On headless systems (like Raspberry Pi), use VNC or X11 forwarding to access the desktop and log in via the browser.

### Step 4: Verify CDP Connection

Test if the CDP endpoint is accessible:

```bash
curl http://localhost:9222/json
```

You should see JSON output with page information including `"title": "Alexa Shopping List"`.

**If Home Assistant is in Docker (host network mode):**

```bash
docker exec -it homeassistant curl http://localhost:9222/json
```

### Step 5: Enable Shopping List in Home Assistant

Add to your `configuration.yaml`:

```yaml
shopping_list:
```

Save and restart Home Assistant (or reload configuration).

### Step 6: Add the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **"Alexa Shopping List"**
4. Configure the integration:

| Parameter | Description | Default | Example |
|-----------|-------------|---------|---------|
| **Amazon Domain** | Your Amazon region | `amazon.com` | `amazon.co.uk`, `amazon.de` |
| **CDP Endpoint** | Chromium remote debugging URL | `http://localhost:9222` | `http://192.168.1.100:9222` |
| **Sync Interval** | Minutes between automatic syncs | `60` | `30`, `120` |

5. Click **Submit**

The integration will:
1. ✅ Connect to Chromium via CDP
2. ✅ Navigate to your Alexa shopping list (if not already there)
3. ✅ Perform the first synchronization
4. ✅ Create a sensor: `sensor.alexa_shopping_list`

---

## Usage

### Automatic Synchronization

The integration automatically syncs every X minutes (configured during setup).

**What happens during auto sync:**
- 📥 Items added via Alexa → appear in Home Assistant
- 📤 Items marked as **complete** in HA → removed from Alexa
- 🔄 Lists stay synchronized bidirectionally

### Manual Synchronization

Force an immediate sync:

```yaml
service: alexa_shopping_list.sync_alexa_shopping_list
```

**Automation example:**

```yaml
script:
  sync_alexa_list:
    alias: "Sync Alexa Shopping List"
    sequence:
      - service: alexa_shopping_list.sync_alexa_shopping_list
```

### Adding Items

#### Via Alexa (Voice Command):
```
"Alexa, add milk to my shopping list"
"Alexa, add bread and eggs to my list"
```
→ Next sync (auto or manual) → Items appear in Home Assistant

#### Via Home Assistant:
1. Open the **Shopping List** panel in Home Assistant
2. Add an item (e.g., "coffee")
3. **Call manual sync service** (force sync)
4. Item appears in Alexa

### Removing Items

| Method | Behavior |
|--------|----------|
| **Mark as complete in HA** | ✅ Removed from Alexa + HA |
| **Voice command via Alexa** | ✅ Removed from Alexa + HA |
| **Delete in HA** | ⚠️ Item returns from Alexa (Alexa is source of truth) |

> **💡 Best Practice**: Always **mark items as complete** instead of deleting them in HA.

**Why?** Deleting an item in HA doesn't communicate the intent to remove it from Alexa. Marking as complete signals "I bought this item" and removes it from both lists.

---

## Configuration Options

### Changing Sync Interval

1. Go to **Settings** → **Devices & Services**
2. Find **Alexa Shopping List**
3. Click **Configure**
4. Adjust **Sync Interval (minutes)**

**Recommended values:**
- **60 minutes**: Normal use (default)
- **30 minutes**: Frequent updates
- **120 minutes**: Low traffic / battery saving
- **5-10 minutes**: Testing only (not recommended for production)

> ⚠️ **Warning**: Very short intervals (< 5 minutes) may trigger rate limiting or cause excessive browser activity.

### Changing Amazon Domain

If you need to switch regions (e.g., from `amazon.com` to `amazon.co.uk`):

1. Remove the integration completely
2. Re-add it with the new domain
3. Ensure Chromium is logged in to the correct Amazon region

---

## Events

The integration fires events you can use in automations:

### `alexa_shopping_list_changed`

Fired when the shopping list changes during sync.

**Event Data:**
```yaml
event_type: alexa_shopping_list_changed
data:
  success: true
  changed: true
  added: ["milk", "eggs"]
  removed: ["bread"]
  alexa_count: 5
  ha_count: 5
```

**Example Automation:**
```yaml
automation:
  - alias: "Notify when items added to shopping list"
    trigger:
      - platform: event
        event_type: alexa_shopping_list_changed
    condition:
      - "{{ trigger.event.data.added | length > 0 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Shopping List Updated"
          message: "Added: {{ trigger.event.data.added | join(', ') }}"
```

---

## Sensor Attributes

The integration creates a sensor: **`sensor.alexa_shopping_list`**

**State:** Number of items in Alexa list

**Attributes:**
- `last_sync`: Timestamp of last successful sync
- `connected`: CDP connection status (true/false)
- `alexa_count`: Number of items in Alexa list
- `ha_count`: Number of items in HA list

**Example Lovelace Card:**
```yaml
type: entities
title: Alexa Shopping List
entities:
  - entity: sensor.alexa_shopping_list
    name: Total Items
  - type: attribute
    entity: sensor.alexa_shopping_list
    attribute: alexa_count
    name: Items in Alexa
  - type: attribute
    entity: sensor.alexa_shopping_list
    attribute: ha_count
    name: Items in Home Assistant
  - type: attribute
    entity: sensor.alexa_shopping_list
    attribute: last_sync
    name: Last Sync
```

---

## Troubleshooting

### Integration Fails to Connect

**Error:** `CDP connection failed`

**Solutions:**
1. Verify Chromium is running: `ps aux | grep chromium`
2. Test CDP endpoint: `curl http://localhost:9222/json`
3. Check the port is correct (default: 9222)
4. Ensure firewall allows connections to port 9222
5. Try restarting Chromium with the correct flags

### Items Not Syncing

**Symptoms:** Items added via Alexa don't appear in HA (or vice versa)

**Solutions:**
1. Check the browser is on the shopping list page
2. Verify you're still logged in to Amazon
3. Force a manual sync: `alexa_shopping_list.sync_alexa_shopping_list`
4. Check Home Assistant logs: **Settings** → **System** → **Logs** (filter: `alexa_shopping_list`)
5. Reload the integration

### Browser Session Expired

**Symptoms:** Sync stops working after days/weeks

**Solutions:**
1. Access Chromium via VNC or direct display
2. Check if Amazon is asking you to log in again
3. Re-authenticate if needed
4. Reload the integration in Home Assistant

### Logs Show "Could not find input/button"

**Cause:** Amazon changed their page structure for your region

**Solutions:**
1. Open a GitHub issue with:
   - Your Amazon domain (e.g., `amazon.com`)
   - Browser console errors (F12 → Console)
   - Screenshot of the shopping list page
2. The selectors may need updating for your specific Amazon region

### Browser Keeps Refreshing or Tabbing

**Cause:** Sync interval is too short

**Solutions:**
1. Check your configured sync interval
2. Increase to at least 30-60 minutes
3. The Tab/refresh behavior should only occur during item addition, not constantly

---

## Advanced Configuration

### Running Chromium as a systemd Service

Create `/etc/systemd/system/chromium-alexa.service`:

```ini
[Unit]
Description=Chromium for Alexa Shopping List Integration
After=network.target graphical.target

[Service]
Type=simple
User=homeassistant
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/homeassistant/.Xauthority"
ExecStart=/usr/bin/chromium-browser \
  --remote-debugging-port=9222 \
  --user-data-dir=/home/homeassistant/.config/chromium-ha \
  --no-first-run \
  --no-default-browser-check \
  "https://www.amazon.com/alexaquantum/sp/alexaShoppingList"
Restart=always
RestartSec=10

[Install]
WantedBy=graphical.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable chromium-alexa
sudo systemctl start chromium-alexa
sudo systemctl status chromium-alexa
```

### Using with Docker Compose (Browserless Chrome)

```yaml
version: '3.8'
services:
  homeassistant:
    image: homeassistant/home-assistant:stable
    volumes:
      - ./config:/config
    network_mode: host
    restart: unless-stopped

  chromium:
    image: browserless/chrome:latest
    ports:
      - "9222:3000"
    environment:
      - CONNECTION_TIMEOUT=600000
      - MAX_CONCURRENT_SESSIONS=1
      - KEEP_ALIVE=true
    restart: unless-stopped
```

**Note:** With browserless/chrome, you'll need to handle authentication differently. Manual login may not persist across container restarts.

---

## FAQ

### Q: Does this work in my country?
**A:** Yes! It supports all Amazon domains worldwide.

### Q: Is this safe? Will Amazon ban my account?
**A:** It's safe. You log in normally via the browser. Home Assistant uses the official Chrome DevTools Protocol (same as Chrome Developer Tools). However, use reasonable sync intervals (≥60 minutes) to avoid rate limiting.

### Q: How much resources does this consume?
**A:** Much less than Selenium! The browser is already open; Home Assistant only connects via WebSocket when syncing. CPU usage is minimal.

### Q: Do I need to keep Chromium running all the time?
**A:** Yes! The browser must stay open and logged in. Configure auto-start on boot (see systemd service example above).

### Q: Can I use this with multiple Amazon accounts?
**A:** Not currently. One Amazon account per Home Assistant instance.

### Q: Does this work with Alexa TODO lists?
**A:** No, only shopping lists are supported at this time.

### Q: What happens if my internet goes down?
**A:** The integration will show as disconnected. Once internet returns, it will reconnect automatically on the next sync.

---

## Contributing

Contributions are welcome! Here's how you can help:

1. 🐛 **Report Bugs**: Open an issue with detailed information
2. 💡 **Suggest Features**: Describe your use case and proposed solution
3. 🔧 **Submit Pull Requests**: Fork, code, test, and submit
4. 📖 **Improve Documentation**: Fix typos, add examples, or translate

### Development Setup

```bash
# Clone the repository
git clone https://github.com/thiagobucca/ha-alexa-shopping-list-sync
cd ha-alexa-shopping-list-sync

# Install in development mode (symlink)
ln -s $(pwd)/custom_components/alexa_shopping_list \
      /path/to/homeassistant/config/custom_components/alexa_shopping_list

# Restart Home Assistant to load changes
```

### Project Structure

```
custom_components/alexa_shopping_list/
├── __init__.py              # Integration entry point
├── config_flow.py           # Configuration UI flow
├── coordinator.py           # Data update coordinator
├── cdp_manager.py           # Chrome DevTools Protocol manager
├── shopping_list_sync.py    # Synchronization logic
├── sensor.py                # Home Assistant sensor platform
├── manifest.json            # Integration metadata
├── strings.json             # UI strings
└── translations/
    └── en.json              # English translations
```

---

## Changelog

### v3.0.0 (2025-11-21) - CDP Architecture Rewrite
- ✨ **Complete rewrite** using Chrome DevTools Protocol (CDP)
- ❌ **Removed** Selenium dependency
- ❌ **Removed** Docker containers architecture
- ❌ **Removed** cookie management complexity
- ✅ **Added** direct WebSocket communication via CDP
- ✅ **Reduced** package size from ~100MB to ~1MB
- ✅ **Improved** reliability and long-term stability
- ✅ **Simplified** configuration to 3 steps
- ✅ **Enhanced** error handling and logging
- ✅ **Fixed** bidirectional synchronization logic

### v2.0.0 (Archived - Selenium-based)
- Used Selenium for browser automation
- Required multi-container Docker setup
- Cookie-based authentication (unreliable)

### v1.x (Archived - Server/Client)
- Original server/client architecture
- Deprecated due to complexity and maintenance burden

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## Disclaimer

This project is **not affiliated** with Amazon, Alexa, or any of their subsidiaries.

"Amazon" and "Alexa" are registered trademarks of Amazon.com, Inc.

**Use at your own risk.** The authors are not responsible for any issues arising from the use of this integration.

---

## Acknowledgments

**Original Author:** [@madmachinations](https://github.com/madmachinations)
**v3.0 Refactor:** [@thiagobucca](https://github.com/thiagobucca)

**Special Thanks:**
- Home Assistant Community
- Chrome DevTools Protocol Team
- All contributors and testers

---

## Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/thiagobucca/ha-alexa-shopping-list-sync/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/thiagobucca/ha-alexa-shopping-list-sync/discussions)
- 📖 **Documentation**: [Setup Guide](CDP_SETUP.md)
- ⭐ **Star this repo** if it helped you!

---

## Roadmap

- [ ] Support for Alexa TODO lists
- [ ] Unidirectional sync mode (Alexa→HA or HA→Alexa only)
- [ ] Multiple Amazon account support
- [ ] Item quantities support
- [ ] Shopping categories/aisles
- [ ] Auto-configuration of systemd service
- [ ] Web-based setup wizard

---

**Made with ❤️ for the Home Assistant community**

**⭐ If this project helped you, please give it a star!**
