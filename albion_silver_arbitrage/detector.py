from dataclasses import dataclass
from collections import defaultdict

from parsers.base import SilverListing
import config


@dataclass
class Deal:
    listing: SilverListing
    avg_price_per_million: float
    market_min_per_million: float   # cheapest across ALL platforms
    discount_vs_avg: float          # % cheaper than average
    platform_prices: dict[str, float]  # best price per platform for context


def detect_deals(all_listings: list[SilverListing]) -> list[Deal]:
    if not all_listings:
        return []

    prices = [lst.price_per_million for lst in all_listings]
    avg    = sum(prices) / len(prices)
    mkt_min = min(prices)

    # Best (cheapest) price per platform
    by_platform: dict[str, list[float]] = defaultdict(list)
    for lst in all_listings:
        by_platform[lst.platform].append(lst.price_per_million)
    platform_best = {p: min(v) for p, v in by_platform.items()}

    deals: list[Deal] = []
    for lst in all_listings:
        disc = (avg - lst.price_per_million) / avg * 100 if avg else 0
        if disc >= config.THRESHOLD_VS_AVERAGE:
            deals.append(Deal(
                listing=lst,
                avg_price_per_million=round(avg, 6),
                market_min_per_million=round(mkt_min, 6),
                discount_vs_avg=round(disc, 1),
                platform_prices=platform_best,
            ))

    deals.sort(key=lambda d: d.discount_vs_avg, reverse=True)
    return deals


def market_summary(all_listings: list[SilverListing]) -> dict:
    """Return per-platform best price + overall stats."""
    if not all_listings:
        return {}

    by_platform: dict[str, list[SilverListing]] = defaultdict(list)
    for lst in all_listings:
        by_platform[lst.platform].append(lst)

    summary = {}
    for platform, items in by_platform.items():
        best = min(items, key=lambda x: x.price_per_million)
        summary[platform] = {
            "best_price_per_million": best.price_per_million,
            "listings_count": len(items),
            "best_url": best.url,
            "best_seller": best.seller,
        }
    return summary
