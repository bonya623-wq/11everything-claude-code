import re
from rapidfuzz import fuzz, process

# Canonical item names — the ground truth for grouping
CANONICAL_ITEMS = [
    # Consumables
    "Royal Jelly",
    "Honey",
    "Ticket",
    "Wax",
    "Oil",
    "Glitter",
    "Tropical Drink",
    "Enzymes",
    "Coconut Oil",
    "Caustic Wax",
    "Hard Wax",
    "Turpentine",
    # Foods
    "Strawberry",
    "Blueberry",
    "Sunflower Seed",
    "Pineapple",
    "Coconut",
    "Pepper",
    "Clover",
    "Honeysuckle",
    "Stinger",
    "Pollen",
    # Dice
    "Field Dice",
    "Smooth Dice",
    "Loaded Dice",
    # Beans
    "Magic Bean",
    "Jelly Bean",
    # Eggs
    "Basic Egg",
    "Silver Egg",
    "Gold Egg",
    "Diamond Egg",
    "Star Egg",
    "Mythic Egg",
    "Festive Egg",
    "Gifted Egg",
    "Magic Egg",
    "Photon Egg",
    "Windy Egg",
    # Special items
    "Marshmallow Bee",
    "Gingerbread Bear",
    "Stump Snail Shell",
    "Scratch-B-Gone",
    "Micro-Convertor",
    "Mountain Top Dew",
    "Ant Pass",
    "Glue",
    "Sap",
    "Star Treat",
    "Honey Token",
    # Maps
    "Pine Tree Forest Map",
    "Mushroom Field Map",
    "Blue Flower Field Map",
    "Bamboo Field Map",
    "Sunflower Field Map",
    "Dandelion Field Map",
    "Spider Field Map",
    "Strawberry Field Map",
    "Clover Field Map",
    "Rose Field Map",
]

_NOISE = re.compile(
    r'\b(?:bee\s*swarm|simulator|roblox|bss|items?|lots?|pack|bundle|cheap|fast|delivery)\b',
    re.IGNORECASE,
)
_QTY_PATTERN = re.compile(
    r'[xх×]\s*(\d+)|(\d+)\s*[xх×]|(\d+)\s*(?:pcs|шт|ед|units?|штук|pc)',
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    """Strip quantity markers and marketplace noise from a listing title."""
    s = _NOISE.sub(' ', title)
    s = _QTY_PATTERN.sub(' ', s)
    s = re.sub(r'[^\w\s\-]', ' ', s)
    return ' '.join(s.split()).strip()


def normalize_item(raw_title: str, threshold: int = 72) -> str | None:
    """Return the closest canonical item name, or None if confidence is too low."""
    cleaned = clean_title(raw_title)
    if not cleaned:
        return None
    result = process.extractOne(
        cleaned,
        CANONICAL_ITEMS,
        scorer=fuzz.partial_ratio,
        score_cutoff=threshold,
    )
    return result[0] if result else None


def extract_quantity(title: str) -> int:
    """Extract lot size from title. Returns 1 if nothing found."""
    m = _QTY_PATTERN.search(title)
    if m:
        for g in m.groups():
            if g:
                return int(g)
    return 1
