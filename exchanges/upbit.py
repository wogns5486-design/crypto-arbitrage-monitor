import json
import gzip
import uuid
from datetime import datetime

import aiohttp

from models import Ticker, CoinStatus
from exchanges.base import BaseExchange
import config


class UpbitExchange(BaseExchange):
    name = "upbit"
    exchange_type = "domestic"
    base_url = "https://api.upbit.com"

    def to_exchange_symbol(self, canonical: str) -> str:
        return f"KRW-{canonical}"

    def from_exchange_symbol(self, raw: str) -> str:
        return raw.replace("KRW-", "")

    async def _connect_and_subscribe(self, symbols: list[str]) -> None:
        session = await self._get_session()
        ws_url = "wss://api.upbit.com/websocket/v1"
        exchange_symbols = [self.to_exchange_symbol(s) for s in symbols]

        async with session.ws_connect(ws_url) as ws:
            self.connected = True
            self.logger.info("Connected to Upbit WebSocket")

            subscribe_msg = [
                {"ticket": "arb-monitor"},
                {"type": "orderbook", "codes": exchange_symbols},
            ]
            await ws.send_str(json.dumps(subscribe_msg))
            self.logger.info("Subscribed to %d symbols", len(exchange_symbols))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data.encode())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error("Upbit WS error: %s", ws.exception())
                    break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    self.logger.warning("Upbit WS closed")
                    break

    def _handle_message(self, raw: bytes) -> None:
        try:
            try:
                text = gzip.decompress(raw).decode("utf-8")
            except (gzip.BadGzipFile, OSError):
                text = raw.decode("utf-8")

            data = json.loads(text)
            if data.get("type") != "orderbook":
                return

            code = data.get("code", "")
            canonical = self.from_exchange_symbol(code)

            units = data.get("orderbook_units", [])
            if not units:
                return

            best = units[0]
            best_bid = float(best.get("bid_price", 0))
            best_ask = float(best.get("ask_price", 0))

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
            self.logger.exception("Error parsing Upbit message")

    async def get_coin_status(self, symbol: str) -> CoinStatus | None:
        if not config.UPBIT_ACCESS_KEY or not config.UPBIT_SECRET_KEY:
            self.logger.debug(
                "Upbit API key not configured, returning unknown status for %s", symbol
            )
            return CoinStatus(
                exchange=self.name,
                symbol=symbol,
                deposit_enabled=None,
                withdraw_enabled=None,
                networks=[],
            )

        try:
            import jwt as pyjwt
        except ImportError:
            self.logger.warning(
                "PyJWT not installed; cannot fetch Upbit coin status. "
                "Install with: pip install PyJWT"
            )
            return None

        try:
            payload = {
                "access_key": config.UPBIT_ACCESS_KEY,
                "nonce": str(uuid.uuid4()),
            }
            token = pyjwt.encode(payload, config.UPBIT_SECRET_KEY)
            headers = {"Authorization": f"Bearer {token}"}

            session = await self._get_session()
            url = f"{self.base_url}/v1/status/wallet"
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    self.logger.warning(
                        "Upbit wallet status returned %d", resp.status
                    )
                    return None
                wallets = await resp.json()

            for wallet in wallets:
                currency = wallet.get("currency", "")
                if currency.upper() == symbol.upper():
                    wallet_state = wallet.get("wallet_state", "")
                    networks = [wallet.get("net_type", "")] if wallet.get("net_type") else []

                    return CoinStatus(
                        exchange=self.name,
                        symbol=symbol,
                        deposit_enabled=wallet_state in ("working", "deposit_only"),
                        withdraw_enabled=wallet_state in ("working", "withdraw_only"),
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
            self.logger.exception("Error fetching Upbit coin status for %s", symbol)
            return None
