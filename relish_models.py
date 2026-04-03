"""Data models for Relish MCP server."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LoginState(StrEnum):
    LOGGED_OUT = "logged_out"
    AWAITING_MFA = "awaiting_mfa"
    LOGGED_IN = "logged_in"


class OrderStatus(StrEnum):
    PLACED = "Order placed"
    DELIVERED = "Delivered"
    PREPARING = "Preparing"
    CANCELED = "Canceled"
    UNKNOWN = "Unknown"


@dataclass
class Subsidy:
    label: str
    remaining: str
    meal_type: str

    def __str__(self) -> str:
        return f"{self.label} — {self.meal_type}: {self.remaining} remaining"


@dataclass
class Restaurant:
    name: str
    description: str
    schedule_entry_id: str
    order_by: str = ""
    delivery_at: str = ""
    meals_left: str = ""
    tags: list[str] = field(default_factory=list)
    closed: bool = False

    def __str__(self) -> str:
        status = "CLOSED" if self.closed else f"Order by {self.order_by}"
        meals = f" ({self.meals_left} meals left)" if self.meals_left else ""
        tags_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"{self.name} — {self.description}{tags_str}\n  {status}{meals} | Delivery at {self.delivery_at}\n  ID: {self.schedule_entry_id}"


@dataclass
class MenuItem:
    name: str
    menu_item_id: str = ""
    price: str = ""
    description: str = ""
    category: str = ""
    order_url: str = ""

    def __str__(self) -> str:
        parts = [self.name]
        if self.price:
            parts.append(f"({self.price})")
        if self.category:
            parts.append(f"[{self.category}]")
        if self.description:
            parts.append(f"— {self.description}")
        if self.menu_item_id:
            parts.append(f"  id:{self.menu_item_id}")
        return " ".join(parts)


@dataclass
class ItemChoice:
    """A single selectable choice within an option group (e.g. 'Regular +$1.00')."""
    label: str
    value: str
    price: str = ""
    selected: bool = False

    def __str__(self) -> str:
        sel = " [SELECTED]" if self.selected else ""
        price = f" +{self.price}" if self.price and self.price != "0" else ""
        return f"{self.label}{price}{sel}  (value={self.value})"


@dataclass
class ItemOptionGroup:
    """A group of choices for an item (e.g. 'Sizes', 'Add toppings')."""
    name: str
    required: bool
    input_type: str  # "radio" or "checkbox"
    group_id: str  # form field name (e.g. "order_item[size_index]" or "options[7632732]choices[]")
    choices: list[ItemChoice] = field(default_factory=list)
    min_choices: int = 0
    max_choices: int = 0

    def __str__(self) -> str:
        req = "Required" if self.required else "Optional"
        lines = [f"{self.name} ({req}, {self.input_type}, group_id={self.group_id}):"]
        for c in self.choices:
            lines.append(f"    • {c}")
        return "\n".join(lines)


@dataclass
class ItemDetails:
    """Full details for a menu item including all customization options."""
    name: str
    price: str
    description: str
    menu_item_id: str
    option_groups: list[ItemOptionGroup] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.name} — {self.price}", f"  {self.description}"]
        for group in self.option_groups:
            lines.append(f"  {group}")
        return "\n".join(lines)


@dataclass
class Order:
    order_id: str
    restaurant: str
    delivery_time: str
    price: str
    items: list[str] = field(default_factory=list)
    status: OrderStatus = OrderStatus.UNKNOWN

    def __str__(self) -> str:
        items_str = ", ".join(self.items) if self.items else "No items"
        status_str = f" — {self.status}" if self.status != OrderStatus.UNKNOWN else ""
        return f"{self.restaurant}{status_str}\n  {self.delivery_time} | {self.price}\n  Items: {items_str}\n  Order ID: {self.order_id}"


@dataclass
class DaySchedule:
    date: str
    date_label: str
    subsidy: Subsidy | None
    my_orders: list[Order]
    restaurants: list[Restaurant]
    available_dates: list[dict[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"Schedule for {self.date_label} ({self.date})"]
        if self.subsidy:
            lines.append(f"\nSubsidy: {self.subsidy}")
        if self.my_orders:
            lines.append(f"\nYour orders ({len(self.my_orders)}):")
            for o in self.my_orders:
                lines.append(f"  • {o}")
        lines.append(f"\nRestaurants ({len(self.restaurants)}):")
        for r in self.restaurants:
            lines.append(f"  • {r}")
        if self.available_dates:
            dates = [f"{d['label']} ({d['date']})" for d in self.available_dates]
            lines.append(f"\nOther available dates: {', '.join(dates)}")
        return "\n".join(lines)
