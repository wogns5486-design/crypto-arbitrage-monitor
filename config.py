import os
from dotenv import load_dotenv

load_dotenv()

# Monitoring symbols (canonical format: uppercase base asset)
SYMBOLS: list[str] = [
    "BTC", "ETH", "XRP", "SOL", "DOGE",
    "ADA", "AVAX", "DOT", "MATIC", "LINK",
]

# Default spread threshold (%)
DEFAULT_THRESHOLD_PCT: float = 0.5

# Alert cooldown (seconds) - prevent duplicate alerts for same pair
ALERT_COOLDOWN_SEC: int = 60

# Alert history max size (FIFO)
ALERT_HISTORY_MAX: int = 1000

# Exchange rate staleness warning (seconds)
RATE_STALE_THRESHOLD_SEC: int = 60

# SSE heartbeat interval (seconds)
SSE_HEARTBEAT_SEC: int = 5

# WebSocket reconnection settings
WS_RECONNECT_BASE_SEC: float = 2.0
WS_RECONNECT_MAX_SEC: float = 60.0

# Telegram settings
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Exchange API keys
UPBIT_ACCESS_KEY: str = os.getenv("UPBIT_ACCESS_KEY", "")
UPBIT_SECRET_KEY: str = os.getenv("UPBIT_SECRET_KEY", "")
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
BYBIT_API_KEY: str = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")

# Server
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
