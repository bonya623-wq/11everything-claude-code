import json
import os
from datetime import date
from typing import Optional

_FILE = os.path.join(os.path.dirname(__file__), "inventory.json")


def _load() -> dict:
    if not os.path.exists(_FILE):
        return {}
    with open(_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_item(item_name: str, quantity: int, buy_price: float) -> dict:
    data = _load()
    today = str(date.today())

    if item_name not in data:
        data[item_name] = {"quantity": 0, "buy_price": buy_price, "date": today, "history": []}

    entry = data[item_name]
    new_qty = entry["quantity"] + quantity
    # Weighted average buy price
    entry["buy_price"] = round(
        (entry["buy_price"] * entry["quantity"] + buy_price * quantity) / new_qty, 6
    )
    entry["quantity"] = new_qty
    entry["date"] = today
    entry["history"].append({"action": "buy", "qty": quantity, "price": buy_price, "date": today})

    _save(data)
    return entry


def remove_item(item_name: str, quantity: int, sell_price: Optional[float] = None) -> dict:
    data = _load()
    if item_name not in data:
        raise KeyError(f"'{item_name}' not in inventory")

    entry = data[item_name]
    if entry["quantity"] < quantity:
        raise ValueError(f"Only {entry['quantity']} available")

    entry["quantity"] -= quantity
    today = str(date.today())
    action = "sell" if sell_price is not None else "remove"
    entry["history"].append({"action": action, "qty": quantity, "price": sell_price, "date": today})

    _save(data)
    return entry


def get_inventory() -> dict:
    return _load()


def get_statistics() -> dict:
    data = _load()
    total_invested = 0.0
    total_profit = 0.0
    items = []

    for name, entry in data.items():
        invested = entry["buy_price"] * entry["quantity"]
        profit = sum(
            (h["price"] - entry["buy_price"]) * h["qty"]
            for h in entry.get("history", [])
            if h["action"] == "sell" and h["price"] is not None
        )
        total_invested += invested
        total_profit += profit
        items.append({
            "name": name,
            "quantity": entry["quantity"],
            "buy_price": entry["buy_price"],
            "date": entry["date"],
            "profit": round(profit, 2),
        })

    return {
        "total_items": len(data),
        "total_invested": round(total_invested, 2),
        "total_profit": round(total_profit, 2),
        "items": items,
    }
