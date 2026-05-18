import asyncio
import logging
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import BaseParser, SilverListing
from ._helpers import parse_millions, detect_server
import config
import re

log = logging.getLogger(__name__)

# DD373 shows prices in CNY — we convert with a rough rate
# Update CNY_TO_USD if the rate changes significantly
CNY_TO_USD = 0.138  # ~7.25 CNY = 1 USD (May 2026)


class DD373Parser(BaseParser):
    """
    DD373.com (唧唧网) — Chinese P2P platform, cheapest source globally.
    ~$0.10–0.14/M for EU server.

    URL structure:
      s-45284s          = Albion Online game
      c-pt2hbv          = game currency (游戏币)
      nbs7qm            = silver (銀币)
      8v8te6            = EU server (欧服)

    Requires: Chinese account + Alipay/WeChat Pay to actually buy.
    Parsing only (no login needed to VIEW listings).
    """
    platform = "DD373"
    URL = "https://www.dd373.com/s-45284s-c-pt2hbv-nbs7qm-8v8te6.html"

    def __init__(self, url: str = None):
        self.url = url or self.URL

    async def get_listings(self) -> list[SilverListing]:
        listings: list[SilverListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
                # Chinese locale so the page renders properly
                locale="zh-CN",
            )
            page = await ctx.new_page()
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=35_000)
                await asyncio.sleep(3)

                # DD373 listing rows
                cards = await page.query_selector_all(
                    ".goods-item, .sell-item, [class*='goods-list'] li, "
                    "[class*='item-list'] li, .list-item"
                )
                log.debug(f"DD373 raw cards: {len(cards)}")

                for card in cards:
                    try:
                        raw = (await card.inner_text()).strip()
                        if not raw:
                            continue

                        # Price in CNY
                        price_el = await card.query_selector(
                            "[class*='price'], .price, [class*='money'], strong, b"
                        )
                        if not price_el:
                            continue

                        price_text = (await price_el.inner_text()).strip()
                        price_cny = _parse_cny(price_text)
                        if not price_cny:
                            continue
                        price_usd = round(price_cny * CNY_TO_USD, 4)

                        amount = parse_millions(raw)
                        if not amount:
                            continue

                        # EU server listings on this URL are pre-filtered,
                        # but double-check if title mentions other servers
                        if _is_other_server(raw):
                            continue

                        link_el = await card.query_selector("a")
                        href = await link_el.get_attribute("href") if link_el else ""
                        url  = href if (href and href.startswith("http")) else f"https://www.dd373.com{href or ''}"

                        seller_el = await card.query_selector(
                            "[class*='seller'], [class*='user'], [class*='nickname']"
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
                        log.debug(f"DD373 card: {e}")

            except PWTimeout:
                log.warning("DD373 timeout")
            except Exception as e:
                log.error(f"DD373: {e}")
            finally:
                await browser.close()

        log.info(f"DD373: {len(listings)} EU silver listings")
        return listings


def _parse_cny(text: str) -> float | None:
    """Extract CNY amount from strings like '¥28.80' or '28.80元'."""
    text = text.replace('\xa5', '').replace('％', '').replace(',', '').strip()
    m = re.search(r'[\d.]+', text)
    if m:
        try:
            v = float(m.group())
            return v if 0 < v < 100_000 else None
        except ValueError:
            return None
    return None


_OTHER_SERVERS = re.compile(r'\b(?:NA|亚服|美服|East|Asia|Steam)\b', re.IGNORECASE)

def _is_other_server(text: str) -> bool:
    return bool(_OTHER_SERVERS.search(text))
