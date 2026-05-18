import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_usd, parse_millions, detect_server
import config

log = logging.getLogger(__name__)


class MMOGAParser(BaseParser):
    """
    MMOGA — German storefront, fixed-price packages (50M, 60M, 80M, 90M).
    Prices ~$0.35–0.55/M. Useful as a price ceiling reference.
    """
    platform = "MMOGA"

    def __init__(self, url: str = None):
        self.url = url or config.MMOGA_URL

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
                await asyncio.sleep(3)

                cards = await page.query_selector_all(
                    "[class*='product'], [class*='article'], [class*='item'], article, li"
                )

                for card in cards:
                    try:
                        raw = (await card.inner_text()).strip()
                        if not raw:
                            continue

                        price_el = await card.query_selector("[class*='price'], [class*='amount'], strong, b")
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
                        url  = href if (href and href.startswith("http")) else f"https://www.mmoga.com{href or ''}"

                        listings.append(SilverListing(
                            amount_millions=amount,
                            price_usd=price,
                            price_per_million=round(price / amount, 6),
                            server=server,
                            seller="MMOGA",
                            url=url or self.url,
                            platform=self.platform,
                            raw_title=raw[:120],
                        ))
                    except Exception as e:
                        log.debug(f"MMOGA card: {e}")

            except PWTimeout:
                log.warning("MMOGA timeout")
            except Exception as e:
                log.error(f"MMOGA: {e}")
            finally:
                await browser.close()

        log.info(f"MMOGA: {len(listings)} EU silver listings")
        return listings
