import re
from dataclasses import dataclass
from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Canonical item names  (base form — without "Gifted" prefix for bees)
# ---------------------------------------------------------------------------
CANONICAL_ITEMS = [
    # Consumables
    "Royal Jelly", "Honey", "Ticket", "Wax", "Oil", "Glitter",
    "Tropical Drink", "Enzymes", "Coconut Oil", "Caustic Wax", "Hard Wax",
    "Turpentine", "Star Jelly",
    # Foods
    "Strawberry", "Blueberry", "Sunflower Seed", "Pineapple", "Coconut",
    "Pepper", "Clover", "Honeysuckle", "Stinger", "Pollen",
    # Dice / beans / misc items
    "Field Dice", "Smooth Dice", "Loaded Dice",
    "Magic Bean", "Jelly Bean",
    "Micro-Convertor", "Scratch-B-Gone", "Mountain Top Dew",
    "Ant Pass", "Glue", "Sap", "Honey Token", "Star Treat",
    "Marshmallow Bee", "Gingerbread Bear", "Stump Snail Shell",
    # Eggs ("Gifted Egg" is a real item, kept as-is)
    "Basic Egg", "Silver Egg", "Gold Egg", "Diamond Egg",
    "Star Egg", "Mythic Egg", "Festive Egg", "Gifted Egg",
    "Magic Egg", "Photon Egg", "Windy Egg",
    # Field maps
    "Pine Tree Forest Map", "Mushroom Field Map", "Blue Flower Field Map",
    "Bamboo Field Map", "Sunflower Field Map", "Dandelion Field Map",
    "Spider Field Map", "Strawberry Field Map", "Clover Field Map", "Rose Field Map",
    # Beequips
    "Petal Wand", "Petal Belt", "Gummy Boots", "Tide Popper", "Pollen Converter",
    "Straw", "Canteen", "Glove", "Mask", "Boots", "Belt", "Cape", "Wand", "Bag",
    # === Bees (base name; Gifted handled as a variant attribute) ===
    # Common
    "Basic Bee", "Bomber Bee", "Brave Bee", "Bumble Bee", "Cool Bee",
    "Hasty Bee", "Looker Bee", "Rad Bee", "Rascal Bee", "Stubborn Bee",
    "Bucko Bee", "Riley Bee",
    # Rare
    "Bubble Bee", "Demo Bee", "Fire Bee", "Frosty Bee", "Honey Bee",
    "Shocked Bee", "Wind Bee", "Exhausted Bee",
    # Epic
    "Carpenter Bee", "Ninja Bee",
    # Legendary
    "Baby Bee", "Demon Bee", "Diamond Bee", "Lion Bee", "Music Bee", "Shy Bee",
    # Mythic
    "Buoyant Bee", "Fuzzy Bee", "Precise Bee", "Spicy Bee", "Tadpole Bee", "Vector Bee",
    # Event
    "Tabby Bee", "Photon Bee", "Vicious Bee", "Digital Bee",
    "Crimsonwing Bee", "Cobalt Bee",
]

