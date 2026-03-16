import abc
import asyncio
import logging
from typing import Callable

import aiohttp

from models import Ticker, CoinStatus


class BaseExchange(abc.ABC):
    name: str = ""
    exchange_type: str = ""  # "domestic" or "foreign"
    base_url: str = ""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"exchange.{self.name}")
        self._callbacks: list[Callable[[Ticker], None]] = []
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self.connected: bool = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    # --- Symbol normalization ---

    @abc.abstractmethod
    def to_exchange_symbol(self, canonical: str) -> str:
        """Convert canonical symbol (e.g. 'BTC') to exchange-specific format."""

    @abc.abstractmethod
    def from_exchange_symbol(self, raw: str) -> str:
        """Convert exchange-specific symbol back to canonical format."""

    # --- Callbacks ---

    def on_ticker_update(self, callback: Callable[[Ticker], None]) -> None:
        self._callbacks.append(callback)

    def _notify_ticker(self, ticker: Ticker) -> None:
        for cb in self._callbacks:
            try:
                cb(ticker)
            except Exception:
                self.logger.exception("Error in ticker callback")

    # --- Main loop ---

    async def run(self, symbols: list[str]) -> None:
        """Main loop with infinite retry + exponential backoff."""
        from config import WS_RECONNECT_BASE_SEC, WS_RECONNECT_MAX_SEC

        self._running = True
        backoff = WS_RECONNECT_BASE_SEC

        while self._running:
            try:
                self.logger.info("Connecting to %s WebSocket...", self.name)
                self.connected = False
                await self._connect_and_subscribe(symbols)
                # If _connect_and_subscribe returns normally, reset backoff
                self.connected = False
                backoff = WS_RECONNECT_BASE_SEC
            except asyncio.CancelledError:
                self.connected = False
                self.logger.info("%s run cancelled", self.name)
                break
            except Exception:
                self.logger.exception(
                    "%s WebSocket error, reconnecting in %.1fs", self.name, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)

    @abc.abstractmethod
    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        """Connect to WebSocket and process messages. Should block until disconnected."""

    # --- REST: coin status ---

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        """Fetch deposit/withdrawal status via REST. Override in subclasses."""
        return None

    # --- Cleanup ---

    async def close(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self.logger.info("%s closed", self.name)
