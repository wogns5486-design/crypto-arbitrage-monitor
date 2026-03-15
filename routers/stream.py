import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from config import SSE_HEARTBEAT_SEC

logger = logging.getLogger(__name__)

router = APIRouter()


async def _event_generator(spread_engine, exchange_rate_manager, alert_manager, exchanges_list):
    """SSE event generator with 5 event types: spread, status, rate, alert, heartbeat."""
    queue: asyncio.Queue = asyncio.Queue()
    start_time = datetime.now(timezone.utc)

    # Register callbacks
    def on_spread(spreads):
        queue.put_nowait(("spread", spreads))

    def on_rate(rate):
        queue.put_nowait(("rate", rate))

    def on_alert(alert_event):
        queue.put_nowait(("alert", alert_event))

    spread_engine.on_spread_update(on_spread)
    exchange_rate_manager.on_rate_update(on_rate)
    alert_manager.on_alert(on_alert)

    try:
        while True:
            # Send heartbeat every SSE_HEARTBEAT_SEC
            try:
                data = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SEC)
                event_type, payload = data

                if event_type == "spread":
                    spreads_data = {
                        "spreads": [s.model_dump(mode="json") for s in payload],
                        "settings_version": spread_engine.get_settings().settings_version,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"event: spread\ndata: {json.dumps(spreads_data, ensure_ascii=False)}\n\n"

                elif event_type == "rate":
                    rate_data = payload.model_dump(mode="json")
                    yield f"event: rate\ndata: {json.dumps(rate_data, ensure_ascii=False)}\n\n"

                elif event_type == "alert":
                    alert_data = payload.model_dump(mode="json")
                    yield f"event: alert\ndata: {json.dumps(alert_data, ensure_ascii=False)}\n\n"

            except asyncio.TimeoutError:
                pass  # No data received, send heartbeat below

            # Always send heartbeat
            uptime = (datetime.now(timezone.utc) - start_time).total_seconds()
            heartbeat = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime_sec": int(uptime),
            }
            yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"

            # Send exchange status periodically (piggyback on heartbeat)
            status_data = {
                "exchanges": {
                    ex.name: "connected" if ex.connected else "disconnected"
                    for ex in exchanges_list
                }
            }
            yield f"event: status\ndata: {json.dumps(status_data, ensure_ascii=False)}\n\n"

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled")
    finally:
        # Unregister callbacks
        if on_spread in spread_engine._callbacks:
            spread_engine._callbacks.remove(on_spread)
        if on_rate in exchange_rate_manager._callbacks:
            exchange_rate_manager._callbacks.remove(on_rate)
        if on_alert in alert_manager._callbacks:
            alert_manager._callbacks.remove(on_alert)


@router.get("/stream")
async def sse_stream():
    """Server-Sent Events stream for real-time data."""
    from main import spread_engine, exchange_rate_manager, alert_manager, exchanges_list

    return StreamingResponse(
        _event_generator(spread_engine, exchange_rate_manager, alert_manager, exchanges_list),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
