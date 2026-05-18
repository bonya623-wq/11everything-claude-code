import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

THRESHOLD_VS_AVERAGE = float(os.getenv("THRESHOLD_VS_AVERAGE", "30"))
THRESHOLD_VS_PLATFORM_MIN = float(os.getenv("THRESHOLD_VS_PLATFORM_MIN", "20"))

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "72"))

FUNPAY_URL = os.getenv("FUNPAY_URL", "https://funpay.com/lots/688/")
G2G_URL = os.getenv("G2G_URL", "https://www.g2g.com/categories/bee-swarm-simulator")
ELDORADO_URL = os.getenv("ELDORADO_URL", "https://www.eldorado.gg/bee-swarm-simulator/r/items")
