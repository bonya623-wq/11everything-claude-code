import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

THRESHOLD_VS_AVERAGE = float(os.getenv("THRESHOLD_VS_AVERAGE", "20"))
SCAN_INTERVAL        = int(os.getenv("SCAN_INTERVAL", "180"))
ALBION_SERVER        = os.getenv("ALBION_SERVER", "EU").upper()

FUNPAY_URL       = os.getenv("FUNPAY_URL",       "https://funpay.com/chips/3/")
G2G_URL          = os.getenv("G2G_URL",          "https://www.g2g.com/categories/albion-online-silver?server=Europe")
ELDORADO_URL     = os.getenv("ELDORADO_URL",     "https://www.eldorado.gg/albion-online/r/silver")
PLAYERAUCTIONS_URL = os.getenv("PLAYERAUCTIONS_URL", "https://www.playerauctions.com/albion-online-silver/")
IGGM_URL         = os.getenv("IGGM_URL",         "https://www.iggm.com/albion-online-silver")
Z2U_URL          = os.getenv("Z2U_URL",          "https://www.z2u.com/albion-online/silver-2-13220")
