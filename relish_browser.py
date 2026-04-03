"""Selenium browser automation for Relish by ezCater.

All browser interaction logic lives here. The MCP server calls these
methods and never touches Selenium directly.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from time import sleep
from typing import Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
)
from selenium_stealth import stealth

from relish_models import (
    DaySchedule,
    ItemChoice,
    ItemDetails,
    ItemOptionGroup,
    LoginState,
    MenuItem,
    Order,
    OrderStatus,
    Restaurant,
    Subsidy,
)

LOG = logging.getLogger("relish.browser")

BASE_URL = "https://relish.ezcater.com"
SCHEDULE_URL = f"{BASE_URL}/schedule"
ORDERS_URL = f"{BASE_URL}/customer_orders"

_PROJECT_DIR = Path(__file__).parent
COOKIES_FILE = _PROJECT_DIR / ".cookies.json"


class RelishBrowser:
    """Manages a single Selenium session against Relish."""

    def __init__(self, headless: bool = True, page_timeout: int = 20):
        self._headless = headless
        self._page_timeout = page_timeout
        self._driver: webdriver.Chrome | None = None
        self._state = LoginState.LOGGED_OUT

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _ensure_driver(self) -> webdriver.Chrome:
        if self._driver is None:
            self._driver = self._make_driver()
        return self._driver

    def _make_driver(self) -> webdriver.Chrome:
        opts = webdriver.ChromeOptions()
        if self._headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(self._page_timeout)
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        return driver

    def close(self) -> None:
        if self._driver:
            self._driver.quit()
            self._driver = None
        self._state = LoginState.LOGGED_OUT

    @property
    def state(self) -> LoginState:
        return self._state

    # ------------------------------------------------------------------
    # Cookie persistence
    # ------------------------------------------------------------------

    def _save_cookies(self) -> None:
        driver = self._ensure_driver()
        cookies = driver.get_cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        LOG.info("Saved %d cookies to %s", len(cookies), COOKIES_FILE)

    def _load_cookies(self) -> bool:
        """Load saved cookies and return True if the file existed."""
        if not COOKIES_FILE.exists():
            return False
        try:
            cookies = json.loads(COOKIES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        if not cookies:
            return False

        driver = self._ensure_driver()
        # Must navigate to a page on the domain before setting cookies
        driver.get(BASE_URL)
        sleep(2)
        for cookie in cookies:
            # Selenium rejects some cookie fields; strip unsupported ones
            cookie.pop("sameSite", None)
            cookie.pop("storeId", None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        LOG.info("Loaded %d cookies from %s", len(cookies), COOKIES_FILE)
        return True

    def _is_logged_in(self) -> bool:
        """Check if the current page indicates a logged-in session."""
        driver = self._ensure_driver()
        url = driver.current_url
        if "login" in url or "sign_in" in url:
            return False
        body = driver.find_element(By.TAG_NAME, "body").text[:500].lower()
        return "sign in" not in body or "hi," in body

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> LoginState:
        """Log in to Relish. Tries saved cookies first to skip MFA.

        Returns AWAITING_MFA if a fresh MFA code is needed — caller
        must then call submit_mfa_code().
        """
        driver = self._ensure_driver()

        # Try cookies first — avoids MFA entirely if "remember 30 days" is active
        if COOKIES_FILE.exists():
            LOG.info("Trying saved cookies")
            self._load_cookies()
            driver.get(SCHEDULE_URL)
            sleep(4)
            if self._is_logged_in():
                self._state = LoginState.LOGGED_IN
                LOG.info("Logged in via saved cookies (no MFA needed)")
                return self._state
            LOG.info("Saved cookies expired or invalid, doing full login")

        # Full login flow
        LOG.info("Navigating to login page")
        driver.get(SCHEDULE_URL)
        sleep(3)

        # Step 1 — email
        try:
            email_field = self._wait_for(By.ID, "identity_email")
            email_field.send_keys(email)
            driver.find_element(By.NAME, "commit").click()
        except (TimeoutException, NoSuchElementException) as exc:
            raise RuntimeError(
                "Could not find the email field on the login page. "
                "The site layout may have changed."
            ) from exc
        LOG.info("Submitted email")
        sleep(4)

        # Step 2 — password (Auth0 page)
        try:
            pw_field = self._wait_for(By.ID, "password")
            self._js_set_value(pw_field, password)
            driver.find_element(By.NAME, "action").click()
        except (TimeoutException, NoSuchElementException) as exc:
            raise RuntimeError(
                "Could not find the password field on the login page. "
                "The site layout may have changed."
            ) from exc
        LOG.info("Submitted password")
        sleep(5)

        # Step 3 — check for MFA
        url = driver.current_url
        if "mfa" in url or "challenge" in url or "verification" in url:
            LOG.info("MFA page detected")
            self._state = LoginState.AWAITING_MFA
            return self._state

        self._state = LoginState.LOGGED_IN
        self._save_cookies()
        LOG.info("Logged in (no MFA required)")
        return self._state

    def submit_mfa_code(self, code: str) -> LoginState:
        """Submit an MFA verification code. Must be called after login()
        returns AWAITING_MFA.
        """
        if self._state != LoginState.AWAITING_MFA:
            raise RuntimeError(
                f"Cannot submit MFA code in state {self._state}. "
                "Call login() first."
            )
        driver = self._ensure_driver()

        try:
            code_field = driver.find_element(By.ID, "code")
        except NoSuchElementException as exc:
            raise RuntimeError(
                "Could not find the MFA code field on the page. "
                "The site layout may have changed."
            ) from exc
        code_field.clear()
        code_field.send_keys(code)

        # Check "remember this device for 30 days"
        try:
            cb = driver.find_element(By.ID, "rememberBrowser")
            if not cb.is_selected():
                driver.execute_script("arguments[0].click()", cb)
        except NoSuchElementException:
            pass

        try:
            driver.find_element(
                By.CSS_SELECTOR, "button[name='action'][value='default']"
            ).click()
        except NoSuchElementException as exc:
            raise RuntimeError(
                "Could not find the MFA submit button on the page. "
                "The site layout may have changed."
            ) from exc
        sleep(6)

        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "invalid" in body or "expired" in body:
            LOG.warning("MFA code rejected")
            return LoginState.AWAITING_MFA

        url = driver.current_url
        if "mfa" in url or "challenge" in url:
            LOG.warning("Still on MFA page")
            return LoginState.AWAITING_MFA

        self._state = LoginState.LOGGED_IN
        self._save_cookies()
        LOG.info("MFA accepted — logged in, cookies saved")
        return self._state

    # ------------------------------------------------------------------
    # Schedule & Restaurants
    # ------------------------------------------------------------------

    def get_schedule(self, date: str | None = None) -> DaySchedule:
        """Get the schedule for a given date (YYYY-MM-DD) or today."""
        self._require_logged_in()
        driver = self._ensure_driver()

        url = f"{SCHEDULE_URL}/{date}" if date else SCHEDULE_URL
        driver.get(url)
        sleep(4)

        return self._parse_schedule_page(driver)

    def get_menu(self, schedule_entry_id: str) -> list[MenuItem]:
        """Get the menu for a specific restaurant schedule entry."""
        self._require_logged_in()
        driver = self._ensure_driver()

        driver.get(f"{BASE_URL}/schedule_entries/{schedule_entry_id}")
        sleep(4)

        return self._parse_menu_page(driver)

    def get_all_menus(self, date: str | None = None) -> dict[str, list[MenuItem]]:
        """Get menus for ALL restaurants on a given date.

        Returns a dict of {restaurant_name: [MenuItem, ...]}.
        """
        schedule = self.get_schedule(date)
        all_menus: dict[str, list[MenuItem]] = {}
        for restaurant in schedule.restaurants:
            if restaurant.closed:
                continue
            items = self.get_menu(restaurant.schedule_entry_id)
            all_menus[restaurant.name] = items
        return all_menus

    def save_menus_to_file(
        self,
        date: str | None = None,
        filepath: str | None = None,
    ) -> str:
        """Get all menus for a date and save them to a markdown file.

        Returns the filepath that was written.
        """
        all_menus = self.get_all_menus(date)
        date_label = date or "today"

        if filepath is None:
            safe_date = (date or "today").replace("-", "")
            filepath = str(_PROJECT_DIR / f"menus_{safe_date}.md")

        lines = [f"# All Available Menus — {date_label}\n"]
        for restaurant, items in all_menus.items():
            lines.append(f"\n## {restaurant} ({len(items)} items)\n")
            for item in items:
                cat = f" [{item.category}]" if item.category else ""
                desc = f" — {item.description}" if item.description else ""
                lines.append(
                    f"- **{item.name}** {item.price}{cat}{desc}"
                    f"  (id:{item.menu_item_id})"
                )

        Path(filepath).write_text("\n".join(lines) + "\n")
        LOG.info("Saved %d restaurant menus to %s", len(all_menus), filepath)
        return filepath

    # ------------------------------------------------------------------
    # Item details & customization
    # ------------------------------------------------------------------

    def get_item_options(
        self, schedule_entry_id: str, menu_item_id: str
    ) -> ItemDetails:
        """Open a menu item's customization modal and parse all options.

        Returns an ItemDetails with all option groups (sizes, sides,
        toppings, sauces, etc.) and their choices with prices.
        """
        self._require_logged_in()
        driver = self._ensure_driver()

        driver.get(f"{BASE_URL}/schedule_entries/{schedule_entry_id}")
        sleep(4)

        # Click the item to open the reveal modal
        links = driver.find_elements(
            By.CSS_SELECTOR, f"a[href*='menu_item_id={menu_item_id}']"
        )
        for link in links:
            if link.is_displayed():
                link.click()
                break
        else:
            raise ValueError(
                f"Menu item {menu_item_id} not found on page for "
                f"schedule entry {schedule_entry_id}."
            )
        sleep(3)

        return self._parse_item_modal(driver, menu_item_id)

    def _parse_item_modal(
        self, driver: webdriver.Chrome, menu_item_id: str
    ) -> ItemDetails:
        """Parse the open item customization modal."""
        modal = None
        for sel in [
            "#menu-item-modal",
            ".reveal.menu-modal",
            ".option-form-container",
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                modal = els[0]
                break
        if not modal:
            raise RuntimeError("Item modal not found after clicking item link.")

        # Item name, price, description from the top of the modal
        name = ""
        price = ""
        description = ""
        try:
            name_el = modal.find_element(
                By.CSS_SELECTOR, "h3, h4, .menu-item-name, strong"
            )
            name = name_el.text.strip()
        except NoSuchElementException:
            pass
        try:
            price_el = modal.find_element(
                By.CSS_SELECTOR, ".menu-item-price, .price"
            )
            price = price_el.text.strip()
        except NoSuchElementException:
            pass
        try:
            desc_el = modal.find_element(
                By.CSS_SELECTOR, ".menu-item-description:not(.prompt), p"
            )
            desc_text = desc_el.text.strip()
            if desc_text and desc_text != name and not desc_text.startswith("$"):
                description = desc_text
        except NoSuchElementException:
            pass

        # Parse option groups
        option_groups: list[ItemOptionGroup] = []

        # 1. Size options (radio buttons)
        size_radios = modal.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name='order_item[size_index]']"
        )
        if size_radios:
            choices: list[ItemChoice] = []
            for radio in size_radios:
                radio_price = radio.get_attribute("data-price") or ""
                radio_value = radio.get_attribute("value") or ""
                selected = radio.get_attribute("checked") is not None
                label_text = ""
                try:
                    parent = radio.find_element(By.XPATH, "./..")
                    label_text = parent.text.strip().split("\n")[0].strip()
                    if label_text.startswith("$"):
                        label_text = ""
                except Exception:
                    pass
                if not label_text:
                    label_text = f"Size {radio_value}"
                choices.append(ItemChoice(
                    label=label_text,
                    value=radio_value,
                    price=f"${radio_price}" if radio_price else "",
                    selected=selected,
                ))
            option_groups.append(ItemOptionGroup(
                name="Sizes",
                required=True,
                input_type="radio",
                group_id="order_item[size_index]",
                choices=choices,
            ))

        # 2. Checkbox option groups
        headers = modal.find_elements(
            By.CSS_SELECTOR, ".menu-item-section-header"
        )
        for header in headers:
            try:
                strong = header.find_element(By.TAG_NAME, "strong")
                group_name = strong.text.strip()
            except NoSuchElementException:
                continue

            if group_name.lower() in ("sizes", "notes", ""):
                continue

            required = False
            try:
                span = header.find_element(By.TAG_NAME, "span")
                required = "required" in span.text.lower()
            except NoSuchElementException:
                pass

            # Find the choices list that follows this header
            parent_section = header.find_element(By.XPATH, "./..")
            checkboxes = parent_section.find_elements(
                By.CSS_SELECTOR, "input[type='checkbox']"
            )
            # Also check for radio buttons in non-size groups
            radios = parent_section.find_elements(
                By.CSS_SELECTOR,
                "input[type='radio']:not([name='order_item[size_index]'])"
            )
            inputs = checkboxes or radios
            input_type = "checkbox" if checkboxes else "radio"

            if not inputs:
                try:
                    sibling_section = header.find_element(
                        By.XPATH, "./following-sibling::*[1]"
                    )
                except NoSuchElementException:
                    continue
                checkboxes = sibling_section.find_elements(
                    By.CSS_SELECTOR, "input[type='checkbox']"
                )
                radios = sibling_section.find_elements(
                    By.CSS_SELECTOR,
                    "input[type='radio']:not([name='order_item[size_index]'])"
                )
                inputs = checkboxes or radios
                input_type = "checkbox" if checkboxes else "radio"

            if not inputs:
                continue

            group_id = inputs[0].get_attribute("name") or ""
            min_choices = 0
            max_choices = 0
            try:
                choices_list = parent_section.find_element(
                    By.CSS_SELECTOR, ".menu_choices_list"
                )
                mc = choices_list.get_attribute("data-minimum-choices-allowed")
                if mc:
                    min_choices = int(mc)
                xc = choices_list.get_attribute("data-maximum-choices-allowed")
                if xc:
                    max_choices = int(xc)
            except (NoSuchElementException, ValueError):
                pass

            choices = []
            for inp in inputs:
                inp_price = inp.get_attribute("data-price") or ""
                inp_value = inp.get_attribute("value") or ""
                selected = inp.is_selected()
                label_text = ""
                try:
                    label_el = inp.find_element(By.XPATH, "./ancestor::label")
                    label_text = label_el.text.strip()
                    label_lines = [
                        l.strip() for l in label_text.split("\n") if l.strip()
                    ]
                    label_text = label_lines[0] if label_lines else ""
                    if label_text.startswith("+") or label_text.startswith("$"):
                        label_text = label_lines[1] if len(label_lines) > 1 else ""
                except Exception:
                    pass
                if not label_text:
                    try:
                        sib = inp.find_element(
                            By.XPATH, "./following-sibling::*[1]"
                        )
                        label_text = sib.text.strip().split("\n")[0]
                    except Exception:
                        label_text = f"Choice {inp_value}"

                price_str = ""
                try:
                    if inp_price and float(inp_price) > 0:
                        price_str = f"${inp_price}"
                except ValueError:
                    price_str = inp_price

                choices.append(ItemChoice(
                    label=label_text,
                    value=inp_value,
                    price=price_str,
                    selected=selected,
                ))

            option_groups.append(ItemOptionGroup(
                name=group_name,
                required=required,
                input_type=input_type,
                group_id=group_id,
                choices=choices,
                min_choices=min_choices,
                max_choices=max_choices,
            ))

        return ItemDetails(
            name=name,
            price=price,
            description=description,
            menu_item_id=menu_item_id,
            option_groups=option_groups,
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_orders(self, tab: str = "upcoming") -> list[Order]:
        """Get orders. tab can be 'upcoming' or 'completed'."""
        self._require_logged_in()
        driver = self._ensure_driver()

        driver.get(ORDERS_URL)
        sleep(3)

        if tab == "completed":
            try:
                completed_tab = driver.find_element(
                    By.XPATH, "//a[contains(text(),'Completed')]"
                )
                completed_tab.click()
                sleep(2)
            except NoSuchElementException:
                pass

        return self._parse_orders_page(driver)

    def _clear_cart(self, driver) -> None:
        """Remove all items currently in the cart via AJAX DELETE."""
        csrf = driver.execute_script(
            "var m = document.querySelector('meta[name=\"csrf-token\"]');"
            "return m ? m.content : '';"
        )
        remove_links = driver.find_elements(
            By.CSS_SELECTOR, "div.cart-action-links a[data-method='delete']"
        )
        for link in remove_links:
            href = link.get_attribute("href")
            if href:
                driver.execute_script(
                    "fetch(arguments[0], {"
                    "  method: 'DELETE',"
                    "  headers: {"
                    "    'X-CSRF-Token': arguments[1],"
                    "    'X-Requested-With': 'XMLHttpRequest'"
                    "  }"
                    "})",
                    href, csrf,
                )
                sleep(1)
        if remove_links:
            sleep(2)
            driver.refresh()
            sleep(3)

    def place_order(
        self,
        schedule_entry_id: str,
        menu_item_id: str,
        options: dict[str, list[str]] | None = None,
        size_index: int | None = None,
        notes: str = "",
    ) -> str:
        """Place an order: open the restaurant menu, click the item,
        apply customization selections, and submit.

        Args:
            schedule_entry_id: Restaurant schedule entry ID.
            menu_item_id: Menu item ID.
            options: Dict of {group_id: [choice_value, ...]} from
                     get_item_options. Keys are group_id strings,
                     values are lists of choice value strings.
            size_index: Size selection (0=Small, 1=Regular, etc.).
                       Defaults to 0 (smallest) if not specified.
            notes: Optional order notes string.
        """
        self._require_logged_in()
        driver = self._ensure_driver()

        # Step 1: Go to the restaurant menu page
        driver.get(f"{BASE_URL}/schedule_entries/{schedule_entry_id}")
        sleep(4)

        # Step 1b: Clear any existing cart items
        self._clear_cart(driver)

        # Step 2: Click the item link to open the reveal modal
        item_link = None
        links = driver.find_elements(
            By.CSS_SELECTOR, f"a[href*='menu_item_id={menu_item_id}']"
        )
        for link in links:
            if link.is_displayed():
                item_link = link
                break

        if not item_link:
            return f"Could not find menu item {menu_item_id} on the page."

        item_link.click()
        sleep(3)

        # Step 2b: Apply customizations
        self._apply_item_options(driver, size_index, options, notes)

        # Step 3: Click "Add to cart" button inside the reveal modal
        add_btn = None
        try:
            add_btn = driver.find_element(By.ID, "add-to-cart-button")
        except NoSuchElementException:
            for sel in ["input[value*='Add to cart']", "input[type='submit']"]:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                if btns:
                    add_btn = btns[0]
                    break

        if not add_btn:
            return "Could not find 'Add to cart' button. The item modal may not have opened correctly."

        driver.execute_script("arguments[0].click()", add_btn)
        sleep(4)

        # Step 4: Click "Continue to checkout" — hidden in cart dropdown,
        # so use JS to find and follow the link href
        checkout_url = driver.execute_script(
            "var el = document.querySelector('div.continue-checkout a');"
            "return el ? el.href : '';"
        )
        if not checkout_url:
            return "Added to cart but no checkout link found. The cart dropdown may not have appeared."

        driver.get(checkout_url)
        sleep(4)

        # Step 5: On the review page, click "Place your order" button
        # It lives inside a <turbo-frame> with a class like place-order-*-btn
        final_submitted = False
        try:
            place_btn = driver.execute_script(
                "var btn = document.querySelector("
                "'turbo-frame button[type=\"submit\"]'"
                ") || document.querySelector("
                "'button[class*=\"place-order\"]'"
                ") || document.querySelector("
                "'button[data-disable-with*=\"Placing\"]'"
                ");"
                "return btn;"
            )
            if place_btn:
                driver.execute_script("arguments[0].click()", place_btn)
                final_submitted = True
                sleep(5)
        except Exception as ex:
            LOG.warning("Place order click error: %s", ex)

        if not final_submitted:
            for selector in [
                "button[type='submit']",
                "input[type='submit']",
            ]:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in btns:
                        txt = (
                            btn.get_attribute("value") or btn.text or ""
                        ).strip().lower()
                        if "place" in txt:
                            driver.execute_script("arguments[0].click()", btn)
                            final_submitted = True
                            sleep(5)
                            break
                    if final_submitted:
                        break
                except Exception:
                    continue

        result_text = driver.execute_script("return document.body.innerText")

        if final_submitted:
            summary = self._extract_order_summary(driver, result_text)
            return f"Order placed successfully. {summary}"
        lines = self._filter_page_lines(result_text)
        return "On review page but could not submit order.\n" + "\n".join(lines[:10])

    def cancel_order(self, order_id: str) -> str:
        """Cancel an order by its ID. Goes through the orders page
        since the cancel link uses AJAX (data-remote).
        """
        self._require_logged_in()
        driver = self._ensure_driver()

        driver.get(ORDERS_URL)
        sleep(3)

        # Extract order info from the card before we cancel it
        restaurant = ""
        items = ""
        try:
            card = driver.find_element(By.ID, f"customer_order_{order_id}")
            card_text = card.text.strip()
            card_lines = [l.strip() for l in card_text.split('\n') if l.strip()]
            if card_lines:
                restaurant = card_lines[0]
            item_els = card.find_elements(By.CSS_SELECTOR, ".card-ordered-item")
            if not item_els:
                item_els = card.find_elements(
                    By.CSS_SELECTOR, ".card-item-description"
                )
            item_names = [el.text.strip() for el in item_els if el.text.strip()]
            items = ", ".join(item_names) if item_names else ""
        except (NoSuchElementException, StaleElementReferenceException):
            pass

        # Click the cancel link
        try:
            cancel_link = driver.find_element(
                By.CSS_SELECTOR,
                f"#customer_order_{order_id} a[href*='confirm_cancel']"
            )
            driver.execute_script("arguments[0].click()", cancel_link)
            sleep(3)
        except NoSuchElementException:
            return f"Could not find cancel button for order {order_id}."

        # Confirm the cancellation
        try:
            for selector in [
                "a[data-method='delete']",
                "a.button[href*='cancel']",
                "button[type='submit']",
                "input[type='submit']",
            ]:
                btns = driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in btns:
                    txt = btn.text.strip().lower()
                    if "cancel" in txt or "yes" in txt or "confirm" in txt:
                        driver.execute_script("arguments[0].click()", btn)
                        sleep(3)
                        break
                else:
                    continue
                break
        except Exception:
            pass

        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        success = "canceled" in body or "cancelled" in body

        detail = f" ({restaurant} — {items})" if restaurant and items else ""
        if success:
            return f"Order {order_id} canceled successfully.{detail}"
        return f"Order {order_id} cancel requested (could not confirm success).{detail}"

    # ------------------------------------------------------------------
    # Subsidy
    # ------------------------------------------------------------------

    def get_subsidy(self, date: str | None = None) -> Subsidy | None:
        """Get subsidy info for a date. Reuses schedule page parsing."""
        schedule = self.get_schedule(date)
        return schedule.subsidy

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_schedule_page(self, driver: webdriver.Chrome) -> DaySchedule:
        inner_text = driver.execute_script("return document.body.innerText")
        html = driver.page_source

        # Date from title
        title = driver.title
        date_label = title.replace("Relish - Place an Order for ", "").strip()

        # Current date from URL
        url = driver.current_url
        date_match = re.search(r"/schedule/(\d{4}-\d{2}-\d{2})", url)
        date_str = date_match.group(1) if date_match else "today"

        # Subsidy — extract the dollar amount from the widget
        subsidy = None
        subsidy_el = driver.find_elements(By.CSS_SELECTOR, "div.subsidy-widget-right")
        if subsidy_el:
            raw = subsidy_el[0].text.strip()
            if not raw:
                raw = driver.execute_script(
                    "return arguments[0].textContent", subsidy_el[0]
                ).strip()
            if not raw:
                raw = driver.execute_script(
                    "return arguments[0].innerText", subsidy_el[0]
                ).strip()
            # Extract just the dollar amount from text like "Lunch\n$16.05"
            amount_match = re.search(r"\$[\d,.]+", raw)
            amount = amount_match.group(0) if amount_match else raw
            # Extract meal type from non-dollar lines
            meal_type = "Lunch"
            for line in raw.split("\n"):
                line = line.strip()
                if line and not line.startswith("$") and not re.match(r"[\d.,]+", line):
                    meal_type = line
                    break
            subsidy_label_els = driver.find_elements(By.XPATH, "//*[contains(text(),'subsidy')]")
            label = "Company subsidy"
            for el in subsidy_label_els:
                txt = el.text.strip()
                if txt and "subsid" in txt.lower() and len(txt) < 50:
                    label = txt
                    break
            subsidy = Subsidy(label=label, remaining=amount, meal_type=meal_type)

        # Available dates
        available_dates: list[dict[str, str]] = []
        date_links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='/schedule/'], a[href='/schedule']"
        )
        for dl in date_links:
            href = dl.get_attribute("href") or ""
            text = dl.text.strip()
            if text and "/schedule" in href and len(text) < 30:
                dm = re.search(r"/schedule/(\d{4}-\d{2}-\d{2})", href)
                d = dm.group(1) if dm else "today"
                available_dates.append({"date": d, "label": text})

        # My orders (on schedule page — the tracking cards)
        my_orders: list[Order] = []
        lines = [l.strip() for l in inner_text.split('\n') if l.strip()]
        # Parse order status from visible text
        tracking_cards = driver.find_elements(
            By.CSS_SELECTOR, "[class*='tracking-card'], [class*='order-progress']"
        )
        for card in tracking_cards:
            try:
                card_text = card.text.strip()
                if not card_text:
                    continue
                card_lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                name = card_lines[0] if card_lines else "Unknown"
                if name.lower() in ("my orders", "lunch options", ""):
                    continue
                status_str = card_lines[1] if len(card_lines) > 1 else "Unknown"
                status = OrderStatus.UNKNOWN
                for s in OrderStatus:
                    if s.value.lower() in status_str.lower():
                        status = s
                        break
                # Find order ID from nearby link
                oid = ""
                try:
                    link = card.find_element(By.CSS_SELECTOR, "a[href*='customer_orders']")
                    href = link.get_attribute("href") or ""
                    oid_m = re.search(r"customer_orders/(\d+)", href)
                    oid = oid_m.group(1) if oid_m else ""
                except NoSuchElementException:
                    pass
                my_orders.append(Order(
                    order_id=oid,
                    restaurant=name,
                    delivery_time="",
                    price="",
                    status=status,
                ))
            except StaleElementReferenceException:
                continue

        # Restaurants
        restaurants: list[Restaurant] = []
        entry_links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='/schedule_entries/']"
        )
        for link in entry_links:
            href = link.get_attribute("href") or ""
            eid_m = re.search(r"/schedule_entries/(\d+)", href)
            if not eid_m:
                continue
            eid = eid_m.group(1)

            card_text = link.text.strip()
            if not card_text:
                continue

            card_lines = [l.strip() for l in card_text.split('\n') if l.strip()]
            # Filter out font-test junk
            card_lines = [l for l in card_lines if 'mmMwWLli' not in l and 'word word' not in l]

            name = ""
            desc = ""
            order_by = ""
            delivery_at = ""
            meals_left = ""
            tags: list[str] = []
            closed = False

            for line in card_lines:
                if "Time's up" in line:
                    closed = True
                elif re.match(r"^\d+ meals? left$", line):
                    meals_left = line
                elif re.match(r"^\d+$", line) and not meals_left:
                    continue
                elif line.startswith("Order by"):
                    order_by = line.replace("Order by ", "")
                elif line.startswith("Delivery at"):
                    delivery_at = line.replace("Delivery at ", "")
                elif line.startswith("Stopped accepting"):
                    closed = True
                elif line in ("New", "Office favorite"):
                    tags.append(line)
                elif not name:
                    name = line
                elif not desc:
                    desc = line

            if name:
                restaurants.append(Restaurant(
                    name=name,
                    description=desc,
                    schedule_entry_id=eid,
                    order_by=order_by,
                    delivery_at=delivery_at,
                    meals_left=meals_left,
                    tags=tags,
                    closed=closed,
                ))

        return DaySchedule(
            date=date_str,
            date_label=date_label,
            subsidy=subsidy,
            my_orders=my_orders,
            restaurants=restaurants,
            available_dates=available_dates,
        )

    def _parse_menu_page(self, driver: webdriver.Chrome) -> list[MenuItem]:
        sleep(2)

        # All menu items are <a> links with menu_item_id in the href
        item_links = driver.find_elements(
            By.CSS_SELECTOR, "a[href*='menu_item_id']"
        )

        seen: set[str] = set()
        items: list[MenuItem] = []

        for link in item_links:
            href = link.get_attribute("href") or ""
            item_id_m = re.search(r"menu_item_id=(\d+)", href)
            if not item_id_m:
                continue
            item_id = item_id_m.group(1)
            if item_id in seen:
                continue
            seen.add(item_id)

            # Category from URL param
            cat_m = re.search(r"category_name=([^&]+)", href)
            category = ""
            if cat_m:
                from urllib.parse import unquote_plus
                category = unquote_plus(cat_m.group(1))

            # Item name + price from the link's visible text,
            # or from nearby item-details element
            text = link.text.strip()
            if not text:
                try:
                    details = link.find_element(
                        By.CSS_SELECTOR, "[class*='item-details'], [class*='item-name']"
                    )
                    text = details.text.strip()
                except NoSuchElementException:
                    text = driver.execute_script(
                        "return arguments[0].innerText", link
                    ).strip()

            lines = [l.strip() for l in text.split('\n') if l.strip()]
            name = ""
            price = ""
            description = ""
            tags: list[str] = []

            for line in lines:
                if line.startswith("$"):
                    price = line
                elif line.startswith("Ordered"):
                    continue
                elif line in (
                    "Halal", "Gluten-free", "Vegetarian", "Vegan",
                    "Spicy", "Kosher", "New",
                ):
                    tags.append(line)
                elif not name:
                    name = line
                elif not description and len(line) > 5:
                    description = line

            if not name:
                continue

            if tags:
                tag_str = ", ".join(tags)
                description = f"[{tag_str}] {description}".strip()

            items.append(MenuItem(
                name=name,
                menu_item_id=item_id,
                price=price,
                description=description,
                category=category,
                order_url=href,
            ))

        return items

    def _parse_orders_page(self, driver: webdriver.Chrome) -> list[Order]:
        orders: list[Order] = []
        cards = driver.find_elements(By.CSS_SELECTOR, "[id^='customer_order_']")

        for card in cards:
            try:
                oid_attr = card.get_attribute("id") or ""
                oid = oid_attr.replace("customer_order_", "")

                text = card.text.strip()
                lines = [l.strip() for l in text.split('\n') if l.strip()]

                restaurant = lines[0] if lines else "Unknown"
                delivery = ""
                price = ""
                item_names: list[str] = []
                status = OrderStatus.UNKNOWN

                for line in lines[1:]:
                    if "Delivery on" in line or "Delivered" in line:
                        delivery = line
                    elif line.startswith("$"):
                        price = line
                    elif "item" in line.lower():
                        continue
                    elif line in ("Cancel order", "Edit order", "Modify"):
                        continue
                    elif line not in (restaurant, delivery, price):
                        for s in OrderStatus:
                            if s.value.lower() in line.lower():
                                status = s
                                break
                        else:
                            if line and not line.startswith("Cancel") and not line.startswith("Edit"):
                                item_names.append(line)

                orders.append(Order(
                    order_id=oid,
                    restaurant=restaurant,
                    delivery_time=delivery,
                    price=price,
                    items=item_names,
                    status=status,
                ))
            except StaleElementReferenceException:
                continue

        return orders

    def _apply_item_options(
        self,
        driver: webdriver.Chrome,
        size_index: int | None,
        options: dict[str, list[str]] | None,
        notes: str,
    ) -> None:
        """Select sizes, checkboxes, and notes inside the open item modal."""
        # Size selection
        if size_index is not None:
            try:
                radio = driver.find_element(
                    By.CSS_SELECTOR,
                    f"input[type='radio'][name='order_item[size_index]']"
                    f"[value='{size_index}']"
                )
                driver.execute_script("arguments[0].click()", radio)
                sleep(0.5)
            except NoSuchElementException:
                LOG.warning("Size index %d not found", size_index)

        # Checkbox/radio option selections
        if options:
            for group_id, values in options.items():
                for val in values:
                    try:
                        inp = driver.find_element(
                            By.CSS_SELECTOR,
                            f"input[name='{group_id}'][value='{val}']"
                        )
                        if not inp.is_selected():
                            driver.execute_script("arguments[0].click()", inp)
                            sleep(0.3)
                    except NoSuchElementException:
                        LOG.warning(
                            "Option %s value %s not found", group_id, val
                        )

        # Auto-select first option for required groups with no selection
        self._auto_fill_required_groups(driver, options)

        # Notes
        if notes:
            try:
                notes_field = driver.find_element(
                    By.CSS_SELECTOR,
                    "textarea[name='order_item[notes]'], #order_item_notes"
                )
                notes_field.clear()
                notes_field.send_keys(notes)
            except NoSuchElementException:
                LOG.warning("Notes field not found")

    def _auto_fill_required_groups(
        self,
        driver: webdriver.Chrome,
        explicit_options: dict[str, list[str]] | None,
    ) -> None:
        """Auto-select the first choice for any required option group that
        has no selection yet. Skips groups already handled by explicit_options."""
        modal = None
        for sel in ["#menu-item-modal", ".reveal.menu-modal", ".option-form-container"]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                modal = els[0]
                break
        if not modal:
            return

        headers = modal.find_elements(By.CSS_SELECTOR, ".menu-item-section-header")
        for header in headers:
            try:
                span = header.find_element(By.TAG_NAME, "span")
                if "required" not in span.text.lower():
                    continue
            except NoSuchElementException:
                continue

            parent = header.find_element(By.XPATH, "./..")
            radios = parent.find_elements(
                By.CSS_SELECTOR,
                "input[type='radio']:not([name='order_item[size_index]'])"
            )
            checkboxes = parent.find_elements(
                By.CSS_SELECTOR, "input[type='checkbox']"
            )
            inputs = radios or checkboxes
            if not inputs:
                try:
                    sibling = header.find_element(By.XPATH, "./following-sibling::*[1]")
                except NoSuchElementException:
                    continue
                radios = sibling.find_elements(
                    By.CSS_SELECTOR,
                    "input[type='radio']:not([name='order_item[size_index]'])"
                )
                checkboxes = sibling.find_elements(
                    By.CSS_SELECTOR, "input[type='checkbox']"
                )
                inputs = radios or checkboxes

            if not inputs:
                continue

            try:
                group_id = inputs[0].get_attribute("name") or ""
                if explicit_options and group_id in explicit_options:
                    continue

                if any(inp.is_selected() for inp in inputs):
                    continue

                driver.execute_script("arguments[0].click()", inputs[0])
                LOG.info("Auto-selected first option for required group: %s", group_id)
                sleep(0.3)
            except (StaleElementReferenceException, NoSuchElementException):
                LOG.warning("Auto-fill: element went stale for a required group, skipping")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_page_lines(raw_text: str) -> list[str]:
        """Filter out font-test junk and empty lines from page innerText."""
        return [
            l.strip() for l in raw_text.split('\n')
            if l.strip()
            and 'word word' not in l
            and 'mmMwWLli' not in l
        ]

    def _extract_order_summary(
        self, driver: webdriver.Chrome, raw_text: str
    ) -> str:
        """Pull item name, restaurant, and price from a confirmation page."""
        parts: list[str] = []

        # Try structured elements first (order detail page)
        try:
            item_el = driver.find_element(
                By.CSS_SELECTOR, ".item-quantity-name, .card-ordered-item"
            )
            parts.append(item_el.text.strip())
        except NoSuchElementException:
            pass

        try:
            store_el = driver.find_element(
                By.CSS_SELECTOR, ".card-store-name, .caterer-logo img"
            )
            name = store_el.get_attribute("alt") or store_el.text.strip()
            name = name.replace("Logo for ", "")
            if name:
                parts.append(f"from {name}")
        except NoSuchElementException:
            pass

        try:
            total_el = driver.find_element(
                By.CSS_SELECTOR, ".last-header .text-right"
            )
            total = total_el.text.strip()
            if total:
                parts.append(f"total: {total}")
        except NoSuchElementException:
            pass

        if parts:
            return " ".join(parts)

        lines = self._filter_page_lines(raw_text)
        useful = [l for l in lines[:15] if l.lower() not in (
            "place an order", "my orders", "sign out", "my account",
            "account actions", "payment methods", "food preferences",
            "notifications", "delete account",
        ) and not l.startswith("Hi, ")]
        return "\n".join(useful[:5]) if useful else "(no details available)"

    def _require_logged_in(self) -> None:
        if self._state != LoginState.LOGGED_IN:
            raise RuntimeError(
                f"Not logged in (state={self._state}). Call login() first."
            )

    def _wait_for(self, by: str, value: str, timeout: int = 10) -> WebElement:
        driver = self._ensure_driver()
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _js_set_value(self, element: WebElement, value: str) -> None:
        """Set an input's value via JS to handle React/Auth0 inputs."""
        driver = self._ensure_driver()
        driver.execute_script("""
            var el = arguments[0], val = arguments[1];
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, element, value)
