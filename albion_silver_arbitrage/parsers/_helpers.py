import re

# ── Price ────────────────────────────────────────────────────────────────────

def parse_usd(text: str) -> float | None:
    """Extract a USD amount from messy text."""
    text = text.replace('\xa0', '').replace(' ', '').replace(',', '')
    text = re.sub(r'[^\d.]', '', text)
    try:
        v = float(text)
        return v if 0 < v < 100_000 else None
    except ValueError:
        return None


# ── Silver amount ─────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r'([\d][\d,.]*)\s*(KK|BN|B|M|K)\b',
    re.IGNORECASE,
)

def parse_millions(text: str) -> float | None:
    """
    Convert any silver amount notation to millions.
    Examples: '100M' -> 100, '1.5B' -> 1500, '500K' -> 0.5,
              '100KK' -> 100 (Chinese: KK = M), '1BN' -> 1000
    """
    text = text.replace(',', '')
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    val  = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('B', 'BN'): return val * 1_000
    if unit == 'M':          return val
    if unit == 'K':          return val / 1_000
    if unit == 'KK':         return val          # KK = million on some CN sites
    return None


# ── Server detection ──────────────────────────────────────────────────────────

_SERVER_MAP = {
    'EU':   re.compile(r'\bEU\b|\bEurop', re.IGNORECASE),
    'NA':   re.compile(r'\bNA\b|\bNorth\s*America\b|\bUS\b', re.IGNORECASE),
    'East': re.compile(r'\bEast\b|\bAsia\b|\bSEA\b', re.IGNORECASE),
}

def detect_server(text: str) -> str:
    for server, pattern in _SERVER_MAP.items():
        if pattern.search(text):
            return server
    return 'Unknown'
