import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import SYMBOLS
from exchanges.bithumb import BithumbExchange
from exchanges.upbit import UpbitExchange
from exchanges.binance import BinanceExchange
from exchanges.gateio import GateioExchange
from exchanges.bybit import BybitExchange
from exchange_rate import ExchangeRateManager
from spread_engine import SpreadEngine
from alert_manager import AlertManager
from routers import stream, api, pages

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Starting crypto arbitrage monitor...")

    # Initialize app state
    app.state.exchanges_list = []
    app.state.exchange_rate_manager = ExchangeRateManager()
    app.state.spread_engine = SpreadEngine()
    app.state.alert_manager = AlertManager()
    app.state.exchange_tasks = []

    # Create exchange adapters
    adapters = [
        BithumbExchange(),
        UpbitExchange(),
        BinanceExchange(),
        GateioExchange(),
        BybitExchange(),
    ]
    app.state.exchanges_list.extend(adapters)

    # Wire up ticker callbacks
    for ex in app.state.exchanges_list:
        ex.on_ticker_update(app.state.spread_engine.update_ticker)

    # Wire up spread engine dependencies
    app.state.spread_engine.set_exchange_rate_manager(app.state.exchange_rate_manager)
    app.state.spread_engine.set_exchanges(app.state.exchanges_list)
    app.state.spread_engine.set_alert_manager(app.state.alert_manager)

    # Start each exchange as individual task (NO TaskGroup - graceful degradation)
    for ex in app.state.exchanges_list:
        task = asyncio.create_task(ex.run(SYMBOLS), name=f"exchange-{ex.name}")
        app.state.exchange_tasks.append(task)
        logger.info(f"Started exchange task: {ex.name}")

    # Start exchange rate manager
    rate_task = asyncio.create_task(
        app.state.exchange_rate_manager.run(), name="exchange-rate"
    )
    app.state.exchange_tasks.append(rate_task)
    logger.info("Started exchange rate manager")

    # Start spread engine
    spread_task = asyncio.create_task(
        app.state.spread_engine.run(), name="spread-engine"
    )
    app.state.exchange_tasks.append(spread_task)
    logger.info("Started spread engine")

    logger.info("All systems started. Dashboard at http://localhost:8000")
    yield

    # Shutdown
    logger.info("Shutting down...")
    for task in app.state.exchange_tasks:
        task.cancel()
    await asyncio.gather(*app.state.exchange_tasks, return_exceptions=True)
    await app.state.exchange_rate_manager.close()
    await app.state.alert_manager.close()
    for ex in app.state.exchanges_list:
        await ex.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Crypto Arbitrage Monitor",
    description="실시간 거래소 간 차익 거래 모니터링 대시보드",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(pages.router)
app.include_router(stream.router, prefix="/api")
app.include_router(api.router, prefix="/api")
