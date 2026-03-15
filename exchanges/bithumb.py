import json
from datetime import datetime

import aiohttp

from models import Ticker, CoinStatus
from exchanges.base import BaseExchange


class BithumbExchange(BaseExchange):
    name = "bithumb"
    exchange_type = "domestic"
    base_url = "https://api.bithumb.com"

    def to_exchange_symbol(self, canonical: str) -> str:
        return f"{canonical}_KRW"

    def from_exchange_symbol(self, raw: str) -> str:
        return raw.replace("_KRW", "")

    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        session = await self._get_session()
        ws_url = "wss://pubwss.bithumb.com/pub/ws"
        exchange_symbols = [self.to_exchange_symbol(s) for s in symbols]

        async with session.ws_connect(ws_url) as ws:
            self.connected = True
            self.logger.info("Connected to Bithumb WebSocket")

            subscribe_msg = {
                "type": "orderbookdepth",
                "symbols": exchange_symbols,
            }
            await ws.send_json(subscribe_msg)
            self.logger.info("Subscribed to %d symbols", len(exchange_symbols))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error("Bithumb WS error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    self.logger.warning("Bithumb WS closed")
                    break

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            if data.get("type") != "orderbookdepth":
                return

            content = data.get("content", {})
            symbol_raw = content.get("symbol", "")
            canonical = self.from_exchange_symbol(symbol_raw)

            bids = content.get("bids", [])
            asks = content.get("asks", [])

            if not bids or not asks:
                return

            best_bid = float(bids[0][0]) if isinstance(bids[0], list) else float(bids[0].get("price", 0))
            best_ask = float(asks[0][0]) if isinstance(asks[0], list) else float(asks[0].get("price", 0))

            if best_bid <= 0 or best_ask <= 0:
                return

            ticker = Ticker(
                exchange=self.name,
                symbol=canonical,
                bid=best_bid,
                ask=best_ask,
                bid_krw=best_bid,
                ask_krw=best_ask,
                timestamp=datetime.now(),
            )
            self._notify_ticker(ticker)
        except Exception:
            self.logger.exception("Error parsing Bithumb message")

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        try:
            session = await self._get_session()
            url = f"{self.base_url}/public/assetsstatus/{symbol}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Bithumb assetsstatus %s returned %d", symbol, resp.status
                    )
                    return None
                data = await resp.json()

            status_data = data.get("data", {})
            deposit_status = status_data.get("deposit_status")
            withdrawal_status = status_data.get("withdrawal_status")

            networks: list[str] = []
            if isinstance(status_data.get("networks"), list):
                networks = [n.get("network", "") for n in status_data["networks"] if n.get("network")]

            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=deposit_status == 1 if deposit_status is not None else None,
                withdraw_enabled=withdrawal_status == 1 if withdrawal_status is not None else None,
                networks=networks,
            )
        except Exception:
            self.logger.exception("Error fetching Bithumb coin status for %s", symbol)
            return None
