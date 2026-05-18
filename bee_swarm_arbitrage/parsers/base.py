from dataclasses import dataclass


@dataclass
class Listing:
    item_name_raw: str
    item_name: str        # canonical name
    variant_key: str      # e.g. "gifted|lv:max|mutated", "base"
    variant_display: str  # e.g. "Gifted Lv15+ Mutated", ""
    price_usd: float      # total lot price
    price_per_unit: float # price_usd / quantity
    quantity: int
    seller: str
    url: str
    platform: str

    @property
    def inventory_key(self) -> str:
        """Key used to store in inventory (name + variant)."""
        if self.variant_display:
            return f"{self.item_name} ({self.variant_display})"
        return self.item_name


class BaseParser:
    platform: str = "unknown"

    async def get_listings(self) -> list[Listing]:
        raise NotImplementedError
