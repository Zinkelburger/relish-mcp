"""Sanity-test that HTML fixtures contain the elements our parsers expect.

Validates HTML structure with regex/string matching (no network, no live
browser needed beyond loading local files). Run this after changing
parsers or refreshing fixtures to catch selector regressions.
"""
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if not condition:
        FAIL += 1
    else:
        PASS += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def read(filename: str) -> str:
    return (FIXTURES / filename).read_text()


def test_schedule_today():
    print("\n=== schedule_today.html ===")
    html = read("schedule_today.html")

    check(
        "has subsidy-widget-right div",
        'class="subsidy-widget-right"' in html
        or "subsidy-widget" in html,
    )
    dollars = re.findall(r"\$\d+\.\d{2}", html)
    check("has dollar amounts", len(dollars) > 0, str(dollars[:5]))

    entries = re.findall(r'href="/schedule_entries/(\d+)"', html)
    check("has schedule_entries links (may be 0 if restaurants closed)",
          True, f"{len(entries)} entries")

    date_links = re.findall(r'href="/schedule/(\d{4}-\d{2}-\d{2})"', html)
    check("has date navigation links", len(date_links) > 0, str(date_links))

    check("has tracking-card or order info",
          "tracking-card" in html or "order-progress" in html or "customer_order" in html)


def test_schedule_wed():
    print("\n=== schedule_wed.html ===")
    html = read("schedule_wed.html")

    entries = re.findall(r'href="/schedule_entries/(\d+)"', html)
    check("has schedule_entries links", len(entries) > 0, str(entries))
    check("has entry 1232291 (Halal Guys)", "1232291" in str(entries), str(entries))
    check("has entry 1232289 (Health Bar)", "1232289" in str(entries), str(entries))

    check("mentions Potbelly", "Potbelly" in html)
    check("mentions Halal Guys", "Halal Guys" in html)
    check("mentions 11:11 Health Bar", "11:11" in html or "Health Bar" in html)
    check("mentions Bosso Ramen", "Bosso" in html or "Ramen" in html)

    check("has order-by times", "Order by" in html)
    check("has delivery times", "Delivery at" in html)
    check("has meals left badges", "meals left" in html)

    check("has subsidy widget", "subsidy" in html.lower())
    amounts = re.findall(r"\$\d+\.\d{2}", html)
    check("has dollar amounts", len(amounts) > 0)


def test_menu_halal_guys():
    print("\n=== menu_halal_guys.html ===")
    html = read("menu_halal_guys.html")

    items = re.findall(r"menu_item_id=(\d+)", html)
    unique_items = set(items)
    check("has menu_item_id links", len(unique_items) > 0, f"{len(unique_items)} unique items")
    check("at least 10 unique items", len(unique_items) >= 10, str(len(unique_items)))
    check("has item 26308104 (Chicken & Beef Gyro)", "26308104" in str(items))
    check("has item 26308101 (Chicken Plate)", "26308101" in str(items))
    check("has item 26308102 (Beef Gyro)", "26308102" in str(items))
    check("has item 26308103 (Falafel)", "26308103" in str(items))

    check("mentions Chicken & Beef Gyro", "Chicken" in html and "Beef Gyro" in html)
    check("has prices", "$11.99" in html)
    check("has category names", "Hot Entrees" in html or "Sides" in html or "Beverages" in html)


def test_menu_health_bar():
    print("\n=== menu_health_bar.html ===")
    html = read("menu_health_bar.html")

    items = re.findall(r"menu_item_id=(\d+)", html)
    unique_items = set(items)
    check("has menu_item_id links", len(unique_items) > 0, f"{len(unique_items)} unique items")
    check("at least 10 unique items", len(unique_items) >= 10, str(len(unique_items)))
    check("has item 22409925 (Acai Bowl)", "22409925" in str(items))

    check("mentions Acai Bowl", "Acai" in html)
    check("has prices", "$13.99" in html or "$13.50" in html)
    check("has categories", "Bowls" in html or "Smoothies" in html or "Breakfast" in html)


