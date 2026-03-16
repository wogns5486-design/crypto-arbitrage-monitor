import pytest
import asyncio
from datetime import datetime, timedelta

from models import Spread, AlertEvent
from alert_manager import AlertManager


class TestCooldown:
    """Test alert cooldown logic."""

    def test_first_alert_passes_cooldown(self):
        mgr = AlertManager()
        assert mgr._is_cooled_down("BTC:binance:upbit") is True

    def test_repeated_alert_blocked(self):
        mgr = AlertManager()
        key = "BTC:binance:upbit"
        mgr._cooldowns[key] = datetime.now()
        assert mgr._is_cooled_down(key) is False

    def test_expired_cooldown_passes(self):
        mgr = AlertManager()
        key = "BTC:binance:upbit"
        mgr._cooldowns[key] = datetime.now() - timedelta(seconds=120)
        assert mgr._is_cooled_down(key) is True

    def test_different_pairs_independent(self):
        mgr = AlertManager()
        mgr._cooldowns["BTC:binance:upbit"] = datetime.now()
        assert mgr._is_cooled_down("ETH:binance:upbit") is True


class TestCooldownKey:
    def test_key_format(self):
        mgr = AlertManager()
        spread = Spread(
            symbol="BTC", buy_exchange="binance", sell_exchange="upbit",
            buy_ask_krw=100_000_000, sell_bid_krw=101_000_000,
            spread_pct=1.0, timestamp=datetime.now()
        )
        key = mgr._make_cooldown_key(spread)
        assert key == "BTC:binance:upbit"


class TestAlertHistory:
    def test_history_append(self):
        mgr = AlertManager()
        alert = AlertEvent(
            symbol="BTC", buy_exchange="binance", sell_exchange="upbit",
            spread_pct=1.5, buy_ask_krw=100_000_000, sell_bid_krw=101_500_000,
        )
        mgr._history.appendleft(alert)
        history = mgr.get_history()
        assert len(history) == 1
        assert history[0].symbol == "BTC"

    def test_history_limit(self):
        mgr = AlertManager()
        history = mgr.get_history(limit=5)
        assert len(history) <= 5


class TestModels:
    """Test Pydantic model defaults."""

    def test_ticker_timestamp_unique(self):
        from models import Ticker
        import time
        t1 = Ticker(exchange="test", symbol="BTC", bid=100, ask=101)
        time.sleep(0.01)
        t2 = Ticker(exchange="test", symbol="BTC", bid=100, ask=101)
        # Each should have a different timestamp (Field default_factory)
        assert t1.timestamp != t2.timestamp

    def test_alert_event_triggered_at_unique(self):
        import time
        a1 = AlertEvent(
            symbol="BTC", buy_exchange="a", sell_exchange="b",
            spread_pct=1.0, buy_ask_krw=100, sell_bid_krw=101,
        )
        time.sleep(0.01)
        a2 = AlertEvent(
            symbol="BTC", buy_exchange="a", sell_exchange="b",
            spread_pct=1.0, buy_ask_krw=100, sell_bid_krw=101,
        )
        assert a1.triggered_at != a2.triggered_at
