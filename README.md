# Relish MCP Server

MCP (Model Context Protocol) server for [Relish by ezCater](https://relish.ezcater.com/) — manage corporate-subsidized lunch orders from your CLI or AI agents.

## Features

- **View schedule** — see available restaurants, delivery times, and meal availability for any date
- **Browse menus** — get full menus with prices, categories, and dietary tags
- **Place orders** — complete end-to-end ordering (add to cart → checkout → confirm)
- **Cancel orders** — cancel existing orders
- **Check subsidy** — see remaining company meal budget
- **Week overview** — see all available dates and orders at once
- **Food preferences** — store and retrieve dietary preferences for AI-assisted ordering
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

```bash
pip install -r requirements.txt
```

### 3. Run the server

**With Cursor IDE (recommended):**

The `.cursor/mcp.json` is already configured. Open this project in Cursor and the `relish` MCP server will be available to the AI agent.

If you cloned this repo to a non-default location, update the `cwd` path in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "relish": {
      "command": "python3",
      "args": ["server.py"],
      "cwd": "/path/to/relish-mcp",
      "env": {
        "RELISH_HEADLESS": "1"
      }
    }
  }
}
```

Set `RELISH_HEADLESS=0` to see the browser window (useful for debugging).

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
| `get_subsidy` | Remaining company meal budget |
| `get_menu` | One restaurant's menu items |
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
  "notes": "Pick restaurants tagged 'Office favorite' when they match preferences"
}
```

Update anytime via the `set_food_preferences` tool or by editing the file.
