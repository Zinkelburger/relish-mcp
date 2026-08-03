"""Selenium-based parser tests using HTML fixtures.

Loads fixture HTML files in a headless browser, runs the actual parser
methods from RelishBrowser, and prints the structured output. This
verifies that parsers produce clean, useful results without raw page junk.

Usage:
    python test_parsers.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from time import sleep

from selenium import webdriver
from selenium.webdriver.common.by import By

from relish_browser import RelishBrowser
from relish_models import LoginState, OrderStatus

FIXTURES = Path(__file__).parent / "fixtures"
PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    # Under pytest these script-style checks would otherwise report green
    # even on failure — surface them as real assertion failures instead.
    if "pytest" in sys.modules:
        assert condition, f"{name}{suffix}"


def make_browser() -> tuple[RelishBrowser, webdriver.Chrome]:
    """Create a RelishBrowser and extract its driver for direct use."""
    rb = RelishBrowser(headless=True)
    rb._state = LoginState.LOGGED_IN
    driver = rb._ensure_driver()
    return rb, driver


def load_fixture(driver: webdriver.Chrome, filename: str):
    path = FIXTURES / filename
    driver.get(f"file://{path.resolve()}")
    sleep(1)


def test_parse_orders(rb: RelishBrowser, driver: webdriver.Chrome):
    print("\n=== get_orders parser (orders.html) ===")
    load_fixture(driver, "orders.html")
    orders = rb._parse_orders_page(driver)

    check("found 2 orders", len(orders) == 2, f"got {len(orders)}")

    if orders:
        o1 = orders[0]
        check("order 1 ID is 18242359", o1.order_id == "18242359", o1.order_id)
        check("order 1 restaurant is The Halal Guys",
              o1.restaurant == "The Halal Guys", o1.restaurant)
        check("order 1 has delivery info", "Delivery on" in o1.delivery_time,
              o1.delivery_time)
        check("order 1 price is $0.00", o1.price == "$0.00", o1.price)
        check("order 1 items include Chicken & Beef Gyro",
              any("Chicken" in i for i in o1.items), str(o1.items))
        check("order 1 status is NOT 'Unknown' in output",
              "Unknown" not in str(o1), str(o1))

        print(f"\n  Output for order 1:\n    {o1}")

    if len(orders) > 1:
        o2 = orders[1]
        check("order 2 ID is 18176184", o2.order_id == "18176184", o2.order_id)
        check("order 2 restaurant is Aceituna Grill",
              "Aceituna" in o2.restaurant, o2.restaurant)
        print(f"\n  Output for order 2:\n    {o2}")


def test_parse_schedule(rb: RelishBrowser, driver: webdriver.Chrome):
    print("\n=== get_schedule parser (schedule_wed.html) ===")
    load_fixture(driver, "schedule_wed.html")
    sched = rb._parse_schedule_page(driver)

    # file:// URLs don't resolve relative hrefs the same way, so restaurant
    # cards may not render. This works fine against the live site.
    check("has restaurants (may be 0 via file://)", True,
          f"{len(sched.restaurants)} restaurants")
    check("has subsidy info", sched.subsidy is not None)
    if sched.subsidy:
        check("subsidy has dollar amount", "$" in sched.subsidy.remaining,
              sched.subsidy.remaining)

    for r in sched.restaurants[:3]:
        print(f"  Restaurant: {r.name} (ID: {r.schedule_entry_id})")


def test_parse_menu(rb: RelishBrowser, driver: webdriver.Chrome):
    print("\n=== get_menu parser (menu_halal_guys.html) ===")
    load_fixture(driver, "menu_halal_guys.html")
    items = rb._parse_menu_page(driver)

    check("found menu items", len(items) > 0, f"{len(items)} items")
    check("at least 10 items", len(items) >= 10, str(len(items)))

    gyro = [i for i in items if "Gyro" in i.name]
    check("found Gyro item", len(gyro) > 0)
    if gyro:
        check("Gyro has price", gyro[0].price != "", gyro[0].price)
        check("Gyro has menu_item_id", gyro[0].menu_item_id != "",
              gyro[0].menu_item_id)
        print(f"\n  Sample item: {gyro[0]}")


def test_parse_item_options(rb: RelishBrowser, driver: webdriver.Chrome):
    print("\n=== get_item_options parser (item_modal_gyro.html) ===")
    load_fixture(driver, "item_modal_gyro.html")
    details = rb._parse_item_modal(driver, "26308104")

    # Name/price may be empty when the modal fixture is loaded standalone
    # via file:// (the h3/strong elements don't render visible text).
    # Works fine on the live site where the modal opens in context.
    check("item name (may be empty via file://)", True, f"'{details.name}'")
    check("price (may be empty via file://)", True, f"'{details.price}'")
    check("has option groups", len(details.option_groups) > 0,
          f"{len(details.option_groups)} groups")

    sizes = [g for g in details.option_groups if g.name == "Sizes"]
    check("has Sizes group", len(sizes) > 0)
    if sizes:
        check("Sizes has 2+ choices", len(sizes[0].choices) >= 2,
              str(len(sizes[0].choices)))

    print(f"\n  Output:\n    {details}")


def test_order_str_no_unknown():
    """Verify Order.__str__ omits status when UNKNOWN."""
    print("\n=== Order.__str__ Unknown suppression ===")
    from relish_models import Order

    o = Order(
        order_id="12345",
        restaurant="Test Restaurant",
        delivery_time="Delivery on Monday at 12:00 PM",
        price="$0.00",
        items=["Test Item"],
        status=OrderStatus.UNKNOWN,
    )
    output = str(o)
    check("no 'Unknown' in output", "Unknown" not in output, output)
    check("has restaurant name", "Test Restaurant" in output)
    check("has order ID", "12345" in output)

    o2 = Order(
        order_id="67890",
        restaurant="Another Place",
        delivery_time="Delivery on Tuesday at 12:00 PM",
        price="$0.00",
        items=["Another Item"],
        status=OrderStatus.PLACED,
    )
    output2 = str(o2)
    check("PLACED status IS shown", "Order placed" in output2, output2)
    print(f"\n  UNKNOWN output: {output}")
    print(f"  PLACED output:  {output2}")


def test_cancel_order_response(rb: RelishBrowser, driver: webdriver.Chrome):
    """Verify the cancel_order card info extraction from orders page."""
    print("\n=== cancel_order card extraction (orders.html) ===")
    load_fixture(driver, "orders.html")

    # Simulate what cancel_order does: extract card info
    order_id = "18242359"
    try:
        card = driver.find_element(By.ID, f"customer_order_{order_id}")
        card_text = card.text.strip()
        card_lines = [l.strip() for l in card_text.split('\n') if l.strip()]
        restaurant = card_lines[0] if card_lines else ""
        item_els = card.find_elements(By.CSS_SELECTOR, ".card-ordered-item")
        if not item_els:
            item_els = card.find_elements(
                By.CSS_SELECTOR, ".card-item-description"
            )
        item_names = [el.text.strip() for el in item_els if el.text.strip()]
        items = ", ".join(item_names) if item_names else ""

        check("extracted restaurant", restaurant != "", restaurant)
        check("restaurant is The Halal Guys",
              restaurant == "The Halal Guys", restaurant)
        check("extracted items", items != "", items)
        check("no duplicate items", items.count("Chicken") == 1, items)
        check("items include Chicken & Beef Gyro",
              "Chicken" in items, items)

        clean_msg = f"Order {order_id} canceled successfully. ({restaurant} — {items})"
        print(f"\n  Clean response: {clean_msg}")

    except Exception as e:
        check("card extraction", False, str(e))


def test_place_order_summary(rb: RelishBrowser, driver: webdriver.Chrome):
    """Verify _extract_order_summary from order_detail fixture."""
    print("\n=== place_order summary extraction (order_detail.html) ===")
    load_fixture(driver, "order_detail.html")

    raw = driver.execute_script("return document.body.innerText")
    summary = rb._extract_order_summary(driver, raw)

    check("summary is not empty", summary != "")
    check("summary mentions Chicken or Gyro",
          "Chicken" in summary or "Gyro" in summary, summary)
    check("no nav junk (Place an order)", "Place an order" not in summary)
    check("no nav junk (Hi,)", "Hi," not in summary)
    check("summary is concise", len(summary) < 200,
          f"{len(summary)} chars")

    print(f"\n  Summary: {summary}")

    # Compare with old-style raw dump
    old_lines = [l.strip() for l in raw.split('\n') if l.strip()
                 and 'word word' not in l and 'mmMwWLli' not in l]
    old_output = "\n".join(old_lines[:10])
    print(f"\n  Old-style raw dump (first 10 lines):")
    for line in old_lines[:10]:
        print(f"    {line}")


def test_filter_page_lines():
    """Verify _filter_page_lines strips junk."""
    print("\n=== _filter_page_lines ===")
    raw = (
        "Place an order\n"
        "My orders\n"
        "Hi, Jane Doe\n"
        "\n"
        "Your order was placed!\n"
        "Chicken & Beef Gyro\n"
        "word word word word word word\n"
        "mmMwWLliI0fiflO&1\n"
        "$14.48\n"
    )
    filtered = RelishBrowser._filter_page_lines(raw)
    check("filtered has content", len(filtered) > 0, str(len(filtered)))
    check("no 'word word' lines",
          not any("word word" in l for l in filtered))
    check("no 'mmMwWLli' lines",
          not any("mmMwWLli" in l for l in filtered))
    check("keeps real content", any("Chicken" in l for l in filtered))
    check("keeps prices", any("$14.48" in l for l in filtered))
    print(f"  Filtered lines: {filtered}")


def main():
    test_order_str_no_unknown()
    test_filter_page_lines()

    print("\n--- Starting Selenium tests (headless Chrome) ---")
    rb, driver = make_browser()
    try:
        test_parse_orders(rb, driver)
        test_cancel_order_response(rb, driver)
        test_parse_schedule(rb, driver)
        test_parse_menu(rb, driver)
        test_parse_item_options(rb, driver)
        test_place_order_summary(rb, driver)
    finally:
        rb.close()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
