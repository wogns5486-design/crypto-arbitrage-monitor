from pydantic import BaseModel, Field
from datetime import datetime


class Ticker(BaseModel):
    exchange: str
    symbol: str  # canonical: "BTC", "ETH" etc.
    bid: float  # best bid price (in exchange's native currency)
    ask: float  # best ask price
    bid_krw: float = 0.0  # normalized to KRW
    ask_krw: float = 0.0  # normalized to KRW
    timestamp: datetime = Field(default_factory=datetime.now)


class Spread(BaseModel):
    symbol: str  # canonical
    buy_exchange: str  # exchange to buy from (lower ask)
    sell_exchange: str  # exchange to sell at (higher bid)
    buy_ask_krw: float  # ask price at buy exchange (KRW)
    sell_bid_krw: float  # bid price at sell exchange (KRW)
    spread_pct: float  # (sell_bid - buy_ask) / buy_ask * 100
    common_networks: list[str] = []
    timestamp: datetime = Field(default_factory=datetime.now)


class CoinStatus(BaseModel):
    exchange: str
    symbol: str  # canonical
    deposit_enabled: bool | None = None  # None = unknown (API key not set)
    withdraw_enabled: bool | None = None
    networks: list[str] = []


class GateLoan(BaseModel):
    symbol: str  # canonical
    loanable: bool
    min_amount: float | None = None
    rate: float | None = None  # daily interest rate


class AlertEvent(BaseModel):
    symbol: str
    buy_exchange: str
    sell_exchange: str
    spread_pct: float
    buy_ask_krw: float
    sell_bid_krw: float
    triggered_at: datetime = Field(default_factory=datetime.now)


class ExchangeRate(BaseModel):
    krw_per_usdt: float
    source: str  # "upbit" or "bithumb"
    timestamp: datetime = Field(default_factory=datetime.now)
    is_stale: bool = False


class Settings(BaseModel):
    threshold_pct: float = 0.5
    filter_deposit_withdraw: bool = True
    filter_common_network: bool = True
    settings_version: int = 0
