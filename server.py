"""Relish MCP Server — control Relish by ezCater from your CLI or AI agents."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from relish_browser import RelishBrowser
from relish_models import LoginState

LOG = logging.getLogger("relish.server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

_PROJECT_DIR = Path(__file__).parent
CREDENTIALS_FILE = _PROJECT_DIR / ".credentials"
PREFS_FILE = _PROJECT_DIR / ".food_preferences.json"

DEFAULT_PREFS: dict = {
    "yes": [],
    "no": [],
    "style": "",
    "notes": "",
    "auto_order": False,
}


def _load_credentials() -> tuple[str | None, str | None]:
    """Load credentials from env vars or .credentials file.

    Priority: env vars > .credentials file.
    Returns (None, None) if no credentials are configured yet.
    """
    email = os.environ.get("RELISH_EMAIL", "")
    password = os.environ.get("RELISH_PASSWORD", "")
    if email and password:
        return email, password

    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text())
            e, p = data.get("email", ""), data.get("password", "")
            if e and p:
                return e, p
        except (json.JSONDecodeError, KeyError) as exc:
            LOG.warning("Bad .credentials file: %s", exc)

    return None, None


def _save_credentials(email: str, password: str) -> None:
    CREDENTIALS_FILE.write_text(
        json.dumps({"email": email, "password": password}, indent=2) + "\n"
    )
    CREDENTIALS_FILE.chmod(0o600)
    LOG.info("Credentials saved to %s", CREDENTIALS_FILE)


def _load_food_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_PREFS)


def _has_food_prefs() -> bool:
    """True if the user has configured any food preferences."""
    return bool(
        FOOD_PREFS.get("yes")
        or FOOD_PREFS.get("no")
        or FOOD_PREFS.get("style")
        or FOOD_PREFS.get("notes")
    )


EMAIL, PASSWORD = _load_credentials()
FOOD_PREFS = _load_food_prefs()

mcp = FastMCP(
    "relish",
    instructions=(
        "Relish MCP server for ordering corporate-subsidized lunches via "
        "relish.ezcater.com.\n\n"
        "## First-time setup\n"
        "If credentials aren't configured yet, the agent should:\n"
        "1. Ask the user for their Relish email and password.\n"
        "2. Call `set_credentials(email, password)` to save them.\n"
        "3. Call `login` — if MFA is needed, ask for the 6-digit email "
        "code and call `submit_mfa_code`.\n"
        "4. Call `get_food_preferences` — if empty, ask the user what "
        "cuisines they like/dislike, then call `set_food_preferences`.\n\n"
        "## Quick start (after setup)\n"
        "1. Call `get_schedule` to see today's restaurants and existing "
        "orders. Each restaurant has a `schedule_entry_id`.\n"
        "2. Call `get_menu(schedule_entry_id)` to see a restaurant's "
        "items. Each item has a `menu_item_id`.\n"
        "3. Call `place_order(schedule_entry_id, menu_item_id)` to order.\n"
        "4. Call `cancel_order(order_id)` to cancel.\n\n"
        "## Tips\n"
        "- Call `get_food_preferences` before choosing food for the user.\n"
        "- Call `get_unordered_days` to batch-order: it scans the week and "
        "returns full menus for every day without an order.\n"
        "- Call `get_week_overview` to see the full week at once.\n"
        "- Most tools auto-login using saved cookies. You only need to "
        "call `login` explicitly on the first use or after cookies expire.\n"
        "- Orders within the company subsidy cost $0.00 out-of-pocket. "
        "Check `get_subsidy` to see the remaining budget."
    ),
)

browser: RelishBrowser | None = None


def _get_browser() -> RelishBrowser:
    global browser
    if browser is None:
        headless = os.environ.get("RELISH_HEADLESS", "1") != "0"
        browser = RelishBrowser(headless=headless)
    return browser


class _MfaRequired(Exception):
    pass


class _NoCredentials(Exception):
    pass


def _ensure_logged_in() -> RelishBrowser:
    """Return a logged-in browser, auto-logging in with saved cookies
    if possible. Raises _NoCredentials or _MfaRequired.
    """
    if EMAIL is None or PASSWORD is None:
        raise _NoCredentials()
    b = _get_browser()
    if b.state == LoginState.LOGGED_IN:
        return b
    state = b.login(EMAIL, PASSWORD)
    if state == LoginState.AWAITING_MFA:
        raise _MfaRequired()
    return b


def _auto_login_wrapper(fn):
    """Decorator: auto-login before running a tool, prompting for MFA
    or credentials setup if needed."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            _ensure_logged_in()
        except _NoCredentials:
            return (
                "No credentials configured yet. "
                "Ask the user for their Relish email and password, then "
                "call `set_credentials(email, password)` to save them."
            )
        except _MfaRequired:
            return (
                "Login required but MFA code is needed. "
                "Call `login` first, then `submit_mfa_code(code)` with "
                "the 6-digit code from your email, then retry this tool."
            )
        return fn(*args, **kwargs)

    return wrapper


