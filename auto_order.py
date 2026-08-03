"""Deterministic weekday backup auto-order for Relish.

Run by cron (installed conversationally via the setup_auto_order_cron
MCP tool). Behavior: if today already has an order, exit quietly.
Otherwise pick ONE item for TODAY ONLY — matching .food_preferences.json
and always within the subsidy — and order it. No AI is involved at
runtime: the picking logic is a plain heuristic, so a scheduled run can
never go off-script.

Usage:
    python auto_order.py            # order if today is unordered
    python auto_order.py --dry-run  # show the pick, order nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from relish_browser import RelishBrowser
from relish_models import DaySchedule, LoginState, MenuItem, Restaurant

PROJECT_DIR = Path(__file__).parent
CREDENTIALS_FILE = PROJECT_DIR / ".credentials"
PREFS_FILE = PROJECT_DIR / ".food_preferences.json"
LOCK_FILE = PROJECT_DIR / ".auto_order.lock"

TAX_RATE = 0.07  # same estimate as the check_subsidy tool


def _keywords(phrases: list[str]) -> set[str]:
    """Lowercase content words from preference phrases
    ('Mexican bowls' -> {'mexican', 'bowls'})."""
    words: set[str] = set()
    for phrase in phrases:
        words.update(
            w for w in re.findall(r"[a-z]+", str(phrase).lower()) if len(w) >= 3
        )
    return words


def _matches(text: str, keywords: set[str]) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _parse_dollars(text: str) -> float | None:
    m = re.search(r"(\d[\d,]*\.?\d*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def choose_order(
    schedule: DaySchedule, get_menu, prefs: dict
) -> tuple[Restaurant, MenuItem] | None:
    """Pick (restaurant, item) for today, or None if nothing fits.

    Restaurants are tried best-first: disliked keywords sink them, liked
    keywords and the 'Office favorite' tag float them. Within a
    restaurant the pick is the highest-priced liked item that fits the
    subsidy after estimated tax — "maximize food, never exceed the
    subsidy". Returns None when the subsidy can't be read: without a
    verified budget, the backup must never risk out-of-pocket cost.
    """
    if schedule.subsidy is None:
        return None
    subsidy = _parse_dollars(schedule.subsidy.remaining)
    if subsidy is None:
        return None

    yes = _keywords(prefs.get("yes", []))
    no = _keywords(prefs.get("no", []))

    def restaurant_rank(r: Restaurant) -> int:
        text = f"{r.name} {r.description}"
        rank = 0
        if _matches(text, no):
            rank -= 10
        if _matches(text, yes):
            rank += 2
        if "Office favorite" in r.tags:
            rank += 1
        return rank

    open_restaurants = sorted(
        (r for r in schedule.restaurants if not r.closed),
        key=restaurant_rank,
        reverse=True,
    )
    for restaurant in open_restaurants:
        best: MenuItem | None = None
        best_key: tuple[bool, float] | None = None
        for item in get_menu(restaurant.schedule_entry_id):
            text = f"{item.name} {item.description}"
            if _matches(text, no):
                continue
            price = _parse_dollars(item.price)
            if price is None or price * (1 + TAX_RATE) > subsidy:
                continue
            key = (_matches(text, yes), price)
            if best_key is None or key > best_key:
                best, best_key = item, key
        if best is not None:
            return restaurant, best
    return None


def run_backup_order(browser: RelishBrowser, prefs: dict, dry_run: bool) -> str:
    """Order for TODAY ONLY if nothing is ordered yet. Returns a summary."""
    schedule = browser.get_schedule()

    if schedule.my_orders:
        existing = ", ".join(o.restaurant for o in schedule.my_orders)
        return (
            f"Already ordered for {schedule.date_label} ({existing}) — "
            "nothing to do."
        )
    if not any(not r.closed for r in schedule.restaurants):
        return f"No open restaurants for {schedule.date_label} — nothing to do."

    pick = choose_order(schedule, browser.get_menu, prefs)
    if pick is None:
        return (
            f"Could not find an item that safely fits the subsidy for "
            f"{schedule.date_label} — no order placed."
        )
    restaurant, item = pick
    summary = f"{item.name} ({item.price}) from {restaurant.name}"
    if dry_run:
        return f"[DRY RUN] Would order: {summary}. Nothing was ordered."
    result = browser.place_order(restaurant.schedule_entry_id, item.menu_item_id)
    return f"Backup auto-order: {summary}. {result}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backup-order today's lunch if not already ordered."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be ordered without ordering",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
    )
    print(f"--- auto_order run {datetime.now():%Y-%m-%d %H:%M:%S} ---", flush=True)

    # fcntl is Unix-only; imported here so the module (run_backup_order)
    # stays importable everywhere.
    import fcntl

    lock_handle = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another auto_order run is already in progress — exiting.", flush=True)
        return 0

    if not CREDENTIALS_FILE.exists():
        print("No .credentials file — do first-time setup via the agent.", flush=True)
        return 1
    creds = json.loads(CREDENTIALS_FILE.read_text())

    prefs: dict = {}
    if PREFS_FILE.exists():
        try:
            prefs = json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            print(
                "Warning: bad .food_preferences.json — ordering without "
                "preferences.",
                flush=True,
            )

    browser = RelishBrowser(headless=True)
    try:
        state = browser.login(creds.get("email", ""), creds.get("password", ""))
        if state != LoginState.LOGGED_IN:
            print(
                "Login needs a fresh MFA code (saved cookies expired). Open "
                "the agent, run login + submit_mfa_code once, and the backup "
                "will work again.",
                flush=True,
            )
            return 1
        print(run_backup_order(browser, prefs, dry_run=args.dry_run), flush=True)
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    finally:
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
