"""24/7 Background Market Watchdog scanning watchlist symbols through the 8-Gate Gauntlet."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

from app.analytics import compute_trading_stats
from app.config import ALLOW_REAL_TRADING
from app.database import (
    add_system_log,
    create_execution_log,
    create_proposal,
    expire_stale_proposals,
    get_proposal,
    get_watchdog_config,
    get_watchlist,
    list_proposals,
    list_trade_logs,
    log_audit,
    record_equity_snapshot,
    update_proposal_status,
    upsert_mt5_deals,
)
from app.discord_notify import (
    notify_discord_autopilot,
    notify_discord_proposal,
    notify_discord_trade_closed,
)
from app.gauntlet import evaluate_gauntlet
from app.mt5_service import mt5_service
from app.sheets_sync import (
    sync_proposal_row,
    sync_stats_snapshot,
    sync_trade_rows,
    sync_watchdog_log_row,
)


class MarketWatchdog:
    """Asynchronous 24/7 market monitor that logs telemetry and queues confirmed-ready proposals."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._scan_lock = asyncio.Lock()
        self._exec_lock = asyncio.Lock()
        self.scanning_now = False
        self.last_scan_at: str | None = None
        self.last_results: dict[str, dict[str, Any]] = {}
        self._last_proposed_at: dict[str, float] = {}
        self._last_run_mono: float = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop(), name="market-watchdog")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        add_system_log("INFO", "WATCHDOG", "24/7 Market Watchdog started")
        # Initial quick delay so FastAPI startup finishes cleanly first
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=6.0)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            cfg = get_watchdog_config()
            interval = max(30, int(cfg.get("interval_sec", 120)))
            now_mono = time.monotonic()

            if cfg.get("enabled", True) and (
                self._last_run_mono == 0.0 or (now_mono - self._last_run_mono) >= interval
            ):
                try:
                    await self.run_scan_cycle()
                except Exception as exc:
                    add_system_log("ERROR", "WATCHDOG", f"Watchdog cycle failed: {exc}")
                self._last_run_mono = time.monotonic()

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def run_scan_cycle(self, symbols_override: list[str] | None = None) -> dict[str, Any]:
        """Run one full scan across the watchlist, sync MT5 deals, and optionally queue PASS setups."""
        async with self._scan_lock:
            self.scanning_now = True
            summary_items: list[dict[str, Any]] = []
            try:
                connected = await asyncio.to_thread(mt5_service.is_connected)
                if not connected:
                    log_entry = add_system_log("WARN", "WATCHDOG", "MT5 not connected; skipping market scan")
                    await asyncio.to_thread(sync_watchdog_log_row, log_entry)
                    return {"scanned": 0, "results": [], "mt5_connected": False}

                # 1. Sync closed MT5 deals & periodic equity snapshot continuously
                try:
                    acc = await asyncio.to_thread(mt5_service.get_account_summary)
                    record_equity_snapshot(
                        balance=acc["balance"],
                        equity=acc["equity"],
                        floating_pnl=acc["profit"],
                        margin_free=acc["margin_free"],
                        min_interval_sec=300,
                    )
                    deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 30)
                    sync_res = upsert_mt5_deals(deals)
                    newly_closed = sync_res.get("newly_closed_rows") or []
                    if newly_closed:
                        closed = list_trade_logs(status="CLOSED", limit=5000)
                        stats = compute_trading_stats(closed, current_balance=acc["balance"])
                        add_system_log(
                            "INFO",
                            "SYNC",
                            f"Auto-synced {len(newly_closed)} newly closed MT5 trade(s)",
                        )
                        await asyncio.to_thread(sync_trade_rows, newly_closed)
                        await asyncio.to_thread(sync_stats_snapshot, stats)
                        for closed_row in newly_closed:
                            await asyncio.to_thread(
                                notify_discord_trade_closed,
                                closed_row,
                                acc["balance"],
                                stats,
                            )
                except Exception as exc:
                    add_system_log("WARN", "SYNC", f"Auto-sync deals warning: {exc}")

                # 2. Scan watchlist symbols through the 9-Gate ML + News Gauntlet
                cfg = get_watchdog_config()
                tf = str(cfg.get("timeframe", "M15")).upper()
                risk_pct = float(cfg.get("risk_pct", 2.0))
                min_conf = float(cfg.get("min_confidence_pct", 75.0))
                auto_propose = bool(cfg.get("auto_propose", True))
                auto_accept_proposals = bool(cfg.get("auto_accept_proposals", False))
                cooldown_sec = max(60, int(cfg.get("cooldown_min", 30)) * 60)
                autopilot_enabled = bool(cfg.get("autopilot_enabled", False))
                autopilot_min_conf = float(cfg.get("autopilot_min_confidence_pct", 80.0))
                autopilot_sizing_mode = str(cfg.get("autopilot_sizing_mode", "FIXED_LOT")).upper()
                autopilot_fixed_lots = float(cfg.get("autopilot_fixed_lots", 0.01))
                autopilot_risk_pct = float(cfg.get("autopilot_risk_pct", 1.0))
                autopilot_max_open = int(cfg.get("autopilot_max_open_positions", 3))
                proposal_ttl_min = int(cfg.get("proposal_ttl_min", 45))
                max_daily_loss_pct = float(cfg.get("max_daily_loss_pct", 5.0))
                max_open_risk_pct = float(cfg.get("max_open_risk_pct", 15.0))
                sl_atr_mult = float(cfg.get("sl_atr_mult", 1.5))
                tp_atr_mult = float(cfg.get("tp_atr_mult", 2.5))
                min_rr_ratio = float(cfg.get("min_rr_ratio", 1.5))

                expire_stale_proposals(proposal_ttl_min)
                risk_status = await asyncio.to_thread(mt5_service.get_portfolio_risk_status)
                daily_circuit_broken = risk_status["daily_total_pnl_pct"] <= -abs(max_daily_loss_pct)
                portfolio_heat_full = risk_status["open_risk_pct"] >= abs(max_open_risk_pct)

                if auto_accept_proposals and not daily_circuit_broken and not portfolio_heat_full:
                    await self.process_pending_auto_accept()

                symbols = symbols_override or get_watchlist()
                open_positions = await asyncio.to_thread(mt5_service.get_open_positions)
                open_symbols = {p["symbol"] for p in open_positions}
                pending_props = list_proposals(status="PENDING", limit=100)
                pending_symbols = {p["symbol"] for p in pending_props}

                for sym in symbols:
                    try:
                        res = await asyncio.to_thread(
                            evaluate_gauntlet,
                            sym,
                            tf,
                            risk_pct,
                            min_conf,
                            sl_atr_mult,
                            tp_atr_mult,
                            min_rr_ratio,
                        )
                        resolved = res["symbol"]
                        ml_info = res.get("ml") or {}
                        conf_pct = ml_info.get("final_confidence_pct")
                        compact = {
                            "symbol": resolved,
                            "timeframe": res["timeframe"],
                            "verdict": res["verdict"],
                            "direction": res["direction"],
                            "passed_count": res["passed_count"],
                            "total_gates": res["total_gates"],
                            "confidence_pct": conf_pct,
                            "min_confidence_pct": min_conf,
                            "evaluated_at": res["evaluated_at"],
                            "bid": res["quote"]["bid"],
                            "sentiment": res["news_summary"]["sentiment"],
                        }
                        self.last_results[resolved] = compact
                        summary_items.append(compact)

                        top_title = res["news"][0]["title"][:70] if res["news"] else "No live news"
                        conf_txt = f"Conf {conf_pct:.1f}%/{min_conf:.0f}%" if conf_pct is not None else "Conf N/A"
                        msg = (
                            f"{resolved} {tf} | {res['verdict']} {res['direction']} | "
                            f"Gauntlet {res['passed_count']}/{res['total_gates']} | {conf_txt} | "
                            f"Bid {res['quote']['bid']} | News({res['news_summary']['sentiment']}): {top_title}"
                        )
                        log_level = "SIGNAL" if res["verdict"] == "PASS" else "INFO"
                        log_entry = add_system_log(log_level, "WATCHDOG", msg, symbol=resolved, details=compact)
                        await asyncio.to_thread(sync_watchdog_log_row, log_entry)

                        # 3. Auto-queue proposal (or Auto-Accept / Auto-Pilot execute) ONLY if 9/9 hard-fail-free PASS
                        if (
                            (auto_propose or auto_accept_proposals or autopilot_enabled)
                            and res["verdict"] == "PASS"
                            and res["fail_count"] == 0
                            and res.get("proposed_order")
                            and resolved not in open_symbols
                            and resolved not in pending_symbols
                        ):
                            if daily_circuit_broken or portfolio_heat_full:
                                reason_txt = (
                                    f"Daily Loss Limit ({risk_status['daily_total_pnl_pct']:.2f}% <= -{max_daily_loss_pct:.1f}%)"
                                    if daily_circuit_broken
                                    else f"Max Portfolio Heat ({risk_status['open_risk_pct']:.2f}% >= {max_open_risk_pct:.1f}%)"
                                )
                                add_system_log(
                                    "WARN",
                                    "RISK_GUARD",
                                    f"Circuit breaker blocked new {resolved} proposal: {reason_txt}",
                                    symbol=resolved,
                                )
                                continue

                            last_prop_ts = self._last_proposed_at.get(resolved, 0.0)
                            if (time.monotonic() - last_prop_ts) >= cooldown_sec:
                                po = res["proposed_order"]
                                should_auto_accept = (
                                    auto_accept_proposals
                                    and len(open_symbols) < autopilot_max_open
                                )
                                should_autopilot = (
                                    not should_auto_accept
                                    and autopilot_enabled
                                    and conf_pct is not None
                                    and float(conf_pct) >= autopilot_min_conf
                                    and len(open_symbols) < autopilot_max_open
                                )
                                should_auto_exec = should_auto_accept or should_autopilot
                                exec_mode = "AUTO_ACCEPT" if should_auto_accept else "AUTOPILOT"
                                prop_source = exec_mode if should_auto_exec else "WATCHDOG"
                                prop_lots = po["lots"]
                                prop_risk_pct = po["risk_pct"]
                                prop_risk_usd = po["est_risk_usd"]
                                prop_reward_usd = po["est_reward_usd"]
                                prop_rr = po["rr_ratio"]

                                if should_auto_exec:
                                    ap_chk = await asyncio.to_thread(
                                        mt5_service.check_order,
                                        po["symbol"],
                                        po["side"],
                                        autopilot_fixed_lots if autopilot_sizing_mode == "FIXED_LOT" else None,
                                        autopilot_risk_pct if autopilot_sizing_mode == "RISK_PCT" else None,
                                        None,
                                        po["sl"],
                                        po["tp"],
                                    )
                                    prop_lots = ap_chk["lots"]
                                    prop_risk_pct = ap_chk["est_risk_pct"]
                                    prop_risk_usd = ap_chk["est_risk_usd"]
                                    prop_reward_usd = ap_chk["est_reward_usd"]
                                    prop_rr = ap_chk["rr_ratio"]

                                proposal = create_proposal(
                                    {
                                        "source": prop_source,
                                        "symbol": po["symbol"],
                                        "side": po["side"],
                                        "order_type": po["order_type"],
                                        "entry_price": po["entry_price"],
                                        "sl": po["sl"],
                                        "tp": po["tp"],
                                        "risk_pct": prop_risk_pct,
                                        "lots": prop_lots,
                                        "est_risk_usd": prop_risk_usd,
                                        "est_reward_usd": prop_reward_usd,
                                        "rr_ratio": prop_rr,
                                        "rationale": po["rationale"],
                                        "timeframe": po["timeframe"],
                                        "gauntlet": {
                                            "verdict": res["verdict"],
                                            "passed_count": res["passed_count"],
                                            "total_gates": res["total_gates"],
                                            "confidence_pct": conf_pct,
                                            "gates": res["gates"],
                                            "ml": ml_info,
                                        },
                                        "news": res["news"],
                                    }
                                )
                                self._last_proposed_at[resolved] = time.monotonic()

                                if should_auto_exec:
                                    await self._execute_autopilot_demo(
                                        proposal,
                                        resolved,
                                        tf,
                                        conf_pct,
                                        open_symbols,
                                        mode_label=exec_mode,
                                    )
                                else:
                                    pending_symbols.add(resolved)
                                    log_audit(
                                        event_type="PROPOSAL_CREATED",
                                        actor="WATCHDOG",
                                        summary=(
                                            f"Watchdog queued Proposal #{proposal['id']}: "
                                            f"{proposal['side']} {proposal['lots']} {resolved}"
                                        ),
                                        payload={"proposal_id": proposal["id"]},
                                    )
                                    sig_log = add_system_log(
                                        "SIGNAL",
                                        "SIGNAL",
                                        f"Queued Proposal #{proposal['id']} ({proposal['side']} {proposal['lots']} {resolved} @ {proposal['entry_price']}) for user confirmation",
                                        symbol=resolved,
                                    )
                                    await asyncio.to_thread(sync_proposal_row, proposal)
                                    await asyncio.to_thread(sync_watchdog_log_row, sig_log)
                                    await asyncio.to_thread(notify_discord_proposal, proposal)
                    except Exception as exc:
                        err_log = add_system_log("WARN", "WATCHDOG", f"{sym} scan skipped: {exc}", symbol=sym)
                        await asyncio.to_thread(sync_watchdog_log_row, err_log)

                self.last_scan_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                self._last_run_mono = time.monotonic()
                return {
                    "scanned": len(summary_items),
                    "last_scan_at": self.last_scan_at,
                    "results": summary_items,
                    "mt5_connected": True,
                }
            finally:
                self.scanning_now = False

    async def auto_accept_proposal(
        self,
        proposal: dict[str, Any],
        mode_label: str = "AUTO_ACCEPT",
    ) -> dict[str, Any]:
        """Auto-accept and execute an AI-generated proposal with full risk & safety guards."""
        pid = int(proposal["id"])
        async with self._exec_lock:
            fresh = get_proposal(pid)
            if fresh is None or fresh.get("status") != "PENDING":
                return {"executed": False, "reason": "not_pending", "proposal": fresh or proposal}

            cfg = get_watchdog_config()
            max_open = int(cfg.get("autopilot_max_open_positions", 3))
            max_daily_loss_pct = float(cfg.get("max_daily_loss_pct", 5.0))
            max_open_risk_pct = float(cfg.get("max_open_risk_pct", 15.0))

            connected = await asyncio.to_thread(mt5_service.is_connected)
            if not connected:
                return {"executed": False, "reason": "mt5_disconnected", "proposal": fresh}

            risk_status = await asyncio.to_thread(mt5_service.get_portfolio_risk_status)
            if risk_status["daily_total_pnl_pct"] <= -abs(max_daily_loss_pct):
                add_system_log(
                    "WARN",
                    "RISK_GUARD",
                    f"Auto-Accept blocked #{pid}: Daily Loss Limit ({risk_status['daily_total_pnl_pct']:.2f}% <= -{max_daily_loss_pct:.1f}%)",
                    symbol=fresh["symbol"],
                )
                return {"executed": False, "reason": "daily_loss_limit", "proposal": fresh}
            if risk_status["open_risk_pct"] >= abs(max_open_risk_pct):
                add_system_log(
                    "WARN",
                    "RISK_GUARD",
                    f"Auto-Accept blocked #{pid}: Max Portfolio Heat ({risk_status['open_risk_pct']:.2f}% >= {max_open_risk_pct:.1f}%)",
                    symbol=fresh["symbol"],
                )
                return {"executed": False, "reason": "portfolio_heat", "proposal": fresh}

            open_positions = await asyncio.to_thread(mt5_service.get_open_positions)
            open_symbols = {p["symbol"] for p in open_positions}
            if len(open_symbols) >= max_open:
                add_system_log(
                    "WARN",
                    "AUTO_ACCEPT",
                    f"Auto-Accept skipped #{pid}: ถือครบสูงสุด {max_open} ไม้แล้ว",
                    symbol=fresh["symbol"],
                )
                return {"executed": False, "reason": "max_open_positions", "proposal": fresh}

            gauntlet = fresh.get("gauntlet") or {}
            conf_pct = gauntlet.get("confidence_pct")
            tf = str(fresh.get("timeframe") or "M15").upper()
            exec_res = await self._execute_autopilot_demo(
                fresh,
                str(fresh["symbol"]),
                tf,
                float(conf_pct) if conf_pct is not None else None,
                open_symbols,
                mode_label=mode_label,
            )
            latest = get_proposal(pid) or fresh
            return {
                "executed": bool(exec_res and exec_res.get("success")),
                "proposal": latest,
                "execution": exec_res,
            }

    async def process_pending_auto_accept(self) -> int:
        """Accept any valid non-expired PENDING AI proposals in the queue when Auto-Accept is ON."""
        cfg = get_watchdog_config()
        if not cfg.get("auto_accept_proposals", False):
            return 0
        if not await asyncio.to_thread(mt5_service.is_connected):
            return 0

        ttl_min = int(cfg.get("proposal_ttl_min", 45))
        expire_stale_proposals(ttl_min)
        pending = list_proposals(status="PENDING", limit=20)
        ai_sources = {"WATCHDOG", "GAUNTLET", "AI", "CLI", "AUTO_ACCEPT", "AUTOPILOT"}
        open_positions = await asyncio.to_thread(mt5_service.get_open_positions)
        open_symbols = {p["symbol"] for p in open_positions}

        accepted_count = 0
        for prop in reversed(pending):
            src = str(prop.get("source") or "").upper()
            if src not in ai_sources:
                continue
            if prop["symbol"] in open_symbols:
                continue
            res = await self.auto_accept_proposal(prop, mode_label="AUTO_ACCEPT")
            if res.get("executed"):
                open_symbols.add(prop["symbol"])
                accepted_count += 1
        return accepted_count

    async def _execute_autopilot_demo(
        self,
        proposal: dict[str, Any],
        resolved: str,
        tf: str,
        conf_pct: float | None,
        open_symbols: set[str],
        mode_label: str = "AUTOPILOT",
    ) -> dict[str, Any] | None:
        """Execute an Auto-Accept or Auto-Pilot proposal (DEMO-only unless ALLOW_REAL_TRADING=true)."""
        pid = int(proposal["id"])
        is_auto_accept = mode_label.upper() == "AUTO_ACCEPT"
        tag_label = "AUTO_ACCEPT" if is_auto_accept else "AUTOPILOT"
        human_label = "Auto-Accept AI" if is_auto_accept else "Auto-Pilot DEMO"
        conf_txt = f"{conf_pct:.1f}%" if conf_pct is not None else "PASS"
        try:
            acc = await asyncio.to_thread(mt5_service.get_account_summary)
            if acc["trade_mode"] != "DEMO" and not ALLOW_REAL_TRADING:
                add_system_log(
                    "WARN",
                    tag_label,
                    f"{human_label} blocked on {acc['trade_mode']} account; Proposal #{pid} kept PENDING for manual confirm",
                    symbol=resolved,
                )
                await asyncio.to_thread(notify_discord_proposal, proposal)
                return None

            if not acc["terminal_trade_allowed"]:
                add_system_log(
                    "WARN",
                    tag_label,
                    f"MT5 Algo Trading is OFF; Proposal #{pid} kept PENDING for manual confirm",
                    symbol=resolved,
                )
                await asyncio.to_thread(notify_discord_proposal, proposal)
                return None

            exec_res = await asyncio.to_thread(
                mt5_service.send_order,
                proposal["symbol"],
                proposal["side"],
                proposal["lots"],
                None,
                proposal["entry_price"] if proposal.get("order_type") == "PENDING" else None,
                proposal["sl"],
                proposal["tp"],
                30,
                f"{'AUTOACC' if is_auto_accept else 'AUTOPILOT'}-P{pid}",
                ALLOW_REAL_TRADING,
            )
            new_status = "EXECUTED" if exec_res["success"] else "FAILED"
            updated_prop = update_proposal_status(
                pid,
                new_status,
                mt5_order_ticket=exec_res["order_ticket"],
                mt5_deal_ticket=exec_res["deal_ticket"],
                exec_price=exec_res["exec_price"],
                exec_comment=f"{tag_label} ({conf_txt}): {exec_res['retcode']} {exec_res['comment']}",
            )
            if exec_res["success"]:
                open_symbols.add(resolved)
                trade_log = create_execution_log(
                    {
                        "mt5_deal_ticket": exec_res["deal_ticket"] or None,
                        "mt5_position_id": exec_res["order_ticket"] or None,
                        "proposal_id": pid,
                        "symbol": proposal["symbol"],
                        "side": proposal["side"],
                        "volume": exec_res["exec_volume"],
                        "entry_price": exec_res["exec_price"],
                        "sl": proposal["sl"],
                        "tp": proposal["tp"],
                        "status": "OPEN",
                        "strategy_tag": f"AI_{tag_label}_{tf}",
                        "notes": f"[{tag_label} {conf_txt}] {proposal['rationale']}",
                        "source": tag_label,
                    }
                )
                record_equity_snapshot(
                    balance=acc["balance"],
                    equity=acc["equity"],
                    floating_pnl=acc["profit"],
                    margin_free=acc["margin_free"],
                    min_interval_sec=0,
                )
                sig_log = add_system_log(
                    "SIGNAL",
                    tag_label,
                    (
                        f"{'⚡' if is_auto_accept else '🤖'} {human_label} executed #{pid}: {proposal['side']} {exec_res['exec_volume']} "
                        f"{resolved} @ {exec_res['exec_price']} (Conf {conf_txt})"
                    ),
                    symbol=resolved,
                )
                log_audit(
                    event_type=f"{tag_label}_EXECUTED",
                    actor=tag_label,
                    summary=f"{human_label} executed Proposal #{pid}: {proposal['side']} {exec_res['exec_volume']} {resolved}",
                    payload={"proposal_id": pid, "execution": exec_res},
                )
                if updated_prop:
                    await asyncio.to_thread(sync_proposal_row, updated_prop)
                    await asyncio.to_thread(notify_discord_autopilot, updated_prop, exec_res, tag_label)
                await asyncio.to_thread(sync_trade_rows, [trade_log])
                await asyncio.to_thread(sync_watchdog_log_row, sig_log)
            else:
                add_system_log(
                    "ERROR",
                    tag_label,
                    f"{human_label} Proposal #{pid} execution failed: {exec_res['comment']}",
                    symbol=resolved,
                )
            return exec_res
        except Exception as exc:
            add_system_log("ERROR", tag_label, f"{human_label} Proposal #{pid} error: {exc}", symbol=resolved)
            return None

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "scanning_now": self.scanning_now,
            "last_scan_at": self.last_scan_at,
            "config": get_watchdog_config(),
            "last_results": list(self.last_results.values()),
        }


watchdog = MarketWatchdog()
