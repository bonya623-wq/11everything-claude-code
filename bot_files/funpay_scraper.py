"""
funpay_scraper.py — парсим цену, название и описание лота с FunPay через Playwright.
"""
import logging
import re
import asyncio
import urllib.request
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("funpay")


@dataclass
class FunPayLot:
    price: float
    title: str
    description: str
    href: str = ""
    lot_id: str = ""
    seller: str = ""           # имя продавца (для блеклиста)
    image_paths: list = None   # локальные пути к скачанным фото лота
    game_id: int = 0           # eldorado game_id (используется в get_seller_lots)
    game_name: str = ""        # название игры  (используется в get_seller_lots)
    region: str = ""           # регион лота (например "Europe", "Asia", "America")

    def __post_init__(self):
        if self.image_paths is None:
            self.image_paths = []


class FunPayScraper:
    def __init__(self, context: BrowserContext):
        self.context = context
        self._setup_done = False

    async def _switch_to_usd(self, page: Page) -> bool:
        try:
            current_url = page.url
            usd_url = current_url.split("?")[0] + "?currency=usd&setlocale=en"
            await page.goto(usd_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)

            switched = await page.evaluate("""
                () => {
                    var active = document.querySelector('.menu-item-currencies .active');
                    if (active) return active.innerText.trim().toUpperCase().indexOf('USD') !== -1;
                    var btn = document.querySelector('.menu-item-currencies .dropdown-toggle') ||
                              document.querySelector('a.menu-item-currencies');
                    if (btn) return btn.innerText.trim().toUpperCase().indexOf('USD') !== -1;
                    return false;
                }
            """)

            if switched:
                logger.info("FunPay: ✓ валюта → USD (через URL)")
                return True

            logger.info("FunPay: пробуем переключить валюту через дропдаун...")

            trigger = await page.query_selector(
                "a.dropdown-toggle.menu-item-currencies, "
                ".menu-item-currencies .dropdown-toggle, "
                ".menu-item-currencies > a"
            )
            if not trigger:
                trigger = await page.query_selector(
                    "a[class*='currencies'], li[class*='currencies'] > a"
                )

            if trigger and await trigger.is_visible():
                await trigger.click()
                await asyncio.sleep(0.8)

                usd_link = await page.evaluate("""
                    () => {
                        var menus = document.querySelectorAll('.dropdown-menu');
                        for (var i = 0; i < menus.length; i++) {
                            var links = menus[i].querySelectorAll('a, li, span');
                            for (var j = 0; j < links.length; j++) {
                                var l = links[j];
                                var txt = l.innerText ? l.innerText.trim().toUpperCase() : '';
                                var href = l.href || '';
                                if (txt === 'USD' || href.indexOf('currency=usd') !== -1) {
                                    if (l.offsetParent !== null) {
                                        l.click();
                                        return true;
                                    }
                                }
                            }
                        }
                        return false;
                    }
                """)

                if usd_link:
                    await asyncio.sleep(1.5)
                    logger.info("FunPay: ✓ валюта → USD (через дропдаун)")
                    return True
                else:
                    logger.warning("FunPay: USD не найден в дропдауне валют")
            else:
                logger.warning("FunPay: дропдаун валют не найден")

        except Exception as e:
            logger.warning(f"FunPay: ошибка переключения валюты: {e}")

        return False

    async def _setup_funpay(self, page: Page, lots_url: str):
        if self._setup_done:
            return
        try:
            base_url = lots_url.split("?")[0]
            setup_url = base_url + "?setlocale=en&currency=usd"
            await page.goto(setup_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)

            is_usd = await page.evaluate("""
                () => {
                    var el = document.querySelector('.menu-item-currencies .dropdown-toggle') ||
                             document.querySelector('a.menu-item-currencies');
                    var text = el ? el.innerText.trim().toUpperCase() : '';
                    return text.indexOf('USD') !== -1 || text.indexOf('$') !== -1;
                }
            """)

            if not is_usd:
                await self._switch_to_usd(page)
            else:
                logger.info("FunPay: ✓ язык EN, валюта USD")

            self._setup_done = True
        except Exception as e:
            logger.warning(f"FunPay: ошибка настройки: {e}")
            self._setup_done = True

    async def get_lots(
        self,
        lots_url: str,
        min_seller_reviews: int = 0,
        require_auto_delivery: bool = False,
        min_price_usd: float = 0.0,
        max_price_usd: float = 999999.0,
        count: int = 1,
    ) -> list["FunPayLot"]:
        """Возвращает список из count подходящих лотов (разные продавцы)."""
        results = []
        seen_sellers = set()
        page = await self.context.new_page()
        try:
            base = lots_url.split("?")[0]
            lots_url = base + "?setlocale=en&currency=usd"

            await self._setup_funpay(page, lots_url)
            await page.goto(lots_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            accounts_btn = await page.query_selector("button[value='Аккаунты'], button[value='Accounts']")
            if accounts_btn:
                await accounts_btn.click()
                await asyncio.sleep(2)

            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 1500)")
                await asyncio.sleep(0.3)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

            all_items = await page.query_selector_all("a.tc-item")
            items = []
            for el in all_items:
                f_type = (await el.get_attribute("data-f-type") or "").lower()
                if "аккаунт" in f_type or "account" in f_type:
                    items.append(el)
            logger.info(f"FunPay: карточек аккаунтов: {len(items)}")
            if not items:
                items = all_items
                logger.info(f"FunPay: fallback — берём все карточки: {len(items)}")

            for item in items:
                if len(results) >= count:
                    break
                try:
                    price_el = await item.query_selector(".tc-price")
                    if not price_el:
                        continue
                    data_s = await price_el.get_attribute("data-s")
                    try:
                        price = float(data_s) if data_s else None
                    except ValueError:
                        price = None
                    if price is None or price <= 0:
                        continue
                    if price < min_price_usd or price > max_price_usd:
                        continue

                    if min_seller_reviews > 0:
                        reviews_el = await item.query_selector(".rating-mini-count, .tc-user .rating-num")
                        reviews = 0
                        if reviews_el:
                            rt = await reviews_el.inner_text()
                            m = re.search(r"\d+", rt.replace(" ", "").replace(",", ""))
                            reviews = int(m.group(0)) if m else 0
                        if reviews < min_seller_reviews:
                            continue

                    if require_auto_delivery:
                        html = await item.inner_html()
                        if not any(x in html.lower() for x in ["auto", "autodelivery", "auto-delivery"]):
                            continue

                    seller_el = await item.query_selector(".media-user-name")
                    seller = (await seller_el.inner_text()).strip() if seller_el else ""
                    if seller in seen_sellers:
                        continue
                    seen_sellers.add(seller)

                    title_el = await item.query_selector(".tc-desc-text")
                    title = (await title_el.inner_text()).strip() if title_el else ""
                    title = self._strip_links(title)
                    lot_href = await item.get_attribute("href")

                    logger.info(f"FunPay: лот {len(results)+1} — «{title[:50]}» ${price:.2f}")
                    results.append(FunPayLot(price=price, title=title, description=title, href=lot_href))

                except Exception as e:
                    logger.debug(f"Ошибка парсинга карточки: {e}")
                    continue

        except Exception as e:
            logger.error(f"FunPay: ошибка: {e}")
        finally:
            await page.close()

        return results

    async def get_best_lot(
        self,
        lots_url: str,
        min_seller_reviews: int = 0,
        require_auto_delivery: bool = False,
        min_price_usd: float = 0.0,
        max_price_usd: float = 999999.0,
        used_lot_ids: set = None,
        funpay_tab: str = None,   # "Sale", "Items", "Accounts" и т.д.
    ) -> Optional[FunPayLot]:
        page = await self.context.new_page()
        try:
            base = lots_url.split("?")[0]
            if "funpay.com" in base and "/en/" not in base:
                base = base.replace("funpay.com/", "funpay.com/en/")
            lots_url = base + "?setlocale=en&currency=usd"

            logger.info(f"FunPay: открываем {lots_url}")

            await self._setup_funpay(page, lots_url)

            await page.goto(lots_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            is_usd = await page.evaluate("""
                () => {
                    var el = document.querySelector('.menu-item-currencies .dropdown-toggle') ||
                             document.querySelector('a.menu-item-currencies');
                    var text = el ? el.innerText.trim().toUpperCase() : '';
                    return text.indexOf('USD') !== -1 || text.indexOf('$') !== -1;
                }
            """)
            if not is_usd:
                logger.info("FunPay: валюта не USD, переключаем...")
                await self._switch_to_usd(page)
                await page.goto(lots_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

            # ── Кликаем нужную вкладку ────────────────────────────────────
            tab_clicked = False
            if funpay_tab:
                # Попытка 1: специфичные селекторы фильтр-кнопок (как в roblox_items_scraper)
                all_btns = await page.query_selector_all(
                    ".lot-field-radio-box button, .lot-field-input + button, "
                    "button.btn-gray, button.btn-dark"
                )
                filter_btn = None
                for btn in all_btns:
                    val = await btn.get_attribute("value") or ""
                    txt = (await btn.inner_text()).strip()
                    if val == funpay_tab or txt == funpay_tab:
                        filter_btn = btn
                        break
                if filter_btn:
                    await filter_btn.click()
                    await asyncio.sleep(3)
                    tab_clicked = True
                    logger.info(f"FunPay: выбран фильтр «{funpay_tab}»")
                else:
                    # Попытка 2: широкий JS-поиск с алиасами (fallback)
                    tab_aliases = {
                        "Items":    ["Items",    "Предметы"],
                        "Sale":     ["Sale",     "Продажа"],
                        "Accounts": ["Accounts", "Аккаунты"],
                    }
                    targets = tab_aliases.get(funpay_tab, [funpay_tab])
                    try:
                        await page.wait_for_selector("button[value], [role='tab'], .btn", timeout=6000)
                    except Exception:
                        logger.warning("FunPay: tab-кнопки не появились за 6с — пробуем без ожидания")
                    for attempt in range(3):
                        clicked_text = await page.evaluate("""
                            (targets) => {
                                var btns = document.querySelectorAll('button, .btn, [role="tab"]');
                                for (var i = 0; i < btns.length; i++) {
                                    var t = btns[i].innerText ? btns[i].innerText.trim() : '';
                                    var v = btns[i].value || '';
                                    if (targets.indexOf(t) !== -1 || targets.indexOf(v) !== -1) {
                                        btns[i].click();
                                        return t || v;
                                    }
                                }
                                return null;
                            }
                        """, targets)
                        if clicked_text:
                            await asyncio.sleep(2)
                            logger.info(f"FunPay: выбран фильтр «{clicked_text}» (fallback, попытка {attempt+1})")
                            tab_clicked = True
                            break
                        if attempt < 2:
                            logger.warning(f"FunPay: попытка {attempt+1} — кнопка '{funpay_tab}' не найдена, повтор...")
                            await asyncio.sleep(1.5)
                    if not tab_clicked:
                        logger.warning(f"FunPay: кнопка '{funpay_tab}' не найдена после всех попыток")

            if not tab_clicked and funpay_tab is None:
                # Дефолт только если tab вообще не задан — кликаем Accounts
                accounts_btn = await page.query_selector("button[value='Аккаунты'], button[value='Accounts']")
                if accounts_btn:
                    await accounts_btn.click()
                    await asyncio.sleep(2)
                    logger.info("FunPay: выбран фильтр Accounts")

            # Прокручиваем для загрузки карточек
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 1500)")
                await asyncio.sleep(0.3)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

            # :not(.hidden) — FunPay скрывает карточки не подходящие под выбранный фильтр
            all_items = await page.query_selector_all("a.tc-item:not(.hidden)")

            if funpay_tab is None:
                # Аккаунты (дефолт): дополнительно фильтруем по data-f-type
                items = []
                for el in all_items:
                    f_type = (await el.get_attribute("data-f-type") or "").lower()
                    if "аккаунт" in f_type or "account" in f_type:
                        items.append(el)
                logger.info(f"FunPay: карточек аккаунтов: {len(items)}")
                if not items:
                    items = list(all_items)
                    logger.info(f"FunPay: fallback — берём все видимые: {len(items)}")
            else:
                # Items, Sale и прочие — берём все видимые карточки (фильтр уже применён)
                items = list(all_items)
                logger.info(f"FunPay: карточек «{funpay_tab}»: {len(items)}")

            first_item_logged = False
            for item in items:
                try:
                    price_el = await item.query_selector(".tc-price")
                    if not price_el:
                        if not first_item_logged:
                            logger.warning("FunPay: .tc-price не найден")
                            first_item_logged = True
                        continue

                    data_s = await price_el.get_attribute("data-s")
                    try:
                        price = float(data_s) if data_s else None
                    except ValueError:
                        price = None

                    if price is None or price <= 0:
                        if not first_item_logged:
                            logger.warning(f"FunPay: цена не распознана data-s={data_s!r}")
                            first_item_logged = True
                        continue

                    if price < min_price_usd or price > max_price_usd:
                        if not first_item_logged:
                            logger.warning(f"FunPay: цена ${price:.2f} вне диапазона ${min_price_usd}–${max_price_usd}")
                            first_item_logged = True
                        continue

                    seller_el = await item.query_selector(".media-user-name")
                    lot_seller = (await seller_el.inner_text()).strip() if seller_el else ""

                    if min_seller_reviews > 0:
                        reviews_el = await item.query_selector(".rating-mini-count, .tc-user .rating-num")
                        reviews = 0
                        if reviews_el:
                            rt = await reviews_el.inner_text()
                            m = re.search(r"\d+", rt.replace(" ", "").replace(",", ""))
                            reviews = int(m.group(0)) if m else 0
                        if reviews < min_seller_reviews:
                            if not first_item_logged:
                                logger.warning(f"FunPay: отзывов {reviews} < {min_seller_reviews}")
                                first_item_logged = True
                            continue

                    if require_auto_delivery:
                        html = await item.inner_html()
                        has_auto = any(x in html.lower() for x in [
                            'auto', 'autodelivery', 'auto-delivery', 'auto_delivery',
                        ])
                        if not has_auto:
                            if not first_item_logged:
                                logger.warning("FunPay: нет автовыдачи")
                                first_item_logged = True
                            continue

                    lot_href = await item.get_attribute("href") or ""
                    lot_id = ""
                    if "id=" in lot_href:
                        lot_id = lot_href.split("id=")[-1].split("&")[0]

                    if used_lot_ids and lot_id and lot_id in used_lot_ids:
                        continue

                    title_el = await item.query_selector(".tc-desc-text")
                    title = (await title_el.inner_text()).strip() if title_el else ""

                    logger.info(f"FunPay: ✓ подходящий лот — «{title}» за ${price:.2f}")

                    description = title
                    lot_region = ""
                    if lot_href:
                        lot_url = lot_href if lot_href.startswith("http") else f"https://funpay.com{lot_href}"
                        logger.info(f"FunPay: открываем страницу лота {lot_url}")
                        description, lot_region = await self._get_lot_description(lot_url)
                        description = description or title
                    if lot_region:
                        logger.info(f"FunPay: регион лота сохранён: {lot_region}")
                    else:
                        logger.warning("FunPay: lot_href пустой — описание не парсим")

                    description = self._strip_links(description)
                    title = self._strip_links(title)

                    image_paths = []
                    if lot_href and lot_id:
                        lot_url_full = lot_href if lot_href.startswith("http") else f"https://funpay.com{lot_href}"
                        image_paths = await self._download_lot_images(lot_url_full, lot_id)
                        if not image_paths:
                            logger.warning("FunPay: фото не найдены — будет использовано дефолтное")

                    return FunPayLot(
                        price=price,
                        title=title or "Account",
                        description=description or title or "Account",
                        href=lot_href,
                        lot_id=lot_id,
                        seller=lot_seller,
                        image_paths=image_paths,
                        region=lot_region,
                    )

                except Exception as e:
                    logger.debug(f"Ошибка парсинга карточки: {e}")
                    continue

            if items:
                try:
                    first_html = await items[0].inner_html()
                    logger.warning(f"FunPay: пример HTML первой карточки:\n{first_html[:500]}")
                except Exception:
                    pass

            logger.warning("FunPay: подходящих лотов не найдено (все отфильтрованы)")
            return None

        except Exception as e:
            logger.error(f"FunPay: ошибка: {e}")
            return None
        finally:
            await page.close()

    async def _get_lot_description(self, lot_url: str) -> tuple:
        """Возвращает (description, region)."""
        page = await self.context.new_page()
        try:
            base = lot_url.split("?")[0]
            sep = "?" if "?" not in lot_url else "&"
            lot_url = lot_url + sep + "setlocale=en&currency=usd"

            await page.goto(lot_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            result = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.param-item');
                    for (const item of items) {
                        const h5 = item.querySelector('h5');
                        if (h5 && h5.innerText.toUpperCase().includes('DETAILED')) {
                            const div = item.querySelector('div');
                            if (div && div.innerText.trim().length > 5)
                                return div.innerText.trim();
                        }
                    }
                    for (const item of items) {
                        const h5 = item.querySelector('h5');
                        if (h5 && h5.innerText.toUpperCase().includes('SHORT')) {
                            const div = item.querySelector('div');
                            if (div && div.innerText.trim().length > 5)
                                return div.innerText.trim();
                        }
                    }
                    return null;
                }
            """)

            region = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.param-item');
                    for (const item of items) {
                        const h5 = item.querySelector('h5');
                        if (h5 && (h5.innerText.toUpperCase().includes('SERVER') || h5.innerText.toUpperCase().includes('REGION'))) {
                            const div = item.querySelector('div');
                            if (div) return div.innerText.trim();
                        }
                    }
                    return '';
                }
            """)
            if region:
                logger.info(f"FunPay: регион лота: {region}")
            if result:
                result = self._strip_links(result)
                logger.info(f"FunPay: описание найдено ({len(result)} символов)")
                return result, region or ""
            logger.warning("FunPay: описание не найдено на странице лота")
            return "", region or ""
        except Exception as e:
            logger.warning(f"FunPay: ошибка при получении описания: {e}")
            return "", ""
        finally:
            await page.close()

    async def _download_lot_images(self, lot_url: str, lot_id: str) -> list:
        folder = Path("lot_images") / lot_id
        folder.mkdir(parents=True, exist_ok=True)

        page = await self.context.new_page()
        saved_paths = []
        try:
            base = lot_url.split("?")[0]
            sep = "?" if "?" not in lot_url else "&"
            url = lot_url + sep + "setlocale=en&currency=usd"

            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            img_urls = await page.evaluate("""
                () => {
                    const results = [];
                    const thumbs = document.querySelectorAll('ul.attachments-list a.attachments-thumb');
                    for (const a of thumbs) {
                        const href = a.getAttribute('href');
                        if (href && !results.includes(href)) {
                            results.push(href);
                        }
                    }
                    return results.slice(0, 5);
                }
            """)

            logger.info(f"FunPay: найдено {len(img_urls)} фото для лота {lot_id}")

            if not img_urls:
                debug_path = f"debug_lot_photo_{lot_id}.png"
                await page.screenshot(path=debug_path)
                logger.warning(f"FunPay: фото не найдены, скриншот → {debug_path}")

            for idx, img_url in enumerate(img_urls):
                try:
                    if not img_url.startswith("http"):
                        img_url = "https://funpay.com" + img_url
                    ext = ".jpg"
                    for candidate in [".png", ".gif", ".webp", ".jpeg", ".jpg"]:
                        if candidate in img_url.lower().split("?")[0]:
                            ext = ".jpg" if candidate == ".jpeg" else candidate
                            break
                    dest = folder / f"photo_{idx+1}{ext}"
                    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        with open(dest, "wb") as f:
                            f.write(resp.read())
                    saved_paths.append(str(dest))
                    logger.info(f"FunPay: ✓ фото {idx+1} → {dest}")
                except Exception as e:
                    logger.warning(f"FunPay: ошибка скачивания фото {idx+1}: {e}")

        except Exception as e:
            logger.warning(f"FunPay: ошибка загрузки фото лота {lot_id}: {e}")
        finally:
            await page.close()

        return saved_paths

    GAME_MAP = [
        (["blox fruit", "bloxfruit"],                         202, "Blox Fruits"),
        (["bee swarm", "bss", "bee sim"],                     347, "Bee Swarm Simulator"),
        (["rivals"],                                          207, "Roblox Rivals"),
        (["attack on titan", "aot", "titan revolution",
          "aot revolution", "attack on titan revolution"],    70,  "Attack on Titan Revolution"),
        (["roblox", "steal a brainrot", "blox", "adopt me",
          "murder mystery", "pet simulator", "brookhaven",
          "jailbreak", "piggy", "da hood", "arsenal",
          "phantom forces"],                                  0,   "Roblox"),
    ]

    def _detect_game(self, title: str) -> tuple[int, str]:
        t = title.lower()
        for keywords, game_id, game_name in self.GAME_MAP:
            for kw in keywords:
                if kw in t:
                    return game_id, game_name
        return 0, "Unknown"

    async def get_seller_lots(
        self,
        seller_url: str,
        min_price_usd: float = 0.0,
        max_price_usd: float = 999999.0,
        used_lot_ids: set = None,
    ) -> list["FunPayLot"]:
        used_lot_ids = used_lot_ids or set()
        page = await self.context.new_page()
        lots = []
        try:
            if not seller_url.endswith("/"):
                seller_url += "/"
            if "/en/" not in seller_url:
                seller_url = seller_url.replace("funpay.com/", "funpay.com/en/")

            logger.info(f"FunPay: открываем профиль продавца {seller_url}")
            await page.goto(seller_url + "?setlocale=en", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            await page.evaluate("""
                () => {
                    var trigger = document.querySelector('a.menu-item-currencies, [data-toggle="dropdown"].menu-item-currencies');
                    if (trigger) trigger.click();
                }
            """)
            await asyncio.sleep(0.8)
            await page.evaluate("""
                () => {
                    var el = document.querySelector('[data-cy="usd"]');
                    if (el) el.click();
                }
            """)
            await asyncio.sleep(1.5)

            items = await page.query_selector_all("a.tc-item, .offer-list-item a, [class*='offer'] a[href*='offer']")
            logger.info(f"FunPay: карточек у продавца: {len(items)}")

            seen = set()
            for item in items:
                try:
                    href = await item.get_attribute("href") or ""
                    if "offer" not in href:
                        continue

                    lot_id = ""
                    if "id=" in href:
                        lot_id = href.split("id=")[-1].split("&")[0]

                    if not lot_id or lot_id in seen or lot_id in used_lot_ids:
                        continue
                    seen.add(lot_id)

                    price_el = await item.query_selector(".tc-price")
                    data_s = await price_el.get_attribute("data-s") if price_el else None
                    try:
                        price = float(data_s) if data_s else None
                    except (ValueError, TypeError):
                        price = None

                    if price is None or price < min_price_usd or price > max_price_usd:
                        continue

                    title_el = await item.query_selector(".tc-desc-text")
                    title = (await title_el.inner_text()).strip() if title_el else ""
                    if not title:
                        continue

                    game_id, game_name = self._detect_game(title)

                    lot_url = href if href.startswith("http") else f"https://funpay.com{href}"

                    lots.append(FunPayLot(
                        price=price,
                        title=self._strip_links(title),
                        description="",
                        href=lot_url,
                        lot_id=lot_id,
                        game_id=game_id,
                        game_name=game_name,
                    ))
                    logger.debug(f"[SELLER] {game_name} | ${price:.2f} | {title[:40]}")

                except Exception as e:
                    logger.debug(f"FunPay seller: ошибка карточки: {e}")
                    continue

        except Exception as e:
            logger.error(f"FunPay seller: ошибка парсинга {seller_url}: {e}")
        finally:
            await page.close()

        logger.info(f"FunPay: у продавца найдено {len(lots)} подходящих лотов")
        return lots

    def _strip_links(self, text: str) -> str:
        text = re.sub(r'https?://\S+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'ftp://\S+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'www\.\S+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\b\S+\.(com|ru|net|org|gg|io|me|co|info|biz|tv|app|shop|store|pro|club|site|online|fun|games?)\b\S*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'@\S+', '', text)
        text = re.sub(r't\.me/\S+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'discord\S*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'vk\.com/\S+', '', text, flags=re.IGNORECASE)
        text = re.sub(r' {2,}', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _parse_price(self, text: str) -> Optional[float]:
        text = text.strip().replace(" ", " ").replace("\xa0", " ")
        for p in [r"\$\s*([\d\s,\.]+)", r"([\d\s,\.]+)\s*\$", r"([\d\s,\.]+)\s*USD"]:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                val = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    return float(val)
                except ValueError:
                    continue
        m = re.search(r"([\d]+[.,]?[\d]*)", text.replace(" ", ""))
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        return None
