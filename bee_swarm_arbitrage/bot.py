import logging
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

import config
import inventory as inv

log = logging.getLogger(__name__)
bot = telebot.TeleBot(config.TELEGRAM_TOKEN, parse_mode="HTML")

# Per-chat state machine: {chat_id: {"step": str, ...}}
_state: dict[int, dict] = {}

_MENU_BUTTONS = {"\U0001f4e6 Инвентарь", "\U0001f4ca Статистика", "➕ Добавить", "➖ Убрать"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("\U0001f4e6 Инвентарь"), KeyboardButton("\U0001f4ca Статистика"))
    kb.row(KeyboardButton("➕ Добавить"), KeyboardButton("➖ Убрать"))
    return kb


def _cancel_state(chat_id: int) -> None:
    _state.pop(chat_id, None)


# ── Deal alert ────────────────────────────────────────────────────────────────

def send_deal_alert(deal) -> None:
    lst = deal.listing
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Купил", callback_data=f"buy:{lst.item_name}:{lst.price_per_unit}"),
        InlineKeyboardButton("❌ Пропустить", callback_data="skip"),
    )
    text = (
        "\U0001f525 <b>Выгодная сделка!</b>\n\n"
        f"\U0001f4e6 Предмет: <b>{lst.item_name}</b>\n"
        f"\U0001f4b0 Средняя цена: <b>${deal.avg_market_price}</b>/ед.\n"
        f"\U0001f3f7 Цена сделки: <b>${lst.price_per_unit}</b>/ед.\n"
        f"\U0001f4c9 Выгода: <b>-{deal.discount_vs_avg}%</b> от среднего\n"
        f"\U0001f310 Площадка: <b>{lst.platform}</b>\n"
        f"\U0001f464 Продавец: {lst.seller}\n"
        f"\U0001f4e6 Лот: {lst.quantity} шт. за ${lst.price_usd}\n"
        f'\U0001f517 <a href="{lst.url}">Открыть лот</a>'
    )
    bot.send_message(
        config.TELEGRAM_CHAT_ID, text,
        reply_markup=markup, disable_web_page_preview=True,
    )


# ── Callback handlers ─────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:"))
def cb_buy(call):
    parts = call.data.split(":", 2)
    item_name, price = parts[1], float(parts[2])
    chat_id = call.message.chat.id
    _state[chat_id] = {"step": "buy_qty", "item": item_name, "price": price}
    bot.answer_callback_query(call.id)
    bot.send_message(
        chat_id,
        f"Сколько единиц <b>{item_name}</b> купил? (цена ${price}/ед.)\n\nВведи число:",
    )


@bot.callback_query_handler(func=lambda c: c.data == "skip")
def cb_skip(call):
    bot.answer_callback_query(call.id, "Пропущено")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("rm:"))
def cb_remove_select(call):
    item_name = call.data[3:]
    chat_id = call.message.chat.id
    _state[chat_id] = {"step": "rm_qty", "item": item_name}
    bot.answer_callback_query(call.id)
    bot.send_message(chat_id, f"Сколько единиц <b>{item_name}</b> убрать?")


# ── Command & menu handlers ───────────────────────────────────────────────────

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    _cancel_state(message.chat.id)
    bot.send_message(message.chat.id, "Привет! Выбери действие:", reply_markup=_menu_kb())


@bot.message_handler(func=lambda m: m.text == "\U0001f4e6 Инвентарь")
def cmd_inventory(message):
    _cancel_state(message.chat.id)
    data = inv.get_inventory()
    if not data:
        bot.send_message(message.chat.id, "Инвентарь пуст.")
        return
    lines = ["\U0001f4e6 <b>Инвентарь:</b>\n"]
    for name, entry in data.items():
        total = round(entry["quantity"] * entry["buy_price"], 2)
        lines.append(f"• <b>{name}</b>: {entry['quantity']} шт. × ${entry['buy_price']} = ${total}")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "\U0001f4ca Статистика")
def cmd_stats(message):
    _cancel_state(message.chat.id)
    s = inv.get_statistics()
    lines = [
        "\U0001f4ca <b>Статистика</b>\n",
        f"Позиций: {s['total_items']}",
        f"Вложено: ${s['total_invested']}",
        f"Прибыль от продаж: ${s['total_profit']}",
    ]
    if s["items"]:
        lines.append("")
        for item in s["items"]:
            if item["profit"]:
                lines.append(f"• {item['name']}: прибыль ${item['profit']}")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "➕ Добавить")
def cmd_add(message):
    _state[message.chat.id] = {"step": "add_name"}
    bot.send_message(message.chat.id, "Название предмета:")


@bot.message_handler(func=lambda m: m.text == "➖ Убрать")
def cmd_remove(message):
    _cancel_state(message.chat.id)
    data = inv.get_inventory()
    if not data:
        bot.send_message(message.chat.id, "Инвентарь пуст.")
        return
    markup = InlineKeyboardMarkup()
    for name in data:
        markup.add(InlineKeyboardButton(name, callback_data=f"rm:{name}"))
    bot.send_message(message.chat.id, "Выбери предмет:", reply_markup=markup)


# ── State machine (catch-all for multi-step flows) ────────────────────────────

@bot.message_handler(
    func=lambda m: m.chat.id in _state and m.text not in _MENU_BUTTONS and not (m.text or "").startswith("/")
)
def handle_state(message):
    chat_id = message.chat.id
    state = _state[chat_id]
    step = state["step"]
    text = message.text.strip()

    if step == "buy_qty":
        qty = _parse_int(text)
        if qty is None:
            bot.send_message(chat_id, "Введи целое число:")
            return
        inv.add_item(state["item"], qty, state["price"])
        _cancel_state(chat_id)
        bot.send_message(
            chat_id,
            f"✅ Добавлено: <b>{state['item']}</b> × {qty} шт. по ${state['price']}/ед.",
        )

    elif step == "rm_qty":
        qty = _parse_int(text)
        if qty is None:
            bot.send_message(chat_id, "Введи целое число:")
            return
        try:
            entry = inv.remove_item(state["item"], qty)
            _cancel_state(chat_id)
            bot.send_message(
                chat_id,
                f"✅ Убрано: <b>{state['item']}</b> × {qty} шт. Осталось: {entry['quantity']}",
            )
        except (KeyError, ValueError) as e:
            _cancel_state(chat_id)
            bot.send_message(chat_id, f"❌ {e}")

    elif step == "add_name":
        state["item"] = text
        state["step"] = "add_price"
        bot.send_message(chat_id, "Цена за единицу ($):")

    elif step == "add_price":
        price = _parse_float(text)
        if price is None:
            bot.send_message(chat_id, "Введи корректную цену (например 4.5):")
            return
        state["price"] = price
        state["step"] = "add_qty"
        bot.send_message(chat_id, "Количество (шт.):")

    elif step == "add_qty":
        qty = _parse_int(text)
        if qty is None:
            bot.send_message(chat_id, "Введи целое число:")
            return
        inv.add_item(state["item"], qty, state["price"])
        _cancel_state(chat_id)
        bot.send_message(
            chat_id,
            f"✅ Добавлено: <b>{state['item']}</b> × {qty} шт. по ${state['price']}/ед.",
        )


def _parse_int(s: str) -> int | None:
    try:
        v = int(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_float(s: str) -> float | None:
    try:
        v = float(s.replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def start_polling():
    log.info("Bot polling started")
    bot.infinity_polling(interval=1, timeout=30)
