import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_usd, parse_millions, detect_server
import config

log = logging.getLogger(__name__)


class PlayerAuctionsParser(BaseParser):
    platform = "PlayerAuctions"

    def __init__(self, url: str = None):
        self.url = url or config.PLAYERAUCTIONS_URL

    async def get_listings(self) -> list[SilverListing]:
        listings: list[SilverListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=40_000)
                await asyncio.sleep(3)

                # PlayerAuctions uses .auction-item or similar rows
                cards = await page.query_selector_all(".auction-item, [class*='offer-row'], [class*='listing-row'], tr.offer")
                if not cards:
                    cards = await page.query_selector_all("article, [class*='offer-card']")

                for card in cards:
                    try:
                        raw    = (await card.inner_text()).strip()
                        price_el = await card.query_selector("[class*='price'], [class*='amount']")
                        link_el  = await card.query_selector("a")

                        if not price_el:
                            continue

                        price  = parse_usd((await price_el.inner_text()).strip())
                        amount = parse_millions(raw)
                        if not price or not amount:
                            continue

                        server = detect_server(raw + " " + self.url)
                        if server != config.ALBION_SERVER:
                            continue

                        href = await link_el.get_attribute("href") if link_el else ""
                        url  = href if (href and href.startswith("http")) else f"https://www.playerauctions.com{href or ''}"

                        seller_el = await card.query_selector("[class*='seller'], [class*='user'], [class*='name']")
                        seller = (await seller_el.inner_text()).strip() if seller_el else "unknown"

                        listings.append(SilverListing(
                            amount_millions=amount,
                            price_usd=price,
                            price_per_million=round(price / amount, 6),
                            server=server,
                            seller=seller,
                            url=url,
                            platform=self.platform,
                            raw_title=raw[:120],
                        ))
                    except Exception as e:
                        log.debug(f"PA card: {e}")

            except PWTimeout:
                log.warning("PlayerAuctions timeout")
            except Exception as e:
                log.error(f"PlayerAuctions: {e}")
            finally:
                await browser.close()

        log.info(f"PlayerAuctions: {len(listings)} EU silver listings")
        return listings
