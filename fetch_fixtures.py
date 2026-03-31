"""Fetch HTML fixtures from Relish for offline sanity testing."""
import json
import os
from pathlib import Path
from time import sleep

from selenium.webdriver.common.by import By

from relish_browser import RelishBrowser
from relish_models import LoginState

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MFA_CODE_FILE = Path(__file__).parent / "mfa_code.txt"
STATUS_FILE = Path(__file__).parent / "probe_status.txt"


def save(name: str, html: str) -> None:
    path = FIXTURES_DIR / name
    path.write_text(html)
    print(f"  Saved {name} ({len(html):,} chars)", flush=True)


def main():
    for f in [MFA_CODE_FILE, STATUS_FILE]:
        if f.exists():
            f.unlink()

    FIXTURES_DIR.mkdir(exist_ok=True)

    creds = json.loads((Path(__file__).parent / ".credentials").read_text())
    b = RelishBrowser(headless=True)

    try:
        state = b.login(creds["email"], creds["password"])
        if state == LoginState.AWAITING_MFA:
            print("MFA needed — aborting. Run after cookies are set.", flush=True)
            return
        print("Logged in\n", flush=True)
        driver = b._driver

        # 1. Schedule page (today)
        print("1. Schedule (today)", flush=True)
        driver.get("https://relish.ezcater.com/schedule")
        sleep(4)
        save("schedule_today.html", driver.page_source)

        # 2. Schedule page (Wednesday 4/1)
        print("2. Schedule (Wednesday 4/1)", flush=True)
        driver.get("https://relish.ezcater.com/schedule/2026-04-01")
        sleep(4)
        save("schedule_wed.html", driver.page_source)

        # 3. Restaurant menu — The Halal Guys (entry 1232291)
        print("3. Menu — The Halal Guys", flush=True)
        driver.get("https://relish.ezcater.com/schedule_entries/1232291")
        sleep(4)
        save("menu_halal_guys.html", driver.page_source)

        # 4. Item modal — Chicken & Beef Gyro Plate (click to open)
        print("4. Item modal — Chicken & Beef Gyro Plate", flush=True)
        links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='menu_item_id=26308104']"
        )
        for link in links:
            if link.is_displayed():
                link.click()
                break
        sleep(3)
        save("item_modal_gyro.html", driver.page_source)

        # 5. Restaurant menu — 11:11 Health Bar (entry 1232289)
        print("5. Menu — 11:11 Health Bar", flush=True)
        driver.get("https://relish.ezcater.com/schedule_entries/1232289")
        sleep(4)
        save("menu_health_bar.html", driver.page_source)

        # 6. Item modal — Acai Bowl (click to open)
        print("6. Item modal — Acai Bowl", flush=True)
        links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='menu_item_id=22409925']"
        )
        for link in links:
            if link.is_displayed():
                link.click()
                break
        sleep(3)
        save("item_modal_acai.html", driver.page_source)

        # 7. Orders page
        print("7. Orders page", flush=True)
        driver.get("https://relish.ezcater.com/customer_orders")
        sleep(3)
        save("orders.html", driver.page_source)

        # 8. Order detail — Wednesday order
        print("8. Order detail", flush=True)
        cards = driver.find_elements(By.CSS_SELECTOR, "[id^='customer_order_']")
        if cards:
            oid = cards[0].get_attribute("id").replace("customer_order_", "")
            driver.get(
                f"https://relish.ezcater.com/customer_orders/{oid}/order_details"
            )
            sleep(3)
            save("order_detail.html", driver.page_source)
        else:
            print("  (no orders found, skipping)", flush=True)

        print("\nDone — all fixtures saved to fixtures/", flush=True)

    except Exception as ex:
        import traceback
        traceback.print_exc()
    finally:
        b.close()
        for f in [MFA_CODE_FILE, STATUS_FILE]:
            if f.exists():
                f.unlink()


if __name__ == "__main__":
    main()
