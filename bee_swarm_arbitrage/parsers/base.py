from dataclasses import dataclass


@dataclass
class Listing:
    item_name_raw: str
    item_name: str        # canonical name after fuzzy match
    price_usd: float      # total lot price
    price_per_unit: float # price_usd / quantity
    quantity: int
    seller: str
    url: str
    platform: str


class BaseParser:
    platform: str = "unknown"

    async def get_listings(self) -> list[Listing]:
        raise NotImplementedError
