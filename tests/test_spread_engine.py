import pytest
from datetime import datetime
from unittest.mock import MagicMock

from models import Ticker, Spread, Settings, ExchangeRate, CoinStatus
from spread_engine import SpreadEngine
from exchange_rate import ExchangeRateManager


class TestSpreadCalculation:
    """Test spread calculation logic."""

    def _make_engine(self, rate_krw=1400.0):
        engine = SpreadEngine()
        mgr = ExchangeRateManager()
        mgr.current_rate = ExchangeRate(
            krw_per_usdt=rate_krw, source="test", timestamp=datetime.now()
        )
        engine.set_exchange_rate_manager(mgr)

        # Mock exchanges
        domestic = MagicMock()
        domestic.name = "upbit"
        domestic.exchange_type = "domestic"
        foreign = MagicMock()
        foreign.name = "binance"
        foreign.exchange_type = "foreign"
        engine.set_exchanges([domestic, foreign])
        return engine

    def test_positive_spread(self):
        engine = self._make_engine(rate_krw=1400.0)
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=False, filter_common_network=False)

        # Upbit: BTC bid=100_000_000 ask=100_100_000 (KRW)
        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=100_100_000, timestamp=datetime.now()
        ))
        # Binance: BTC bid=72000 ask=71900 (USDT) → bid_krw=100_800_000 ask_krw=100_660_000
        engine.update_ticker(Ticker(
            exchange="binance", symbol="BTC",
            bid=72000, ask=71900, timestamp=datetime.now()
        ))

        spreads = engine._calculate_spreads()
        assert len(spreads) > 0
        # At least one spread should be positive (buy cheap, sell expensive)
        positive = [s for s in spreads if s.spread_pct > 0]
        assert len(positive) > 0

    def test_no_spread_below_threshold(self):
        engine = self._make_engine(rate_krw=1400.0)
        engine._settings = Settings(threshold_pct=10.0, filter_deposit_withdraw=False, filter_common_network=False)

        # Very similar prices → spread < 10%
        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=100_000_000, timestamp=datetime.now()
        ))
        engine.update_ticker(Ticker(
            exchange="binance", symbol="BTC",
            bid=71428, ask=71428, timestamp=datetime.now()
        ))

        spreads = engine._calculate_spreads()
        assert len(spreads) == 0

    def test_no_rate_returns_empty(self):
        engine = SpreadEngine()
        mgr = ExchangeRateManager()
        engine.set_exchange_rate_manager(mgr)
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=False, filter_common_network=False)

        spreads = engine._calculate_spreads()
        assert spreads == []

    def test_single_exchange_returns_empty(self):
        engine = self._make_engine()
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=False, filter_common_network=False)

        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=100_100_000, timestamp=datetime.now()
        ))

        spreads = engine._calculate_spreads()
        assert spreads == []

    def test_spreads_sorted_descending(self):
        engine = self._make_engine(rate_krw=1400.0)
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=False, filter_common_network=False)

        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=99_000_000, timestamp=datetime.now()
        ))
        engine.update_ticker(Ticker(
            exchange="binance", symbol="BTC",
            bid=72000, ask=71000, timestamp=datetime.now()
        ))

        spreads = engine._calculate_spreads()
        for i in range(len(spreads) - 1):
            assert spreads[i].spread_pct >= spreads[i + 1].spread_pct

    def test_common_network_filter(self):
        engine = self._make_engine(rate_krw=1400.0)
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=False, filter_common_network=True)

        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=90_000_000, timestamp=datetime.now()
        ))
        engine.update_ticker(Ticker(
            exchange="binance", symbol="BTC",
            bid=72000, ask=71000, timestamp=datetime.now()
        ))

        # No coin statuses set → no common networks → filtered out
        spreads = engine._calculate_spreads()
        assert len(spreads) == 0

    def test_deposit_withdraw_filter(self):
        engine = self._make_engine(rate_krw=1400.0)
        engine._settings = Settings(threshold_pct=0.0, filter_deposit_withdraw=True, filter_common_network=False)

        engine.update_ticker(Ticker(
            exchange="upbit", symbol="BTC",
            bid=100_000_000, ask=90_000_000, timestamp=datetime.now()
        ))
        engine.update_ticker(Ticker(
            exchange="binance", symbol="BTC",
            bid=72000, ask=71000, timestamp=datetime.now()
        ))

        # Set withdrawal disabled on upbit
        engine._coin_statuses["BTC"] = {
            "upbit": CoinStatus(exchange="upbit", symbol="BTC", withdraw_enabled=False, deposit_enabled=True),
            "binance": CoinStatus(exchange="binance", symbol="BTC", withdraw_enabled=True, deposit_enabled=True),
        }

        spreads = engine._calculate_spreads()
        # Spreads involving upbit as buy exchange should be filtered (can't withdraw)
        for s in spreads:
            assert not (s.buy_exchange == "upbit")


class TestSettings:
    def test_update_increments_version(self):
        engine = SpreadEngine()
        assert engine.get_settings().settings_version == 0

        engine.update_settings(threshold_pct=1.5)
        assert engine.get_settings().settings_version == 1
        assert engine.get_settings().threshold_pct == 1.5

        engine.update_settings(filter_deposit_withdraw=False)
        assert engine.get_settings().settings_version == 2
