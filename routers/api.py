import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import Settings, CoinStatus, GateLoan

logger = logging.getLogger(__name__)

router = APIRouter()


class SettingsUpdate(BaseModel):
    threshold_pct: float | None = None
    filter_deposit_withdraw: bool | None = None
    filter_common_network: bool | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


@router.get("/settings", response_model=Settings)
async def get_settings():
    """Get current monitoring settings."""
    from main import spread_engine
    return spread_engine.get_settings()


@router.post("/settings", response_model=Settings)
async def update_settings(update: SettingsUpdate):
    """Update monitoring settings. Returns updated settings with incremented version."""
    from main import spread_engine
    kwargs = {k: v for k, v in update.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")
    return spread_engine.update_settings(**kwargs)


@router.get("/exchanges")
async def get_exchanges():
    """Get exchange connection status."""
    from main import exchanges_list
    return {
        "exchanges": [
            {
                "name": ex.name,
                "type": ex.exchange_type,
                "connected": ex.connected,
            }
            for ex in exchanges_list
        ]
    }


@router.get("/rate")
async def get_exchange_rate():
    """Get current KRW/USDT exchange rate."""
    from main import exchange_rate_manager
    rate = exchange_rate_manager.get_rate()
    if rate is None:
        raise HTTPException(status_code=503, detail="Exchange rate not available yet")
    return rate.model_dump(mode="json")


@router.get("/coin-status/{symbol}")
async def get_coin_status(symbol: str):
    """Get deposit/withdrawal/network status for a coin across all exchanges."""
    from main import spread_engine
    symbol = symbol.upper()
    statuses = spread_engine.get_coin_status(symbol)
    if not statuses:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    return {
        "symbol": symbol,
        "exchanges": {name: s.model_dump(mode="json") for name, s in statuses.items()},
    }


@router.get("/gate-loans")
async def get_gate_loans():
    """Get Gate.io margin loan availability."""
    from main import exchanges_list

    gate = None
    for ex in exchanges_list:
        if ex.name == "gate.io":
            gate = ex
            break

    if gate is None:
        raise HTTPException(status_code=503, detail="Gate.io adapter not available")

    try:
        loans = await gate.get_loan_info()
        return {
            "loans": [loan.model_dump(mode="json") for loan in loans],
            "count": len(loans),
        }
    except Exception as e:
        logger.error(f"Failed to fetch Gate.io loans: {e}")
        raise HTTPException(status_code=503, detail="Failed to fetch loan data")


@router.get("/spreads")
async def get_spreads():
    """Get current spread data (snapshot, not streaming)."""
    from main import spread_engine
    spreads = spread_engine.get_spreads()
    settings = spread_engine.get_settings()
    return {
        "spreads": [s.model_dump(mode="json") for s in spreads],
        "settings_version": settings.settings_version,
        "count": len(spreads),
    }
