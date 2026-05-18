"""
eldorado_bot.py — создаём и удаляем лоты на Eldorado.gg через API.
Подключается к уже открытому Chrome через CDP.
"""
import logging
import re
import asyncio
import json
import base64
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from playwright.async_api import BrowserContext, Page

logger       = logging.getLogger("eldorado")
BASE         = "https://www.eldorado.gg"
URL_SELL     = f"{BASE}/sell"
LOGIN_DOMAIN = "login.eldorado.gg"


@dataclass
class Lot:
    lot_id: str
    title: str
    price: float


class EldoradoBot:
    def __init__(self, context: BrowserContext):
        self.context = context
        self._page: Optional[Page] = None

    async def _page_(self) -> Page:
        if self._page is None or self._page.is_closed():
            self._page = await self.context.new_page()
        return self._page

    # ------------------------------------------------------------------
    # Вспомогательные: токен и базовая страница
    # ------------------------------------------------------------------

    async def _ensure_base_page(self) -> Page:
        """Открывает eldorado.gg если ещё не открыт (нужно для fetch с cookies)."""
        page = await self._page_()
        if "eldorado.gg" not in page.url:
            await page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)
        return page

    async def _get_xsrf_token(self, page: Page) -> str:
        """Читает XSRF-токен из cookies браузера."""
        cookies = await self.context.cookies()
        for c in cookies:
            if c["name"] == "__Host-XSRF-TOKEN":
                return c["value"]
        return ""

    # ------------------------------------------------------------------
    # Авторизация
    # ------------------------------------------------------------------

    async def is_logged_in(self) -> bool:
        page = await self._page_()
        try:
            await page.goto(URL_SELL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            if LOGIN_DOMAIN in page.url or "login" in page.url:
                return False
            return True
        except Exception as e:
            logger.warning(f"Eldorado: ошибка проверки авторизации: {e}")
            return False

    async def wait_for_manual_login(self):
        page = await self._page_()
        await page.goto(URL_SELL, wait_until="domcontentloaded", timeout=20000)
        logger.info("=" * 55)
        logger.info("  ВОЙДИТЕ В АККАУНТ ВРУЧНУЮ В ОТКРЫТОМ БРАУЗЕРЕ")
        logger.info("=" * 55)
        try:
            await page.wait_for_url(
                lambda url: LOGIN_DOMAIN not in url and "login" not in url,
                timeout=180000,
            )
        except Exception:
            pass
        await asyncio.sleep(3)

    # ------------------------------------------------------------------
    # Получение своих лотов
    # ------------------------------------------------------------------

    async def get_my_lots(self, category: str) -> list[Lot]:
        page      = await self._ensure_base_page()
        lots: list[Lot] = []
        seen_ids: set   = set()
        page_index = 1
        page_size  = 50

        xsrf_token = await self._get_xsrf_token(page)
        if not xsrf_token:
            logger.error("Eldorado: get_my_lots — XSRF-токен не найден, сессия истекла")
            return lots

        try:
            while True:
                result = await page.evaluate("""
                    async ({pageIndex, pageSize, xsrf}) => {
                        const headers = {'x-xsrf-token': xsrf};
                        const opts    = {credentials: 'include', headers};
                        try {
                            const r = await fetch(
                                `/api/flexibleOffers/me/search?pageIndex=${pageIndex}&pageSize=${pageSize}&category=Account`,
                                opts
                            );
                            if (r.status === 200) {
                                return {ok: true, data: await r.json(), via: 'GET /me/search'};
                            }
                            return {ok: false, statuses: {r1: r.status}};
                        } catch(e) {
                            return {ok: false, error: String(e)};
                        }
                    }
                """, {"pageIndex": page_index, "pageSize": page_size, "xsrf": xsrf_token})

                if not result or not result.get("ok"):
                    statuses = result.get("statuses", {}) if result else {}
                    error    = result.get("error", "") if result else "no result"
                    logger.warning(
                        f"Eldorado: get_my_lots стр.{page_index} — все варианты провалились: {statuses}"
                        + (f" | error: {error}" if error else "")
                    )
                    break
                logger.debug(f"Eldorado: get_my_lots — используем вариант: {result.get('via')}")

                data = result["data"]
                if isinstance(data, dict):
                    items = (data.get("items") or data.get("data", {}).get("items")
                             or data.get("offers") or data.get("data") or [])
                else:
                    items = data if isinstance(data, list) else []

                if not items:
                    break

                new_on_page = 0
                for item in items:
                    lot_id = str(item.get("id") or item.get("offerId") or item.get("flexibleOfferId") or "")
                    title  = item.get("title") or item.get("offerTitle") or item.get("name") or "—"
                    price  = float(item.get("price") or item.get("amount") or item.get("pricePerUnit") or 0)
                    if lot_id and lot_id not in seen_ids:
                        seen_ids.add(lot_id)
                        lots.append(Lot(lot_id=lot_id, title=title, price=price))
                        new_on_page += 1

                logger.debug(f"Eldorado: get_my_lots стр.{page_index} → +{new_on_page} лотов")

                if len(items) < page_size:
                    break

                page_index += 1
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"Eldorado: ошибка API лотов: {e}")

        logger.info(f"Eldorado: лотов всего: {len(lots)} (страниц просмотрено: {page_index})")
        return lots

    async def get_total_lots_count(self) -> int:
        return len(await self.get_my_lots(""))

    # ------------------------------------------------------------------
    # Загрузка фото
    # ------------------------------------------------------------------

    async def _upload_image(self, page: Page, image_path: str, xsrf_token: str) -> Optional[dict]:
        """
        Загружает фото через POST /api/files/me/Offer (multipart/form-data).
        Возвращает dict с ключами smallImage, largeImage, originalSizeImage или None.
        """
        try:
            img_path = Path(image_path)
            if not img_path.exists():
                logger.warning(f"Eldorado: фото не найдено: {image_path}")
                return None

            img_bytes = img_path.read_bytes()
            img_b64   = base64.b64encode(img_bytes).decode()

            suffix = img_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".webp": "image/webp",
                        ".gif": "image/gif"}
            mime = mime_map.get(suffix, "image/jpeg")

            result = await page.evaluate("""
                async ({b64, mime, filename, xsrf}) => {
                    try {
                        const byteChars = atob(b64);
                        const byteNums  = new Array(byteChars.length);
                        for (let i = 0; i < byteChars.length; i++) {
                            byteNums[i] = byteChars.charCodeAt(i);
                        }
                        const byteArr = new Uint8Array(byteNums);
                        const blob    = new Blob([byteArr], {type: mime});

                        const form = new FormData();
                        form.append('image', blob, filename);

                        const r = await fetch('/api/files/me/Offer', {
                            method: 'POST',
                            credentials: 'include',
                            headers: {'x-xsrf-token': xsrf},
                            body: form,
                        });

                        const text = await r.text();
                        return {status: r.status, body: text};
                    } catch(e) {
                        return {status: 0, error: String(e)};
                    }
                }
            """, {"b64": img_b64, "mime": mime, "filename": img_path.name, "xsrf": xsrf_token})

            if not result:
                logger.warning("Eldorado: upload_image — нет ответа")
                return None

            status = result.get("status", 0)
            if status not in (200, 201):
                logger.warning(f"Eldorado: upload_image статус {status}: {result.get('body', '')[:200]}")
                return None

            body_text = result["body"]
            logger.debug(f"Eldorado: upload ответ: {body_text[:400]}")

            body = json.loads(body_text)

            if isinstance(body, list) and len(body) > 0:
                body = body[0]

            local_paths = body.get("localPaths", [])
            if local_paths:
                def fname(path): return Path(path).name
                small = next((fname(p) for p in local_paths if "Small" in p), "")
                large = next((fname(p) for p in local_paths if "Large" in p), small)
                orig  = next((fname(p) for p in local_paths if "Original" in p), large)
                if not small:
                    small = fname(local_paths[0])
                    large = fname(local_paths[1]) if len(local_paths) > 1 else small
                    orig  = fname(local_paths[2]) if len(local_paths) > 2 else large
                result_img = {"smallImage": small, "largeImage": large, "originalSizeImage": orig}
                logger.info(f"Eldorado: фото загружено → {small}")
                return result_img

            small = (body.get("smallImage") or body.get("small") or "")
            large = (body.get("largeImage") or body.get("large") or body.get("imageUrl") or small)
            orig  = (body.get("originalSizeImage") or body.get("original") or large)

            if not small:
                logger.warning(f"Eldorado: upload — неизвестный формат ответа: {body_text[:200]}")
                return None

            result_img = {"smallImage": small, "largeImage": large, "originalSizeImage": orig}
            logger.info(f"Eldorado: фото загружено → {small}")
            return result_img

        except Exception as e:
            logger.warning(f"Eldorado: ошибка загрузки фото: {e}")
            return None

    # ------------------------------------------------------------------
    # Создание лота через API
    # ------------------------------------------------------------------

    async def create_lot(
        self,
        category: str,
        title: str,
        description: str,
        price_usd: float,
        dropdowns: list[dict] = None,
        game_id: int = None,
        image_path: str = None,
        image_paths: list = None,
        lot_folder: str = None,
        trade_environment_id: str = None,
    ) -> Optional[str]:
        """
        Создаёт лот через API. Возвращает UUID лота или None при ошибке.
        Поддерживает category="Account" и category="CustomItem".
        """
        page = await self._ensure_base_page()

        try:
            logger.info(f"Eldorado: создаём лот (API) — «{title[:50]}» за ${price_usd}")

            xsrf_token = await self._get_xsrf_token(page)
            if not xsrf_token:
                logger.error("Eldorado: XSRF-токен не найден — возможно сессия истекла")
                return None

            # ── Шаг 1: Загрузка фото ──────────────────────────────────────
            main_image = None

            photos = []
            if image_paths:
                photos = [p for p in image_paths if Path(p).exists()]
            if not photos and image_path and Path(image_path).exists():
                photos = [image_path]

            if photos:
                main_image = await self._upload_image(page, photos[0], xsrf_token)
                if not main_image:
                    logger.warning("Eldorado: фото не загружено — создаём лот без фото")
            else:
                logger.warning(f"Eldorado: нет фото для загрузки")
                logger.warning(f"Eldorado: image_path из конфига = {repr(image_path)}")
                logger.warning(f"Eldorado: файл существует = {Path(image_path).exists() if image_path else 'image_path не задан'}")
                logger.warning(f"Eldorado: image_paths с FunPay = {image_paths}")

            # ── Шаг 2: Формируем offerAttributes из dropdowns ─────────────
            offer_attributes = []
            if dropdowns:
                for d in dropdowns:
                    if isinstance(d, dict) and "id" in d and "value" in d:
                        offer_attributes.append({
                            "id":    d["id"],
                            "type":  d.get("type", "Select"),
                            "value": d["value"],
                        })

            # ── Шаг 3: Определяем endpoint и category ─────────────────────
            eld_category = "CustomItem" if category == "CustomItem" else "Account"
            endpoint = (
                "/api/v1/item-management/me/offers/item"
                if eld_category == "CustomItem"
                else "/api/flexibleOffers/account"
            )
            logger.info(f"Eldorado: category={eld_category} → endpoint={endpoint}")

            pricing = {
                "quantity": 1,
                "pricePerUnit": {"amount": price_usd, "currency": "USD"},
            }
            if eld_category == "CustomItem":
                pricing["volumeDiscounts"] = []

            # ── Шаг 4: Формируем тело запроса ────────────────────────────
            payload = {
                "augmentedGame": {
                    "gameId":            str(game_id) if game_id else None,
                    "category":          eld_category,
                    "tradeEnvironmentId": trade_environment_id,
                    "offerAttributes":   offer_attributes,
                    "attributeIdsCsv":   None,
                },
                "details": {
                    "offerTitle":             title[:200],
                    "description":            description[:3000] if description else None,
                    "hasOriginalEmail":       False,
                    "guaranteedDeliveryTime": "Day1",
                    "mainOfferImage":         main_image,
                    "offerImages":            [],
                    "pricing":                pricing,
                },
            }

            payload_json = json.dumps(payload)
            logger.debug(f"Eldorado: payload → {payload_json[:300]}")

            # ── Шаг 5: Отправляем запрос ──────────────────────────────────
            result = await page.evaluate("""
                async ({payloadJson, xsrf, endpoint}) => {
                    try {
                        const r = await fetch(endpoint, {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'Content-Type': 'application/json',
                                'x-xsrf-token': xsrf,
                            },
                            body: payloadJson,
                        });
                        const text = await r.text();
                        return {status: r.status, body: text};
                    } catch(e) {
                        return {status: 0, error: String(e)};
                    }
                }
            """, {"payloadJson": payload_json, "xsrf": xsrf_token, "endpoint": endpoint})

            if not result:
                logger.error("Eldorado: create_lot — нет ответа от API")
                return None

            status = result.get("status", 0)
            body_text = result.get("body", "")

            if status not in (200, 201):
                logger.error(f"Eldorado: create_lot статус {status}: {body_text[:300]}")
                if status == 400 and "Maximum of 100 active offers" in body_text:
                    logger.warning("Eldorado: достигнут лимит 100 лотов — игра будет пропущена")
                    return "MAX_LOTS_REACHED"
                return None

            # ── Шаг 6: Извлекаем UUID из ответа ──────────────────────────
            try:
                body = json.loads(body_text)
            except Exception:
                body = {}

            lot_id = (
                body.get("id") or body.get("offerId") or
                body.get("flexibleOfferId") or body.get("lotId")
            )

            if not lot_id:
                m = re.search(
                    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                    body_text, re.IGNORECASE
                )
                if m:
                    lot_id = m.group(0)

            if not lot_id:
                logger.warning(f"Eldorado: UUID не найден в ответе — пробуем fallback (последний лот)")
                logger.debug(f"Eldorado: тело ответа: {body_text[:500]}")
                try:
                    latest = await page.evaluate("""
                        async () => {
                            const r = await fetch(
                                '/api/flexibleOffers/me/search?pageIndex=1&pageSize=1',
                                {credentials: 'include'}
                            );
                            if (r.status === 200) {
                                const d = await r.json();
                                const items = (d.items || (d.data && d.data.items) || d.offers || d.data || []);
                                return items.length > 0 ? items[0] : null;
                            }
                            return null;
                        }
                    """)
                    if latest:
                        lot_id = str(
                            latest.get("id") or latest.get("offerId") or
                            latest.get("flexibleOfferId") or ""
                        )
                        if lot_id:
                            logger.info(f"Eldorado: UUID получен через fallback: {lot_id}")
                except Exception as fe:
                    logger.warning(f"Eldorado: fallback UUID ошибка: {fe}")

            if lot_id:
                logger.info(f"Eldorado: ✓ лот создан — «{title[:50]}» ${price_usd} (ID: {lot_id})")
            else:
                logger.warning(f"Eldorado: UUID так и не определён — возвращаем True (пара НЕ будет в lot_pairs)")
                return True

            if lot_folder and Path(lot_folder).exists():
                try:
                    import shutil
                    shutil.rmtree(lot_folder)
                    logger.info(f"Eldorado: папка лота удалена → {lot_folder}")
                except Exception as e:
                    logger.warning(f"Eldorado: не удалось удалить папку {lot_folder}: {e}")

            return lot_id

        except Exception as e:
            logger.error(f"Eldorado: общее исключение в create_lot: {e}")
            return None

    # ------------------------------------------------------------------
    # Проверка активности лота
    # ------------------------------------------------------------------

    async def verify_lot_active(self, lot_id: str, max_attempts: int = 4, delay: float = 5.0) -> str | None:
        """
        Проверяет что лот реально активен на Eldorado после создания.
        Возвращает:
          - lot_id (str)          — лот найден и Active
          - 'MAX_LOTS_REACHED'    — на аккаунте уже 100 лотов
          - None                  — лот не подтверждён за все попытки
        """
        page = await self._ensure_base_page()
        xsrf_token = await self._get_xsrf_token(page)

        for attempt in range(1, max_attempts + 1):
            await asyncio.sleep(delay)
            try:
                result = await page.evaluate("""
                    async ({lotId, xsrf}) => {
                        try {
                            const r = await fetch(
                                '/api/flexibleOffers/me/search?pageIndex=1&pageSize=50',
                                {credentials: 'include', headers: {'x-xsrf-token': xsrf}}
                            );
                            if (r.status === 200) {
                                return {ok: true, data: await r.json()};
                            }
                            return {ok: false, status: r.status};
                        } catch(e) {
                            return {ok: false, error: String(e)};
                        }
                    }
                """, {"lotId": lot_id, "xsrf": xsrf_token})

                if not result or not result.get("ok"):
                    logger.warning(f"Eldorado: verify попытка {attempt}/{max_attempts} — ошибка API: {result}")
                    continue

                data    = result["data"]
                results = data.get("results") or data.get("items") or []

                for item in results:
                    item_id = str(item.get("id") or "")
                    if item_id == lot_id and item.get("offerState") == "Active":
                        logger.info(f"Eldorado: ✓ лот {lot_id} подтверждён активным (попытка {attempt})")
                        return lot_id

                logger.info(f"Eldorado: verify попытка {attempt}/{max_attempts} — лот {lot_id} ещё не найден, ждём {delay}с...")

            except Exception as e:
                logger.warning(f"Eldorado: verify попытка {attempt}/{max_attempts} — исключение: {e}")

        logger.warning(f"Eldorado: лот {lot_id} не подтверждён после {max_attempts} попыток — пара не будет записана")
        return None

    # ------------------------------------------------------------------
    # Удаление лотов
    # ------------------------------------------------------------------

    async def delete_lot(self, lot: Lot) -> bool:
        page = await self._ensure_base_page()
        try:
            xsrf_token = await self._get_xsrf_token(page)

            result = await page.evaluate("""
                async ({lotId, xsrf}) => {
                    try {
                        const r = await fetch(`/api/flexibleOffers/${lotId}`, {
                            method: 'DELETE',
                            credentials: 'include',
                            headers: {'x-xsrf-token': xsrf},
                        });
                        return {status: r.status};
                    } catch(e) {
                        return {status: 0, error: String(e)};
                    }
                }
            """, {"lotId": lot.lot_id, "xsrf": xsrf_token})

            status = result.get("status", 0) if result else 0

            if status in (200, 204):
                logger.info(f"Eldorado: ✓ лот {lot.lot_id} удалён")
                return True
            else:
                logger.warning(f"Eldorado: API удаления вернул {status} — пробуем через UI")
                return await self._delete_lot_ui(lot)

        except Exception as e:
            logger.error(f"Eldorado: ошибка удаления {lot.lot_id}: {e}")
            return False

    async def _delete_lot_ui(self, lot: Lot) -> bool:
        """Fallback удаление через UI если API не сработал."""
        page = await self._page_()
        try:
            for url in [f"{BASE}/account/offers/{lot.lot_id}", f"{BASE}/offer/{lot.lot_id}/edit"]:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
                if LOGIN_DOMAIN not in page.url and "404" not in page.url:
                    break

            del_btn = await page.query_selector(
                "button:has-text('Delete'), button:has-text('Remove'), [class*='delete']"
            )
            if not del_btn:
                return False

            await del_btn.click()
            await asyncio.sleep(1)
            confirm = await page.query_selector(
                "button:has-text('Confirm'), button:has-text('Yes'), button:has-text('Delete')"
            )
            if confirm:
                await confirm.click()
                await asyncio.sleep(2)

            logger.info(f"Eldorado: ✓ лот {lot.lot_id} удалён через UI")
            return True
        except Exception as e:
            logger.error(f"Eldorado: ошибка UI удаления {lot.lot_id}: {e}")
            return False

    async def delete_lots_batch(self, lots: list[Lot], count: int) -> int:
        deleted = 0
        for lot in lots[:count]:
            if await self.delete_lot(lot):
                deleted += 1
            await asyncio.sleep(1)
        return deleted

    # ------------------------------------------------------------------
    # Массовое удаление через Dashboard UI
    # ------------------------------------------------------------------

    async def mass_delete_by_game(self, game_name: str) -> int:
        page = await self._page_()
        total_deleted = 0

        logger.info(f"Eldorado: открываем Dashboard для игры «{game_name}»")
        await page.goto(
            "https://www.eldorado.gg/dashboard/offers/Account",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

        opened = await page.evaluate("""
            () => {
                var triggers = document.querySelectorAll(
                    'eld-dropdown .dropdown-trigger, .dropdown-trigger'
                );
                for (var i = 0; i < triggers.length; i++) {
                    if (triggers[i].offsetParent !== null) {
                        triggers[i].click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if not opened:
            logger.warning("Eldorado: дропдаун Select Game не найден")
        await asyncio.sleep(1)

        search = await page.query_selector(
            "input.search-input.active, "
            "input[class*='search-input']:not([aria-hidden='true'])"
        )
        if search and await search.is_visible():
            await search.fill("")
            await asyncio.sleep(0.2)
            await search.type(game_name, delay=80)
            await asyncio.sleep(1.5)
        else:
            logger.warning("Eldorado: поле поиска игры не найдено")

        selected_game = await page.evaluate("""
            (name) => {
                var containers = document.querySelectorAll(
                    '[role="listbox"], .dropdown-menu, [class*="dropdown-content"]'
                );
                for (var c = 0; c < containers.length; c++) {
                    var items = containers[c].querySelectorAll(
                        '[role="option"], li, [class*="option-item"]'
                    );
                    for (var i = 0; i < items.length; i++) {
                        var t = items[i].innerText ? items[i].innerText.trim() : '';
                        if (t.toLowerCase() === name.toLowerCase()
                                && items[i].offsetParent !== null) {
                            items[i].click();
                            return t;
                        }
                    }
                }
                var all = document.querySelectorAll('[role="option"], [class*="option"]');
                for (var i = 0; i < all.length; i++) {
                    var t = all[i].innerText ? all[i].innerText.trim() : '';
                    if (t.toLowerCase().includes(name.toLowerCase())
                            && all[i].offsetParent !== null) {
                        all[i].click();
                        return t;
                    }
                }
                return null;
            }
        """, game_name)

        if selected_game:
            logger.info(f"Eldorado: игра «{selected_game}» выбрана")
            await asyncio.sleep(3)

            filter_ok = await page.evaluate("""
                (name) => {
                    var triggers = document.querySelectorAll(
                        'eld-dropdown .dropdown-trigger, .dropdown-trigger'
                    );
                    for (var i = 0; i < triggers.length; i++) {
                        var t = triggers[i].innerText ? triggers[i].innerText.trim().toLowerCase() : '';
                        if (t.includes(name.toLowerCase())) return true;
                    }
                    return false;
                }
            """, game_name)

            if not filter_ok:
                logger.warning(f"Eldorado: фильтр «{game_name}» не подтверждён — удаление отменено!")
                return 0
        else:
            logger.warning(f"Eldorado: игра «{game_name}» не найдена — удаление отменено!")
            return 0

        target_index = 0

        for iteration in range(1000):
            for _ in range(60):
                try:
                    spinner = await page.query_selector("eld-spinner")
                    if not spinner or not await spinner.is_visible():
                        break
                except Exception:
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.5)

            try:
                count = await page.evaluate("""
                    () => {
                        var icons = document.querySelectorAll('span.icomoon-icon.icon.icon-delete');
                        var n = 0;
                        for (var i = 0; i < icons.length; i++) {
                            if (icons[i].offsetParent !== null) n++;
                        }
                        return n;
                    }
                """)
            except Exception as e:
                logger.warning(f"Eldorado: ошибка подсчёта иконок: {e}")
                await asyncio.sleep(1)
                continue

            if count == 0:
                logger.info("Eldorado: лоты закончились")
                break

            idx = target_index if count > target_index else 0
            logger.info(f"Eldorado: [{iteration+1}] видимых лотов: {count} → кликаем #{idx+1}")

            try:
                clicked = await page.evaluate("""
                    (idx) => {
                        var icons = document.querySelectorAll('span.icomoon-icon.icon.icon-delete');
                        var visible = [];
                        for (var i = 0; i < icons.length; i++) {
                            if (icons[i].offsetParent !== null) visible.push(icons[i]);
                        }
                        if (visible.length > idx) { visible[idx].click(); return visible.length; }
                        if (visible.length > 0)   { visible[0].click();   return visible.length; }
                        return 0;
                    }
                """, idx)
            except Exception as e:
                logger.warning(f"Eldorado: ошибка клика корзины: {e}")
                await asyncio.sleep(2)
                continue

            if not clicked:
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(1.2)

            confirmed = False
            for sel in ["button:has-text('Delete')", "button:has-text('Confirm')", "button:has-text('Yes')"]:
                try:
                    btn = await page.wait_for_selector(sel, timeout=4000, state="visible")
                    if btn:
                        await btn.click()
                        confirmed = True
                        total_deleted += 1
                        logger.info(f"Eldorado: ✓ лот удалён (всего: {total_deleted})")
                        break
                except Exception:
                    continue

            if not confirmed:
                try:
                    confirmed = await page.evaluate("""
                        () => {
                            var btns = document.querySelectorAll('button');
                            for (var i = 0; i < btns.length; i++) {
                                var t = btns[i].innerText ? btns[i].innerText.trim().toLowerCase() : '';
                                if ((t === 'delete' || t === 'confirm' || t === 'yes')
                                        && btns[i].offsetParent !== null) {
                                    btns[i].click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if confirmed:
                        total_deleted += 1
                        logger.info(f"Eldorado: ✓ лот удалён через JS (всего: {total_deleted})")
                except Exception:
                    pass

            if not confirmed:
                logger.warning(f"Eldorado: модальное окно не появилось (итерация {iteration+1})")
                await asyncio.sleep(1.5)

            target_index = 2 if target_index == 0 else 0

        logger.info(f"Eldorado: удаление «{game_name}» завершено. Итого: {total_deleted}")
        return total_deleted

    def _parse_price(self, text: str) -> float:
        text = text.replace(" ", "").replace(",", ".")
        m = re.search(r"[\d]+\.?[\d]*", text.replace(" ", ""))
        return float(m.group(0)) if m else 0.0
