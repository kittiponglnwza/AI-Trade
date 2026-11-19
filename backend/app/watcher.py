"""24/7 Background Market Watchdog scanning watchlist symbols through the 8-Gate Gauntlet."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any

from app.analytics import compute_trading_stats
from app.database import (
    add_system_log,
    create_proposal,
    get_watchdog_config,
    get_watchlist,
    list_proposals,
    list_trade_logs,
    log_audit,
    upsert_mt5_deals,
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

                # 1. Sync closed MT5 deals continuously
                try:
                    deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 30)
                    sync_res = upsert_mt5_deals(deals)
                    if sync_res["inserted"] > 0:
                        closed = list_trade_logs(status="CLOSED", limit=5000)
                        acc = await asyncio.to_thread(mt5_service.get_account_summary)
                        stats = compute_trading_stats(closed, current_balance=acc["balance"])
                        add_system_log(
                            "INFO",
                            "SYNC",
                            f"Auto-synced {sync_res['inserted']} newly closed MT5 trade(s)",
                        )
                        await asyncio.to_thread(sync_trade_rows, list_trade_logs(limit=sync_res["inserted"]))
                        await asyncio.to_thread(sync_stats_snapshot, stats)
                except Exception as exc:
                    add_system_log("WARN", "SYNC", f"Auto-sync deals warning: {exc}")

                # 2. Scan watchlist symbols through the 8-Gate Gauntlet
                cfg = get_watchdog_config()
                tf = str(cfg.get("timeframe", "M15")).upper()
                risk_pct = float(cfg.get("risk_pct", 15.0))
                auto_propose = bool(cfg.get("auto_propose", True))
                cooldown_sec = max(60, int(cfg.get("cooldown_min", 30)) * 60)

                symbols = symbols_override or get_watchlist()
                open_positions = await asyncio.to_thread(mt5_service.get_open_positions)
                open_symbols = {p["symbol"] for p in open_positions}
                pending_props = list_proposals(status="PENDING", limit=100)
                pending_symbols = {p["symbol"] for p in pending_props}

                for sym in symbols:
                    try:
                        res = await asyncio.to_thread(evaluate_gauntlet, sym, tf, risk_pct)
                        resolved = res["symbol"]
                        compact = {
                            "symbol": resolved,
                            "timeframe": res["timeframe"],
                            "verdict": res["verdict"],
                            "direction": res["direction"],
                            "passed_count": res["passed_count"],
                            "total_gates": res["total_gates"],
                            "evaluated_at": res["evaluated_at"],
                            "bid": res["quote"]["bid"],
                            "sentiment": res["news_summary"]["sentiment"],
                        }
                        self.last_results[resolved] = compact
                        summary_items.append(compact)

                        top_title = res["news"][0]["title"][:75] if res["news"] else "No live news"
                        msg = (
                            f"{resolved} {tf} | {res['verdict']} {res['direction']} | "
                            f"Gauntlet {res['passed_count']}/{res['total_gates']} | "
                            f"Bid {res['quote']['bid']} | News({res['news_summary']['sentiment']}): {top_title}"
                        )
                        log_level = "SIGNAL" if res["verdict"] == "PASS" else "INFO"
                        log_entry = add_system_log(log_level, "WATCHDOG", msg, symbol=resolved, details=compact)
                        await asyncio.to_thread(sync_watchdog_log_row, log_entry)

                        # 3. Auto-queue proposal ONLY if 8/8 hard-fail-free PASS and within cooldown/limits
                        if (
                            auto_propose
                            and res["verdict"] == "PASS"
                            and res["fail_count"] == 0
                            and res.get("proposed_order")
                            and resolved not in open_symbols
                            and resolved not in pending_symbols
                        ):
                            last_prop_ts = self._last_proposed_at.get(resolved, 0.0)
                            if (time.monotonic() - last_prop_ts) >= cooldown_sec:
                                po = res["proposed_order"]
                                proposal = create_proposal(
                                    {
                                        "source": "WATCHDOG",
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
                                            "verdict": res["verdict"],
                                            "passed_count": res["passed_count"],
                                            "total_gates": res["total_gates"],
                                            "gates": res["gates"],
                                        },
                                        "news": res["news"],
                                    }
                                )
                                self._last_proposed_at[resolved] = time.monotonic()
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

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "scanning_now": self.scanning_now,
            "last_scan_at": self.last_scan_at,
            "config": get_watchdog_config(),
            "last_results": list(self.last_results.values()),
        }


watchdog = MarketWatchdog()
