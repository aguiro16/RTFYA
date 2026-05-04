import os

BINANCE_BASE_URL         = "https://api.binance.com"
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

ENABLE_FUTURES_TRADING = True
ENABLE_SPOT_TRADING    = False

MAX_LEVERAGE = int(os.environ.get("MAX_LEVERAGE", "1"))
