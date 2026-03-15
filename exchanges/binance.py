import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import urlencode

import aiohttp

from models import Ticker, CoinStatus
from exchanges.base import BaseExchange
import config


class BinanceExchange(BaseExchange):
    name = "binance"
    exchange_type = "foreign"
    base_url = "https://api.binance.com"

    def to_exchange_symbol(self, canonical: str) -> str:
        return f"{canonical.lower()}usdt"

    def from_exchange_symbol(self, raw: str) -> str:
        return raw.upper().replace("USDT", "")

    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        session = await self._get_session()
        ws_url = "wss://stream.binance.com:9443/ws"
        params = [f"{self.to_exchange_symbol(s)}@bookTicker" for s in symbols]

        async with session.ws_connect(ws_url) as ws:
            self.connected = True
            self.logger.info("Connected to Binance WebSocket")

            subscribe_msg = {
                "method": "SUBSCRIBE",
                "params": params,
                "id": 1,
            }
            await ws.send_json(subscribe_msg)
            self.logger.info("Subscribed to %d symbols", len(params))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error("Binance WS error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    self.logger.warning("Binance WS closed")
                    break

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)

            # Skip subscription confirmations
            if "result" in data and "id" in data:
                return

            symbol_raw = data.get("s")
            if not symbol_raw:
                return

            canonical = self.from_exchange_symbol(symbol_raw)
            best_bid = float(data.get("b", 0))
            best_ask = float(data.get("a", 0))

            if best_bid <= 0 or best_ask <= 0:
                return

            ticker = Ticker(
                exchange=self.name,
                symbol=canonical,
                bid=best_bid,
                ask=best_ask,
                timestamp=datetime.now(),
            )
            self._notify_ticker(ticker)
        except Exception:
            self.logger.exception("Error parsing Binance message")

    def _sign(self, params: dict) -> str:
        query_string = urlencode(params)
        signature = hmac.new(
            config.BINANCE_API_SECRET.encode(),
            query_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        if not config.BINANCE_API_KEY or not config.BINANCE_API_SECRET:
            self.logger.debug(
                "Binance API key not configured, returning unknown status for %s",
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
            params = {"timestamp": int(time.time() * 1000)}
            params["signature"] = self._sign(params)

            headers = {"X-MBX-APIKEY": config.BINANCE_API_KEY}
            url = f"{self.base_url}/sapi/v1/capital/config/getall"

            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Binance capital config returned %d", resp.status
                    )
                    return None
                coins = await resp.json()

            for coin in coins:
                if coin.get("coin", "").upper() == symbol.upper():
                    network_list = coin.get("networkList", [])
                    networks = [n.get("network", "") for n in network_list if n.get("network")]
                    deposit_enabled = any(
                        n.get("depositEnable", False) for n in network_list
                    )
                    withdraw_enabled = any(
                        n.get("withdrawEnable", False) for n in network_list
                    )

                    return CoinStatus(
                        exchange=self.name,
                        symbol=symbol,
                        deposit_enabled=deposit_enabled,
                        withdraw_enabled=withdraw_enabled,
                        networks=networks,
                    )

            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=None,
                withdraw_enabled=None,
                networks=[],
            )
        except Exception:
            self.logger.exception("Error fetching Binance coin status for %s", symbol)
            return None
