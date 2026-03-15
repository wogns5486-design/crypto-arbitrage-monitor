import json
import time
from datetime import datetime

import aiohttp

from models import Ticker, CoinStatus, GateLoan
from exchanges.base import BaseExchange


class GateioExchange(BaseExchange):
    name = "gate.io"
    exchange_type = "foreign"
    base_url = "https://api.gateio.ws"

    def to_exchange_symbol(self, canonical: str) -> str:
        return f"{canonical}_USDT"

    def from_exchange_symbol(self, raw: str) -> str:
        return raw.replace("_USDT", "")

    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        session = await self._get_session()
        ws_url = "wss://api.gateio.ws/ws/v4/"
        exchange_symbols = [self.to_exchange_symbol(s) for s in symbols]

        async with session.ws_connect(ws_url) as ws:
            self.connected = True
            self.logger.info("Connected to Gate.io WebSocket")

            subscribe_msg = {
                "time": int(time.time()),
                "channel": "spot.book_ticker",
                "event": "subscribe",
                "payload": exchange_symbols,
            }
            await ws.send_json(subscribe_msg)
            self.logger.info("Subscribed to %d symbols", len(exchange_symbols))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error("Gate.io WS error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    self.logger.warning("Gate.io WS closed")
                    break

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)

            # Only process update events for book_ticker channel
            channel = data.get("channel", "")
            event = data.get("event", "")
            if channel != "spot.book_ticker" or event != "update":
                return

            result = data.get("result", {})
            symbol_raw = result.get("s", "")
            if not symbol_raw:
                return

            canonical = self.from_exchange_symbol(symbol_raw)
            best_bid = float(result.get("b", 0))
            best_ask = float(result.get("a", 0))

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
            self.logger.exception("Error parsing Gate.io message")

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        try:
            session = await self._get_session()
            url = f"{self.base_url}/api/v4/spot/currencies/{symbol}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Gate.io currencies %s returned %d", symbol, resp.status
                    )
                    return None
                data = await resp.json()

            trade_disabled = data.get("trade_disabled", False)
            deposit_disabled = data.get("deposit_disabled", False)
            withdraw_disabled = data.get("withdraw_disabled", False)

            networks: list[str] = []
            if isinstance(data.get("chains"), list):
                networks = [c.get("chain", "") for c in data["chains"] if c.get("chain")]

            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=not deposit_disabled,
                withdraw_enabled=not withdraw_disabled,
                networks=networks,
            )
        except Exception:
            self.logger.exception("Error fetching Gate.io coin status for %s", symbol)
            return None

    async def get_loan_info(self) -> list[GateLoan]:
        """Fetch margin loan info for all available currency pairs."""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/api/v4/margin/uni/currency_pairs"
            async with session.get(url) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Gate.io margin currency_pairs returned %d", resp.status
                    )
                    return []
                pairs = await resp.json()

            loans: list[GateLoan] = []
            for pair in pairs:
                base = pair.get("base", "")
                loanable = pair.get("loanable", False)

                if not base:
                    continue

                loan = GateLoan(
                    symbol=base,
                    loanable=bool(loanable),
                    min_amount=float(pair["min_base_amount"]) if pair.get("min_base_amount") else None,
                    rate=float(pair["rate"]) if pair.get("rate") else None,
                )
                loans.append(loan)

            return loans
        except Exception:
            self.logger.exception("Error fetching Gate.io loan info")
            return []
