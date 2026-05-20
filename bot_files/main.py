"""
main.py — подключается к уже открытому браузеру через CDP.
Запустите Chrome с флагом: --remote-debugging-port=9222
"""
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright

from funpay_scraper import FunPayScraper, FunPayLot
from eldorado_bot import EldoradoBot
from lot_sync import LotSyncManager

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_DIR / f"bot_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("main")

CDP_URL = "http://127.0.0.1:9222"
UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def load_config() -> dict:
    with open("config.json", encoding="utf-8") as f:
        return json.load(f)


def _used_lots_path(game_name: str) -> Path:
    safe = game_name.replace(" ", "_").replace("/", "_")
    return Path(f"used_lots_{safe}.json")


def load_used_lots(game_name: str = "") -> set:
    p = _used_lots_path(game_name) if game_name else Path("used_lots.json")
    if not p.exists():
        return set()
    with open(p, encoding="utf-8") as f:
        return set(json.load(f))


def save_used_lot(lot_id: str, game_name: str = ""):
    p = _used_lots_path(game_name) if game_name else Path("used_lots.json")
    used = set()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            used = set(json.load(f))
    used.add(lot_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(list(used), f)


def clear_used_lots(game_name: str = ""):
    p = _used_lots_path(game_name) if game_name else Path("used_lots.json")
    p.write_text("[]", encoding="utf-8")


def select_games(games: list[dict]):
    # Если запущено с аргументом (из telegram_control.py) — не спрашиваем
    if len(sys.argv) > 1:
        raw = sys.argv[1].strip()
        logger.info(f"Режим из аргумента: '{raw}'")
    else:
        print("\n" + "=" * 55)
        print("  Выберите режим для запуска:")
        print("=" * 55)
        print("  [d] Массовое удаление лотов (Eldorado)")
        print("  [c] Проверить базу на проданные товары")
        for i, g in enumerate(games):
            status = "+" if g.get("enabled", True) else "-"
            print(f"  [{i+1}] {status} {g['name']}")
        print("=" * 55)
        print("  Введите номера через запятую (например: 1,3)")
        print("  Или нажмите Enter чтобы использовать config.json")
        print("=" * 55)
        raw = input("Выбор: ").strip()

    if raw.lower() == "c":
        return "clean_storage"

    if raw.lower() == "ca":
        return "clean_accounts"

    if raw.lower() == "ci":
        return "clean_items"

    if raw.lower() == "d":
        # Второй аргумент — выбор игр для удаления
        if len(sys.argv) > 2:
            sub = sys.argv[2].strip().lower()
        else:
            print("\n" + "=" * 55)
            print("  Выберите игры для удаления:")
            print("  (номера через запятую или 'all')")
            print("=" * 55)
            for i, g in enumerate(games):
                print(f"  [{i+1}] {g['name']}")
            print("=" * 55)
            sub = input("Выбор: ").strip().lower()

        if sub == "all":
            selected_games = games[:]
        else:
            selected_games = []
            for part in sub.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(games):
                        selected_games.append(games[idx])

        if not selected_games:
            logger.warning("Игры не выбраны — отмена")
            return []

        return {"mode": "mass_delete", "games": selected_games}

    if not raw or raw.lower() == "all":
        selected = [g for g in games if g.get("enabled", True)]
        names = [g['name'] for g in selected]
        logger.info(f"Используем настройки из config: {names}")
        return selected

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(games):
                selected.append(games[idx])

    if not selected:
        logger.warning("Ничего не выбрано — берём все enabled из config")
        return [g for g in games if g.get("enabled", True)]

    names = [g['name'] for g in selected]
    logger.info(f"Выбраны режимы: {names}")
    return selected


async def _resolve_eldorado_lot_id(
    eldorado,
    category: str,
    ids_before: set,
    result,
    max_attempts: int = 5,
    delay: float = 5.0,
) -> str | None:
    """
    Определяет eldorado_lot_id после создания лота.

    Приоритет 1: create_lot() вернул UUID напрямую.
    Приоритет 2: сравниваем get_my_lots() до/после с повторными попытками.

    Возвращает UUID-строку или None если не удалось.
    """
    # Приоритет 1: create_lot вернул UUID напрямую
    if isinstance(result, str) and UUID_RE.match(result):
        logger.info(f"UUID получен напрямую от create_lot: {result}")
        return result

    # Приоритет 2: ищем новый лот через сравнение списков
    logger.info(f"UUID не в ответе — ищем через get_my_lots (до {max_attempts} попыток)...")
    for attempt in range(1, max_attempts + 1):
        await asyncio.sleep(delay)
        try:
            lots_after = await eldorado.get_my_lots(category)
        except Exception as e:
            logger.warning(f"get_my_lots попытка {attempt}/{max_attempts} ошибка: {e}")
            continue

        ids_after = {l.lot_id for l in lots_after}
        new_lots  = [l for l in lots_after if l.lot_id not in ids_before]
        valid_new = [l for l in new_lots if UUID_RE.match(l.lot_id or "")]

        logger.info(f"Попытка {attempt}/{max_attempts}: лотов до={len(ids_before)}, после={len(ids_after)}, новых={len(new_lots)}, UUID={len(valid_new)}")

        if valid_new:
            found = valid_new[-1].lot_id
            logger.info(f"UUID найден сравнением (попытка {attempt}): {found}")
            return found

        if new_lots:
            logger.warning(
                f"Попытка {attempt}/{max_attempts}: новые лоты есть, но ID не UUID: "
                f"{[l.lot_id for l in new_lots]}"
            )
            # ID не UUID — нет смысла повторять
            break

        logger.debug(f"Попытка {attempt}/{max_attempts}: новых лотов пока нет, ждём {delay}с...")

    logger.warning("_resolve_eldorado_lot_id: UUID так и не определён после всех попыток")
    return None


SERVER_KEYWORDS = {
    # Albion Online
    "albion": {
        "skip": ["asia", "singapore", "east", "america", "washington", "americas", "west", "na", "us"],
        "2": ["europe", "amsterdam", "eu"],
    },
    # Zenless Zone Zero — только EU, остальное пропускаем
    "zenless": {
        "skip": ["asia", "america", "global", "na", "us", "cn", "china", "sea", "tw", "sar"],
        "1": ["europe", "eu"],
    },
}

def detect_trade_environment(game: dict, lot_title: str, lot_description: str) -> str | None:
    """Автоопределяет tradeEnvironmentId по ключевым словам в названии/описании лота."""
    base_env = game.get("trade_environment_id")
    game_name = game.get("name", "").lower()

    # Ищем подходящий маппинг по названию игры
    mapping = None
    for key, m in SERVER_KEYWORDS.items():
        if key in game_name:
            mapping = m
            break

    if not mapping:
        return base_env

    text = (lot_title + " " + lot_description).lower()

    # Пропускаем нежелательные серверы
    skip_keywords = mapping.get("skip", [])
    for kw in skip_keywords:
        if kw in text:
            logger.info(f"Лот пропущен — нежелательный сервер ({kw})")
            return None

    for env_id, keywords in mapping.items():
        if env_id == "skip":
            continue
        if any(kw in text for kw in keywords):
            logger.info(f"Сервер определён автоматически: tradeEnvironmentId={env_id}")
            return env_id

    logger.info(f"Сервер не определён по ключевым словам, используем default: {base_env}")
    return base_env


async def process_game(game, funpay, eldorado, sync_manager, mode, global_threshold, session_used: set, seller_blacklist: list = None):
    name          = game["name"]
    category      = game.get("eldorado_category") or game.get("zeusx_category", "")
    max_lots      = game.get("max_lots", 50)
    lots_per_pass = game.get("lots_per_pass", 5)
    multiplier    = game.get("price_multiplier", 2.0)
    threshold     = game.get("lot_threshold", global_threshold)
    game_id       = game.get("eldorado_game_id")

    logger.info(f"\n{'─' * 55}\n  Игра: {name}\n{'─' * 55}")

    if mode == "delete_only":
        my_lots = await eldorado.get_my_lots(category)
        if my_lots:
            deleted = await eldorado.delete_lots_batch(my_lots, len(my_lots))
            logger.info(f"Удалено: {deleted}")
        return

    my_lots  = await eldorado.get_my_lots(category)
    my_count = len(my_lots)
    total    = await eldorado.get_total_lots_count()
    logger.info(f"Моих лотов: {my_count}/{max_lots} | Всего: {total} | Порог: {threshold}")

    if total >= threshold:
        to_del = min(my_count, lots_per_pass)
        if to_del > 0:
            await eldorado.delete_lots_batch(my_lots, to_del)
        return

    if my_count >= max_lots:
        logger.info(f"Лимит max_lots={max_lots} достигнут.")
        return

    lot_fp = await funpay.get_best_lot(
        lots_url=game["funpay_url"],
        min_seller_reviews=game.get("min_seller_reviews", 0),
        require_auto_delivery=game.get("require_auto_delivery", False),
        min_price_usd=game.get("min_funpay_price_usd", 0.0),
        max_price_usd=game.get("max_funpay_price_usd", 999999.0),
        used_lot_ids=session_used,
        funpay_tab=game.get("funpay_tab", None),
        seller_blacklist=seller_blacklist,
    )
    if lot_fp is None:
        logger.warning("Не удалось получить лот с FunPay")
        return

    our_price   = round(lot_fp.price * multiplier, 2)
    logger.info(f"FunPay: ${lot_fp.price:.4f} x {multiplier} = ${our_price:.2f}")

    free_slots  = max_lots - my_count
    to_create   = min(free_slots, lots_per_pass)
    created     = 0
    _attempts   = 0
    current_lot = lot_fp

    while created < to_create and _attempts < to_create + 20:
        _attempts += 1
        our_price = round(current_lot.price * multiplier, 2)

        # Помечаем как использованный ДО создания
        if current_lot.lot_id:
            session_used.add(current_lot.lot_id)
            save_used_lot(current_lot.lot_id, name)

        # Используем region из лота если есть, иначе title+description
        lot_text_for_region = current_lot.region if current_lot.region else (current_lot.title + " " + (current_lot.description or ""))
        trade_env = detect_trade_environment(game, lot_text_for_region, "")

        # Пропускаем лот если сервер нежелательный (например Asia)
        if trade_env is None and any(k in game.get("name", "").lower() for k in SERVER_KEYWORDS):
            if current_lot.lot_id:
                session_used.add(current_lot.lot_id)
                save_used_lot(current_lot.lot_id, name)
            # Берём следующий лот
            next_lot = await funpay.get_best_lot(
                lots_url=game["funpay_url"],
                min_seller_reviews=game.get("min_seller_reviews", 0),
                require_auto_delivery=game.get("require_auto_delivery", False),
                min_price_usd=game.get("min_funpay_price_usd", 0.0),
                max_price_usd=game.get("max_funpay_price_usd", 999999.0),
                used_lot_ids=session_used,
                funpay_tab=game.get("funpay_tab", None),
                seller_blacklist=seller_blacklist,
            )
            if next_lot is None:
                logger.warning("FunPay: подходящих лотов больше нет")
                break
            current_lot = next_lot
            continue

        result = await eldorado.create_lot(
            category=category,
            title=current_lot.title,
            description=current_lot.description,
            price_usd=our_price,
            dropdowns=game.get("eldorado_dropdowns") or game.get("zeusx_dropdowns", []),
            game_id=game_id,
            image_path=game.get("image_path"),
            image_paths=current_lot.image_paths if current_lot.image_paths else None,
            lot_folder=str(Path("lot_images") / current_lot.lot_id) if current_lot.lot_id else None,
            trade_environment_id=trade_env,
        )

        # Лимит 100 лотов — пропускаем всю игру
        if result == "MAX_LOTS_REACHED":
            logger.warning(f"⏭️ [{name}] Достигнут лимит 100 активных лотов — пропускаем игру")
            break

        if result:
            created += 1

            # ── Проверяем что лот реально активен на Eldorado ──────────────
            if isinstance(result, str) and UUID_RE.match(result):
                if category == "CustomItem":
                    # verify_lot_active использует Account-API — CustomItem там не отображается
                    verified = result
                    logger.info(f"[{name}] CustomItem: проверка активности пропущена, UUID: {result}")
                else:
                    verified = await eldorado.verify_lot_active(
                        lot_id=result,
                        max_attempts=4,
                        delay=5.0,
                    )
            else:
                logger.warning(f"[{name}] create_lot не вернул UUID — пропускаем запись пары")
                verified = None

            # Лимит обнаружен при проверке
            if verified == "MAX_LOTS_REACHED":
                logger.warning(f"⏭️ [{name}] Лимит 100 лотов подтверждён при проверке — пропускаем игру")
                break

            eldorado_lot_id = verified  # UUID если подтверждён, None если нет

            if eldorado_lot_id and current_lot.lot_id:
                # href — для удобства, его отсутствие не блокирует запись в базу
                funpay_url = current_lot.href or f"https://funpay.com/en/lots/offer?id={current_lot.lot_id}"
                sync_manager.register(
                    funpay_lot_id=current_lot.lot_id,
                    funpay_lot_url=funpay_url,
                    eldorado_lot_id=eldorado_lot_id,
                    eldorado_game_id=str(game_id) if game_id else "",
                    description=current_lot.title,
                    category=category,
                )
                logger.info(f"+ Пара: FP:{current_lot.lot_id} -> ELD:{eldorado_lot_id}")
                try:
                    from lot_doc_manager import rebuild_from_pairs
                    rebuild_from_pairs(sync_manager.storage.all())
                except Exception as e:
                    logger.debug(f"lot_doc: {e}")
            else:
                missing = []
                if not eldorado_lot_id:
                    missing.append("eldorado_lot_id не определён")
                if not current_lot.lot_id:
                    missing.append("funpay lot_id пустой")
                logger.warning(
                    f"LotSync: пара НЕ сохранена — {', '.join(missing)}. "
                    f"title={current_lot.title[:60]}"
                )
                # ── Записываем в missing_pairs.json для ручной проверки ──
                try:
                    mp = Path("missing_pairs.json")
                    missed = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
                    missed.append({
                        "title":         current_lot.title,
                        "funpay_lot_id": current_lot.lot_id or "",
                        "funpay_url":    current_lot.href or "",
                        "eldorado_id":   eldorado_lot_id or "",
                        "reason":        ", ".join(missing),
                        "time":          datetime.now().isoformat(),
                    })
                    mp.write_text(json.dumps(missed, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.warning(f"LotSync: запись добавлена в missing_pairs.json")
                except Exception as me:
                    logger.debug(f"missing_pairs write error: {me}")

        if created < to_create:
            next_lot = await funpay.get_best_lot(
                lots_url=game["funpay_url"],
                min_seller_reviews=game.get("min_seller_reviews", 0),
                require_auto_delivery=game.get("require_auto_delivery", False),
                min_price_usd=game.get("min_funpay_price_usd", 0.0),
                max_price_usd=game.get("max_funpay_price_usd", 999999.0),
                used_lot_ids=session_used,
                funpay_tab=game.get("funpay_tab", None),
                seller_blacklist=seller_blacklist,
            )
            if next_lot:
                current_lot = next_lot
            else:
                break
        await asyncio.sleep(2)

    logger.info(f"+ Создано {created}/{to_create} лотов для {name}")

    my_lots_now = await eldorado.get_my_lots(category)
    if len(my_lots_now) > max_lots:
        excess = len(my_lots_now) - max_lots
        await eldorado.delete_lots_batch(my_lots_now, excess)


async def main():
    cfg              = load_config()
    mode             = cfg.get("mode", "list_and_delete")
    interval         = cfg.get("loop_interval_seconds", 35)
    global_threshold = cfg.get("global_lot_threshold", 2000)
    sync_interval    = cfg.get("sync_check_interval_seconds", 300)
    seller_blacklist = [s.lower().strip() for s in cfg.get("seller_blacklist", [])]
    active_games     = select_games(cfg["games"])

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(CDP_URL, timeout=60000)
            logger.info(f"+ Подключились к Chrome на {CDP_URL}")
        except Exception as e:
            logger.error(f"Не удалось подключиться к Chrome: {e}")
            logger.error("  chrome.exe --remote-debugging-port=9222")
            return

        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            logger.info(f"+ Используем существующий контекст (вкладок: {len(context.pages)})")
        else:
            context = await browser.new_context()
            logger.warning("Контекст не найден — создан новый (нужна авторизация)")

        funpay   = FunPayScraper(context)
        eldorado = EldoradoBot(context)

        logged = await eldorado.is_logged_in()
        if not logged:
            logger.error("Не авторизованы на eldorado.gg!")
            logger.error("Войдите в аккаунт в открытом браузере и перезапустите бота.")
            return

        logger.info("+ Авторизация подтверждена — запускаем бота!")

        sync_manager = LotSyncManager(context, check_interval=sync_interval)
        pairs_count  = sync_manager.storage.count()
        if pairs_count > 0:
            logger.info(f"LotSync: загружено {pairs_count} пар из прошлой сессии")

        # ── [c / ca / ci] Проверка базы ──────────────────────────────────
        if active_games in ("clean_storage", "clean_accounts", "clean_items"):
            _cat_filter = {
                "clean_accounts": "Account",
                "clean_items":    "CustomItem",
            }.get(active_games)
            _cat_label = {
                "clean_storage":  "все лоты",
                "clean_accounts": "аккаунты",
                "clean_items":    "предметы",
            }.get(active_games, "")
            logger.info(f"Проверяем базу ({_cat_label}) на проданные/недоступные лоты...")
            deleted = await sync_manager.check_once(category_filter=_cat_filter)
            logger.info(f"Очистка завершена. Удалено лотов: {deleted}")
            try:
                from lot_doc_manager import rebuild_from_pairs
                rebuild_from_pairs(sync_manager.storage.all())
            except Exception as e:
                logger.debug(f"lot_doc: {e}")
            return

        # ── [d] Массовое удаление через Dashboard UI ──────────────────────
        if isinstance(active_games, dict) and active_games.get("mode") == "mass_delete":
            games_to_delete = active_games.get("games", [])
            total_deleted = 0
            custom_item_games = []  # хранилище уже очищается внутри check_once

            for game in games_to_delete:
                game_name    = game.get("name", "")
                display_name = game.get("eldorado_display_name") or game_name
                category     = game.get("eldorado_category", "Account")

                if category == "CustomItem":
                    # CustomItem: сначала проверяем FunPay, удаляем только недоступные лоты
                    game_id_str = str(game.get("eldorado_game_id", ""))
                    logger.info(f"Проверяем FunPay и удаляем недоступные лоты для «{game_name}»...")
                    deleted = await sync_manager.check_once(
                        category_filter="CustomItem",
                        game_id_filter=game_id_str if game_id_str else None,
                    )
                    logger.info(f"{game_name}: удалено {deleted} CustomItem лотов (FunPay проверен)")
                    total_deleted += deleted
                    custom_item_games.append(game)
                else:
                    logger.info(f"Удаляем лоты для «{game_name}» (Eldorado: «{display_name}»)...")
                    deleted = await eldorado.mass_delete_by_game(display_name)
                    total_deleted += deleted
                    logger.info(f"{game_name}: удалено {deleted} лотов")

            logger.info(f"\nВсего удалено на сайте: {total_deleted} лотов")

            if total_deleted > 0:
                # Если запущено из Telegram (есть аргументы) — автоматически очищаем базы
                from_telegram = len(sys.argv) > 1
                if from_telegram:
                    confirm = "yes"
                    logger.info(f"Удалено лотов на сайте: {total_deleted} — автоочистка баз (режим Telegram)")
                else:
                    print("\n" + "=" * 55)
                    print(f"  Удалено лотов на сайте: {total_deleted}")
                    print("  Очистить базы lot_pairs.json и used_lots?")
                    print("=" * 55)
                    confirm = input("  Введите 'yes' для подтверждения: ").strip().lower()
                if confirm == "yes":
                    for game in games_to_delete:
                        game_id   = str(game.get("eldorado_game_id", ""))
                        game_name = game.get("name", "")
                        cat       = game.get("eldorado_category", "Account")
                        if cat != "CustomItem":
                            # Account: все лоты удалены — чистим всю запись в хранилище
                            sync_manager.storage.clear_game_from_storage(game_id)
                        # CustomItem: check_once уже удалил только проданные пары — не трогаем остальные
                        clear_used_lots(game_name)
                    logger.info("Базы очищены.")
                else:
                    logger.info("Очистка баз отменена.")
            else:
                logger.info("Лоты не удалялись — базы не тронуты.")

            logger.info("Готово. Бот завершил работу.")
            return

        if not isinstance(active_games, list) or not active_games:
            logger.info("Нет активных игр. Завершение.")
            return

        logger.info(f"Режим: {mode} | Интервал: {interval}с | Игр: {len(active_games)}")
        logger.info("LotSync: автопроверка отключена. Используйте [c] для проверки базы.")

        # Загружаем использованные лоты для всех активных игр
        session_used = set()
        for g in active_games:
            session_used |= load_used_lots(g.get("name", ""))
        logger.info(f"Загружено использованных лотов: {len(session_used)}")

        iteration = 0
        try:
            while True:
                iteration += 1
                logger.info(f"\n{'#' * 55}")
                logger.info(f"  Итерация #{iteration} | {datetime.now():%Y-%m-%d %H:%M:%S}")
                logger.info(f"  Отслеживается пар FP->ELD: {sync_manager.storage.count()}")
                logger.info(f"{'#' * 55}")

                for game in active_games:
                    try:
                        await process_game(
                            game, funpay, eldorado, sync_manager,
                            mode, global_threshold, session_used,
                            seller_blacklist=seller_blacklist
                        )
                    except Exception as e:
                        logger.error(f"Ошибка в игре {game['name']}: {e}", exc_info=True)
                    await asyncio.sleep(3)

                logger.info(f"\nСледующий цикл через {interval} сек.")
                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
