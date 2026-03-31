# HTML Fixtures

Snapshots of real Relish pages for offline sanity testing of parsers.

## Files

| File | Page | What it tests |
|------|------|---------------|
| `schedule_today.html` | `/schedule` | Schedule parser: subsidy, restaurants, orders, date tabs |
| `schedule_wed.html` | `/schedule/2026-04-01` | Schedule parser with specific date |
| `menu_halal_guys.html` | `/schedule_entries/1232291` | Menu parser: item links, prices, categories |
| `menu_health_bar.html` | `/schedule_entries/1232289` | Menu parser: different restaurant layout |
| `item_modal_gyro.html` | Gyro Plate modal open | Item options parser: sizes (radio), extras (checkbox) |
| `item_modal_acai.html` | Acai Bowl modal open | Item options parser: substitutions (radio), 37 toppings |
| `orders.html` | `/customer_orders` | Orders parser: order cards, IDs, statuses |
| `order_detail.html` | `/customer_orders/{id}/order_details` | Order detail page |

## Refreshing

```bash
python fetch_fixtures.py
```

Requires valid `.credentials` and `.cookies.json` (or MFA). Overwrites existing files.
