"""
lot_sync.py — синхронизация лотов FunPay ↔ Eldorado.gg

Логика:
  1. При выставлении лота сохраняем пару funpay_lot_id → eldorado_lot_id в JSON-файл.
  2. Периодически проверяем каждый FunPay лот — доступен ли он ещё.
  3. Если лот продан / снят / недоступен — удаляем соответствующий лот на Eldorado.gg.

Формат lot_pairs.json:
  {
    "accounts": [ ...пары аккаунтов... ],
    "items":    [ ...пары предметов... ]
  }
"""

import logging
import asyncio
import json
import aiohttp
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from playwright.async_api import BrowserContext

logger = logging.getLogger("lot_sync")

SYNC_FILE  = Path("lot_pairs.json")
SALES_FILE = Path("sales_log.json")


def log_sale(pair):
    """Записывает продажу в sales_log.json."""
    import time
    from datetime import datetime
    try:
        data = json.loads(SALES_FILE.read_text(encoding="utf-8")) if SALES_FILE.exists() else []
    except Exception:
        data = []
    data.append({
        "funpay_lot_id":   pair.funpay_lot_id,
        "eldorado_lot_id": pair.eldorado_lot_id,
        "eldorado_game_id": pair.eldorado_game_id or "",
        "description":     pair.description or "",
        "category":        pair.category or "Account",
        "sold_at":         time.time(),
        "sold_date":       datetime.now().strftime("%Y-%m-%d"),
    })
    try:
        SALES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"sales_log: ошибка записи: {e}")


@dataclass
class LotPair:
    funpay_lot_id: str
    funpay_lot_url: str
    eldorado_lot_id: str
    eldorado_game_id: str
    created_at: float = 0.0
    description: str = ""
    category: str = "Account"   # "Account" или "CustomItem"


class LotPairStorage:
    """Хранилище пар FunPay ID → Eldorado ID в JSON-файле.

    Формат файла:
        { "accounts": [...], "items": [...] }

    Обратно совместим со старым форматом (плоский список).
    """

    def __init__(self, filepath: Path = SYNC_FILE):
        self.filepath = filepath
        self._pairs: dict[str, LotPair] = {}  # ключ: funpay_lot_id
        self._load()

    def _load(self):
        if not self.filepath.exists():
            return
        try:
            raw = json.loads(self.filepath.read_text(encoding="utf-8"))
            valid_fields = {f for f in LotPair.__dataclass_fields__}

            # Поддержка старого формата (плоский список) и нового (dict с секциями)
            if isinstance(raw, list):
                records = raw                                           # старый формат
            elif isinstance(raw, dict):
                records = raw.get("accounts", []) + raw.get("items", [])  # новый формат
            else:
                records = []

            loaded = 0
            for item in records:
                try:
                    filtered = {k: v for k, v in item.items() if k in valid_fields}
                    p = LotPair(**filtered)
                    self._pairs[p.funpay_lot_id] = p
                    loaded += 1
                except Exception as e:
                    logger.warning(f"LotSync: пропущена запись {item.get('funpay_lot_id', '?')}: {e}")

            logger.info(f"LotSync: загружено пар: {loaded} (пропущено: {len(records) - loaded})")
        except Exception as e:
            logger.warning(f"LotSync: ошибка загрузки {self.filepath}: {e}")

    def _save(self):
        try:
            accounts = [asdict(p) for p in self._pairs.values() if p.category != "CustomItem"]
            items    = [asdict(p) for p in self._pairs.values() if p.category == "CustomItem"]
            data = {"accounts": accounts, "items": items}
            self.filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"LotSync: ошибка сохранения: {e}")

    def add(self, pair: LotPair):
        import time
        if not pair.created_at:
            pair.created_at = time.time()
        self._pairs[pair.funpay_lot_id] = pair
        self._save()
        logger.info(
            f"LotSync: сохранена пара [{pair.category}] "
            f"FP:{pair.funpay_lot_id} → ELD:{pair.eldorado_lot_id}"
        )
        try:
            from lot_doc_manager import rebuild_from_pairs
            rebuild_from_pairs(list(self._pairs.values()))
        except Exception as e:
            logger.debug(f"lot_doc: ошибка обновления docx: {e}")

    def remove(self, funpay_lot_id: str):
        if funpay_lot_id in self._pairs:
            del self._pairs[funpay_lot_id]
            self._save()
            try:
                from lot_doc_manager import rebuild_from_pairs
                rebuild_from_pairs(list(self._pairs.values()))
            except Exception as e:
                logger.debug(f"lot_doc: ошибка обновления docx: {e}")

    def all(self) -> list[LotPair]:
        return list(self._pairs.values())

    def count(self) -> int:
        return len(self._pairs)

    def clear_game_from_storage(self, eldorado_game_id: str):
        """Удаляет из хранилища все пары с указанным eldorado_game_id."""
        to_remove = [
            p.funpay_lot_id for p in self.all()
            if p.eldorado_game_id == eldorado_game_id
        ]
        removed = 0
        for funpay_id in to_remove:
            if funpay_id in self._pairs:
                del self._pairs[funpay_id]
                removed += 1
        if removed:
            self._save()
            try:
                from lot_doc_manager import rebuild_from_pairs
                rebuild_from_pairs(list(self._pairs.values()))
            except Exception as e:
                logger.debug(f"lot_doc: ошибка обновления docx: {e}")
        logger.info(f"LotSync: удалено {removed} пар для game_id={eldorado_game_id}")
        return removed


