import re


def parse_usd(text: str) -> float | None:
    """Extract a USD price from messy text. Returns None if unparseable."""
    text = text.replace('\xa0', '').replace(' ', '').replace(',', '.')
    # Remove currency symbols and spaces
    text = re.sub(r'[^\d.]', '', text)
    try:
        value = float(text)
        return value if 0 < value < 1_000_000 else None
    except ValueError:
        return None
