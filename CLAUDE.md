# Relish MCP Server — Agent Guide (Claude Code)

Selenium-based MCP server for relish.ezcater.com corporate lunch ordering. The server is registered in `.mcp.json`, so Claude Code picks it up automatically in this project. (Cursor uses `.cursor/mcp.json` + `.cursor/rules/` for the same thing.)

## Architecture

- `server.py` — MCP tool definitions (thin wrapper). `relish_browser.py` — ALL Selenium logic. `relish_models.py` — pure dataclasses. `auto_order.py` — deterministic weekday backup order, run by cron.
- Secrets (`.credentials`, `.cookies.json`, `.food_preferences.json`) are local, chmod 600 where sensitive, gitignored.
- Keep Selenium contained: new site data → method on `RelishBrowser` → model → tool in `server.py`.

## Using the server

1. **Always call `login` first** each session — warms up the browser (~12s) in its own short call so heavy tools don't time out.
2. **First-run setup** (each step self-detects; skip if done): `set_credentials` → `login` (+ `submit_mfa_code` with the emailed 6-digit code) → `get_food_preferences`, and if empty ask likes / dislikes / style / auto-order in one message, then `set_food_preferences`. Finally offer the optional 9AM backup (below).
3. **ID chain**: `get_schedule` → `schedule_entry_id` → `get_menu` → `menu_item_id` → `get_item_options` → `group_id`/`value` + `size_index` → `place_order`. `cancel_order` takes `order_id` from `get_orders`.
4. **Always call `get_item_options` before `place_order`** (required sizes/choices), and **always `check_subsidy` before ordering** — item + ~7% tax must fit the subsidy so the order is $0.00 out-of-pocket. Never exceed the subsidy.
5. **Never call browser tools in parallel** — one shared WebDriver; calls are serialized and can time out (90s cap). Sequential only.
6. Batch flow ("order my lunches"): `get_unordered_days` → per NEEDS ORDER day `get_all_menus(date)` → pick per preferences → `get_item_options` → `check_subsidy` → `place_order`. Skips days already ordered, so it's safe to run daily. Respect `auto_order`: OFF = show picks and wait for approval; ON = order and report after.

## Backup auto-order (optional 9AM safety net)

`setup_auto_order_cron` installs a weekday cron job running `auto_order.py`: if today is unordered by 9AM it orders ONE item for TODAY ONLY, preference-matched, always within the subsidy — deterministic Python, no AI at runtime. **Ask the user explicitly ("Want me to install this?") and only proceed on a clear yes — never install unprompted.** `preview_auto_order` shows today's would-be pick without ordering; `auto_order_status` shows install state + log; `remove_auto_order_cron` uninstalls (also confirm first). If the log shows MFA warnings, run `login` once to refresh cookies.

## Tests

`python test_fixtures.py` (offline HTML checks) and `python test_parsers.py` (headless Chrome against fixtures). Refresh fixtures with `fetch_fixtures.py`. Both also work under pytest.
