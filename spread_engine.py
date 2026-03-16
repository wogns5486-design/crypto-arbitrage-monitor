import asyncio
import logging
import time
from datetime import datetime
from typing import Callable

from models import CoinStatus, Settings, Spread, Ticker
from exchange_rate import ExchangeRateManager

logger = logging.getLogger(__name__)

RECALC_INTERVAL_SEC = 1.0
STATUS_CACHE_TTL_SEC = 300  # 5 minutes


class SpreadEngine:
    """Calculates spreads across exchanges in real-time."""

    def __init__(self) -> None:
        self._tickers: dict[str, dict[str, Ticker]] = {}  # {symbol: {exchange_name: Ticker}}
        self._coin_statuses: dict[str, dict[str, CoinStatus]] = {}  # {symbol: {exchange: CoinStatus}}
        self._spreads: list[Spread] = []
        self._settings = Settings()
        self._exchange_rate_manager: ExchangeRateManager | None = None
        self._exchanges: list = []
        self._alert_manager = None
        self._callbacks: list[Callable[[list[Spread]], None]] = []
        self._status_cache_ttl = STATUS_CACHE_TTL_SEC
        self._last_status_fetch: float = 0

    # --- Wiring ---

    def set_exchange_rate_manager(self, mgr: ExchangeRateManager) -> None:
        self._exchange_rate_manager = mgr

    def set_exchanges(self, exchanges: list) -> None:
        self._exchanges = exchanges

    def set_alert_manager(self, mgr) -> None:
        self._alert_manager = mgr

    def on_spread_update(self, callback: Callable[[list[Spread]], None]) -> None:
        """Register callback for spread updates (used by SSE)."""
        self._callbacks.append(callback)

    def off_spread_update(self, callback: Callable[[list[Spread]], None]) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    # --- Ticker ingestion ---

    def update_ticker(self, ticker: Ticker) -> None:
        """Called by exchange adapters when new ticker data arrives.
        Normalize bid/ask to KRW and store in _tickers dict."""
        exchange_obj = self._get_exchange(ticker.exchange)
        is_domestic = (
            exchange_obj is not None and getattr(exchange_obj, "exchange_type", "") == "domestic"
        )

        if is_domestic:
            bid_krw = ticker.bid
            ask_krw = ticker.ask
        else:
            rate = self._exchange_rate_manager.get_rate() if self._exchange_rate_manager else None
            if rate is None:
                # Cannot normalize without exchange rate; store zeros and skip
                bid_krw = 0.0
                ask_krw = 0.0
            else:
                bid_krw = ticker.bid * rate.krw_per_usdt
                ask_krw = ticker.ask * rate.krw_per_usdt

        normalized = ticker.model_copy(update={"bid_krw": bid_krw, "ask_krw": ask_krw})

        if ticker.symbol not in self._tickers:
            self._tickers[ticker.symbol] = {}
        self._tickers[ticker.symbol][ticker.exchange] = normalized

    # --- Main loop ---

    async def run(self) -> None:
        """Main loop - periodically recalculate spreads and fetch coin statuses."""
        while True:
            try:
                now = time.monotonic()

                # Refresh coin statuses every STATUS_CACHE_TTL_SEC
                if now - self._last_status_fetch >= self._status_cache_ttl:
                    try:
                        await self._fetch_coin_statuses()
                        self._last_status_fetch = time.monotonic()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Failed to fetch coin statuses")

                # Recalculate spreads
                self._spreads = self._calculate_spreads()
                self._notify_spreads(self._spreads)

            except asyncio.CancelledError:
                logger.info("SpreadEngine run cancelled")
                break
            except Exception:
                logger.exception("Error in SpreadEngine main loop")

            await asyncio.sleep(RECALC_INTERVAL_SEC)

    # --- Spread calculation ---

    def _calculate_spreads(self) -> list[Spread]:
        """Calculate spreads for all symbol/exchange pairs.

        Formula: spread_pct = (sell_bid_krw - buy_ask_krw) / buy_ask_krw * 100

        Filters applied based on settings:
        - threshold_pct: only include spreads above threshold
        - filter_deposit_withdraw: exclude coins where deposit or withdrawal is disabled
        - filter_common_network: exclude pairs without at least one common network
        """
        rate = self._exchange_rate_manager.get_rate() if self._exchange_rate_manager else None
        if rate is None:
            logger.warning("No exchange rate available, skipping spread calculation")
            return []

        if rate.is_stale:
            logger.warning("Exchange rate is stale (%.0f KRW/USDT), continuing with caution", rate.krw_per_usdt)

        results: list[Spread] = []
        now = datetime.now()

        for symbol, exchange_tickers in self._tickers.items():
            exchanges_with_data = [
                (name, tkr)
                for name, tkr in exchange_tickers.items()
                if tkr.ask_krw > 0 and tkr.bid_krw > 0
            ]

            if len(exchanges_with_data) < 2:
                continue

            # Consider every ordered pair (buy_exchange, sell_exchange)
            for i, (buy_name, buy_tkr) in enumerate(exchanges_with_data):
                for j, (sell_name, sell_tkr) in enumerate(exchanges_with_data):
                    if i == j:
                        continue

                    buy_ask_krw = buy_tkr.ask_krw
                    sell_bid_krw = sell_tkr.bid_krw

                    if buy_ask_krw <= 0:
                        continue

                    spread_pct = (sell_bid_krw - buy_ask_krw) / buy_ask_krw * 100

                    if spread_pct < self._settings.threshold_pct:
                        continue

                    # Determine common networks
                    common_networks = self._get_common_networks(symbol, buy_name, sell_name)

                    # Filter: deposit/withdrawal status
                    if self._settings.filter_deposit_withdraw:
                        if not self._check_deposit_withdraw(symbol, buy_name, sell_name):
                            continue

                    # Filter: common network required
                    if self._settings.filter_common_network:
                        if not common_networks:
                            continue

                    results.append(
                        Spread(
                            symbol=symbol,
                            buy_exchange=buy_name,
                            sell_exchange=sell_name,
                            buy_ask_krw=buy_ask_krw,
                            sell_bid_krw=sell_bid_krw,
                            spread_pct=spread_pct,
                            common_networks=common_networks,
                            timestamp=now,
                        )
                    )

        # Sort descending by spread_pct
        results.sort(key=lambda s: s.spread_pct, reverse=True)
        return results

    # Network name normalization map (different exchanges use different names)
    _NETWORK_ALIASES: dict[str, str] = {
        "ERC20": "ETH", "TRC20": "TRX", "BEP20": "BSC", "BEP2": "BNB",
        "Ethereum": "ETH", "ETHEREUM": "ETH", "Tron": "TRX", "TRON": "TRX",
        "Polygon": "MATIC", "POLYGON": "MATIC", "Arbitrum One": "ARBITRUM",
        "ARBITRUM": "ARBITRUM", "Optimism": "OPTIMISM", "OPTIMISM": "OPTIMISM",
        "Solana": "SOL", "SOLANA": "SOL", "Avalanche C-Chain": "AVAXC",
        "AVAXC": "AVAXC", "BASE": "BASE", "Base": "BASE",
    }

    def _normalize_network(self, name: str) -> str:
        """Normalize network name for cross-exchange comparison."""
        return self._NETWORK_ALIASES.get(name, name.upper())

    def _get_common_networks(self, symbol: str, exchange_a: str, exchange_b: str) -> list[str]:
        """Return list of network names available on both exchanges for symbol."""
        statuses = self._coin_statuses.get(symbol, {})
        status_a = statuses.get(exchange_a)
        status_b = statuses.get(exchange_b)
        if status_a is None or status_b is None:
            return []
        networks_a = {self._normalize_network(n) for n in status_a.networks}
        networks_b = {self._normalize_network(n) for n in status_b.networks}
        return sorted(networks_a & networks_b)

    def _check_deposit_withdraw(self, symbol: str, buy_exchange: str, sell_exchange: str) -> bool:
        """Return True if deposit is enabled on sell exchange and withdrawal on buy exchange."""
        statuses = self._coin_statuses.get(symbol, {})

        # Need to withdraw from buy_exchange to move coins
        buy_status = statuses.get(buy_exchange)
        if buy_status is not None and buy_status.withdraw_enabled is False:
            return False

        # Need to deposit on sell_exchange to sell
        sell_status = statuses.get(sell_exchange)
        if sell_status is not None and sell_status.deposit_enabled is False:
            return False

        return True

    # --- Coin status fetch ---

    async def _fetch_coin_statuses(self) -> None:
        """Fetch deposit/withdrawal/network status from all exchanges."""
        from config import SYMBOLS
        sem = asyncio.Semaphore(10)

        async def limited_fetch(exchange, symbol):
            async with sem:
                return await self._fetch_one_status(exchange, symbol)

        tasks = []
        for exchange in self._exchanges:
            for symbol in SYMBOLS:
                tasks.append(limited_fetch(exchange, symbol))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.debug("Coin status fetch error: %s", result)
                continue
            if result is None:
                continue
            status: CoinStatus = result
            if status.symbol not in self._coin_statuses:
                self._coin_statuses[status.symbol] = {}
            self._coin_statuses[status.symbol][status.exchange] = status

        logger.info("Coin statuses refreshed for %d exchanges", len(self._exchanges))

    async def _fetch_one_status(self, exchange, symbol: str) -> CoinStatus | None:
        """Fetch status for a single exchange/symbol pair."""
        try:
            return await exchange.get_coin_status(symbol)
        except Exception:
            logger.debug("get_coin_status failed for %s/%s", exchange.name, symbol)
            return None

    # --- Notifications ---

    def _notify_spreads(self, spreads: list[Spread]) -> None:
        """Notify SSE callbacks and alert manager."""
        # Alert manager (async - schedule as tasks)
        if self._alert_manager is not None:
            try:
                for spread in spreads:
                    task = asyncio.create_task(
                        self._alert_manager.check_and_alert(spread, self._settings.threshold_pct)
                    )
                    task.add_done_callback(self._handle_alert_task_error)
            except Exception:
                logger.exception("Error notifying alert manager")

        # SSE callbacks
        for cb in list(self._callbacks):
            try:
                cb(spreads)
            except Exception:
                logger.exception("Error in spread update callback")

    # --- Public accessors ---

    def get_spreads(self) -> list[Spread]:
        return list(self._spreads)

    def get_settings(self) -> Settings:
        return self._settings

    def update_settings(self, **kwargs) -> Settings:
        """Update settings and increment settings_version."""
        current = self._settings.model_dump()
        current.update(kwargs)
        current["settings_version"] = self._settings.settings_version + 1
        self._settings = Settings(**current)
        return self._settings

    def get_coin_status(self, symbol: str) -> dict[str, CoinStatus]:
        return dict(self._coin_statuses.get(symbol, {}))

    def _handle_alert_task_error(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Alert task error: %s", exc)

    # --- Helpers ---

    def _get_exchange(self, name: str):
        for ex in self._exchanges:
            if ex.name == name:
                return ex
        return None