class FunPayChecker:
    """Проверяет доступность лота на FunPay через HTTP (без браузера)."""

    async def is_lot_available(self, lot_url: str, lot_id: str) -> bool:
        import re as _re

        try:
            if not lot_url.startswith("http"):
                lot_url = f"https://funpay.com{lot_url}"

            if lot_id and "id=" not in lot_url:
                sep = "&" if "?" in lot_url else "?"
                lot_url = f"{lot_url}{sep}id={lot_id}"

            lot_url = lot_url.replace("&setlocale=en", "").replace("?setlocale=en&", "?").replace("?setlocale=en", "")

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    lot_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True,
                ) as resp:
                    final_url = str(resp.url)
                    logger.info(f"LotSync: финальный URL: {final_url}")

                    if resp.status == 404:
                        logger.info(f"LotSync: FP:{lot_id} → 404 (удалён)")
                        return False

                    m = _re.search(r"[?&]id=(\d+)", final_url)
                    if m and m.group(1) != str(lot_id):
                        logger.info(f"LotSync: FP:{lot_id} → редирект на {m.group(1)} (продан/снят)")
                        return False

                    if resp.status != 200:
                        logger.warning(f"LotSync: FP:{lot_id} → HTTP {resp.status} — считаем активным")
                        return True

                    html = await resp.text()
                    html_lower = html.lower()

                    sold_markers = [
                        "lot not found", "лот не найден", "sold out",
                        "offer is not available", "предложение недоступно",
                        "this offer has been sold", "page not found",
                        "offer not found",
                    ]
                    for marker in sold_markers:
                        if marker in html_lower:
                            logger.info(f"LotSync: FP:{lot_id} → маркер «{marker}» (удалён)")
                            return False

                    logger.info(f"LotSync: FP:{lot_id} → активен (HTTP 200, маркеров удаления нет)")
                    return True

        except asyncio.TimeoutError:
            logger.warning(f"LotSync: таймаут проверки FP:{lot_id} — считаем активным")
            return True
        except Exception as e:
            logger.warning(f"LotSync: ошибка проверки FP:{lot_id}: {e} — считаем активным")
            return True


class EldoradoDeleter:
    """Удаляет лоты на Eldorado.gg через API или браузер."""

    BASE = "https://www.eldorado.gg"

    def __init__(self, context: BrowserContext):
        self.context = context

    async def delete_by_id(self, eldorado_lot_id: str) -> bool:
        page = await self.context.new_page()
        try:
            captured_headers = {}

            async def handle_request(request):
                hdrs = request.headers
                if "x-xsrf-token" in hdrs or "X-XSRF-Token" in hdrs:
                    captured_headers.update(hdrs)

            page.on("request", handle_request)

            await page.goto(
                f"{self.BASE}/dashboard/offers?category=Account&pageIndex=1&pageSize=40",
                wait_until="domcontentloaded", timeout=20000
            )
            await asyncio.sleep(3)

            xsrf       = (captured_headers.get("x-xsrf-token") or captured_headers.get("X-XSRF-Token") or "")
            build_time = captured_headers.get("x-client-build-time", "")
            ga_session = captured_headers.get("x-ga-sessionid", "Unknown")
            ga_user    = captured_headers.get("x-ga-userpseudoid", "")
            ms_vid     = captured_headers.get("x-ms-vid", "")
            ms_sid     = captured_headers.get("x-ms-sid", "")
            nsure      = captured_headers.get("nsure-device-id", "")

            logger.info(f"LotSync: XSRF токен перехвачен (len={len(xsrf)})")

            result = await page.evaluate("""
                async (args) => {
                    var url = '/api/flexibleOffersUser/me/' + args.lotId;
                    try {
                        var r = await fetch(url, {
                            method: 'DELETE',
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json, text/plain, */*',
                                'Content-Type': 'application/json',
                                'X-XSRF-Token': args.xsrf,
                                'X-Client-Build-Time': args.buildTime,
                                'X-GA-SessionId': args.gaSession,
                                'X-GA-UserPseudoId': args.gaUser,
                                'X-MS-VID': args.msVid,
                                'X-MS-SID': args.msSid,
                                'Nsure-Device-Id': args.nsure,
                            },
                        });
                        return {ok: r.status === 204 || r.status === 200 || r.status === 404,
                                status: r.status};
                    } catch(e) {
                        return {ok: false, error: String(e)};
                    }
                }
            """, {
                "lotId":     eldorado_lot_id,
                "xsrf":      xsrf,
                "buildTime": build_time,
                "gaSession": ga_session,
                "gaUser":    ga_user,
                "msVid":     ms_vid,
                "msSid":     ms_sid,
                "nsure":     nsure,
            })

            if result and result.get("ok"):
                logger.info(f"LotSync: ✓ ELD лот {eldorado_lot_id} удалён (статус {result.get('status')})")
                return True

            logger.warning(f"LotSync: API вернул {result} — пробуем UI...")
            return await self._delete_via_ui(page, eldorado_lot_id)

        except Exception as e:
            logger.error(f"LotSync: ошибка удаления ELD {eldorado_lot_id}: {e}")
            return False
        finally:
            await page.close()

    async def _delete_via_ui(self, page, eldorado_lot_id: str) -> bool:
        try:
            await page.goto(
                f"{self.BASE}/dashboard/offers?category=Account&pageIndex=1&pageSize=40",
                wait_until="domcontentloaded", timeout=20000
            )
            await asyncio.sleep(3)

            deleted = await page.evaluate("""
                async (lotId) => {
                    var els = document.querySelectorAll('[data-id],[data-offer-id],[data-lot-id]');
                    for (var i = 0; i < els.length; i++) {
                        var id = els[i].getAttribute('data-id') ||
                                 els[i].getAttribute('data-offer-id') ||
                                 els[i].getAttribute('data-lot-id');
                        if (id === lotId) {
                            var row = els[i].closest('tr, li, [class*="row"], [class*="item"], [class*="card"]');
                            if (row) {
                                var btn = row.querySelector('button[class*="delete" i], button[class*="remove" i]');
                                if (btn) { btn.click(); return 'clicked'; }
                            }
                        }
                    }
                    return false;
                }
            """, eldorado_lot_id)

            if deleted == 'clicked':
                await asyncio.sleep(1.5)
                confirm = await page.query_selector(
                    "button:has-text('Confirm'), button:has-text('Yes'), button:has-text('Delete')"
                )
                if confirm:
                    await confirm.click()
                    await asyncio.sleep(2)
                logger.info(f"LotSync: ✓ ELD лот {eldorado_lot_id} удалён через UI")
                return True

            logger.warning(f"LotSync: кнопка Delete не найдена для {eldorado_lot_id}")
            return False
        except Exception as e:
            logger.error(f"LotSync: ошибка UI удаления {eldorado_lot_id}: {e}")
            return False


