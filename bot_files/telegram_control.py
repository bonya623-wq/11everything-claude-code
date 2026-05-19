"""
telegram_control.py — управление FunPay Zeus Bot через Telegram
Инлайн-кнопка "Стоп" для остановки процесса, фильтрация логов, исправлена ошибка bot_process.
"""

import subprocess
import sys
import json
import re
import time
import threading
import logging
from pathlib import Path

import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN   = "8690921428:AAF5759VL1gBpzyVXtMEcTUk8iO3sWYGHkE"  # ОБЯЗАТЕЛЬНО ЗАМЕНИТЕ!
ALLOWED_ID  = 444942538
MAIN_SCRIPT = "main.py"
LOG_DIR     = Path("logs")
CONFIG_PATH = Path("config.json")
LOT_PAIRS   = Path("lot_pairs.json")

# ==================================================
bot = telebot.TeleBot(BOT_TOKEN)
logger = logging.getLogger("tg_control")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

bot_process = None
log_streaming = False
_selected = {}        # аккаунты (Account)
_items_selected = {}  # предметы (CustomItem)
running_message_id = None

def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Ошибка config.json: {e}")
        return {"games": []}


def _send_lot_pairs_file(chat_id):
    """Отправляет lot_pairs.json как файл в Telegram."""
    # Ищем файл рядом со скриптом, если не нашли по текущей директории
    path = LOT_PAIRS
    if not path.exists():
        alt = Path(__file__).parent / "lot_pairs.json"
        if alt.exists():
            path = alt

    if not path.exists():
        bot.send_message(chat_id, "📋 Файл lot_pairs.json не найден")
        return

    try:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            total = sum(len(v) for v in data.values() if isinstance(v, list))
            caption = f"📋 База лотов: {total} шт."
        except Exception:
            caption = "📋 База лотов"
        with open(path, "rb") as f:
            bot.send_document(chat_id, f, caption=caption)
    except Exception as e:
        logger.warning(f"lot_pairs send: {e}")
        try:
            bot.send_message(chat_id, f"❌ Ошибка отправки файла: {e}")
        except Exception:
            pass

def is_running():
    return bot_process is not None and bot_process.poll() is None

def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if is_running():
        kb.row(KeyboardButton("⛔ Остановить бота"))
    else:
        kb.row(KeyboardButton("🚀 Запустить все"))
        kb.row(KeyboardButton("🎮 Выбрать аккаунты"), KeyboardButton("🎯 Выбрать предметы"))
    kb.row(KeyboardButton("📋 Логи"), KeyboardButton("📊 Статус"))
    kb.row(KeyboardButton("🔍 Проверить аккаунты"), KeyboardButton("🎯 Проверить предметы"))
    kb.row(KeyboardButton("🗑 Удалить лоты"), KeyboardButton("📄 База лотов"))
    return kb