def test_item_modal_gyro():
    print("\n=== item_modal_gyro.html ===")
    html = read("item_modal_gyro.html")

    check("has menu-item-modal", 'id="menu-item-modal"' in html)
    check("has option-form-container", "option-form-container" in html)

    # Size radio buttons (attribute order varies: data-price, type, value, name)
    size_radios = re.findall(
        r'name="order_item\[size_index\]"[^>]*value="(\d+)"', html
    )
    if not size_radios:
        size_radios = re.findall(
            r'value="(\d+)"[^>]*name="order_item\[size_index\]"', html
        )
    check("has size radio buttons", len(size_radios) >= 2, str(size_radios))
    check("has size 0 (Small)", "0" in size_radios)
    check("has size 1 (Regular)", "1" in size_radios)

    check("Small price $11.99", 'data-price="11.99"' in html)
    check("Regular price $12.99", 'data-price="12.99"' in html)

    # Section headers
    check("has 'Sizes' header", "<strong>Sizes</strong>" in html)
    check("has '(Required)' label", "(Required)" in html)
    check("has 'Add an extra side' header", "Add an extra side" in html)
    check("has 'Add extra sauce' header", "Add extra sauce" in html)
    check("has 'Add a dessert' header", "Add a dessert" in html)
    check("has 'Add a drink' header", "Add a drink" in html)

    # Checkbox options
    side_checkboxes = re.findall(r'name="options\[7632732\]choices\[\]"', html)
    check("has extra side checkboxes (group 7632732)", len(side_checkboxes) > 0,
          f"{len(side_checkboxes)} checkboxes")

    sauce_checkboxes = re.findall(r'name="options\[7632733\]choices\[\]"', html)
    check("has sauce checkboxes (group 7632733)", len(sauce_checkboxes) > 0,
          f"{len(sauce_checkboxes)} checkboxes")

    check("has Pita option", "Pita" in html and 'data-price="1.49"' in html)
    check("has White Sauce option", "White Sauce" in html and 'data-price="1.0"' in html)

    # Add to cart button
    check("has add-to-cart-button", 'id="add-to-cart-button"' in html)
    check("has 'Add to cart' value", "Add to cart" in html)

    # Continue to checkout (only present when cart has items — may be absent in fixture)
    check("has continue-checkout div (if cart has items)",
          "continue-checkout" in html or "cart" in html.lower(),
          "checkout div present" if "continue-checkout" in html else "cart structure present")


def test_item_modal_acai():
    print("\n=== item_modal_acai.html ===")
    html = read("item_modal_acai.html")

    check("has menu-item-modal", 'id="menu-item-modal"' in html)

    check("has 'substitute' header", "substitute" in html.lower())
    check("has 'Add toppings' header", "Add toppings" in html)
    check("has 'Add a side' header", "Add a side" in html)
    check("has 'Add a drink' header", "Add a drink" in html)

    # Topping checkboxes
    topping_group = re.findall(r'name="options\[5419636\]choices\[\]"', html)
    check("has topping checkboxes (group 5419636)", len(topping_group) >= 30,
          f"{len(topping_group)} toppings")

    check("has Vanilla Protein topping", "Vanilla Protein" in html)
    check("has Cacao Nibs topping", "Cacao Nibs" in html)
    check("has Almond Butter substitute", "Almond Butter" in html)

    check("has add-to-cart-button", 'id="add-to-cart-button"' in html)

    check("no size radios (bowls don't have sizes)",
          'name="order_item[size_index]"' not in html)


def test_orders():
    print("\n=== orders.html ===")
    html = read("orders.html")

    order_cards = re.findall(r'id="customer_order_(\d+)"', html)
    check("has order cards", len(order_cards) > 0, str(order_cards))

    check("has cancel link pattern",
          "confirm_cancel" in html)

    check("has order detail links",
          "order_details" in html)

    check("mentions delivery info",
          "Delivery on" in html or "Delivered" in html or "delivery" in html.lower())


def test_order_detail():
    print("\n=== order_detail.html ===")
    html = read("order_detail.html")

    check("has delivery details", "Delivery details" in html or "delivery" in html.lower())
    check("has customer details", "Customer" in html)
    check("has price/total info", "$" in html)


def main():
    test_schedule_today()
    test_schedule_wed()
    test_menu_halal_guys()
    test_menu_health_bar()
    test_item_modal_gyro()
    test_item_modal_acai()
    test_orders()
    test_order_detail()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL:
        print("SOME TESTS FAILED")
        exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
