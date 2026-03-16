import asyncio
import logging
from datetime import datetime
from typing import Callable

import aiohttp

from config import RATE_STALE_THRESHOLD_SEC, WS_RECONNECT_BASE_SEC, WS_RECONNECT_MAX_SEC
from models import ExchangeRate

logger = logging.getLogger(__name__)

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"
UPBIT_REST_URL = "https://api.upbit.com/v1/ticker?markets=KRW-USDT"
REST_POLL_INTERVAL_SEC = 30


class ExchangeRateManager:
    """Manages real-time KRW/USDT exchange rate."""

    def __init__(self) -> None:
        self.current_rate: ExchangeRate | None = None
        self._session: aiohttp.ClientSession | None = None
        self._callbacks: list[Callable[[ExchangeRate], None]] = []

    # --- Public API ---

    def get_rate(self) -> ExchangeRate | None:
        """Get current rate. Sets is_stale=True if older than RATE_STALE_THRESHOLD_SEC."""
        if self.current_rate is None:
            return None
        age = (datetime.now() - self.current_rate.timestamp).total_seconds()
        if age > RATE_STALE_THRESHOLD_SEC:
            return self.current_rate.model_copy(update={"is_stale": True})
        return self.current_rate

    def on_rate_update(self, callback: Callable[[ExchangeRate], None]) -> None:
        """Register callback for rate updates."""
        self._callbacks.append(callback)

    def off_rate_update(self, callback: Callable[[ExchangeRate], None]) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    # --- Main loop ---

    async def run(self) -> None:
        """Main loop - connect to Upbit USDT/KRW WebSocket for real-time rate.
        Fallback to REST polling every 30 seconds if WebSocket fails."""
        while True:
            try:
                logger.info("Connecting to Upbit WebSocket for KRW/USDT rate...")
                await self._run_websocket()
                # Normal return means disconnected; reset and reconnect immediately
            except asyncio.CancelledError:
                logger.info("ExchangeRateManager run cancelled")
                break
            except Exception:
                logger.exception(
                    "WebSocket error in ExchangeRateManager, falling back to REST polling"
                )
                try:
                    await self._run_rest_fallback()
                except asyncio.CancelledError:
                    logger.info("ExchangeRateManager REST fallback cancelled")
                    break
                except Exception:
                    logger.exception("REST fallback also failed, retrying WebSocket shortly")
                    await asyncio.sleep(WS_RECONNECT_BASE_SEC)

    async def close(self) -> None:
        """Cleanup aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        logger.info("ExchangeRateManager closed")

    # --- Internal helpers ---

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _run_websocket(self) -> None:
        """Connect to Upbit WebSocket and stream KRW-USDT ticker."""
        import json

        session = await self._get_session()
        backoff = WS_RECONNECT_BASE_SEC

        while True:
            try:
                async with session.ws_connect(UPBIT_WS_URL) as ws:
                    subscribe_msg = json.dumps([
                        {"ticket": "rate"},
                        {"type": "ticker", "codes": ["KRW-USDT"]},
                    ])
                    await ws.send_str(subscribe_msg)
                    logger.info("Upbit WebSocket subscribed to KRW-USDT")
                    backoff = WS_RECONNECT_BASE_SEC  # reset on successful connect

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            data = json.loads(msg.data.decode("utf-8"))
                            trade_price = data.get("trade_price") or data.get("tradePrice")
                            if trade_price:
                                self._set_rate(float(trade_price), source="upbit")
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            trade_price = data.get("trade_price") or data.get("tradePrice")
                            if trade_price:
                                self._set_rate(float(trade_price), source="upbit")
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            logger.warning("Upbit WebSocket closed/error, reconnecting...")
                            break

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Upbit WebSocket connection error, reconnecting in %.1fs", backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)
                continue

            # Clean disconnect - back off briefly then reconnect
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)

    async def _run_rest_fallback(self) -> None:
        """Poll Upbit REST endpoint every REST_POLL_INTERVAL_SEC seconds."""
        session = await self._get_session()
        logger.info("Starting REST fallback polling for KRW/USDT rate")

        while True:
            try:
                async with session.get(UPBIT_REST_URL) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # Returns list; first element is KRW-USDT
                    if data and isinstance(data, list):
                        trade_price = data[0].get("trade_price")
                        if trade_price:
                            self._set_rate(float(trade_price), source="upbit")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("REST fallback fetch failed")

            await asyncio.sleep(REST_POLL_INTERVAL_SEC)

    def _set_rate(self, krw_per_usdt: float, source: str) -> None:
        """Store new rate and notify callbacks."""
        rate = ExchangeRate(
            krw_per_usdt=krw_per_usdt,
            source=source,
            timestamp=datetime.now(),
            is_stale=False,
        )
        self.current_rate = rate
        for cb in list(self._callbacks):
            try:
                cb(rate)
            except Exception:
                logger.exception("Error in rate update callback")
