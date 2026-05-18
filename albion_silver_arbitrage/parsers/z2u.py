import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_usd, parse_millions, detect_server
import config

log = logging.getLogger(__name__)


class Z2UParser(BaseParser):
    """
    Z2U — Chinese origin marketplace, often the cheapest source.
    Has English interface and USD prices.
    """
    platform = "Z2U"

    def __init__(self, url: str = None):
        self.url = url or config.Z2U_URL

    async def get_listings(self) -> list[SilverListing]:
        listings: list[SilverListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=40_000)
                await asyncio.sleep(4)  # Z2U is slower to load

                cards = await page.query_selector_all(
                    ".goods-list-item, [class*='offer-item'], [class*='goods-item'], li.item"
                )

                for card in cards:
                    try:
                        raw = (await card.inner_text()).strip()
                        if not raw:
                            continue

                        price_el = await card.query_selector("[class*='price'], .price, strong")
                        if not price_el:
                            continue

                        price  = parse_usd((await price_el.inner_text()).strip())
                        amount = parse_millions(raw)

                        if not price or not amount:
                            continue

                        server = detect_server(raw + " " + self.url)
                        if server != config.ALBION_SERVER:
                            continue

                        link_el = await card.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else ""
                        url  = href if (href and href.startswith("http")) else f"https://www.z2u.com{href or ''}"

                        seller_el = await card.query_selector("[class*='seller'], [class*='user'], [class*='name']")
                        seller = (await seller_el.inner_text()).strip() if seller_el else "unknown"

                        listings.append(SilverListing(
                            amount_millions=amount,
                            price_usd=price,
                            price_per_million=round(price / amount, 6),
                            server=server,
                            seller=seller,
                            url=url or self.url,
                            platform=self.platform,
                            raw_title=raw[:120],
                        ))
                    except Exception as e:
                        log.debug(f"Z2U card: {e}")

            except PWTimeout:
                log.warning("Z2U timeout")
            except Exception as e:
                log.error(f"Z2U: {e}")
            finally:
                await browser.close()

        log.info(f"Z2U: {len(listings)} EU silver listings")
        return listings
