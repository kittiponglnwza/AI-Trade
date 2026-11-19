"""FastAPI REST & WebSocket server bridging the React Trading Desk with MetaTrader 5."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.analytics import compute_trading_stats
from app.config import ALLOWED_ORIGINS, API_KEY, DEFAULT_SYMBOL
from app.database import (
    create_execution_log,
    create_proposal,
    export_trade_logs_csv,
    get_proposal,
    init_db,
    list_audit_events,
    list_proposals,
    list_trade_logs,
    log_audit,
    record_equity_snapshot,
    update_proposal_status,
    update_trade_log_notes,
    upsert_mt5_deals,
)
from app.mt5_service import mt5_service
from app.schemas import (
    OrderCheckRequest,
    PositionCloseRequest,
    PositionModifyRequest,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    ProposalRejectRequest,
    TradeLogUpdateRequest,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        mt5_service.connect()
    except Exception:
        pass
    yield
    mt5_service.disconnect()


app = FastAPI(
    title="MT5 Real-Time Trading Bridge",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Require matching X-API-Key on mutating routes whenever API_KEY is configured."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def _map_mt5_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


@app.get("/api/health")
async def get_health() -> dict[str, Any]:
    connected = await asyncio.to_thread(mt5_service.is_connected)
    trade_mode = None
    if connected:
        try:
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            trade_mode = acc["trade_mode"]
        except Exception:
            connected = False

    return {
        "status": "ok",
        "mt5_connected": connected,
        "trade_mode": trade_mode,
        "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "api_key_required": bool(API_KEY),
    }


@app.get("/api/market/snapshot")
async def get_market_snapshot(symbol: str = Query(default=DEFAULT_SYMBOL)) -> dict[str, Any]:
    try:
        snap = await asyncio.to_thread(mt5_service.get_market_snapshot, symbol)
        acc = snap["account"]
        record_equity_snapshot(
            balance=acc["balance"],
            equity=acc["equity"],
            floating_pnl=acc["profit"],
            margin_free=acc["margin_free"],
            min_interval_sec=300,
        )
        return snap
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/candles")
async def get_candles(
    symbol: str = Query(default=DEFAULT_SYMBOL),
    tf: str = Query(default="M15"),
    bars: int = Query(default=250, ge=30, le=1000),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(mt5_service.get_candles, symbol, tf, bars)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.post("/api/order/check")
async def post_order_check(body: OrderCheckRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            mt5_service.check_order,
            body.symbol,
            body.side,
            body.lots,
            body.risk_pct,
            body.entry_price,
            body.sl,
            body.tp,
        )
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/proposals")
async def get_proposals(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    items = list_proposals(status=status, limit=limit)
    return {"proposals": items, "count": len(items)}


@app.post("/api/proposals", dependencies=[Depends(verify_api_key)])
async def post_create_proposal(body: ProposalCreateRequest) -> dict[str, Any]:
    try:
        checked = await asyncio.to_thread(
            mt5_service.check_order,
            body.symbol,
            body.side,
            body.lots,
            body.risk_pct,
            body.entry_price,
            body.sl,
            body.tp,
        )
    except Exception as exc:
        raise _map_mt5_error(exc) from exc

    if not checked["valid"]:
        raise HTTPException(
            status_code=400,
            detail=f"MT5 order_check rejected proposal ({checked['retcode']}: {checked['comment']}).",
        )

    proposal = create_proposal(
        {
            "source": body.source.upper(),
            "symbol": checked["symbol"],
            "side": checked["side"],
            "order_type": checked["order_type"],
            "entry_price": checked["entry_price"],
            "sl": checked["sl"],
            "tp": checked["tp"],
            "risk_pct": checked["est_risk_pct"] if body.risk_pct is None else body.risk_pct,
            "lots": checked["lots"],
            "est_risk_usd": checked["est_risk_usd"],
            "est_reward_usd": checked["est_reward_usd"],
            "rr_ratio": checked["rr_ratio"],
            "rationale": body.rationale,
            "timeframe": body.timeframe.upper(),
        }
    )
    log_audit(
        event_type="PROPOSAL_CREATED",
        actor=body.source.upper(),
        summary=f"Proposed {proposal['side']} {proposal['lots']} {proposal['symbol']} @ {proposal['entry_price']}",
        payload={"proposal_id": proposal["id"], "checked": checked},
    )
    return {"proposal": proposal, "order_check": checked}


@app.post("/api/proposals/{proposal_id}/confirm", dependencies=[Depends(verify_api_key)])
async def post_confirm_proposal(
    proposal_id: int,
    body: ProposalConfirmRequest | None = None,
) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal #{proposal_id} not found.")
    if proposal["status"] != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal #{proposal_id} is already '{proposal['status']}' and cannot be confirmed again.",
        )

    req = body or ProposalConfirmRequest()
    comment = req.comment or f"{proposal['source']}-P{proposal_id}"

    try:
        exec_res = await asyncio.to_thread(
            mt5_service.send_order,
            proposal["symbol"],
            proposal["side"],
            proposal["lots"],
            None,
            proposal["entry_price"] if proposal["order_type"] == "PENDING" else None,
            proposal["sl"],
            proposal["tp"],
            req.deviation,
            comment,
            req.allow_real,
        )
    except Exception as exc:
        update_proposal_status(proposal_id, "FAILED", exec_comment=str(exc))
        log_audit(
            event_type="PROPOSAL_EXEC_FAILED",
            actor="USER",
            summary=f"Proposal #{proposal_id} failed: {exc}",
            payload={"proposal_id": proposal_id},
        )
        raise _map_mt5_error(exc) from exc

    new_status = "EXECUTED" if exec_res["success"] else "FAILED"
    updated_proposal = update_proposal_status(
        proposal_id,
        new_status,
        mt5_order_ticket=exec_res["order_ticket"],
        mt5_deal_ticket=exec_res["deal_ticket"],
        exec_price=exec_res["exec_price"],
        exec_comment=f"{exec_res['retcode']}: {exec_res['comment']}",
    )

    trade_log = None
    if exec_res["success"]:
        trade_log = create_execution_log(
            {
                "mt5_deal_ticket": exec_res["deal_ticket"] or None,
                "mt5_position_id": exec_res["order_ticket"] or None,
                "proposal_id": proposal_id,
                "symbol": proposal["symbol"],
                "side": proposal["side"],
                "volume": exec_res["exec_volume"],
                "entry_price": exec_res["exec_price"],
                "sl": proposal["sl"],
                "tp": proposal["tp"],
                "status": "OPEN",
                "strategy_tag": proposal["timeframe"],
                "notes": proposal["rationale"],
                "source": proposal["source"],
            }
        )
        try:
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            record_equity_snapshot(
                balance=acc["balance"],
                equity=acc["equity"],
                floating_pnl=acc["profit"],
                margin_free=acc["margin_free"],
                min_interval_sec=0,
            )
        except Exception:
            pass

    log_audit(
        event_type="PROPOSAL_CONFIRMED" if exec_res["success"] else "PROPOSAL_EXEC_FAILED",
        actor="USER",
        summary=(
            f"Confirmed Proposal #{proposal_id}: {proposal['side']} {exec_res['exec_volume']} "
            f"{proposal['symbol']} @ {exec_res['exec_price']} (ret={exec_res['retcode']})"
        ),
        payload={"proposal_id": proposal_id, "execution": exec_res},
    )
    return {"proposal": updated_proposal, "execution": exec_res, "trade_log": trade_log}


@app.post("/api/proposals/{proposal_id}/reject", dependencies=[Depends(verify_api_key)])
async def post_reject_proposal(
    proposal_id: int,
    body: ProposalRejectRequest | None = None,
) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal #{proposal_id} not found.")
    if proposal["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Proposal #{proposal_id} is '{proposal['status']}'.")

    reason = body.reason if body and body.reason else "Rejected by user"
    updated = update_proposal_status(proposal_id, "REJECTED", exec_comment=reason)
    log_audit(
        event_type="PROPOSAL_REJECTED",
        actor="USER",
        summary=f"Rejected Proposal #{proposal_id} ({proposal['side']} {proposal['symbol']}): {reason}",
        payload={"proposal_id": proposal_id, "reason": reason},
    )
    return {"proposal": updated}


@app.patch("/api/positions/{ticket}", dependencies=[Depends(verify_api_key)])
async def patch_modify_position(ticket: int, body: PositionModifyRequest) -> dict[str, Any]:
    if body.sl is None and body.tp is None:
        raise HTTPException(status_code=400, detail="Provide at least one of sl or tp.")
    try:
        res = await asyncio.to_thread(
            mt5_service.modify_position,
            ticket,
            body.sl,
            body.tp,
            body.allow_real,
        )
        log_audit(
            event_type="POSITION_MODIFIED",
            actor="USER",
            summary=f"Modified #{ticket} SL={res['sl']} TP={res['tp']}",
            payload=res,
        )
        return res
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.post("/api/positions/{ticket}/close", dependencies=[Depends(verify_api_key)])
async def post_close_position(
    ticket: int,
    body: PositionCloseRequest | None = None,
) -> dict[str, Any]:
    req = body or PositionCloseRequest()
    try:
        res = await asyncio.to_thread(
            mt5_service.close_position,
            ticket,
            req.lots,
            req.deviation,
            req.allow_real,
        )
        deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 30)
        sync_summary = upsert_mt5_deals(deals)
        log_audit(
            event_type="POSITION_CLOSED",
            actor="USER",
            summary=f"Closed #{ticket} ({res['symbol']}) @ {res.get('close_price', '-')}",
            payload={"close": res, "sync": sync_summary},
        )
        return {"close": res, "sync": sync_summary}
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/logs")
async def get_logs(
    status: str | None = Query(default=None),
    side: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    logs = list_trade_logs(status=status, side=side, search=search, limit=limit)
    audit = list_audit_events(limit=40)
    return {"logs": logs, "count": len(logs), "audit_events": audit}


@app.post("/api/logs/sync", dependencies=[Depends(verify_api_key)])
async def post_sync_logs(days: int = Query(default=90, ge=1, le=3650)) -> dict[str, Any]:
    try:
        deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, days)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc

    summary = upsert_mt5_deals(deals)
    log_audit(
        event_type="HISTORY_SYNCED",
        actor="SYSTEM",
        summary=f"Synced {summary['total']} closed MT5 deals (new: {summary['inserted']}, updated: {summary['updated']})",
        payload=summary,
    )
    return summary


@app.patch("/api/logs/{log_id}", dependencies=[Depends(verify_api_key)])
async def patch_update_log(log_id: int, body: TradeLogUpdateRequest) -> dict[str, Any]:
    updated = update_trade_log_notes(log_id, body.strategy_tag, body.notes)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Trade log #{log_id} not found.")
    log_audit(
        event_type="JOURNAL_UPDATED",
        actor="USER",
        summary=f"Updated journal notes on trade log #{log_id}",
        payload={"log_id": log_id, "strategy_tag": updated["strategy_tag"]},
    )
    return {"log": updated}


@app.get("/api/logs/export.csv")
async def get_export_logs_csv() -> Response:
    csv_text = export_trade_logs_csv()
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="trade_journal.csv"'},
    )


@app.get("/api/stats")
async def get_stats(sync: bool = Query(default=False)) -> dict[str, Any]:
    current_balance: float | None = None
    if mt5_service.is_connected():
        try:
            if sync:
                deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 90)
                upsert_mt5_deals(deals)
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            current_balance = acc["balance"]
        except Exception:
            pass

    closed_trades = list_trade_logs(status="CLOSED", limit=5000)
    stats = compute_trading_stats(closed_trades, current_balance=current_balance)
    open_logs = list_trade_logs(status="OPEN", limit=200)
    stats["open_logged_count"] = len(open_logs)
    return stats


def _build_ws_packet(symbol: str, tf: str) -> dict[str, Any]:
    connected = mt5_service.is_connected()
    pending_count = len(list_proposals(status="PENDING", limit=100))
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if not connected:
        return {
            "type": "tick",
            "mt5_connected": False,
            "server_time": now_str,
            "symbol": symbol,
            "tf": tf,
            "pending_proposals_count": pending_count,
            "account": None,
            "quote": None,
            "positions": [],
            "orders": [],
            "last_bar": None,
        }

    resolved = mt5_service.resolve_symbol(symbol)
    account = mt5_service.get_account_summary()
    quote = mt5_service.get_quote(resolved)
    positions = mt5_service.get_open_positions()
    orders = mt5_service.get_pending_orders()
    candles_res = mt5_service.get_candles(resolved, tf, bars=5)
    last_bar = candles_res["candles"][-1] if candles_res["candles"] else None

    return {
        "type": "tick",
        "mt5_connected": True,
        "server_time": now_str,
        "symbol": resolved,
        "tf": tf.upper(),
        "pending_proposals_count": pending_count,
        "account": account,
        "quote": quote,
        "positions": positions,
        "orders": orders,
        "last_bar": last_bar,
    }


@app.websocket("/ws/live")
async def websocket_live(
    websocket: WebSocket,
    symbol: str = Query(default=DEFAULT_SYMBOL),
    tf: str = Query(default="M15"),
) -> None:
    await websocket.accept()
    sub_symbol = symbol
    sub_tf = tf.upper()

    try:
        while True:
            try:
                packet = await asyncio.to_thread(_build_ws_packet, sub_symbol, sub_tf)
            except Exception as exc:
                packet = {
                    "type": "error",
                    "mt5_connected": False,
                    "detail": str(exc),
                    "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                }

            await websocket.send_json(packet)

            try:
                incoming = await asyncio.wait_for(websocket.receive_json(), timeout=0.5)
                if isinstance(incoming, dict) and incoming.get("action") == "subscribe":
                    if incoming.get("symbol"):
                        sub_symbol = str(incoming["symbol"])
                    if incoming.get("tf"):
                        sub_tf = str(incoming["tf"]).upper()
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except Exception:
        return
