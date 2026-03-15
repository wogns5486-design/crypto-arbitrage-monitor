import asyncio
import logging
from collections import deque
from datetime import datetime
import aiohttp

from models import AlertEvent, Spread
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ALERT_COOLDOWN_SEC,
    ALERT_HISTORY_MAX,
)

logger = logging.getLogger(__name__)


class AlertManager:
    """Manages alerts when spread exceeds threshold.

    - Sound alerts: handled by frontend (browser Audio API) via SSE alert events
    - Telegram alerts: sent via aiohttp direct Bot API call
    - Cooldown: same symbol/exchange pair suppressed for ALERT_COOLDOWN_SEC
    - History: FIFO queue, max ALERT_HISTORY_MAX entries
    """

    def __init__(self):
        self._history: deque[AlertEvent] = deque(maxlen=ALERT_HISTORY_MAX)
        self._cooldowns: dict[str, datetime] = {}  # "BTC:binance:bithumb" -> last_alert_time
        self._callbacks: list = []  # SSE callbacks for alert events
        self._session: aiohttp.ClientSession | None = None

    def on_alert(self, callback):
        """Register callback for alert events (used by SSE stream)."""
        self._callbacks.append(callback)

    async def check_and_alert(self, spread: Spread, threshold_pct: float):
        """Check if spread exceeds threshold and trigger alerts.

        1. Check if spread_pct >= threshold_pct
        2. Check cooldown - skip if same pair was alerted within ALERT_COOLDOWN_SEC
        3. Create AlertEvent
        4. Add to history
        5. Notify SSE callbacks (for browser sound alert)
        6. Send Telegram message (if configured)
        """
        try:
            if spread.spread_pct < threshold_pct:
                return

            key = self._make_cooldown_key(spread)
            if not self._is_cooled_down(key):
                return

            alert = AlertEvent(
                symbol=spread.symbol,
                buy_exchange=spread.buy_exchange,
                sell_exchange=spread.sell_exchange,
                spread_pct=spread.spread_pct,
                buy_ask_krw=spread.buy_ask_krw,
                sell_bid_krw=spread.sell_bid_krw,
                triggered_at=datetime.now(),
            )

            self._cooldowns[key] = alert.triggered_at
            self._history.appendleft(alert)

            # Notify SSE callbacks (fire-and-forget, catch per callback)
            dead_callbacks = []
            for cb in self._callbacks:
                try:
                    result = cb(alert)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    logger.debug("SSE callback error (removing): %s", exc)
                    dead_callbacks.append(cb)
            for cb in dead_callbacks:
                self._callbacks.remove(cb)

            # Send Telegram alert
            await self._send_telegram(alert)

        except Exception as exc:
            logger.error("check_and_alert error: %s", exc)

    def _is_cooled_down(self, key: str) -> bool:
        """Check if cooldown period has passed for this alert key."""
        last = self._cooldowns.get(key)
        if last is None:
            return True
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed >= ALERT_COOLDOWN_SEC:
            # Remove expired entry to keep dict tidy
            del self._cooldowns[key]
            return True
        return False

    def _make_cooldown_key(self, spread: Spread) -> str:
        """Create unique key: 'SYMBOL:buy_exchange:sell_exchange'"""
        return f"{spread.symbol}:{spread.buy_exchange}:{spread.sell_exchange}"

    async def _send_telegram(self, alert: AlertEvent):
        """Send Telegram message via Bot API using aiohttp.

        POST https://api.telegram.org/bot{TOKEN}/sendMessage
        Body: {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}

        If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is empty, skip silently.
        If request fails, log error but don't raise.
        """
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return

        message = (
            f"🔔 <b>차익 기회 감지</b>\n"
            f"코인: {alert.symbol}\n"
            f"매수: {alert.buy_exchange} ({alert.buy_ask_krw:,.0f} KRW)\n"
            f"매도: {alert.sell_exchange} ({alert.sell_bid_krw:,.0f} KRW)\n"
            f"스프레드: {alert.spread_pct:.2f}%\n"
            f"시간: {alert.triggered_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()

            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram API error %d: %s", resp.status, body)
        except Exception as exc:
            logger.error("Failed to send Telegram alert: %s", exc)

    def get_history(self, limit: int = 50) -> list[AlertEvent]:
        """Return recent alert history, newest first."""
        return list(self._history)[:limit]

    async def close(self):
        """Cleanup aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