# ------------------------------------------------------------------
# Auth tools
# ------------------------------------------------------------------


@mcp.tool()
def set_credentials(email: str, password: str) -> str:
    """Save the user's Relish login credentials.

    Call this during first-time setup. Ask the user for their email and
    password, then pass them here. Credentials are saved locally in
    .credentials (chmod 600, never committed to git).

    Args:
        email: Relish / company email (e.g. 'user@company.com').
        password: Relish password.
    """
    global EMAIL, PASSWORD
    _save_credentials(email, password)
    EMAIL, PASSWORD = email, password
    return "Credentials saved. You can now call `login` to authenticate."


@mcp.tool()
def login() -> str:
    """Log in to Relish.

    If saved cookies are valid, logs in instantly (no MFA).
    If cookies expired and MFA is required, returns 'awaiting_mfa' —
    you must then call submit_mfa_code with the 6-digit email code.
    If no credentials are configured, tells you to call set_credentials first.
    """
    if EMAIL is None or PASSWORD is None:
        return (
            "No credentials configured yet. "
            "Ask the user for their Relish email and password, then "
            "call `set_credentials(email, password)` to save them."
        )
    b = _get_browser()
    if b.state == LoginState.LOGGED_IN:
        return "Already logged in."

    state = b.login(EMAIL, PASSWORD)
    if state == LoginState.AWAITING_MFA:
        return (
            "MFA code required. A verification code was sent to your email. "
            "Call submit_mfa_code(code) with the 6-digit code."
        )
    return "Logged in successfully."


@mcp.tool()
def submit_mfa_code(code: str) -> str:
    """Submit the MFA verification code sent to your email.
    Only needed when login() returns 'awaiting_mfa'.
    """
    b = _get_browser()
    state = b.submit_mfa_code(code)
    if state == LoginState.AWAITING_MFA:
        return (
            "Code was invalid or expired. Check your email for a new code "
            "and try again."
        )
    return "MFA accepted — logged in successfully."


# ------------------------------------------------------------------
# Schedule & menu tools
# ------------------------------------------------------------------


@mcp.tool()
@_auto_login_wrapper
def get_schedule(date: str | None = None) -> str:
    """Get today's (or a specific date's) restaurants and your existing orders.

    Returns: restaurant names, descriptions, tags (e.g. 'Office favorite'),
    order-by times, delivery times, meals remaining, and your current orders
    with their status. Each restaurant has a `schedule_entry_id` you'll need
    for get_menu and place_order.

    Args:
        date: YYYY-MM-DD format, or omit for today.
    """
    b = _get_browser()
    schedule = b.get_schedule(date)
    return str(schedule)


@mcp.tool()
@_auto_login_wrapper
def get_week_overview() -> str:
    """Get a summary of the whole week: all available dates, restaurants,
    and any orders you've already placed.

    Useful for planning meals or seeing what's coming up.
    """
    b = _get_browser()
    today_schedule = b.get_schedule()
    all_dates = today_schedule.available_dates

    lines = [f"=== {today_schedule.date_label} ({today_schedule.date}) ==="]
    if today_schedule.subsidy:
        lines.append(f"Subsidy: {today_schedule.subsidy}")
    if today_schedule.my_orders:
        for o in today_schedule.my_orders:
            lines.append(f"  ORDER: {o.restaurant} — {o.status}")
    for r in today_schedule.restaurants:
        tag = f" [{', '.join(r.tags)}]" if r.tags else ""
        status = "CLOSED" if r.closed else f"by {r.order_by}"
        lines.append(f"  • {r.name}{tag} ({status})")

    for d in all_dates:
        if d["date"] == today_schedule.date or d["date"] == "today":
            continue
        try:
            sched = b.get_schedule(d["date"])
            lines.append(f"\n=== {sched.date_label} ({sched.date}) ===")
            if sched.subsidy:
                lines.append(f"Subsidy: {sched.subsidy}")
            if sched.my_orders:
                for o in sched.my_orders:
                    lines.append(f"  ORDER: {o.restaurant} — {o.status}")
            for r in sched.restaurants:
                tag = f" [{', '.join(r.tags)}]" if r.tags else ""
                status = "CLOSED" if r.closed else f"by {r.order_by}"
                lines.append(f"  • {r.name}{tag} ({status})")
        except Exception as ex:
            lines.append(f"\n=== {d['label']} ({d['date']}) ===")
            lines.append(f"  Error: {ex}")

    return "\n".join(lines)


