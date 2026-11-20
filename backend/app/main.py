"""FastAPI REST & WebSocket server bridging the React Trading Desk with MetaTrader 5."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hmac
from typing import Any
import urllib.parse

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.analytics import compute_trading_stats
from app.config import ALLOWED_ORIGINS, API_KEY, DEFAULT_SYMBOL, SUPABASE_OWNER_EMAIL, SUPABASE_URL
from app.database import (
    add_system_log,
    create_execution_log,
    create_proposal,
    export_trade_logs_csv,
    get_discord_config,
    get_latest_system_log_id,
    get_position_manager_config,
    get_proposal,
    get_sheets_config,
    get_watchdog_config,
    get_watchlist,
    init_db,
    list_audit_events,
    list_proposals,
    list_system_logs,
    list_trade_logs,
    log_audit,
    record_equity_snapshot,
    set_discord_config,
    set_position_manager_config,
    set_sheets_config,
    set_watchdog_config,
    set_watchlist,
    update_proposal_status,
    update_trade_log_notes,
    upsert_mt5_deals,
)
from app.day_trader_skill import scan_watchlist_setups
from app.discord_notify import (
    notify_discord_execution_result,
    notify_discord_proposal,
    notify_discord_trade_closed,
    render_discord_action_html,
    test_discord_connection,
    verify_discord_action_token,
)
from app.gauntlet import evaluate_gauntlet, run_historical_backtest
from app.ml_engine import get_model_status, train_symbol_model
from app.mt5_service import mt5_service
from app.news_service import fetch_symbol_news
from app.position_manager import enrich_open_positions, position_manager
from app.schemas import (
    DiscordConfigRequest,
    GauntletEvaluateRequest,
    MLTrainRequest,
    OrderCheckRequest,
    PositionCloseRequest,
    PositionManagerConfigPatchRequest,
    PositionModifyRequest,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    ProposalRejectRequest,
    SheetsConfigRequest,
    TradeLogUpdateRequest,
    WatchdogConfigPatchRequest,
    WatchlistUpdateRequest,
)
from app.sheets_sync import (
    sync_all_to_sheets,
    sync_proposal_row,
    sync_stats_snapshot,
    sync_trade_rows,
    test_sheets_connection,
)
from app.supabase_sync import (
    is_supabase_configured,
    sync_all_to_supabase,
    sync_bridge_state_to_supabase,
    sync_settings_to_supabase,
    verify_supabase_owner_jwt,
)
from app.watcher import watchdog


async def _initial_supabase_boot_sync() -> None:
    try:
        connected = await asyncio.to_thread(mt5_service.is_connected)
        acc = None
        bal = None
        t_mode = None
        if connected:
            try:
                acc = await asyncio.to_thread(mt5_service.get_account_summary)
                bal = acc.get("balance")
                t_mode = acc.get("trade_mode")
            except Exception:
                pass
        await asyncio.to_thread(sync_all_to_supabase, bal, connected, t_mode, acc)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        mt5_service.connect()
    except Exception:
        pass
    watchdog.start()
    position_manager.start()
    asyncio.create_task(_initial_supabase_boot_sync())
    yield
    await position_manager.stop()
    await watchdog.stop()
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


def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Require either a valid Supabase Owner JWT (Bearer) or matching X-API-Key."""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
        if verify_supabase_owner_jwt(bearer):
            return

    expected = (API_KEY or "mt5-local-dev-key").encode("utf-8")
    provided = (x_api_key or "").encode("utf-8")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing authentication (Supabase Owner JWT or X-API-Key).",
        )


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
        snap["positions"] = enrich_open_positions(snap.get("positions") or [])
        try:
            snap["risk_status"] = await asyncio.to_thread(mt5_service.get_portfolio_risk_status)
        except Exception:
            snap["risk_status"] = None
        return snap
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/risk-status")
async def get_risk_status_endpoint() -> dict[str, Any]:
    try:
        status = await asyncio.to_thread(mt5_service.get_portfolio_risk_status)
        cfg = get_watchdog_config()
        return {
            **status,
            "max_daily_loss_pct": float(cfg.get("max_daily_loss_pct", 5.0)),
            "max_open_risk_pct": float(cfg.get("max_open_risk_pct", 15.0)),
            "proposal_ttl_min": int(cfg.get("proposal_ttl_min", 45)),
            "max_drift_atr": float(cfg.get("max_drift_atr", 0.6)),
        }
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
            "risk_pct": checked["est_risk_pct"],
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
    add_system_log(
        "SIGNAL",
        "TRADE",
        f"Queued Proposal #{proposal['id']} ({proposal['side']} {proposal['lots']} {proposal['symbol']} @ {proposal['entry_price']})",
        symbol=proposal["symbol"],
    )
    asyncio.create_task(asyncio.to_thread(sync_proposal_row, proposal))
    asyncio.create_task(asyncio.to_thread(notify_discord_proposal, proposal))
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
        acc = await asyncio.to_thread(mt5_service.get_account_summary)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc

    if not acc["terminal_trade_allowed"]:
        msg = (
            "ปุ่ม Algo Trading บน MT5 ยังปิดอยู่ (OFF) — "
            "กดปุ่ม Algo Trading ด้านบน MT5 (หรือ Ctrl+E) ให้เป็นสีเขียวก่อน แล้วกด Confirm ใหม่อีกครั้ง"
        )
        log_audit(
            event_type="PROPOSAL_BLOCKED_ALGO_OFF",
            actor="USER",
            summary=f"Proposal #{proposal_id} paused: Terminal Algo Trading is OFF",
            payload={"proposal_id": proposal_id},
        )
        raise HTTPException(status_code=400, detail=msg)

    # Proposal TTL, Price-Drift, and Circuit Breaker Safety Checks (unless force=True)
    wd_cfg = get_watchdog_config()
    if not req.force:
        ttl_min = int(wd_cfg.get("proposal_ttl_min", 45))
        if ttl_min > 0 and proposal.get("created_at"):
            try:
                created_dt = datetime.strptime(proposal["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                age_min = (datetime.now(timezone.utc) - created_dt).total_seconds() / 60.0
                if age_min > ttl_min:
                    raise HTTPException(
                        status_code=400,
                        detail=f"โพย #{proposal_id} สร้างมาแล้ว {int(age_min)} นาที (เกินเวลาหมดอายุ {ttl_min} นาที) — กรุณาวิเคราะห์ใหม่เพื่อป้องกันเข้าไม้ราคาเก่า",
                    )
            except ValueError:
                pass

        # Check Daily Max Loss & Portfolio Heat Circuit Breakers
        try:
            risk_st = await asyncio.to_thread(mt5_service.get_portfolio_risk_status)
            max_daily_loss = float(wd_cfg.get("max_daily_loss_pct", 5.0))
            max_open_heat = float(wd_cfg.get("max_open_risk_pct", 15.0))
            if risk_st["daily_total_pnl_pct"] <= -abs(max_daily_loss):
                raise HTTPException(
                    status_code=400,
                    detail=f"ระบบตัดไฟรายวันทำงาน (Daily Loss {risk_st['daily_total_pnl_pct']:.2f}% แตะลิมิต -{max_daily_loss:.1f}%) — ปรับลิมิตใน Watchdog Settings หากต้องการเทรดต่อ",
                )
            if risk_st["open_risk_pct"] >= abs(max_open_heat):
                raise HTTPException(
                    status_code=400,
                    detail=f"ความเสี่ยงรวมของไม้ที่ถืออยู่ ({risk_st['open_risk_pct']:.1f}%) เต็มเพดานพอร์ต ({max_open_heat:.1f}%) แล้ว — ปิดไม้เดิมหรือเลื่อน SL บังทุนก่อนเปิดไม้เพิ่ม",
                )
        except HTTPException:
            raise
        except Exception:
            pass

        # Check Price-Drift on MARKET orders
        if proposal.get("order_type") == "MARKET":
            try:
                q = await asyncio.to_thread(mt5_service.get_quote, proposal["symbol"])
                is_buy = str(proposal["side"]).upper().startswith("BUY")
                cur_p = float(q["ask"] if is_buy else q["bid"])
                prop_entry = float(proposal["entry_price"])
                prop_sl = float(proposal["sl"]) if proposal.get("sl") else None
                if prop_sl:
                    sl_dist = abs(prop_entry - prop_sl)
                    max_drift_ratio = float(wd_cfg.get("max_drift_atr", 0.6))
                    if sl_dist > 0 and abs(cur_p - prop_entry) > sl_dist * max_drift_ratio:
                        raise HTTPException(
                            status_code=400,
                            detail=f"ราคาปัจจุบัน ({cur_p}) วิ่งหนีจากจุดเข้าเดิม ({prop_entry}) เกินระยะปลอดภัยแล้ว — กรุณากดประเมินใหม่",
                        )
            except HTTPException:
                raise
            except Exception:
                pass

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
    except (PermissionError, ValueError) as exc:
        log_audit(
            event_type="PROPOSAL_CONFIRM_BLOCKED",
            actor="USER",
            summary=f"Proposal #{proposal_id} blocked: {exc}",
            payload={"proposal_id": proposal_id},
        )
        raise _map_mt5_error(exc) from exc
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
    add_system_log(
        "INFO" if exec_res["success"] else "ERROR",
        "TRADE",
        f"Proposal #{proposal_id} {'EXECUTED' if exec_res['success'] else 'FAILED'}: {proposal['side']} {exec_res['exec_volume']} {proposal['symbol']} @ {exec_res['exec_price']}",
        symbol=proposal["symbol"],
    )
    if updated_proposal:
        asyncio.create_task(asyncio.to_thread(sync_proposal_row, updated_proposal))
    if trade_log:
        asyncio.create_task(asyncio.to_thread(sync_trade_rows, [trade_log]))
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
    add_system_log(
        "INFO",
        "TRADE",
        f"Rejected Proposal #{proposal_id} ({proposal['side']} {proposal['symbol']}): {reason}",
        symbol=proposal["symbol"],
    )
    if updated:
        asyncio.create_task(asyncio.to_thread(sync_proposal_row, updated))
    return {"proposal": updated}


@app.patch("/api/positions/{ticket}", dependencies=[Depends(verify_api_key)])
async def patch_modify_position(ticket: int, body: PositionModifyRequest) -> dict[str, Any]:
    if body.sl is None and body.tp is None and body.price_open is None:
        raise HTTPException(status_code=400, detail="Provide at least one of sl, tp, or price_open.")
    try:
        res = await asyncio.to_thread(
            mt5_service.modify_position,
            ticket,
            body.sl,
            body.tp,
            body.price_open,
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


@app.post("/api/positions/panic-close-all", dependencies=[Depends(verify_api_key)])
async def post_panic_close_all(allow_real: bool = Query(default=False)) -> dict[str, Any]:
    """Emergency 1-Click Kill-Switch: pause Auto-Pilot, close all open positions, and cancel all pending orders."""
    try:
        set_watchdog_config({"autopilot_enabled": False})
        res = await asyncio.to_thread(mt5_service.panic_close_all, allow_real)
        deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 30)
        sync_summary = upsert_mt5_deals(deals)
        msg = (
            f"🚨 PANIC KILL-SWITCH: ปิดออเดอร์ {res['closed_positions_count']} ไม้, "
            f"ยกเลิก Pending {res['cancelled_orders_count']} รายการ และปิดโหมด Auto-Pilot แล้ว"
        )
        log_audit(
            event_type="PANIC_CLOSE_ALL",
            actor="USER",
            summary=msg,
            payload=res,
        )
        add_system_log("WARN", "RISK_GUARD", msg)
        newly_closed = sync_summary.get("newly_closed_rows") or []
        if newly_closed:
            asyncio.create_task(asyncio.to_thread(sync_trade_rows, newly_closed))
        return {**res, "message": msg}
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
        add_system_log(
            "INFO",
            "TRADE",
            f"Closed #{ticket} ({res['symbol']}) @ {res.get('close_price', '-')}",
            symbol=res["symbol"],
        )
        newly_closed = sync_summary.get("newly_closed_rows") or []
        if newly_closed:
            asyncio.create_task(asyncio.to_thread(sync_trade_rows, newly_closed))
            try:
                acc = await asyncio.to_thread(mt5_service.get_account_summary)
                all_closed = list_trade_logs(status="CLOSED", limit=5000)
                st = compute_trading_stats(all_closed, current_balance=acc["balance"])
                for cr in newly_closed:
                    asyncio.create_task(
                        asyncio.to_thread(notify_discord_trade_closed, cr, acc["balance"], st)
                    )
            except Exception:
                pass
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
    add_system_log(
        "INFO",
        "SYNC",
        f"Synced {summary['total']} closed MT5 deal(s) (new: {summary['inserted']}, updated: {summary['updated']})",
    )
    newly_closed = summary.get("newly_closed_rows") or []
    if newly_closed:
        asyncio.create_task(asyncio.to_thread(sync_trade_rows, newly_closed))
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


@app.get("/api/symbols")
async def get_symbols(
    q: str = Query(default=""),
    category: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=100),
) -> dict[str, Any]:
    try:
        items = await asyncio.to_thread(mt5_service.search_symbols, q, category, limit)
        return {"symbols": items, "count": len(items)}
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/watchlist")
async def get_watchlist_endpoint() -> dict[str, Any]:
    symbols = get_watchlist()
    quotes: list[dict[str, Any]] = []
    if await asyncio.to_thread(mt5_service.is_connected):
        try:
            quotes = await asyncio.to_thread(mt5_service.get_watchlist_quotes, symbols)
        except Exception:
            quotes = []
    return {"symbols": symbols, "quotes": quotes}


@app.put("/api/watchlist", dependencies=[Depends(verify_api_key)])
async def put_watchlist_endpoint(body: WatchlistUpdateRequest) -> dict[str, Any]:
    updated = set_watchlist(body.symbols)
    quotes = []
    if await asyncio.to_thread(mt5_service.is_connected):
        quotes = await asyncio.to_thread(mt5_service.get_watchlist_quotes, updated)
    add_system_log("INFO", "WATCHLIST", f"Updated watchlist ({len(updated)} symbols): {', '.join(updated)}")
    asyncio.create_task(asyncio.to_thread(sync_settings_to_supabase))
    return {"symbols": updated, "quotes": quotes}


@app.get("/api/news")
async def get_news_endpoint(
    symbol: str = Query(default=DEFAULT_SYMBOL),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_symbol_news, symbol, refresh)


@app.post("/api/gauntlet/evaluate")
async def post_gauntlet_evaluate(
    body: GauntletEvaluateRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    if body.auto_queue:
        verify_api_key(x_api_key, authorization)

    try:
        result = await asyncio.to_thread(
            evaluate_gauntlet,
            body.symbol,
            body.tf,
            body.risk_pct,
            body.min_confidence_pct,
            body.sl_atr_mult,
            body.tp_atr_mult,
            body.min_rr_ratio,
        )
    except Exception as exc:
        raise _map_mt5_error(exc) from exc

    ml_conf = (result.get("ml") or {}).get("final_confidence_pct")
    conf_tag = f" | Conf {ml_conf:.1f}%" if ml_conf is not None else ""
    add_system_log(
        "SIGNAL" if result["verdict"] == "PASS" else "INFO",
        "GAUNTLET",
        f"Evaluated {result['symbol']} {result['timeframe']}: {result['verdict']} {result['direction']} ({result['passed_count']}/{result['total_gates']}{conf_tag})",
        symbol=result["symbol"],
    )

    queued_proposal = None
    if body.auto_queue and result["verdict"] == "PASS" and result.get("proposed_order"):
        po = result["proposed_order"]
        queued_proposal = create_proposal(
            {
                "source": "GAUNTLET",
                "symbol": po["symbol"],
                "side": po["side"],
                "order_type": po["order_type"],
                "entry_price": po["entry_price"],
                "sl": po["sl"],
                "tp": po["tp"],
                "risk_pct": po["risk_pct"],
                "lots": po["lots"],
                "est_risk_usd": po["est_risk_usd"],
                "est_reward_usd": po["est_reward_usd"],
                "rr_ratio": po["rr_ratio"],
                "rationale": po["rationale"],
                "timeframe": po["timeframe"],
                "gauntlet": {
                    "verdict": result["verdict"],
                    "passed_count": result["passed_count"],
                    "total_gates": result["total_gates"],
                    "confidence_pct": ml_conf,
                    "gates": result["gates"],
                    "ml": result.get("ml"),
                },
                "news": result["news"],
            }
        )
        log_audit(
            event_type="PROPOSAL_CREATED",
            actor="GAUNTLET",
            summary=f"Gauntlet queued Proposal #{queued_proposal['id']}: {po['side']} {po['lots']} {po['symbol']}",
            payload={"proposal_id": queued_proposal["id"]},
        )
        asyncio.create_task(asyncio.to_thread(sync_proposal_row, queued_proposal))
        asyncio.create_task(asyncio.to_thread(notify_discord_proposal, queued_proposal))

    return {**result, "queued_proposal": queued_proposal}


@app.get("/api/scanner/watchlist")
async def get_scanner_watchlist_endpoint(
    tf: str = Query(default="M15"),
) -> dict[str, Any]:
    try:
        symbols = get_watchlist()
        items = await asyncio.to_thread(scan_watchlist_setups, symbols, tf)
        return {"tf": tf.upper(), "count": len(items), "items": items}
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/ml/status")
async def get_ml_status_endpoint(
    symbol: str = Query(default=DEFAULT_SYMBOL),
    tf: str = Query(default="M15"),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_status, symbol, tf)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.post("/api/ml/train", dependencies=[Depends(verify_api_key)])
async def post_ml_train_endpoint(body: MLTrainRequest) -> dict[str, Any]:
    try:
        meta = await asyncio.to_thread(train_symbol_model, body.symbol, body.tf, body.bars)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc

    oos = meta["oos_summary"]
    add_system_log(
        "INFO",
        "ML",
        f"Trained LightGBM {meta['symbol']} {meta['tf']} ({meta['bars_used']} bars) | OOS AUC B:{oos['auc_buy']}/S:{oos['auc_sell']} | Net OOS R: {oos['net_r_combined']}",
        symbol=meta["symbol"],
    )
    return {"trained": True, "symbol": meta["symbol"], "tf": meta["tf"], "meta": meta}


@app.get("/api/backtest")
async def get_backtest_endpoint(
    symbol: str = Query(default=DEFAULT_SYMBOL),
    tf: str = Query(default="M15"),
    bars: int = Query(default=600, ge=120, le=1500),
    sl_atr_mult: float = Query(default=1.5, ge=0.4, le=6.0),
    tp_atr_mult: float = Query(default=2.5, ge=0.5, le=10.0),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(run_historical_backtest, symbol, tf, bars, sl_atr_mult, tp_atr_mult)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/watchdog/status")
async def get_watchdog_status() -> dict[str, Any]:
    return watchdog.get_status()


@app.patch("/api/watchdog/config", dependencies=[Depends(verify_api_key)])
async def patch_watchdog_config(body: WatchdogConfigPatchRequest) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    updated = set_watchdog_config(patch)
    add_system_log("INFO", "WATCHDOG", f"Updated watchdog config: {updated}")
    asyncio.create_task(asyncio.to_thread(sync_settings_to_supabase))
    return watchdog.get_status()


@app.post("/api/watchdog/scan", dependencies=[Depends(verify_api_key)])
async def post_watchdog_scan(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    override = [symbol] if symbol else None
    res = await watchdog.run_scan_cycle(symbols_override=override)
    return {"scan": res, "status": watchdog.get_status()}


@app.get("/api/system-logs")
async def get_system_logs(
    category: str | None = Query(default=None),
    level: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=500),
) -> dict[str, Any]:
    logs = list_system_logs(category=category, level=level, limit=limit)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/sheets/config", dependencies=[Depends(verify_api_key)])
async def get_sheets_config_endpoint() -> dict[str, Any]:
    cfg = get_sheets_config()
    return {
        "enabled": bool(cfg.get("enabled")),
        "webhook_url": cfg.get("webhook_url", ""),
        "service_account_file": cfg.get("service_account_file", ""),
        "sheet_id": cfg.get("sheet_id", ""),
    }


@app.put("/api/sheets/config", dependencies=[Depends(verify_api_key)])
async def put_sheets_config_endpoint(body: SheetsConfigRequest) -> dict[str, Any]:
    w_url = (body.webhook_url or "").strip()
    if w_url and not (
        w_url.startswith("https://script.google.com/")
        or w_url.startswith("https://script.googleusercontent.com/")
        or w_url.startswith("http://127.0.0.1:")
        or w_url.startswith("http://localhost:")
    ):
        raise HTTPException(
            status_code=400,
            detail="Google Sheets Webhook URL ต้องขึ้นต้นด้วย https://script.google.com/macros/s/...",
        )
    updated = set_sheets_config(body.model_dump(exclude_none=True))
    add_system_log("INFO", "SHEETS", f"Updated Google Sheets sync config (enabled={updated.get('enabled')})")
    return updated


@app.post("/api/sheets/test", dependencies=[Depends(verify_api_key)])
async def post_sheets_test() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(test_sheets_connection)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sheets/sync-all", dependencies=[Depends(verify_api_key)])
async def post_sheets_sync_all() -> dict[str, Any]:
    bal = None
    if await asyncio.to_thread(mt5_service.is_connected):
        try:
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            bal = acc["balance"]
        except Exception:
            pass
    try:
        return await asyncio.to_thread(sync_all_to_sheets, bal)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/position-manager/status")
async def get_position_manager_status() -> dict[str, Any]:
    return position_manager.get_status()


@app.patch("/api/position-manager/config", dependencies=[Depends(verify_api_key)])
async def patch_position_manager_config(body: PositionManagerConfigPatchRequest) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    updated = set_position_manager_config(patch)
    add_system_log("INFO", "POS_MGR", f"Updated Smart Position Manager config: {updated}")
    asyncio.create_task(asyncio.to_thread(sync_settings_to_supabase))
    return position_manager.get_status()


@app.post("/api/position-manager/run", dependencies=[Depends(verify_api_key)])
async def post_position_manager_run() -> dict[str, Any]:
    res = await position_manager.run_cycle()
    return {"cycle": res, "status": position_manager.get_status()}


@app.post("/api/positions/{ticket}/breakeven", dependencies=[Depends(verify_api_key)])
async def post_position_breakeven(ticket: int) -> dict[str, Any]:
    try:
        return await position_manager.move_position_to_breakeven(ticket)
    except Exception as exc:
        raise _map_mt5_error(exc) from exc


@app.get("/api/discord/config", dependencies=[Depends(verify_api_key)])
async def get_discord_config_endpoint() -> dict[str, Any]:
    return get_discord_config()


@app.put("/api/discord/config", dependencies=[Depends(verify_api_key)])
async def put_discord_config_endpoint(body: DiscordConfigRequest) -> dict[str, Any]:
    updated = set_discord_config(body.model_dump(exclude_none=True))
    add_system_log("INFO", "DISCORD", f"Updated Discord notification config (enabled={updated.get('enabled')})")
    asyncio.create_task(asyncio.to_thread(sync_settings_to_supabase))
    asyncio.create_task(
        asyncio.to_thread(
            sync_bridge_state_to_supabase,
            updated.get("public_base_url"),
            mt5_service.is_connected(),
        )
    )
    return updated


@app.get("/api/supabase/status")
async def get_supabase_status() -> dict[str, Any]:
    return {
        "configured": is_supabase_configured(),
        "supabase_url": SUPABASE_URL,
        "owner_email": SUPABASE_OWNER_EMAIL,
    }


@app.post("/api/supabase/sync-all", dependencies=[Depends(verify_api_key)])
async def post_supabase_sync_all() -> dict[str, Any]:
    connected = await asyncio.to_thread(mt5_service.is_connected)
    acc = None
    bal = None
    t_mode = None
    if connected:
        try:
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            bal = acc.get("balance")
            t_mode = acc.get("trade_mode")
        except Exception:
            pass
    try:
        res = await asyncio.to_thread(sync_all_to_supabase, bal, connected, t_mode, acc)
        add_system_log("INFO", "SUPABASE", f"Full sync to Supabase completed: {res.get('written')}")
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/discord/test", dependencies=[Depends(verify_api_key)])
async def post_discord_test(body: DiscordConfigRequest | None = None) -> dict[str, Any]:
    try:
        webhook_url = body.webhook_url if body and body.webhook_url else None
        public_base = body.public_base_url if body and body.public_base_url else None
        return await asyncio.to_thread(test_discord_connection, webhook_url, public_base)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/discord/action", response_class=HTMLResponse)
async def get_discord_action_page(
    proposal_id: int = Query(...),
    action: str = Query(...),
    token: str = Query(...),
) -> HTMLResponse:
    act = action.strip().lower()
    if act not in ("confirm", "reject") or not verify_discord_action_token(proposal_id, act, token):
        return HTMLResponse(
            content=render_discord_action_html(None, act, token, executed=True, result_ok=False, result_message="ลิงก์ไม่ถูกต้องหรือหมดอายุ"),
            status_code=403,
        )
    proposal = get_proposal(proposal_id)
    return HTMLResponse(content=render_discord_action_html(proposal, act, token, executed=False))


@app.post("/api/discord/action", response_class=HTMLResponse)
async def post_discord_action_execute(request: Request) -> HTMLResponse:
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(raw_body)
    try:
        proposal_id = int((parsed.get("proposal_id") or [request.query_params.get("proposal_id", "0")])[0])
    except ValueError:
        proposal_id = 0
    action = str((parsed.get("action") or [request.query_params.get("action", "")])[0]).strip().lower()
    token = str((parsed.get("token") or [request.query_params.get("token", "")])[0]).strip()

    if action not in ("confirm", "reject") or not verify_discord_action_token(proposal_id, action, token):
        return HTMLResponse(
            content=render_discord_action_html(None, action, token, executed=True, result_ok=False, result_message="Token ไม่ถูกต้อง"),
            status_code=403,
        )

    proposal = get_proposal(proposal_id)
    if proposal is None:
        return HTMLResponse(
            content=render_discord_action_html(None, action, token, executed=True, result_ok=False, result_message="ไม่พบ Proposal นี้"),
            status_code=404,
        )
    if proposal["status"] != "PENDING":
        return HTMLResponse(
            content=render_discord_action_html(
                proposal,
                action,
                token,
                executed=True,
                result_ok=proposal["status"] == "EXECUTED",
                result_message=f"Proposal #{proposal_id} ถูกดำเนินการไปแล้ว ({proposal['status']})",
            )
        )

    if action == "reject":
        updated = update_proposal_status(proposal_id, "REJECTED", exec_comment="Rejected via Discord 1-Click")
        log_audit(
            event_type="PROPOSAL_REJECTED",
            actor="DISCORD_USER",
            summary=f"Rejected Proposal #{proposal_id} via Discord 1-Click",
            payload={"proposal_id": proposal_id},
        )
        add_system_log("INFO", "DISCORD", f"Rejected Proposal #{proposal_id} via Discord 1-Click", symbol=proposal["symbol"])
        if updated:
            asyncio.create_task(asyncio.to_thread(sync_proposal_row, updated))
            asyncio.create_task(
                asyncio.to_thread(
                    notify_discord_execution_result,
                    updated,
                    "reject",
                    f"กดปฏิเสธแผนเทรด #{proposal_id} ({proposal['side']} {proposal['symbol']}) เรียบร้อยแล้ว",
                )
            )
        return HTMLResponse(
            content=render_discord_action_html(
                updated or proposal,
                action,
                token,
                executed=True,
                result_ok=False,
                result_message=f"❌ ปฏิเสธแผนเทรด #{proposal_id} เรียบร้อยแล้ว",
            )
        )

    # Confirm via Discord 1-Click
    try:
        res = await post_confirm_proposal(proposal_id, ProposalConfirmRequest(comment=f"DISCORD-P{proposal_id}"))
        updated_prop = res["proposal"]
        exec_res = res["execution"]
        msg = f"✅ ยิงออเดอร์เข้า MT5 สำเร็จ! Ticket #{exec_res.get('order_ticket')} @ {exec_res.get('exec_price')}"
        if updated_prop:
            asyncio.create_task(
                asyncio.to_thread(
                    notify_discord_execution_result,
                    updated_prop,
                    "confirm",
                    msg,
                )
            )
        return HTMLResponse(
            content=render_discord_action_html(
                updated_prop,
                action,
                token,
                executed=True,
                result_ok=True,
                result_message=msg,
            )
        )
    except HTTPException as exc:
        return HTMLResponse(
            content=render_discord_action_html(
                proposal,
                action,
                token,
                executed=True,
                result_ok=False,
                result_message=f"⚠️ ยิงออเดอร์ไม่สำเร็จ: {exc.detail}",
            ),
            status_code=400,
        )


def _build_ws_packet(symbol: str, tf: str) -> dict[str, Any]:
    connected = mt5_service.is_connected()
    pending_count = len(list_proposals(status="PENDING", limit=100))
    latest_log_id = get_latest_system_log_id()
    wd_status = watchdog.get_status()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if not connected:
        return {
            "type": "tick",
            "mt5_connected": False,
            "server_time": now_str,
            "symbol": symbol,
            "tf": tf,
            "pending_proposals_count": pending_count,
            "latest_log_id": latest_log_id,
            "watchdog_running": wd_status["running"] and bool(wd_status["config"].get("enabled", True)),
            "watchdog_scanning": wd_status["scanning_now"],
            "account": None,
            "quote": None,
            "positions": [],
            "orders": [],
            "last_bar": None,
        }

    resolved = mt5_service.resolve_symbol(symbol)
    account = mt5_service.get_account_summary()
    quote = mt5_service.get_quote(resolved)
    positions = enrich_open_positions(mt5_service.get_open_positions())
    orders = mt5_service.get_pending_orders()
    last_bar = mt5_service.get_last_bar_fast(resolved, tf)

    return {
        "type": "tick",
        "mt5_connected": True,
        "server_time": now_str,
        "symbol": resolved,
        "tf": tf.upper(),
        "pending_proposals_count": pending_count,
        "latest_log_id": latest_log_id,
        "watchdog_running": wd_status["running"] and bool(wd_status["config"].get("enabled", True)),
        "watchdog_scanning": wd_status["scanning_now"],
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
