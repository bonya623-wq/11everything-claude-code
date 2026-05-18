import asyncio
import logging
import re
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_millions
import config

log = logging.getLogger(__name__)

CNY_TO_USD = 0.138  # ~7.25 CNY = 1 USD (May 2026)


class UU898Parser(BaseParser):
    """
    UU898.com (悠悠网) — Chinese P2P platform, ~$0.12–0.16/M.
    URL: https://www.uu898.com/newTrade-1588/
    Filter to EU server (欧服) after page load.
    """
    platform = "UU898"
    URL = "https://www.uu898.com/newTrade-1588/"

    def __init__(self, url: str = None):
        self.url = url or self.URL

    async def get_listings(self) -> list[SilverListing]:
        listings: list[SilverListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=35_000)
                await asyncio.sleep(3)

                # Try to click EU server filter if available
                eu_btn = await page.query_selector(
                    "a:has-text('欧服'), a:has-text('EU'), "
                    "[data-area]:has-text('欧'), span:has-text('欧服')"
                )
                if eu_btn:
                    await eu_btn.click()
                    await asyncio.sleep(2)
                    log.debug("UU898: clicked EU server filter")

                cards = await page.query_selector_all(
                    ".sell-list li, .goods-list li, [class*='trade-item'], "
                    "[class*='sell-item'], [class*='goods-item']"
                )
                log.debug(f"UU898 raw cards: {len(cards)}")

                for card in cards:
                    try:
                        raw = (await card.inner_text()).strip()
                        if not raw:
                            continue

                        # Skip non-EU listings
                        if not _is_eu(raw):
                            continue

                        price_el = await card.query_selector(
                            "[class*='price'], .price, [class*='money'], strong, b"
                        )
                        if not price_el:
                            continue

                        price_cny = _parse_cny((await price_el.inner_text()).strip())
                        if not price_cny:
                            continue
                        price_usd = round(price_cny * CNY_TO_USD, 4)

                        amount = parse_millions(raw)
                        if not amount:
                            continue

                        link_el = await card.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else ""
                        url  = href if (href and href.startswith("http")) else f"https://www.uu898.com{href or ''}"

                        seller_el = await card.query_selector(
                            "[class*='seller'], [class*='user'], [class*='nick'], [class*='name']"
                        )
                        seller = (await seller_el.inner_text()).strip() if seller_el else "unknown"

                        listings.append(SilverListing(
                            amount_millions=amount,
                            price_usd=price_usd,
                            price_per_million=round(price_usd / amount, 6),
                            server="EU",
                            seller=seller,
                            url=url or self.url,
                            platform=self.platform,
                            raw_title=raw[:120],
                        ))
                    except Exception as e:
                        log.debug(f"UU898 card: {e}")

            except PWTimeout:
                log.warning("UU898 timeout")
            except Exception as e:
                log.error(f"UU898: {e}")
            finally:
                await browser.close()

        log.info(f"UU898: {len(listings)} EU silver listings")
        return listings


def _parse_cny(text: str) -> float | None:
    text = text.replace('\xa5', '').replace(',', '').strip()
    m = re.search(r'[\d.]+', text)
    if m:
        try:
            v = float(m.group())
            return v if 0 < v < 100_000 else None
        except ValueError:
            return None
    return None


_EU_RE = re.compile(r'\b(?:EU|欧服|欧洲)\b', re.IGNORECASE)

def _is_eu(text: str) -> bool:
    return bool(_EU_RE.search(text))