@mcp.tool()
@_auto_login_wrapper
def get_unordered_days() -> str:
    """Scan the whole week and return full menus for every day you haven't
    ordered on yet.

    This is the starting point for batch-ordering: call it once to see
    every unordered day's restaurants and menu items, then call
    get_item_options + place_order for each day.

    Returns: for each unordered day — date, subsidy, restaurants with
    full menu items (name, price, category, item ID). Days that already
    have orders are listed briefly so you can see the full picture.
    """
    b = _get_browser()
    today_schedule = b.get_schedule()
    all_dates = today_schedule.available_dates

    schedules = [
        (today_schedule.date, today_schedule),
    ]
    for d in all_dates:
        if d["date"] == today_schedule.date or d["date"] == "today":
            continue
        try:
            schedules.append((d["date"], b.get_schedule(d["date"])))
        except Exception as ex:
            LOG.warning("Skipping %s: %s", d["date"], ex)

    lines: list[str] = []
    unordered_count = 0
    ordered_count = 0

    for date_str, sched in schedules:
        has_order = bool(sched.my_orders)
        has_open_restaurants = any(not r.closed for r in sched.restaurants)

        if has_order:
            ordered_count += 1
            lines.append(f"\n{'='*50}")
            lines.append(f"{sched.date_label} ({date_str}) — ALREADY ORDERED")
            lines.append(f"{'='*50}")
            for o in sched.my_orders:
                lines.append(f"  • {o}")
            continue

        if not has_open_restaurants:
            lines.append(f"\n{'='*50}")
            lines.append(f"{sched.date_label} ({date_str}) — ALL RESTAURANTS CLOSED")
            lines.append(f"{'='*50}")
            continue

        unordered_count += 1
        lines.append(f"\n{'='*50}")
        lines.append(f"{sched.date_label} ({date_str}) — NEEDS ORDER")
        lines.append(f"{'='*50}")
        if sched.subsidy:
            lines.append(f"Subsidy: {sched.subsidy}")

        all_menus = b.get_all_menus(date_str)
        if all_menus:
            for restaurant, items in all_menus.items():
                tag_info = ""
                for r in sched.restaurants:
                    if r.name == restaurant and r.tags:
                        tag_info = f" [{', '.join(r.tags)}]"
                        break
                lines.append(f"\n  --- {restaurant}{tag_info} ({len(items)} items) ---")
                for item in items:
                    lines.append(f"    • {item}")
        else:
            for r in sched.restaurants:
                if not r.closed:
                    tag = f" [{', '.join(r.tags)}]" if r.tags else ""
                    lines.append(f"  • {r.name}{tag} (ID: {r.schedule_entry_id})")

    summary = f"Week summary: {unordered_count} day(s) need orders, {ordered_count} already ordered."
    return summary + "\n" + "\n".join(lines)


@mcp.tool()
@_auto_login_wrapper
def get_subsidy(date: str | None = None) -> str:
    """Get your remaining company meal subsidy for a date.

    The subsidy is how much your company covers. Orders within the subsidy
    are $0.00 out-of-pocket.

    Args:
        date: YYYY-MM-DD format, or omit for today.
    """
    b = _get_browser()
    subsidy = b.get_subsidy(date)
    if subsidy is None:
        return "No subsidy information found."
    return str(subsidy)


@mcp.tool()
@_auto_login_wrapper
def get_all_menus(date: str | None = None) -> str:
    """Get menus for ALL restaurants on a given date.

    Browses every open restaurant and returns all menu items with prices,
    categories, and item IDs. Slower than get_menu (one page load per
    restaurant) but gives a complete picture.

    Args:
        date: YYYY-MM-DD format, or omit for today.
    """
    b = _get_browser()
    all_menus = b.get_all_menus(date)
    if not all_menus:
        return "No restaurant menus found for this date."
    lines: list[str] = []
    for restaurant, items in all_menus.items():
        lines.append(f"\n{'='*50}")
        lines.append(f"{restaurant} ({len(items)} items)")
        lines.append(f"{'='*50}")
        for item in items:
            lines.append(f"  • {item}")
    return "\n".join(lines)


