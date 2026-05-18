import re

# ── USD price ──────────────────────────────────────────────────────────────────

def parse_usd(text: str) -> float | None:
    text = text.replace('\xa0', '').replace(' ', '').replace(',', '')
    text = re.sub(r'[^\d.]', '', text)
    try:
        v = float(text)
        return v if 0 < v < 100_000 else None
    except ValueError:
        return None


# ── Silver amount ───────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r'([\d][\d,.]*(?:\.[\d]+)?)\s*(KK|BN|B|M|K|万|亿)\b',
    re.IGNORECASE,
)

def parse_millions(text: str) -> float | None:
    """
    Convert any silver amount to millions:
      100M -> 100,  1.5B -> 1500,  500K -> 0.5
      100KK -> 100 (Chinese: KK = M)
      1万 -> 0.01M (10,000),  1亿 -> 100M (100,000,000)
    """
    text = text.replace(',', '')
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    val  = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('B', 'BN'):  return val * 1_000
    if unit == 'M':           return val
    if unit == 'K':           return val / 1_000
    if unit == 'KK':          return val
    if unit == '万':      return val / 100       # 1万 = 10,000 = 0.01M
    if unit == '亿':      return val * 100       # 1亿 = 100M
    return None


# ── Server detection ───────────────────────────────────────────────────────────

_SERVER_MAP = {
    'EU':   re.compile(r'\bEU\b|\bEurop|欧服|欧洲', re.IGNORECASE),
    'NA':   re.compile(r'\bNA\b|\bNorth\s*America\b|\bUS\b|美服', re.IGNORECASE),
    'East': re.compile(r'\bEast\b|\bAsia\b|\bSEA\b|亚服', re.IGNORECASE),
}

def detect_server(text: str) -> str:
    for server, pattern in _SERVER_MAP.items():
        if pattern.search(text):
            return server
    return 'Unknown'
