import asyncio
import logging
import threading

import config
from parsers import ALL_PARSERS
from detector import detect_deals
from bot import bot, send_deal_alert, set_listings, start_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

_seen: set[str] = set()


async def scan_once() -> None:
    log.info("Scan started")
    all_listings = []

    # Run all parsers concurrently
    tasks = [parser_cls().get_listings() for parser_cls in ALL_PARSERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for parser_cls, result in zip(ALL_PARSERS, results):
        if isinstance(result, Exception):
            log.error(f"{parser_cls.__name__}: {result}")
        else:
            all_listings.extend(result)

    log.info(f"Total: {len(all_listings)} EU silver listings")
    set_listings(all_listings)

    deals = detect_deals(all_listings)
    log.info(f"Deals: {len(deals)}")

    for deal in deals:
        key = f"{deal.listing.platform}|{deal.listing.url}"
        if key not in _seen:
            _seen.add(key)
            try:
                send_deal_alert(deal)
                log.info(f"Alert: {deal.listing.platform} ${deal.listing.price_per_million:.4f}/M (-{deal.discount_vs_avg}%)")
            except Exception as e:
                log.error(f"Alert failed: {e}")


async def scan_loop() -> None:
    while True:
        await scan_once()
        log.info(f"Next scan in {config.SCAN_INTERVAL}s")
        await asyncio.sleep(config.SCAN_INTERVAL)


def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN not set")
    if not config.TELEGRAM_CHAT_ID:
        raise SystemExit("TELEGRAM_CHAT_ID not set")

    threading.Thread(
        target=lambda: asyncio.run(scan_loop()),
        daemon=True, name="scanner",
    ).start()
    log.info("Scanner started")

    start_polling()


if __name__ == "__main__":
    main()