class LotSyncManager:
    def __init__(self, context: BrowserContext, check_interval: int = 300):
        self.storage = LotPairStorage()
        self.checker = FunPayChecker()
        self.deleter = EldoradoDeleter(context)
        self.check_interval = check_interval

    def register(
        self,
        funpay_lot_id: str,
        funpay_lot_url: str,
        eldorado_lot_id: str,
        eldorado_game_id: str = "",
        description: str = "",
        category: str = "Account",
    ):
        """Регистрирует пару после успешного выставления лота."""
        if not funpay_lot_id or not eldorado_lot_id:
            logger.warning("LotSync: пустой ID — пара не сохранена")
            return
        import time
        pair = LotPair(
            funpay_lot_id=funpay_lot_id,
            funpay_lot_url=funpay_lot_url,
            eldorado_lot_id=eldorado_lot_id,
            eldorado_game_id=eldorado_game_id,
            created_at=time.time(),
            description=description,
            category=category,
        )
        self.storage.add(pair)

    async def check_once(self) -> int:
        pairs = self.storage.all()
        if not pairs:
            logger.info("LotSync: нет пар для проверки")
            return 0

        logger.info(f"LotSync: проверяем {len(pairs)} пар...")
        deleted = 0

        for idx, pair in enumerate(pairs, 1):
            if idx > 1 and (idx - 1) % 50 == 0:
                logger.info(f"LotSync: пауза 20 сек (проверено {idx-1}/{len(pairs)})...")
                await asyncio.sleep(20)

            try:
                available = await self.checker.is_lot_available(
                    pair.funpay_lot_url, pair.funpay_lot_id
                )
                if available:
                    logger.info(
                        f"LotSync: [{idx}/{len(pairs)}] FP:{pair.funpay_lot_id} активен"
                    )
                    continue

                logger.info(
                    f"LotSync: FP:{pair.funpay_lot_id} недоступен → "
                    f"удаляем ELD:{pair.eldorado_lot_id}"
                )
                ok = await self.deleter.delete_by_id(pair.eldorado_lot_id)
                if ok:
                    log_sale(pair)
                    self.storage.remove(pair.funpay_lot_id)
                    deleted += 1
                else:
                    logger.warning(
                        f"LotSync: не удалось удалить ELD:{pair.eldorado_lot_id}"
                    )

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"LotSync: ошибка при проверке FP:{pair.funpay_lot_id}: {e}")

        logger.info(f"LotSync: проверка завершена, удалено: {deleted}/{len(pairs)}")
        return deleted

    async def run_forever(self):
        logger.info(f"LotSync: запущен (интервал {self.check_interval}с)")
        while True:
            try:
                await self.check_once()
            except Exception as e:
                logger.error(f"LotSync: критическая ошибка цикла: {e}")
            await asyncio.sleep(self.check_interval)
