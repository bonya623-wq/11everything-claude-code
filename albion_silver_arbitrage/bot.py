import logging
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

import config
from detector import market_summary

log = logging.getLogger(__name__)
bot = telebot.TeleBot(config.TELEGRAM_TOKEN, parse_mode="HTML")

_last_listings: list = []


def set_listings(listings: list) -> None:
    global _last_listings
    _last_listings = listings


def _menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("\U0001f4b0 Текущие цены"), KeyboardButton("ℹ️ Инфо"))
    return kb


@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "\U0001f30d <b>Albion Online Silver — EU</b>\n"
        "Отслеживаю <b>11 площадок</b>:\n"
        "FunPay • G2G • Eldorado • PlayerAuctions\n"
        "IGGM • Z2U • U7BUY • IGVault\n"
        "Odealo • G2A • MMOGA\n\n"
        f"Порог алерта: <b>-{config.THRESHOLD_VS_AVERAGE}%</b> от средней\n"
        f"Скан: каждые <b>{config.SCAN_INTERVAL // 60} мин.</b>",
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

    lines = ["\U0001f4b0 <b>Лучшие цены — Albion EU Silver</b>\n"]
    ranked = sorted(summary.items(), key=lambda x: x[1]["best_price_per_million"])
    for i, (platform, info) in enumerate(ranked, 1):
        ppm = info["best_price_per_million"]
        cnt = info["listings_count"]
        medal = ["\U0001f947", "\U0001f948", "\U0001f949"].pop(0) if i <= 3 else "  "
        lines.append(f"{medal} <b>{platform}</b>: ${ppm:.4f}/M ({cnt} лотов)")

    # Avg across all
    all_prices = [i["best_price_per_million"] for i in summary.values()]
    avg = sum(all_prices) / len(all_prices)
    lines.append(f"\n\U0001f4ca Средняя: <b>${avg:.4f}/M</b>")

    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "ℹ️ Инфо")
def cmd_info(message):
    bot.send_message(
        message.chat.id,
        "ℹ️ <b>Как работает:</b>\n"
        "1. Каждые 3 мин. открываю 11 сайтов\n"
        "2. Собираю все лоты EU silver\n"
        "3. Перевожу в $/млн\n"
        "4. Считаю среднюю цену\n"
        f"5. Если лот дешевле на {config.THRESHOLD_VS_AVERAGE}%+ → алерт в Telegram\n\n"
        "<b>Самые дешёвые доступные площадки:</b>\n"
        "• FunPay ~$0.15–0.22/M\n"
        "• G2G ~$0.18–0.25/M\n"
        "• U7BUY ~$0.22–0.28/M\n\n"
        "<i>⚠️ Покупка silver наушает ToS Albion Online.</i>",
    )


def send_deal_alert(deal) -> None:
    lst = deal.listing
    other_prices = [
        f"• {p}: ${v:.4f}/M"
        for p, v in sorted(deal.platform_prices.items(), key=lambda x: x[1])
        if p != lst.platform
    ]

    text = (
        "\U0001f4b8 <b>Дешёвый silver!</b>\n\n"
        f"\U0001f310 Площадка: <b>{lst.platform}</b>\n"
        f"\U0001f4b0 Цена: <b>${lst.price_per_million:.4f}/M</b>\n"
        f"\U0001f4ca Средняя: <b>${deal.avg_price_per_million:.4f}/M</b>\n"
        f"\U0001f4c9 Выгода: <b>-{deal.discount_vs_avg}%</b>\n"
        f"\U0001f4e6 Лот: {lst.amount_millions:.0f}M за ${lst.price_usd}\n"
        f"\U0001f464 Продавец: {lst.seller}\n"
        f'\U0001f517 <a href="{lst.url}">Открыть лот</a>\n'
        f"\n\U0001f4cb Цены на других:\n" + "\n".join(other_prices)
    )
    bot.send_message(config.TELEGRAM_CHAT_ID, text, disable_web_page_preview=True)


def start_polling():
    log.info("Bot polling started")
    bot.infinity_polling(interval=1, timeout=30)
