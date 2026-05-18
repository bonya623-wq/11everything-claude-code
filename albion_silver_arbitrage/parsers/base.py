from dataclasses import dataclass


@dataclass
class SilverListing:
    amount_millions: float    # normalised to millions
    price_usd: float          # total lot price in USD
    price_per_million: float  # price_usd / amount_millions
    server: str               # "EU", "NA", "East", "Unknown"
    seller: str
    url: str
    platform: str
    raw_title: str


class BaseParser:
    platform: str = "unknown"

    async def get_listings(self) -> list[SilverListing]:
        raise NotImplementedError