@mcp.tool()
@_auto_login_wrapper
def save_menus_to_file(date: str | None = None, filepath: str | None = None) -> str:
    """Get all menus for a date and save to a markdown file.

    Args:
        date: YYYY-MM-DD format, or omit for today.
        filepath: Where to write. Defaults to menus_YYYYMMDD.md in project dir.
    """
    b = _get_browser()
    path = b.save_menus_to_file(date, filepath)
    return f"Saved all menus to {path}"


@mcp.tool()
@_auto_login_wrapper
def get_menu(schedule_entry_id: str) -> str:
    """Get a single restaurant's menu items.

    Returns item names, prices, descriptions, categories, dietary tags,
    and the menu_item_id needed for place_order.

    Args:
        schedule_entry_id: From get_schedule output (e.g. '1232291').
    """
    b = _get_browser()
    items = b.get_menu(schedule_entry_id)
    if not items:
        return "No menu items found."
    lines = [f"Menu ({len(items)} items):"]
    for item in items:
        lines.append(f"  • {item}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Order tools
# ------------------------------------------------------------------


@mcp.tool()
@_auto_login_wrapper
def get_orders(tab: str = "upcoming") -> str:
    """Get your orders.

    Each order includes: restaurant, delivery time, price, item names,
    status, and the order_id needed for cancel_order.

    Args:
        tab: 'upcoming' (default) or 'completed'.
    """
    b = _get_browser()
    orders = b.get_orders(tab)
    if not orders:
        return f"No {tab} orders found."
    lines = [f"{tab.title()} orders ({len(orders)}):"]
    for o in orders:
        lines.append(f"\n  • {o}")
    return "\n".join(lines)


@mcp.tool()
@_auto_login_wrapper
def get_item_options(schedule_entry_id: str, menu_item_id: str) -> str:
    """Get all customization options for a menu item (sizes, sides,
    toppings, sauces, drinks, etc.).

    Call this before place_order to see what choices are available.
    Many items have required options (e.g. size) and optional add-ons
    (e.g. extra sides for +$1.49). Some items are "build your own"
    where the options ARE the meal.

    Returns each option group with its choices, prices, and the
    group_id/value strings needed for place_order's options parameter.

    Typical workflow:
      1. get_menu(schedule_entry_id) → find menu_item_id
      2. get_item_options(schedule_entry_id, menu_item_id) → see choices
      3. place_order(schedule_entry_id, menu_item_id, options=..., size_index=...)

    Args:
        schedule_entry_id: Restaurant's ID from get_schedule (e.g. '1232291').
        menu_item_id: Item's ID from get_menu (e.g. '26308104').
    """
    b = _get_browser()
    details = b.get_item_options(schedule_entry_id, menu_item_id)
    return str(details)


@mcp.tool()
@_auto_login_wrapper
def place_order(
    schedule_entry_id: str,
    menu_item_id: str,
    size_index: int | None = None,
    options: dict[str, list[str]] | None = None,
    notes: str = "",
) -> str:
    """Place an order for a menu item with customization.

    This clears any existing cart, opens the item, applies your
    selections, adds to cart, checks out, and confirms the order.

    Call get_item_options first to see available sizes, sides, etc.
    If you skip options/size_index, the defaults are used (usually
    smallest size, no extras).

    Args:
        schedule_entry_id: Restaurant's ID from get_schedule (e.g. '1232291').
        menu_item_id: Item's ID from get_menu (e.g. '26308104').
        size_index: Size choice (0=first/smallest, 1=next, etc.).
                   From get_item_options Sizes group.
        options: Dict of {group_id: [choice_value, ...]}. The group_id
                and choice values come from get_item_options output.
                Example: {"options[7632732]choices[]": ["57944357"]}
        notes: Optional special instructions (e.g. "no onions").
    """
    b = _get_browser()
    return b.place_order(
        schedule_entry_id, menu_item_id,
        options=options, size_index=size_index, notes=notes,
    )


@mcp.tool()
@_auto_login_wrapper
def cancel_order(order_id: str) -> str:
    """Cancel an existing order.

    Args:
        order_id: From get_orders output (e.g. '18242111').
    """
    b = _get_browser()
    return b.cancel_order(order_id)


# ------------------------------------------------------------------
# Utility tools
# ------------------------------------------------------------------


@mcp.tool()
def check_subsidy(
    items: list[dict],
    subsidy: float,
    tax_rate: float = 0.07,
) -> str:
    """Check whether menu items fit within the subsidy after tax.

    Call this before place_order to make sure the total won't exceed
    the subsidy. No browser needed — pure math.

    Args:
        items: List of {"name": "Item Name", "price": 14.50} dicts.
        subsidy: Remaining subsidy in dollars (from get_subsidy).
        tax_rate: Estimated tax rate as a decimal. Default 0.07 (7%).
    """
    lines: list[str] = []
    for item in items:
        name = item.get("name", "Unknown")
        price = float(item.get("price", 0))
        total = round(price * (1 + tax_rate), 2)
        fits = total <= subsidy
        verdict = "SAFE" if fits else "OVER"
        remaining = round(subsidy - total, 2)
        lines.append(
            f"{name}: ${price:.2f} + {tax_rate:.0%} tax = ${total:.2f} "
            f"vs ${subsidy:.2f} subsidy — {verdict} "
            f"({'${:.2f} left'.format(remaining) if fits else '${:.2f} over'.format(-remaining)})"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Preferences
# ------------------------------------------------------------------


@mcp.tool()
def get_food_preferences() -> str:
    """Get the user's food preferences and ordering guidelines.

    Call this before recommending or choosing food for the user.
    Preferences are stored in .food_preferences.json and can be
    updated with set_food_preferences.

    If no preferences are set, ask the user what they like/dislike
    and call set_food_preferences to save them.
    """
    if not _has_food_prefs():
        return (
            "No food preferences configured yet. "
            "Ask the user what cuisines/foods they like, what they want "
            "to avoid, and any ordering style notes (e.g. 'prefer bowls "
            "over sandwiches'). Then call `set_food_preferences` to save."
        )
    auto = FOOD_PREFS.get("auto_order", False)
    lines = ["Food preferences:"]
    yes = FOOD_PREFS.get("yes", [])
    no = FOOD_PREFS.get("no", [])
    style = FOOD_PREFS.get("style", "")
    notes = FOOD_PREFS.get("notes", "")
    if yes:
        lines.append(f"  YES: {', '.join(yes)}")
    if no:
        lines.append(f"  NO: {', '.join(no)}")
    if style:
        lines.append(f"  Style: {style}")
    if notes:
        lines.append(f"  Notes: {notes}")
    lines.append(f"  Auto-order: {'ON — pick and order without asking' if auto else 'OFF — show picks for confirmation first'}")
    return "\n".join(lines)


@mcp.tool()
def set_food_preferences(
    yes: list[str] | None = None,
    no: list[str] | None = None,
    style: str | None = None,
    notes: str | None = None,
    auto_order: bool | None = None,
) -> str:
    """Update the user's food preferences.

    Only provided fields are updated; others are kept.

    Args:
        yes: Cuisines/foods the user likes (e.g. ['Mexican bowls', 'Greek']).
        no: Cuisines/foods to avoid (e.g. ['Sushi']).
        style: General preference (e.g. 'Prefer bowls over sandwiches').
        notes: Extra notes (e.g. 'Pick Office favorite restaurants').
        auto_order: If true, the agent picks and orders without asking
                   for confirmation. If false (default), the agent shows
                   its picks and waits for the user to confirm.
    """
    global FOOD_PREFS
    if yes is not None:
        FOOD_PREFS["yes"] = yes
    if no is not None:
        FOOD_PREFS["no"] = no
    if style is not None:
        FOOD_PREFS["style"] = style
    if notes is not None:
        FOOD_PREFS["notes"] = notes
    if auto_order is not None:
        FOOD_PREFS["auto_order"] = auto_order
    PREFS_FILE.write_text(json.dumps(FOOD_PREFS, indent=2) + "\n")
    return f"Preferences updated: {json.dumps(FOOD_PREFS)}"


# ------------------------------------------------------------------
# Shutdown
# ------------------------------------------------------------------


@mcp.tool()
def logout() -> str:
    """Close the browser session and log out."""
    b = _get_browser()
    b.close()
    return "Logged out and browser closed."


if __name__ == "__main__":
    mcp.run(transport="stdio")