# Sets used for variant logic
_BEE_NAMES: frozenset[str] = frozenset(n for n in CANONICAL_ITEMS if n.endswith(" Bee"))
_BEEQUIP_NAMES: frozenset[str] = frozenset([
    "Petal Wand", "Petal Belt", "Gummy Boots", "Tide Popper", "Pollen Converter",
    "Straw", "Canteen", "Glove", "Mask", "Boots", "Belt", "Cape", "Wand", "Bag",
])

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
_NOISE = re.compile(
    r'\b(?:bee\s*swarm|simulator|roblox|bss|items?|lots?|pack|bundle|cheap|fast|delivery)\b',
    re.IGNORECASE,
)
_QTY = re.compile(
    r'[xх×]\s*(\d+)|(\d+)\s*[xх×]|(\d+)\s*(?:pcs|шт|ед|units?|штук|pc)',
    re.IGNORECASE,
)
_GIFTED_RE = re.compile(r'\bgifted\b', re.IGNORECASE)
_NOT_GIFTED_RE = re.compile(r'\bnon[-\s]?gifted\b|\bnot\s+gifted\b', re.IGNORECASE)
_LEVEL_RE = re.compile(r'\b(?:level|lvl|lv|l)\.?\s*(\d+)\b', re.IGNORECASE)
_MUTATED_RE = re.compile(r'\b(?:mutated?|mutation|mut\.?)\b', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Variant dataclass
# ---------------------------------------------------------------------------
@dataclass
class Variant:
    gifted: bool = False
    level_bucket: str = ""   # "low" / "mid" / "high" / "max" / ""
    mutated: bool = False
    is_beequip: bool = False

    def key(self) -> str:
        parts = []
        if self.gifted:
            parts.append("gifted")
        if self.level_bucket:
            parts.append(f"lv:{self.level_bucket}")
        if self.mutated:
            parts.append("mutated")
        if self.is_beequip:
            parts.append("beequip")
        return "|".join(parts) if parts else "base"

    def display(self) -> str:
        """Human-readable label, e.g. 'Gifted Lv15+'"""
        parts = []
        if self.gifted:
            parts.append("Gifted")
        if self.level_bucket:
            parts.append({"low": "Lv1-4", "mid": "Lv5-9",
                          "high": "Lv10-14", "max": "Lv15+"}[self.level_bucket])
        if self.mutated:
            parts.append("Mutated")
        if self.is_beequip:
            parts.append("[rolls vary]")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _level_bucket(n: int) -> str:
    if n <= 4:  return "low"
    if n <= 9:  return "mid"
    if n <= 14: return "high"
    return "max"


def _clean(title: str, keep_gifted: bool) -> str:
    """Strip noise/qty markers; optionally remove the word 'Gifted'."""
    s = title
    if not keep_gifted:
        s = _GIFTED_RE.sub(' ', s)
        s = _NOT_GIFTED_RE.sub(' ', s)
    s = _NOISE.sub(' ', s)
    s = _QTY.sub(' ', s)
    s = _LEVEL_RE.sub(' ', s)
    s = _MUTATED_RE.sub(' ', s)
    s = re.sub(r'[^\w\s\-]', ' ', s)
    return ' '.join(s.split()).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def normalize_and_extract(
    raw_title: str, threshold: int = 72
) -> tuple[str | None, Variant | None]:
    """
    Return (canonical_name, Variant) or (None, None) if confidence too low.

    Two-pass strategy:
    1. Match with 'Gifted' kept  → catches 'Gifted Egg' as its own canonical item.
    2. Match with 'Gifted' stripped → catches 'Gifted Basic Bee' → canonical='Basic Bee'.
    The higher-scoring pass wins; 'Gifted' becomes a variant attribute only for bees.
    """
    has_gifted = bool(_GIFTED_RE.search(raw_title)) and not bool(_NOT_GIFTED_RE.search(raw_title))

    c_keep = _clean(raw_title, keep_gifted=True)
    c_strip = _clean(raw_title, keep_gifted=False)

    m_keep  = process.extractOne(c_keep,  CANONICAL_ITEMS, scorer=fuzz.partial_ratio, score_cutoff=threshold)
    m_strip = process.extractOne(c_strip, CANONICAL_ITEMS, scorer=fuzz.partial_ratio, score_cutoff=threshold)

    if not m_keep and not m_strip:
        return None, None

    # Decide which match to use
    if m_keep and m_strip:
        # Prefer the kept-gifted match if it's a canonical "Gifted X" item, or scores clearly better
        if m_keep[0].startswith("Gifted") or m_keep[1] >= m_strip[1] + 5:
            canonical, gifted_variant = m_keep[0], False
        else:
            canonical = m_strip[0]
            gifted_variant = has_gifted and canonical in _BEE_NAMES
    elif m_keep:
        canonical, gifted_variant = m_keep[0], False
    else:
        canonical = m_strip[0]
        gifted_variant = has_gifted and canonical in _BEE_NAMES

    level_m = _LEVEL_RE.search(raw_title)
    level_bucket = _level_bucket(int(level_m.group(1))) if level_m else ""

    variant = Variant(
        gifted=gifted_variant,
        level_bucket=level_bucket,
        mutated=bool(_MUTATED_RE.search(raw_title)),
        is_beequip=canonical in _BEEQUIP_NAMES,
    )
    return canonical, variant


def extract_quantity(title: str) -> int:
    m = _QTY.search(title)
    if m:
        for g in m.groups():
            if g:
                return int(g)
    return 1
