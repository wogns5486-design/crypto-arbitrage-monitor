import logging
from fastapi import APIRouter, HTTPException, Request
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
async def get_settings(request: Request):
    """Get current monitoring settings."""
    return request.app.state.spread_engine.get_settings()


@router.post("/settings", response_model=Settings)
async def update_settings(update: SettingsUpdate, request: Request):
    """Update monitoring settings. Returns updated settings with incremented version."""
    kwargs = {k: v for k, v in update.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")
    return request.app.state.spread_engine.update_settings(**kwargs)


@router.get("/exchanges")
async def get_exchanges(request: Request):
    """Get exchange connection status."""
    return {
        "exchanges": [
            {
                "name": ex.name,
                "type": ex.exchange_type,
                "connected": ex.connected,
            }
            for ex in request.app.state.exchanges_list
        ]
    }


@router.get("/rate")
async def get_exchange_rate(request: Request):
    """Get current KRW/USDT exchange rate."""
    rate = request.app.state.exchange_rate_manager.get_rate()
    if rate is None:
        raise HTTPException(status_code=503, detail="Exchange rate not available yet")
    return rate.model_dump(mode="json")


@router.get("/coin-status/{symbol}")
async def get_coin_status(symbol: str, request: Request):
    """Get deposit/withdrawal/network status for a coin across all exchanges."""
    symbol = symbol.upper()
    statuses = request.app.state.spread_engine.get_coin_status(symbol)
    if not statuses:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    return {
        "symbol": symbol,
        "exchanges": {name: s.model_dump(mode="json") for name, s in statuses.items()},
    }


@router.get("/gate-loans")
async def get_gate_loans(request: Request):
    """Get Gate.io margin loan availability."""
    gate = None
    for ex in request.app.state.exchanges_list:
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
async def get_spreads(request: Request):
    """Get current spread data (snapshot, not streaming)."""
    spreads = request.app.state.spread_engine.get_spreads()
    settings = request.app.state.spread_engine.get_settings()
    return {
        "spreads": [s.model_dump(mode="json") for s in spreads],
        "settings_version": settings.settings_version,
        "count": len(spreads),
    }


@router.get("/alert-history")
async def get_alert_history(request: Request, limit: int = 50):
    """Get recent alert history, newest first."""
    history = request.app.state.alert_manager.get_history(limit=limit)
    return {
        "alerts": [a.model_dump(mode="json") for a in history],
        "count": len(history),
    }
