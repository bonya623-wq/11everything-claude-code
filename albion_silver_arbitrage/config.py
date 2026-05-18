import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

THRESHOLD_VS_AVERAGE = float(os.getenv("THRESHOLD_VS_AVERAGE", "20"))
SCAN_INTERVAL        = int(os.getenv("SCAN_INTERVAL", "180"))
ALBION_SERVER        = os.getenv("ALBION_SERVER", "EU").upper()

FUNPAY_URL         = os.getenv("FUNPAY_URL",         "https://funpay.com/en/chips/30/")
G2G_URL            = os.getenv("G2G_URL",            "https://www.g2g.com/categories/albion-online-global-gold?server=Europe")
ELDORADO_URL       = os.getenv("ELDORADO_URL",       "https://www.eldorado.gg/albion-online-silver/g/41-2-0")
PLAYERAUCTIONS_URL = os.getenv("PLAYERAUCTIONS_URL", "https://www.playerauctions.com/albion-online-silver/")
IGGM_URL           = os.getenv("IGGM_URL",           "https://www.iggm.com/albion-online-silver")
Z2U_URL            = os.getenv("Z2U_URL",            "https://www.z2u.com/albion-online-global/Gold-1-1613")
U7BUY_URL          = os.getenv("U7BUY_URL",          "https://www.u7buy.com/albion-online/albion-online-silver")
IGVAULT_URL        = os.getenv("IGVAULT_URL",        "https://www.igv.com/items/1783372034590978050")
ODEALO_URL         = os.getenv("ODEALO_URL",         "https://odealo.com/games/albion-online/silver")
G2A_URL            = os.getenv("G2A_URL",            "https://www.g2a.com/albion-online-silver-1m-albion-europe-i10000340100023")
MMOGA_URL          = os.getenv("MMOGA_URL",          "https://www.mmoga.com/Albion-Online/Albion-Silver,Europe-Server/")
