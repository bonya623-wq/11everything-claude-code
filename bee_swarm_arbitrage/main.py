import asyncio
import logging
import threading

import config
from parsers import FunPayParser, G2GParser, EldoradoParser
from detector import detect_deals
from bot import bot, send_deal_alert, start_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# Track sent deals to avoid duplicate alerts within the same session
_seen: set[str] = set()


async def scan_once() -> None:
    log.info("Scan started")
    parsers = [FunPayParser(), G2GParser(), EldoradoParser()]
    all_listings = []

    for parser in parsers:
        try:
            listings = await parser.get_listings()
            all_listings.extend(listings)
        except Exception as e:
            log.error(f"{parser.platform} failed: {e}")

    log.info(f"Total listings: {len(all_listings)}")
    if not all_listings:
        return

    deals = detect_deals(all_listings)
    log.info(f"Deals found: {len(deals)}")

    for deal in deals:
        key = f"{deal.listing.platform}|{deal.listing.url}"
        if key in _seen:
            continue
        _seen.add(key)
        try:
            send_deal_alert(deal)
            log.info(f"Alert: {deal.listing.item_name} -{deal.discount_vs_avg}% @ {deal.listing.platform}")
        except Exception as e:
            log.error(f"Alert send failed: {e}")


async def scan_loop() -> None:
    while True:
        await scan_once()
        log.info(f"Next scan in {config.SCAN_INTERVAL}s")
        await asyncio.sleep(config.SCAN_INTERVAL)


def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN not set — copy .env.example to .env and fill it in")
    if not config.TELEGRAM_CHAT_ID:
        raise SystemExit("TELEGRAM_CHAT_ID not set — copy .env.example to .env and fill it in")

    # Scanner runs in a background thread with its own event loop
    def _run_scanner():
        asyncio.run(scan_loop())

    scanner = threading.Thread(target=_run_scanner, daemon=True, name="scanner")
    scanner.start()
    log.info("Scanner thread started")

    # Bot polling runs in the main thread
    start_polling()


if __name__ == "__main__":
    main()
