import hashlib
import hmac
import json
import time
from datetime import datetime

import aiohttp

from models import Ticker, CoinStatus
from exchanges.base import BaseExchange
import config


class BybitExchange(BaseExchange):
    name = "bybit"
    exchange_type = "foreign"
    base_url = "https://api.bybit.com"

    def to_exchange_symbol(self, canonical: str) -> str:
        return f"{canonical}USDT"

    def from_exchange_symbol(self, raw: str) -> str:
        return raw.upper().replace("USDT", "")

    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        session = await self._get_session()
        ws_url = "wss://stream.bybit.com/v5/public/spot"
        args = [f"orderbook.1.{self.to_exchange_symbol(s)}" for s in symbols]

        async with session.ws_connect(ws_url, heartbeat=20) as ws:
            self.connected = True
            self.logger.info("Connected to Bybit WebSocket")

            subscribe_msg = {
                "op": "subscribe",
                "args": args,
            }
            await ws.send_json(subscribe_msg)
            self.logger.info("Subscribed to %d symbols", len(args))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error("Bybit WS error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    self.logger.warning("Bybit WS closed")
                    break

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)

            # Skip subscription confirmations and pong responses
            if data.get("op") or data.get("ret_msg"):
                return

            topic = data.get("topic", "")
            if not topic.startswith("orderbook.1."):
                return

            order_data = data.get("data", {})
            bids = order_data.get("b", [])
            asks = order_data.get("a", [])

            if not bids or not asks:
                return

            # Bybit orderbook format: [["price", "size"], ...]
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])

            if best_bid <= 0 or best_ask <= 0:
                return

            # Extract symbol from topic: "orderbook.1.BTCUSDT" -> "BTCUSDT"
            symbol_raw = topic.split(".")[-1]
            canonical = self.from_exchange_symbol(symbol_raw)

            ticker = Ticker(
                exchange=self.name,
                symbol=canonical,
                bid=best_bid,
                ask=best_ask,
                timestamp=datetime.now(),
            )
            self._notify_ticker(ticker)
        except Exception:
            self.logger.exception("Error parsing Bybit message")

    def _sign(self, timestamp: str, params: str) -> str:
        param_str = f"{timestamp}{config.BYBIT_API_KEY}5000{params}"
        return hmac.new(
            config.BYBIT_API_SECRET.encode(),
            param_str.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        if not config.BYBIT_API_KEY or not config.BYBIT_API_SECRET:
            self.logger.debug(
                "Bybit API key not configured, returning unknown status for %s",
                symbol,
            )
            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=None,
                withdraw_enabled=None,
                networks=[],
            )

        try:
            session = await self._get_session()
            timestamp = str(int(time.time() * 1000))
            params = f"coin={symbol}"
            signature = self._sign(timestamp, params)

            headers = {
                "X-BAPI-API-KEY": config.BYBIT_API_KEY,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": "5000",
                "X-BAPI-SIGN": signature,
            }
            url = f"{self.base_url}/v5/asset/coin/query-info?coin={symbol}"

            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Bybit coin info returned %d", resp.status
                    )
                    return None
                data = await resp.json()

            result = data.get("result", {})
            rows = result.get("rows", [])
            if not rows:
                return CoinStatus(
                    exchange=self.name,
                    symbol=symbol,
                    deposit_enabled=None,
                    withdraw_enabled=None,
                    networks=[],
                )

            coin_data = rows[0]
            chains = coin_data.get("chains", [])
            networks = [c.get("chain", "") for c in chains if c.get("chain")]
            deposit_enabled = any(
                str(c.get("chainDeposit", "0")) == "1" for c in chains
            )
            withdraw_enabled = any(
                str(c.get("chainWithdraw", "0")) == "1" for c in chains
            )

            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=deposit_enabled,
                withdraw_enabled=withdraw_enabled,
                networks=networks,
            )
        except Exception:
            self.logger.exception("Error fetching Bybit coin status for %s", symbol)
            return None
