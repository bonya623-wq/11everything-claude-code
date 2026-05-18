from dataclasses import dataclass
from collections import defaultdict

from parsers.base import Listing
import config


@dataclass
class Deal:
    listing: Listing
    avg_market_price: float
    platform_min_price: float
    discount_vs_avg: float
    discount_vs_platform: float


def detect_deals(all_listings: list[Listing]) -> list[Deal]:
    """
    Group listings by (item_name, variant_key) so that e.g.
    'Gifted Basic Bee Lv15+' and 'Basic Bee Lv5-9' are compared
    only within their own group.
    """
    # group key = canonical name + variant (e.g. "Basic Bee::gifted|lv:max")
    by_group: dict[str, list[Listing]] = defaultdict(list)
    for lst in all_listings:
        key = f"{lst.item_name}::{lst.variant_key}"
        by_group[key].append(lst)

    deals: list[Deal] = []

    for group_listings in by_group.values():
        if len(group_listings) < 2:
            continue

        prices = [lst.price_per_unit for lst in group_listings]
        avg_price = sum(prices) / len(prices)

        by_platform: dict[str, list[float]] = defaultdict(list)
        for lst in group_listings:
            by_platform[lst.platform].append(lst.price_per_unit)
        platform_mins = {p: min(v) for p, v in by_platform.items()}

        for lst in group_listings:
            ppu      = lst.price_per_unit
            plat_min = platform_mins[lst.platform]

            disc_avg  = (avg_price - ppu) / avg_price * 100 if avg_price else 0
            disc_plat = (plat_min - ppu) / plat_min * 100  if plat_min  else 0

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
