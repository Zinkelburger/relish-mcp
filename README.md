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

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Requires Chrome/Chromium and ChromeDriver installed on your system.

### 2. Configure credentials

On first run, a `.credentials` template is created. Fill it in:

```json
{"email": "you@company.com", "password": "your-password"}
```

Or use environment variables:

```bash
export RELISH_EMAIL="you@company.com"
export RELISH_PASSWORD="your-password"
```

### 3. Run the server

**Standalone (stdio transport):**

```bash
python server.py
```

**With Cursor IDE:**

The `.cursor/mcp.json` is already configured. Open this project in Cursor and the `relish` MCP server will be available to the AI agent. Edit the `cwd` path if you cloned this repo elsewhere:

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

### 4. First login (MFA)

The first time you connect, MFA will be triggered. The agent will ask you for the 6-digit code from your email. After that, cookies are saved and MFA is skipped for 30 days.

## Tools

| Tool | Description |
|------|-------------|
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

Stored in `.food_preferences.json`. Default:

```json
{
  "yes": ["Mexican bowls", "Greek", "Mediterranean", "Indian"],
  "no": ["Sushi"],
  "style": "Prefer bowls and plates over sandwiches",
  "notes": "Pick restaurants tagged 'Office favorite' when they match preferences"
}
```

Update via the `set_food_preferences` tool or edit the file directly.
