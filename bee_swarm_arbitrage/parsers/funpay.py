import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, Listing
from ._helpers import parse_usd
from normalizer import normalize_item, extract_quantity
import config

log = logging.getLogger(__name__)


class FunPayParser(BaseParser):
    """
    Parses FunPay lot listing page.
    URL: https://funpay.com/lots/<category_id>/
    Find the correct category ID by browsing FunPay for Bee Swarm Simulator.
    """
    platform = "FunPay"

    def __init__(self, url: str = None):
        self.url = url or config.FUNPAY_URL

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
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(2)

                cards = await page.query_selector_all("a.tc-item")
                log.debug(f"FunPay raw cards: {len(cards)}")

                for card in cards:
                    try:
                        title_el = await card.query_selector(".tc-desc-text")
                        # Price can be in .tc-price div or direct .tc-price
                        price_el = (
                            await card.query_selector(".tc-price div")
                            or await card.query_selector(".tc-price")
                        )
                        seller_el = await card.query_selector(".media-user-name span")

                        if not title_el or not price_el:
                            continue

                        raw_title = (await title_el.inner_text()).strip()
                        price_text = (await price_el.inner_text()).strip()
                        seller = (
                            (await seller_el.inner_text()).strip()
                            if seller_el else "unknown"
                        )
                        href = await card.get_attribute("href") or ""

                        price = parse_usd(price_text)
                        if not price:
                            continue

                        canonical = normalize_item(raw_title, config.FUZZY_THRESHOLD)
                        if not canonical:
                            log.debug(f"FunPay no match: '{raw_title}'")
                            continue

                        qty = extract_quantity(raw_title)
                        url = href if href.startswith("http") else f"https://funpay.com{href}"

                        listings.append(Listing(
                            item_name_raw=raw_title,
                            item_name=canonical,
                            price_usd=price,
                            price_per_unit=round(price / max(qty, 1), 6),
                            quantity=qty,
                            seller=seller,
                            url=url,
                            platform=self.platform,
                        ))
                    except Exception as e:
                        log.debug(f"FunPay card error: {e}")

            except PWTimeout:
                log.warning(f"FunPay timeout: {self.url}")
            except Exception as e:
                log.error(f"FunPay error: {e}")
            finally:
                await browser.close()

        log.info(f"FunPay: {len(listings)} listings")
        return listings
