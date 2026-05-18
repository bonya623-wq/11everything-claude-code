from dataclasses import dataclass
from collections import defaultdict

from parsers.base import Listing
import config


@dataclass
class Deal:
    listing: Listing
    avg_market_price: float    # avg price/unit across all platforms
    platform_min_price: float  # cheapest price/unit on this listing's platform
    discount_vs_avg: float     # % cheaper than avg (positive = good deal)
    discount_vs_platform: float


def detect_deals(all_listings: list[Listing]) -> list[Deal]:
    """Return listings that are significantly below average or platform minimum."""
    by_item: dict[str, list[Listing]] = defaultdict(list)
    for lst in all_listings:
        by_item[lst.item_name].append(lst)

    deals: list[Deal] = []

    for item_listings in by_item.values():
        if len(item_listings) < 2:
            continue

        prices = [lst.price_per_unit for lst in item_listings]
        avg_price = sum(prices) / len(prices)

        by_platform: dict[str, list[float]] = defaultdict(list)
        for lst in item_listings:
            by_platform[lst.platform].append(lst.price_per_unit)
        platform_mins = {p: min(v) for p, v in by_platform.items()}

        for lst in item_listings:
            ppu = lst.price_per_unit
            plat_min = platform_mins[lst.platform]

            disc_avg = (avg_price - ppu) / avg_price * 100 if avg_price else 0
            disc_plat = (plat_min - ppu) / plat_min * 100 if plat_min else 0

            if disc_avg >= config.THRESHOLD_VS_AVERAGE or disc_plat >= config.THRESHOLD_VS_PLATFORM_MIN:
                deals.append(Deal(
                    listing=lst,
                    avg_market_price=round(avg_price, 4),
                    platform_min_price=round(plat_min, 4),
                    discount_vs_avg=round(disc_avg, 1),
                    discount_vs_platform=round(disc_plat, 1),
                ))

    deals.sort(key=lambda d: d.discount_vs_avg, reverse=True)
    return deals
