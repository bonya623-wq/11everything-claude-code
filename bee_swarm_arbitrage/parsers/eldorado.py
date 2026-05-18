import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, Listing
from ._helpers import parse_usd
from normalizer import normalize_and_extract, extract_quantity
import config

log = logging.getLogger(__name__)

_CARD_SELECTORS = [
    "[class*='offer-card']", "[class*='listing-card']",
    "[class*='product-card']", "[class*='item-card']", "article",
]
_TITLE_SELECTORS = ["[class*='title']", "[class*='name']", "h3", "h2", "h4"]
_PRICE_SELECTORS = ["[class*='price']", "[class*='amount']", "[class*='cost']"]
_SELLER_SELECTORS = ["[class*='seller']", "[class*='user']", "[class*='merchant']"]


class EldoradoParser(BaseParser):
    platform = "Eldorado"

    def __init__(self, url: str = None):
        self.url = url or config.ELDORADO_URL

    async def get_listings(self) -> list[Listing]:
        listings: list[Listing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=40_000)
                await asyncio.sleep(3)

                cards = []
                for sel in _CARD_SELECTORS:
                    cards = await page.query_selector_all(sel)
                    if cards:
                        log.debug(f"Eldorado selector: {sel}, {len(cards)} cards")
                        break

                for card in cards:
                    try:
                        title_el  = await _first(card, _TITLE_SELECTORS)
                        price_el  = await _first(card, _PRICE_SELECTORS)
                        seller_el = await _first(card, _SELLER_SELECTORS)
                        link_el   = await card.query_selector("a")

                        if not title_el or not price_el:
                            continue

                        raw_title = (await title_el.inner_text()).strip()
                        price_text = (await price_el.inner_text()).strip()
                        seller    = (await seller_el.inner_text()).strip() if seller_el else "unknown"
                        href      = await link_el.get_attribute("href") if link_el else ""

                        price = parse_usd(price_text)
                        if not price:
                            continue

                        canonical, variant = normalize_and_extract(raw_title, config.FUZZY_THRESHOLD)
                        if canonical is None:
                            log.debug(f"Eldorado no match: '{raw_title}'")
                            continue

                        qty = extract_quantity(raw_title)
                        url = href if (href and href.startswith("http")) else f"https://www.eldorado.gg{href or ''}"

                        listings.append(Listing(
                            item_name_raw=raw_title,
                            item_name=canonical,
                            variant_key=variant.key(),
                            variant_display=variant.display(),
                            price_usd=price,
                            price_per_unit=round(price / max(qty, 1), 6),
                            quantity=qty,
                            seller=seller,
                            url=url,
                            platform=self.platform,
                        ))
                    except Exception as e:
                        log.debug(f"Eldorado card error: {e}")

            except PWTimeout:
                log.warning(f"Eldorado timeout: {self.url}")
            except Exception as e:
                log.error(f"Eldorado error: {e}")
            finally:
                await browser.close()

        log.info(f"Eldorado: {len(listings)} listings")
        return listings


async def _first(element, selectors):
    for sel in selectors:
        el = await element.query_selector(sel)
        if el:
            return el
    return None
