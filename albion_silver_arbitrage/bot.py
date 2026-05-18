import logging
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

import config
from detector import market_summary

log = logging.getLogger(__name__)
bot = telebot.TeleBot(config.TELEGRAM_TOKEN, parse_mode="HTML")

# Shared state: updated by scanner after each scan
_last_listings: list = []


def set_listings(listings: list) -> None:
    global _last_listings
    _last_listings = listings


# ── Keyboard ─────────────────────────────────────────────────────────────────

def _menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("\U0001f4b0 Текущие цены"), KeyboardButton("ℹ️ Инфо"))
    return kb


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "\U0001f30d <b>Albion Online Silver — EU</b>\n"
        "Автоматически отслеживаю 6 площадок.\n"
        f"Порог сигнала: <b>-{config.THRESHOLD_VS_AVERAGE}%</b> от средней цены\n"
        f"Интервал скана: {config.SCAN_INTERVAL // 60} мин.",
        reply_markup=_menu_kb(),
    )


@bot.message_handler(func=lambda m: m.text == "\U0001f4b0 Текущие цены")
def cmd_prices(message):
    if not _last_listings:
        bot.send_message(message.chat.id, "Данных ещё нет — подожди первого скана.")
        return

    summary = market_summary(_last_listings)
    if not summary:
        bot.send_message(message.chat.id, "Нет данных по EU silver.")
        return

    lines = ["\U0001f4b0 <b>Лучшие цены на Albion EU Silver (/1M)</b>\n"]
    for platform, info in sorted(summary.items(), key=lambda x: x[1]["best_price_per_million"]):
        ppm = info["best_price_per_million"]
        cnt = info["listings_count"]
        lines.append(f"\U0001f3f7 <b>{platform}</b>: ${ppm:.4f}/M ({cnt} лотов)")

    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "ℹ️ Инфо")
def cmd_info(message):
    bot.send_message(
        message.chat.id,
        "\U0001f50d <b>Отслеживаемые площадки:</b>\n"
        "• FunPay\n• G2G\n• Eldorado\n• PlayerAuctions\n• IGGM\n• Z2U\n\n"
        "Программа читает цены, нормализует до $/млн\n"
        "и шлёт алерт если лот дешевле среднего на "
        f"<b>{config.THRESHOLD_VS_AVERAGE}%+</b>.",
    )


# ── Deal alert (called from scanner) ─────────────────────────────────────────

def send_deal_alert(deal) -> None:
    lst = deal.listing

    # Show prices on other platforms for arbitrage context
    other_prices = [
        f"• {p}: ${v:.4f}/M"
        for p, v in sorted(deal.platform_prices.items(), key=lambda x: x[1])
        if p != lst.platform
    ]
    other_block = "\n".join(other_prices)

    text = (
        "\U0001f4b8 <b>Дешёвый silver!</b>\n\n"
        f"\U0001f310 Площадка: <b>{lst.platform}</b>\n"
        f"\U0001f4b0 Цена: <b>${lst.price_per_million:.4f}/M</b>\n"
        f"\U0001f4ca Средняя по рынку: <b>${deal.avg_price_per_million:.4f}/M</b>\n"
        f"\U0001f4c9 Выгода: <b>-{deal.discount_vs_avg}%</b>\n"
        f"\U0001f4e6 Лот: {lst.amount_millions:.0f}M за ${lst.price_usd}\n"
        f"\U0001f464 Продавец: {lst.seller}\n"
        f'\U0001f517 <a href="{lst.url}">Открыть лот</a>\n'
    )

    if other_block:
        text += f"\n\U0001f4cb Цены на других площадках:\n" + other_block

    bot.send_message(
        config.TELEGRAM_CHAT_ID, text,
        disable_web_page_preview=True,
    )


def start_polling():
    log.info("Bot polling started")
    bot.infinity_polling(interval=1, timeout=30)