def games_keyboard(selected=None):
    """Клавиатура только для Account-игр."""
    cfg = load_config()
    games = cfg.get("games", [])
    kb = InlineKeyboardMarkup(row_width=1)
    sel = selected or set()
    for i, g in enumerate(games):
        if g.get("eldorado_category", "Account") == "CustomItem":
            continue
        status = "✅" if i in sel else "⬜"
        kb.add(InlineKeyboardButton(f"{status} {g['name']}", callback_data=f"toggle_{i}"))
    kb.add(InlineKeyboardButton("▶️ Запустить выбранные", callback_data="start_selected"))
    kb.add(InlineKeyboardButton("🗑 Удалить лоты выбранных", callback_data="delete_selected"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    return kb

def items_keyboard(selected=None):
    """Клавиатура только для CustomItem-игр."""
    cfg = load_config()
    games = cfg.get("games", [])
    kb = InlineKeyboardMarkup(row_width=1)
    sel = selected or set()
    for i, g in enumerate(games):
        if g.get("eldorado_category", "Account") != "CustomItem":
            continue
        status = "✅" if i in sel else "⬜"
        kb.add(InlineKeyboardButton(f"{status} {g['name']}", callback_data=f"item_toggle_{i}"))
    kb.add(InlineKeyboardButton("▶️ Запустить выбранные", callback_data="item_start"))
    kb.add(InlineKeyboardButton("🗑 Удалить лоты выбранных", callback_data="item_delete"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="item_cancel"))
    return kb

def start_bot_process(args_list, chat_id=None):
    global bot_process, log_streaming, running_message_id
    if is_running():
        bot.send_message(chat_id, "⚠️ Бот уже работает!")
        return

    cmd = [sys.executable, MAIN_SCRIPT] + args_list

    if not args_list or args_list[0] == "all":
        mode_label = "все игры"
    elif args_list[0] == "d":
        mode_label = f"удаление лотов [{args_list[1] if len(args_list) > 1 else ''}]"
    elif args_list[0] == "c":
        mode_label = "проверка базы"
    else:
        mode_label = f"игры [{args_list[0]}]"

    bot.send_message(chat_id, f"🔄 Запускаю: {mode_label}")

    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    try:
        bot_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=1,
            env=env,
            cwd=str(Path.cwd())
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка запуска: {e}", reply_markup=main_keyboard())
        return

    msg = bot.send_message(
        chat_id,
        f"▶️ Запущено: {mode_label}\nДля остановки нажмите кнопку ниже 👇",
        reply_markup=main_keyboard()
    )
    running_message_id = msg.message_id

    log_streaming = True
    mode = args_list[0] if args_list else None
    threading.Thread(target=stream_logs, args=(chat_id, mode), daemon=True).start()

def decode_line(raw_bytes: bytes) -> str:
    """Пробуем utf-8, потом cp1251, потом cp866 — берём первый без ошибок."""
    for enc in ("utf-8", "cp1251", "cp866"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")

_STATUS_MAP = {
    "авториза": ("🔑", "Авторизация на FunPay"),
    "подключ": ("🌐", "Подключение..."),
    "connecting": ("🌐", "Подключение..."),
    "загружено": ("📦", "Данные загружены"),
    "создан": ("✅", "Лот создан"),
    "created": ("✅", "Лот создан"),
    "удалён": ("🗑", "Лот удалён"),
    "deleted": ("🗑", "Лот удалён"),
    "цена": ("💰", None),
    "price": ("💰", None),
    "фильтр": ("🔍", None),
    "подходящих": ("📋", None),
    "лотов:": ("📋", None),
    "не найдено": ("❌", "Не найдено"),
    "достигнут лимит": ("⏭️", None),
    "пропускаем игру": ("⏭️", None),
    "ошибка": ("⚠️", None),
    "error": ("⚠️", None),
    "остановлен": ("🔴", "Процесс остановлен"),
    "завершён": ("✅", "Завершено"),
    "✓": ("✅", None),
}

def _make_status(line_lower: str, line_raw: str) -> str | None:
    """Возвращает короткое статус-сообщение или None если строку надо пропустить."""
    for kw, (emoji, label) in _STATUS_MAP.items():
        if kw in line_lower:
            if label:
                return f"{emoji} {label}"
            else:
                short = line_raw
                for sep in ("] ", "]: ", ": "):
                    if sep in short:
                        short = short.split(sep, 1)[-1]
                return f"{emoji} {short[:120]}"
    return None

def stream_logs(chat_id, mode=None):
    global bot_process, log_streaming, running_message_id

    checked_count = 0
    deleted_count = 0
    total_count   = 0
    is_check_mode = (mode in ("c", "ca", "ci"))

    # Состояние для уведомления о публикации лота
    _cur_game  = ""
    _cur_title = ""
    _cur_price = ""

    skip_prefixes = (
        "traceback", "file ", "  file ", "    ", "during handling",
        "call stack", "--- logging error ---", "logger.info", "logger.warning",
        "await ", "lot_fp", "async def", "return ", "raise "
    )
    skip_contains = (
        "charmap", "codec can't encode", "codec can't decode",
        "unicodeencodeerror", "unicodedecodeerror", "character maps to <undefined>"
    )
    interesting = list(_STATUS_MAP.keys())

    buffer = []

    def flush_buffer():
        if buffer:
            try:
                bot.send_message(chat_id, "\n".join(buffer))
            except Exception as e:
                logger.warning(f"Не отправить: {e}")
            buffer.clear()

    try:
        if bot_process is None:
            return
        for raw in bot_process.stdout:
            if not log_streaming:
                break
            line_raw = decode_line(raw).strip()
            if not line_raw:
                continue
            line_lower = line_raw.lower()

            if any(line_lower.startswith(p) for p in skip_prefixes):
                continue
            if any(s in line_lower for s in skip_contains):
                continue

            if is_check_mode:
                m = re.search(r"проверяем\s+(\d+)\s+пар", line_lower)
                if m:
                    total_count = int(m.group(1))
                    try:
                        bot.send_message(chat_id, f"🔍 Начинаю проверку {total_count} лотов...")
                    except Exception:
                        pass
                    continue

                m = re.search(r"\[(\d+)/(\d+)\].*активен", line_lower)
                if m:
                    checked_count = int(m.group(1))
                    if total_count == 0:
                        total_count = int(m.group(2))
                    if checked_count % 50 == 0 or checked_count == 1:
                        try:
                            bot.send_message(
                                chat_id,
                                f"🔍 Проверено: {checked_count} из {total_count} | Удалено: {deleted_count}"
                            )
                        except Exception:
                            pass
                    continue

                if "недоступен" in line_lower and "удаляем" in line_lower:
                    fp_m   = re.search(r"fp:(\S+)", line_lower)
                    eld_m  = re.search(r"eld:(\S+)", line_lower)
                    fp_id  = fp_m.group(1) if fp_m else "?"
                    eld_id = eld_m.group(1) if eld_m else "?"
                    try:
                        bot.send_message(
                            chat_id,
                            f"🛒 Лот продан/снят\nFunPay: {fp_id}\nУдаляю с Eldorado..."
                        )
                    except Exception:
                        pass
                    continue

                if "eld лот" in line_lower and "удалён" in line_lower:
                    deleted_count += 1
                    try:
                        bot.send_message(
                            chat_id,
                            f"✅ Удалено с Eldorado | Проверено: {checked_count} из {total_count} | Удалено: {deleted_count}"
                        )
                    except Exception:
                        pass
                    continue

                if "проверка завершена" in line_lower:
                    continue

                if any(k in line_lower for k in ("ошибка", "error", "не удалось")):
                    try:
                        bot.send_message(chat_id, f"⚠️ {line_raw[:150]}")
                    except Exception:
                        pass
                    continue

                continue

            # ── Отслеживаем состояние для уведомления о публикации ───────
            if "игра:" in line_lower:
                m = re.search(r"игра:\s*(.+)", line_raw, re.IGNORECASE)
                if m:
                    _cur_game = m.group(1).strip()

            elif "подходящий лот" in line_lower:
                m = re.search(r"«(.+?)»", line_raw)
                if m:
                    _cur_title = m.group(1).strip()

            elif "funpay:" in line_lower and "= $" in line_lower:
                m = re.search(r"=\s*\$(\d[\d.]*)", line_raw)
                if m:
                    _cur_price = m.group(1)

            elif "+ пара: fp:" in line_lower:
                m_fp  = re.search(r"FP:(\S+?)(?:\s|->|$)", line_raw, re.IGNORECASE)
                m_eld = re.search(r"ELD:(\S+)", line_raw, re.IGNORECASE)
                if m_fp and m_eld:
                    fp_id  = m_fp.group(1).rstrip(".")
                    eld_id = m_eld.group(1).rstrip(".")
                    fp_url = f"https://funpay.com/en/lots/offer?id={fp_id}"
                    notify = (
                        f"✅ Лот опубликован\n\n"
                        f"🎯 {_cur_game}\n"
                        f"📌 {_cur_title[:80]}\n"
                        f"💵 Цена Eldorado: ${_cur_price}\n\n"
                        f"🔗 Пара:\n"
                        f"FunPay: {fp_url}\n"
                        f"Eldorado ID: {eld_id}"
                    )
                    try:
                        bot.send_message(chat_id, notify)
                    except Exception as _ne:
                        logger.warning(f"lot notify: {_ne}")

            if not any(kw in line_lower for kw in interesting):
                continue

            status = _make_status(line_lower, line_raw)
            if status:
                buffer.append(status)

            important = any(k in line_lower for k in ("ошибка", "создан", "удалён", "created", "deleted"))
            if len(buffer) >= 5 or (important and buffer):
                flush_buffer()

    except Exception as e:
        logger.error(f"Ошибка чтения логов: {e}")
    finally:
        flush_buffer()
        if bot_process:
            bot_process.wait()
        log_streaming = False
        running_message_id = None

        if is_check_mode:
            bot.send_message(
                chat_id,
                f"✅ Проверка базы завершена\n"
                f"📊 Проверено: {checked_count} из {total_count} лотов\n"
                f"🗑 Удалено: {deleted_count} лотов",
                reply_markup=main_keyboard()
            )
        else:
            bot.send_message(chat_id, "🔴 Бот остановлен", reply_markup=main_keyboard())
        bot_process = None

def stop_bot(chat_id=None):
    global bot_process, log_streaming, running_message_id
    log_streaming = False
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(3)
        except:
            bot_process.kill()
        bot_process = None
    if running_message_id and chat_id:
        running_message_id = None

# ====================== ХЕНДЛЕРЫ ======================
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    if msg.from_user.id != ALLOWED_ID:
        return
    bot.send_message(msg.chat.id, "👋 **Управление FunPay Zeus Bot**",
                     parse_mode="Markdown", reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "🚀 Запустить все")
def cmd_run_all(msg):
    if msg.from_user.id != ALLOWED_ID: return
    start_bot_process(["all"], msg.chat.id)

# ── Аккаунты ──────────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🎮 Выбрать аккаунты")
def cmd_choose_accounts(msg):
    if msg.from_user.id != ALLOWED_ID: return
    _selected[msg.chat.id] = set()
    bot.send_message(msg.chat.id, "Выберите аккаунты для запуска:",
                     reply_markup=games_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("toggle_"))
def cb_toggle(call):
    if call.from_user.id != ALLOWED_ID: return
    idx = int(call.data.split("_")[1])
    sel = _selected.setdefault(call.message.chat.id, set())
    if idx in sel:
        sel.remove(idx)
    else:
        sel.add(idx)
    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=games_keyboard(sel)
    )

@bot.callback_query_handler(func=lambda c: c.data == "start_selected")
def cb_start_selected(call):
    if call.from_user.id != ALLOWED_ID: return
    sel = _selected.get(call.message.chat.id, set())
    if not sel:
        bot.answer_callback_query(call.id, "Ничего не выбрано!")
        return
    indices_str = ",".join(str(i + 1) for i in sorted(sel))
    bot.edit_message_text(f"▶️ Запускаю аккаунты: {indices_str}",
                          call.message.chat.id, call.message.message_id)
    _selected.pop(call.message.chat.id, None)
    start_bot_process([indices_str], call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "delete_selected")
def cb_delete_selected(call):
    if call.from_user.id != ALLOWED_ID: return
    sel = _selected.get(call.message.chat.id, set())
    if not sel:
        bot.answer_callback_query(call.id, "Ничего не выбрано!")
        return
    indices_str = ",".join(str(i + 1) for i in sorted(sel))
    bot.edit_message_text(f"🗑 Удаляю лоты для аккаунтов: {indices_str}",
                          call.message.chat.id, call.message.message_id)
    _selected.pop(call.message.chat.id, None)
    start_bot_process(["d", indices_str], call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(call):
    if call.from_user.id != ALLOWED_ID: return
    bot.edit_message_text("❌ Отменено", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_keyboard())

# ── Предметы (CustomItem) ─────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🎯 Выбрать предметы")
def cmd_choose_items(msg):
    if msg.from_user.id != ALLOWED_ID: return
    _items_selected[msg.chat.id] = set()
    bot.send_message(msg.chat.id, "Выберите предметы для запуска:",
                     reply_markup=items_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("item_toggle_"))
def cb_item_toggle(call):
    if call.from_user.id != ALLOWED_ID: return
    idx = int(call.data.split("_")[2])
    sel = _items_selected.setdefault(call.message.chat.id, set())
    if idx in sel:
        sel.remove(idx)
    else:
        sel.add(idx)
    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=items_keyboard(sel)
    )

@bot.callback_query_handler(func=lambda c: c.data == "item_start")
def cb_item_start(call):
    if call.from_user.id != ALLOWED_ID: return
    sel = _items_selected.get(call.message.chat.id, set())
    if not sel:
        bot.answer_callback_query(call.id, "Ничего не выбрано!")
        return
    indices_str = ",".join(str(i + 1) for i in sorted(sel))
    bot.edit_message_text(f"▶️ Запускаю предметы: {indices_str}",
                          call.message.chat.id, call.message.message_id)
    _items_selected.pop(call.message.chat.id, None)
    start_bot_process([indices_str], call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "item_delete")
def cb_item_delete(call):
    if call.from_user.id != ALLOWED_ID: return
    sel = _items_selected.get(call.message.chat.id, set())
    if not sel:
        bot.answer_callback_query(call.id, "Ничего не выбрано!")
        return
    indices_str = ",".join(str(i + 1) for i in sorted(sel))
    bot.edit_message_text(f"🗑 Удаляю лоты для предметов: {indices_str}",
                          call.message.chat.id, call.message.message_id)
    _items_selected.pop(call.message.chat.id, None)
    start_bot_process(["d", indices_str], call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "item_cancel")
def cb_item_cancel(call):
    if call.from_user.id != ALLOWED_ID: return
    bot.edit_message_text("❌ Отменено", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_keyboard())

# ── Общие кнопки ──────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "⛔ Остановить бота")
def cmd_stop(msg):
    if msg.from_user.id != ALLOWED_ID: return
    stop_bot(msg.chat.id)
    bot.send_message(msg.chat.id, "⛔ Бот остановлен", reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📋 Логи")
def cmd_logs(msg):
    if msg.from_user.id != ALLOWED_ID: return
    log_files = sorted(LOG_DIR.glob("bot_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if log_files:
        try:
            text = log_files[0].read_text(encoding="utf-8", errors="ignore")[-2000:]
            bot.send_message(msg.chat.id, f"**{log_files[0].name}**\n\n```\n{text}\n```", parse_mode="Markdown")
        except:
            bot.send_message(msg.chat.id, "Не удалось прочитать лог")
    else:
        bot.send_message(msg.chat.id, "Логов пока нет")

@bot.message_handler(func=lambda m: m.text == "🔍 Проверить аккаунты")
def cmd_check_accounts(msg):
    if msg.from_user.id != ALLOWED_ID: return
    if is_running():
        bot.send_message(msg.chat.id, "⚠️ Сначала остановите бота!")
        return
    bot.send_message(msg.chat.id, "🔍 Запускаю проверку аккаунтов...\n⚠️ Chrome должен быть открыт!")
    start_bot_process(["ca"], msg.chat.id)


@bot.message_handler(func=lambda m: m.text == "🎯 Проверить предметы")
def cmd_check_items(msg):
    if msg.from_user.id != ALLOWED_ID: return
    if is_running():
        bot.send_message(msg.chat.id, "⚠️ Сначала остановите бота!")
        return
    bot.send_message(msg.chat.id, "🎯 Запускаю проверку предметов...\n⚠️ Chrome должен быть открыт!")
    start_bot_process(["ci"], msg.chat.id)

@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def cmd_status(msg):
    if msg.from_user.id != ALLOWED_ID: return
    cfg = load_config()
    games = cfg.get("games", [])

    game_id_to_name = {str(g.get("eldorado_game_id", "")): g["name"] for g in games if g.get("eldorado_game_id")}

    enabled  = [g["name"] for g in games if g.get("enabled", True)]
    disabled = [g["name"] for g in games if not g.get("enabled", True)]
    status = "🟢 Запущен" if is_running() else "🔴 Остановлен"

    from datetime import datetime
    from pathlib import Path
    import json as _json
    today      = datetime.now().strftime("%Y-%m-%d")
    sales_file = Path("sales_log.json")
    sales_text = ""
    try:
        if sales_file.exists():
            sales = _json.loads(sales_file.read_text(encoding="utf-8"))
            today_sales = [s for s in sales if s.get("sold_date") == today]
            if today_sales:
                counts = {}
                for s in today_sales:
                    gid  = str(s.get("eldorado_game_id", ""))
                    name = game_id_to_name.get(gid) or gid or "Неизвестно"
                    counts[name] = counts.get(name, 0) + 1
                lines = "\n".join(f"  • {name}: {cnt} шт." for name, cnt in sorted(counts.items(), key=lambda x: -x[1]))
                sales_text = f"\n\n💰 Продано сегодня ({len(today_sales)} всего):\n{lines}"
            else:
                sales_text = "\n\n💰 Продаж сегодня пока нет"
    except Exception as e:
        sales_text = f"\n\n💰 Ошибка чтения продаж: {e}"

    text = (
        f"📊 Статус бота: {status}\n\n"
        f"✅ Активных игр: {len(enabled)}\n"
        + "\n".join(f"  • {n}" for n in enabled)
        + (f"\n\n⏸ Отключённых: {len(disabled)}\n" + "\n".join(f"  • {n}" for n in disabled) if disabled else "")
        + sales_text
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📄 База лотов")
def cmd_lot_pairs(msg):
    if msg.from_user.id != ALLOWED_ID: return
    _send_lot_pairs_file(msg.chat.id)


@bot.message_handler(func=lambda m: m.text == "🗑 Удалить лоты")
def cmd_delete_lots(msg):
    if msg.from_user.id != ALLOWED_ID: return
    if is_running():
        bot.send_message(msg.chat.id, "⚠️ Сначала остановите бота!")
        return
    _selected[msg.chat.id] = set()
    bot.send_message(msg.chat.id, "Выберите игры для удаления лотов:",
                     reply_markup=games_keyboard())

# ====================== ЗАПУСК С АВТОПЕРЕЗАПУСКОМ ======================
if __name__ == "__main__":
    try:
        me = bot.get_me()
        logger.info(f"✅ Бот @{me.username} подключён")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Telegram: {e}")
        sys.exit(1)

    try:
        bot.send_message(ALLOWED_ID, "✅ **Telegram Control запущен!**\nВыберите действие:",
                         parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        logger.warning(f"Не удалось отправить стартовое сообщение: {e}")

    while True:
        try:
            logger.info("🔄 Запуск polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except KeyboardInterrupt:
            logger.info("⛔ Остановлено вручную")
            break
        except Exception as e:
            logger.error(f"💥 Polling упал: {e}", exc_info=True)
            logger.info("⏳ Перезапуск через 10 секунд...")
            time.sleep(10)
