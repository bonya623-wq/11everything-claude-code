import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_usd, parse_millions, detect_server
import config

log = logging.getLogger(__name__)

_CARDS   = ["[class*='offer-card']", "[class*='listing-card']", "[class*='product-card']", "article"]
_TITLES  = ["[class*='title']", "[class*='name']", "h3", "h2"]
_PRICES  = ["[class*='price']", "[class*='amount']", "[class*='cost']"]
_SELLERS = ["[class*='seller']", "[class*='user']", "[class*='merchant']"]


class EldoradoParser(BaseParser):
    platform = "Eldorado"

    def __init__(self, url: str = None):
        self.url = url or config.ELDORADO_URL

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

                cards = []
                for sel in _CARDS:
                    cards = await page.query_selector_all(sel)
                    if cards:
                        break

                for card in cards:
                    try:
                        title_el  = await _first(card, _TITLES)
                        price_el  = await _first(card, _PRICES)
                        seller_el = await _first(card, _SELLERS)
                        link_el   = await card.query_selector("a")

                        if not title_el or not price_el:
                            continue

                        raw    = (await title_el.inner_text()).strip()
                        price  = parse_usd((await price_el.inner_text()).strip())
                        seller = (await seller_el.inner_text()).strip() if seller_el else "unknown"
                        href   = await link_el.get_attribute("href") if link_el else ""

                        amount = parse_millions(raw)
                        if not price or not amount:
                            continue

                        server = detect_server(raw + " " + self.url)
                        if server != config.ALBION_SERVER:
                            continue

                        url = href if (href and href.startswith("http")) else f"https://www.eldorado.gg{href or ''}"
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
                        log.debug(f"Eldorado card: {e}")

            except PWTimeout:
                log.warning(f"Eldorado timeout")
            except Exception as e:
                log.error(f"Eldorado: {e}")
            finally:
                await browser.close()

        log.info(f"Eldorado: {len(listings)} EU silver listings")
        return listings


async def _first(el, sels):
    for s in sels:
        found = await el.query_selector(s)
        if found:
            return found
    return None
