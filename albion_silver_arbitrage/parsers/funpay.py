import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_usd, parse_millions, detect_server
import config

log = logging.getLogger(__name__)


class FunPayParser(BaseParser):
    """
    FunPay chips page for Albion Online.
    Find the correct category URL: funpay.com/chips/ → Albion Online.
    """
    platform = "FunPay"

    def __init__(self, url: str = None):
        self.url = url or config.FUNPAY_URL

    async def get_listings(self) -> list[SilverListing]:
        listings: list[SilverListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(2)

                cards = await page.query_selector_all("a.tc-item")
                log.debug(f"FunPay cards: {len(cards)}")

                for card in cards:
                    try:
                        title_el = await card.query_selector(".tc-desc-text")
                        price_el = await card.query_selector(".tc-price div") or await card.query_selector(".tc-price")
                        seller_el = await card.query_selector(".media-user-name span")

                        if not title_el or not price_el:
                            continue

                        raw   = (await title_el.inner_text()).strip()
                        price = parse_usd((await price_el.inner_text()).strip())
                        seller = (await seller_el.inner_text()).strip() if seller_el else "unknown"
                        href  = await card.get_attribute("href") or ""

                        amount = parse_millions(raw)
                        if not price or not amount:
                            continue

                        server = detect_server(raw)
                        if server != config.ALBION_SERVER:
                            continue

                        url = href if href.startswith("http") else f"https://funpay.com{href}"
                        listings.append(SilverListing(
                            amount_millions=amount,
                            price_usd=price,
                            price_per_million=round(price / amount, 6),
                            server=server,
                            seller=seller,
                            url=url,
                            platform=self.platform,
                            raw_title=raw,
                        ))
                    except Exception as e:
                        log.debug(f"FunPay card: {e}")

            except PWTimeout:
                log.warning(f"FunPay timeout")
            except Exception as e:
                log.error(f"FunPay: {e}")
            finally:
                await browser.close()

        log.info(f"FunPay: {len(listings)} EU silver listings")
        return listings
