# Relish MCP Server

MCP (Model Context Protocol) server for [Relish by ezCater](https://relish.ezcater.com/) — manage corporate-subsidized lunch orders from your CLI or AI agents.

## Usage

Once set up, just tell the agent:

> **order my lunches**

That's it. The agent will check which days you haven't ordered on yet, pick food based on your saved preferences, and place orders. Run it daily or once a week — it only orders for days that are missing.

By default the agent shows you its picks and waits for a thumbs-up. If you'd rather it just handle everything, say **"turn on auto-order"** and it'll pick and order without asking.

Other things you can say:

| You say | What happens |
|---------|--------------|
| **order my lunches** | Fills in all unordered days for the week |
| **turn on auto-order** | Agent picks and orders without asking from now on |
| **let me pick** | Back to showing picks for confirmation |
| **what's for lunch today?** | Shows today's restaurants and your existing order |
| **order me something good** | Picks and orders one item for today |
| **change my Wednesday order** | Cancels and re-orders for that day |
| **show me Thursday's menus** | Lists every menu item available Thursday |

## Features

- **Batch ordering** — one command orders for every unordered day in the week
- **Food preferences** — remembers what you like and picks accordingly
- **View schedule** — see available restaurants, delivery times, and meal availability
- **Browse menus** — full menus with prices, categories, and dietary tags
- **Place & cancel orders** — end-to-end ordering and cancellation
- **Subsidy tracking** — stay within your company meal budget automatically
- **Cookie persistence** — MFA only needed once every 30 days

## Setup

### 1. Install Chrome/Chromium

The server uses Selenium with a headless Chrome browser. You need Chrome or Chromium installed:

**Fedora/RHEL:**
```bash
sudo dnf install chromium chromedriver
```

**Ubuntu/Debian:**
```bash
sudo apt install chromium-browser chromium-chromedriver
```

**macOS (Homebrew):**
```bash
brew install --cask google-chrome
```
ChromeDriver is bundled automatically via `selenium-manager` in recent Selenium versions.

**Verify it works:**
```bash
chromium --version   # or google-chrome --version
```

### 2. Install Python dependencies

Requires **Python 3.11+**.

```bash
pip install -r requirements.txt
```

### 3. Run the server

**With Cursor IDE (recommended):**

The `.cursor/mcp.json` is already configured — just open this project in Cursor and the `relish` MCP server will be available.

> **Note:** The MCP config runs `python3 server.py`. If you installed
> dependencies in a virtualenv, update `.cursor/mcp.json` to use your
> venv's Python path (e.g. `".venv/bin/python3"`), or install globally.

Set `RELISH_HEADLESS=0` in `.cursor/mcp.json` env to see the browser window (useful for debugging).

**Standalone (stdio transport):**

```bash
python server.py
```

### 4. First-time setup (agent-guided)

The agent handles all first-time configuration for you:

1. **Credentials** — the agent will ask for your Relish email and password and save them securely (`.credentials`, chmod 600, gitignored). You can also set them manually or via environment variables (`RELISH_EMAIL`, `RELISH_PASSWORD`).
2. **MFA** — on first login, a verification code is emailed to you. The agent will ask you to paste the 6-digit code. After that, cookies are saved and MFA is skipped for 30 days.
3. **Food preferences** — the agent will ask what cuisines you like/dislike and how you prefer to order, then save your preferences (`.food_preferences.json`, gitignored).

All of this happens conversationally — just start chatting with the agent and it will walk you through it.

## Tools

| Tool | Description |
|------|-------------|
| `set_credentials` | Save email + password (first-time setup) |
| `login` | Authenticate (tries saved cookies first) |
| `submit_mfa_code` | Complete MFA verification |
| `get_schedule` | Restaurants + orders for a date |
| `get_week_overview` | Full week summary |
| `get_unordered_days` | Full menus for every day without an order (batch ordering) |
| `get_subsidy` | Remaining company meal budget |
| `get_menu` | One restaurant's menu items |
| `get_item_options` | Sizes, sides, toppings for an item (call before ordering) |
| `get_all_menus` | All restaurants' menus for a date |
| `save_menus_to_file` | Export menus to markdown |
| `get_orders` | Upcoming or completed orders |
| `place_order` | Order a menu item |
| `cancel_order` | Cancel an order |
| `get_food_preferences` | User's dietary preferences |
| `set_food_preferences` | Update preferences |
| `logout` | Close browser session |

## Architecture

```
server.py              — MCP tool definitions (thin wrapper)
relish_browser.py      — All Selenium automation logic
relish_models.py       — Dataclasses (DaySchedule, MenuItem, Order, etc.)
.credentials           — Login credentials (chmod 600, gitignored)
.cookies.json          — Session cookies (gitignored)
.food_preferences.json — Dietary preferences (gitignored)
```

## Food preferences

Stored in `.food_preferences.json` (gitignored). On first use, the agent will ask what you like and save your preferences. You can also edit the file directly:

```json
{
  "yes": ["Mexican bowls", "Greek", "Mediterranean"],
  "no": ["Sushi"],
  "style": "Prefer bowls and plates over sandwiches",
  "notes": "Pick restaurants tagged 'Office favorite' when they match preferences",
  "auto_order": false
}
```

Set `auto_order` to `true` if you want the agent to pick and order without confirmation.

Update anytime via the `set_food_preferences` tool or by editing the file.
