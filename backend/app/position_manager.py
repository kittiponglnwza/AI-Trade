"""Smart Position Manager: Auto Breakeven (+1.0R), Partial Close (50% @ +1.5R), and R-based Trailing Stop."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
from typing import Any

from app.database import (
    add_system_log,
    get_position_manager_config,
    get_position_state,
    list_position_states,
    log_audit,
    prune_position_states,
    upsert_mt5_deals,
    upsert_position_state,
)
from app.discord_notify import notify_discord_position_action
from app.mt5_service import mt5_service
from app.sheets_sync import sync_watchdog_log_row


def compute_initial_risk_distance(
    entry_price: float,
    sl: float,
    side: str,
    point: float = 0.01,
) -> float:
    """Compute 1R price distance from entry and initial SL, with a safe 0.35% fallback if no SL."""
    is_buy = side.upper().startswith("BUY")
    if sl and sl > 0:
        if is_buy and entry_price > sl + point * 3:
            return round(entry_price - sl, 6)
        if not is_buy and sl > entry_price + point * 3:
            return round(sl - entry_price, 6)
    return round(max(entry_price * 0.0035, point * 50), 6)


def evaluate_position_plan(
    pos: dict[str, Any],
    state: dict[str, Any],
    quote: dict[str, Any] | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Pure deterministic evaluation of what Smart Position Manager should do for an open position."""
    side = str(pos["side"]).upper()
    is_buy = side.startswith("BUY")
    entry = float(pos["price_open"])
    current_price = float(
        (quote["bid"] if is_buy else quote["ask"])
        if quote and quote.get("bid", 0) > 0
        else pos["price_current"]
    )
    cur_sl = float(pos.get("sl") or 0.0)
    cur_tp = float(pos.get("tp") or 0.0)
    volume = float(pos.get("volume") or 0.01)

    point = float(quote["point"]) if quote and quote.get("point") else 0.01
    digits = int(quote["digits"]) if quote and quote.get("digits") is not None else 2
    stops_level = float(quote.get("stops_level_price") or 0.0) if quote else 0.0
    vol_min = float(quote.get("volume_min") or 0.01) if quote else 0.01
    vol_step = float(quote.get("volume_step") or 0.01) if quote else 0.01

    risk_distance = float(state.get("risk_distance") or 0.0)
    if risk_distance <= 0:
        risk_distance = compute_initial_risk_distance(entry, cur_sl, side, point)

    profit_dist = (current_price - entry) if is_buy else (entry - current_price)
    current_r = round(profit_dist / risk_distance, 2) if risk_distance > 0 else 0.0

    be_applied = bool(state.get("be_applied", 0))
    if not be_applied and cur_sl > 0:
        if is_buy and cur_sl >= entry:
            be_applied = True
        elif not is_buy and cur_sl <= entry:
            be_applied = True

    partial_applied = bool(state.get("partial_applied", 0))
    trail_count = int(state.get("trail_count", 0))

    new_sl: float | None = None
    sl_reason: str | None = None
    partial_close_lots: float | None = None
    partial_reason: str | None = None

    if not cfg.get("enabled", True):
        return {
            "current_r": current_r,
            "risk_distance": risk_distance,
            "be_applied": be_applied,
            "partial_applied": partial_applied,
            "trail_count": trail_count,
            "new_sl": None,
            "sl_reason": None,
            "partial_close_lots": None,
            "partial_reason": None,
        }

    # 1. Auto Breakeven check (+1.0R default, OR >=60% of TP distance if TP < 1.0R)
    be_trigger_r = float(cfg.get("be_trigger_r", 1.0))
    be_offset_pts = int(cfg.get("be_offset_points", 5))
    tp_dist = abs(cur_tp - entry) if cur_tp > 0 else 0.0
    tp_progress = (profit_dist / tp_dist) if tp_dist > 0 and profit_dist > 0 else 0.0
    be_triggered = (current_r >= be_trigger_r) or (tp_dist > 0 and tp_dist < risk_distance * be_trigger_r and tp_progress >= 0.60)
    if cfg.get("auto_breakeven", True) and be_triggered:
        target_be = round(
            entry + (be_offset_pts * point if is_buy else -be_offset_pts * point),
            digits,
        )
        trigger_note = (
            f"+{current_r:.2f}R ≥ {be_trigger_r:.1f}R"
            if current_r >= be_trigger_r
            else f"{tp_progress * 100:.0f}% ของ TP (+{current_r:.2f}R)"
        )
        if is_buy:
            if cur_sl < target_be - point * 0.5 and (current_price - target_be) > stops_level:
                new_sl = target_be
                sl_reason = f"Auto-Breakeven ({trigger_note}): เลื่อน SL บังทุน -> {target_be}"
                be_applied = True
        else:
            if (cur_sl <= 0 or cur_sl > target_be + point * 0.5) and (target_be - current_price) > stops_level:
                new_sl = target_be
                sl_reason = f"Auto-Breakeven ({trigger_note}): เลื่อน SL บังทุน -> {target_be}"
                be_applied = True

    # 2. Auto Trailing SL check (+1.5R start, 0.8R trail distance default)
    trail_start_r = float(cfg.get("trail_start_r", 1.5))
    trail_dist_r = float(cfg.get("trail_distance_r", 0.8))
    if cfg.get("auto_trailing_sl", True) and current_r >= trail_start_r:
        trail_dist = risk_distance * trail_dist_r
        min_step = max(risk_distance * 0.10, point * 10)
        ref_sl = new_sl if new_sl is not None else cur_sl
        if is_buy:
            cand_sl = round(current_price - trail_dist, digits)
            if cand_sl > entry and cand_sl > ref_sl + min_step and (current_price - cand_sl) > stops_level:
                new_sl = cand_sl
                sl_reason = f"Trailing SL (+{current_r:.2f}R): ลาก SL ล็อกกำไรตามกราฟ -> {cand_sl}"
                be_applied = True
                trail_count += 1
        else:
            cand_sl = round(current_price + trail_dist, digits)
            if cand_sl < entry and (ref_sl <= 0 or cand_sl < ref_sl - min_step) and (cand_sl - current_price) > stops_level:
                new_sl = cand_sl
                sl_reason = f"Trailing SL (+{current_r:.2f}R): ลาก SL ล็อกกำไรตามกราฟ -> {cand_sl}"
                be_applied = True
                trail_count += 1

    # 3. Auto Partial Close check (50% @ +1.5R default)
    partial_trigger_r = float(cfg.get("partial_trigger_r", 1.5))
    partial_pct = float(cfg.get("partial_close_pct", 50.0))
    if cfg.get("auto_partial_tp", True) and not partial_applied and current_r >= partial_trigger_r:
        if volume >= vol_min * 2 - 1e-9:
            raw_close = volume * (partial_pct / 100.0)
            steps = math.floor((raw_close + 1e-9) / vol_step)
            close_vol = round(max(vol_min, min(steps * vol_step, volume - vol_min)), 2)
            if close_vol >= vol_min and (volume - close_vol) >= vol_min - 1e-9:
                partial_close_lots = close_vol
                partial_reason = (
                    f"Partial TP (+{current_r:.2f}R ≥ {partial_trigger_r:.1f}R): "
                    f"แบ่งปิดทำกำไร {close_vol:.2f} Lot ({partial_pct:.0f}%)"
                )
        else:
            # Minimum lot size (0.01): cannot split volume further, mark partial_applied so it doesn't re-check
            partial_applied = True

    return {
        "current_r": current_r,
        "risk_distance": risk_distance,
        "be_applied": be_applied,
        "partial_applied": partial_applied,
        "trail_count": trail_count,
        "new_sl": new_sl,
        "cur_tp": cur_tp,
        "sl_reason": sl_reason,
        "partial_close_lots": partial_close_lots,
        "partial_reason": partial_reason,
    }


def enrich_open_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach live R-multiple and Smart Position Manager state badges to open positions."""
    if not positions:
        return []
    states = list_position_states()
    out: list[dict[str, Any]] = []
    for pos in positions:
        ticket = int(pos["ticket"])
        st = states.get(ticket)
        entry = float(pos["price_open"])
        cur = float(pos["price_current"])
        sl = float(pos.get("sl") or 0.0)
        side = str(pos["side"]).upper()
        is_buy = side.startswith("BUY")

        risk_dist = float(st["risk_distance"]) if st and st.get("risk_distance", 0) > 0 else compute_initial_risk_distance(entry, sl, side)
        profit_dist = (cur - entry) if is_buy else (entry - cur)
        current_r = round(profit_dist / risk_dist, 2) if risk_dist > 0 else 0.0

        be_applied = bool(st.get("be_applied", 0)) if st else False
        if not be_applied and sl > 0:
            if (is_buy and sl >= entry) or (not is_buy and sl <= entry):
                be_applied = True

        out.append(
            {
                **pos,
                "current_r": current_r,
                "risk_distance": risk_dist,
                "be_applied": be_applied,
                "partial_applied": bool(st.get("partial_applied", 0)) if st else False,
                "trail_count": int(st.get("trail_count", 0)) if st else 0,
                "last_action": str(st.get("last_action", "")) if st else "",
            }
        )
    return out


class SmartPositionManager:
    """Fast background loop monitoring open MT5 positions for Breakeven, Partial TP, and Trailing SL."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self.last_run_at: str | None = None
        self.actions_taken_count: int = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop(), name="smart-position-manager")

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
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=4.0)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            cfg = get_position_manager_config()
            poll_sec = max(2, int(cfg.get("poll_interval_sec", 5)))
            if cfg.get("enabled", True):
                try:
                    await self.run_cycle()
                except Exception as exc:
                    add_system_log("WARN", "POS_MGR", f"Position manager cycle warning: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=float(poll_sec))
            except asyncio.TimeoutError:
                pass

    async def run_cycle(self) -> dict[str, Any]:
        """Inspect all open MT5 positions and apply Auto-BE, Partial Close, and Trailing SL."""
        async with self._lock:
            connected = await asyncio.to_thread(mt5_service.is_connected)
            if not connected:
                return {"checked": 0, "actions": [], "mt5_connected": False}

            positions = await asyncio.to_thread(mt5_service.get_open_positions)
            active_tickets = {int(p["ticket"]) for p in positions}
            prune_position_states(active_tickets)

            cfg = get_position_manager_config()
            actions_taken: list[dict[str, Any]] = []

            for pos in positions:
                ticket = int(pos["ticket"])
                symbol = str(pos["symbol"])
                side = str(pos["side"])
                try:
                    quote = await asyncio.to_thread(mt5_service.get_quote, symbol)
                except Exception:
                    quote = None

                point = float(quote["point"]) if quote and quote.get("point") else 0.01
                existing_state = get_position_state(ticket)
                if existing_state is None:
                    risk_dist = compute_initial_risk_distance(
                        float(pos["price_open"]),
                        float(pos.get("sl") or 0.0),
                        side,
                        point,
                    )
                    existing_state = upsert_position_state(
                        {
                            "ticket": ticket,
                            "symbol": symbol,
                            "side": side,
                            "initial_volume": float(pos["volume"]),
                            "entry_price": float(pos["price_open"]),
                            "initial_sl": float(pos.get("sl") or 0.0),
                            "initial_tp": float(pos.get("tp") or 0.0),
                            "risk_distance": risk_dist,
                            "be_applied": 0,
                            "partial_applied": 0,
                            "trail_count": 0,
                            "last_action": "Monitoring",
                        }
                    )

                plan = evaluate_position_plan(pos, existing_state, quote, cfg)
                last_action = existing_state.get("last_action", "")
                be_applied = plan["be_applied"]
                partial_applied = plan["partial_applied"]
                trail_count = plan["trail_count"]

                # Execute SL modification (Auto-BE or Trailing SL)
                if plan["new_sl"] is not None:
                    try:
                        mod_res = await asyncio.to_thread(
                            mt5_service.modify_position,
                            ticket,
                            plan["new_sl"],
                            float(pos.get("tp") or 0.0) if float(pos.get("tp") or 0.0) > 0 else None,
                            False,
                        )
                        if mod_res.get("success"):
                            last_action = str(plan["sl_reason"])
                            self.actions_taken_count += 1
                            act_record = {
                                "ticket": ticket,
                                "symbol": symbol,
                                "type": "MODIFY_SL",
                                "new_sl": plan["new_sl"],
                                "current_r": plan["current_r"],
                                "reason": last_action,
                            }
                            actions_taken.append(act_record)
                            log_entry = add_system_log(
                                "SIGNAL",
                                "POS_MGR",
                                f"#{ticket} {side} {symbol} | {last_action}",
                                symbol=symbol,
                                details=act_record,
                            )
                            log_audit(
                                event_type="POS_MGR_SL_MOVED",
                                actor="POS_MGR",
                                summary=f"#{ticket} {symbol}: {last_action}",
                                payload=act_record,
                            )
                            await asyncio.to_thread(sync_watchdog_log_row, log_entry)
                            await asyncio.to_thread(
                                notify_discord_position_action,
                                ticket,
                                symbol,
                                side,
                                "ขยับ SL บังทุน / ล็อกกำไร",
                                last_action,
                            )
                    except Exception as exc:
                        add_system_log("WARN", "POS_MGR", f"#{ticket} SL update skipped: {exc}", symbol=symbol)

                # Execute Partial Close
                if plan["partial_close_lots"] is not None:
                    try:
                        close_res = await asyncio.to_thread(
                            mt5_service.close_position,
                            ticket,
                            plan["partial_close_lots"],
                            30,
                            False,
                        )
                        if close_res.get("success"):
                            partial_applied = True
                            last_action = str(plan["partial_reason"])
                            self.actions_taken_count += 1
                            act_record = {
                                "ticket": ticket,
                                "symbol": symbol,
                                "type": "PARTIAL_CLOSE",
                                "closed_lots": plan["partial_close_lots"],
                                "current_r": plan["current_r"],
                                "reason": last_action,
                            }
                            actions_taken.append(act_record)
                            deals = await asyncio.to_thread(mt5_service.fetch_closed_deals, 7)
                            upsert_mt5_deals(deals)
                            log_entry = add_system_log(
                                "SIGNAL",
                                "POS_MGR",
                                f"#{ticket} {side} {symbol} | {last_action}",
                                symbol=symbol,
                                details=act_record,
                            )
                            log_audit(
                                event_type="POS_MGR_PARTIAL_CLOSE",
                                actor="POS_MGR",
                                summary=f"#{ticket} {symbol}: {last_action}",
                                payload=act_record,
                            )
                            await asyncio.to_thread(sync_watchdog_log_row, log_entry)
                            await asyncio.to_thread(
                                notify_discord_position_action,
                                ticket,
                                symbol,
                                side,
                                "แบ่งปิดทำกำไร (Partial TP)",
                                last_action,
                            )
                    except Exception as exc:
                        add_system_log("WARN", "POS_MGR", f"#{ticket} Partial close skipped: {exc}", symbol=symbol)

                upsert_position_state(
                    {
                        **existing_state,
                        "risk_distance": plan["risk_distance"],
                        "be_applied": int(be_applied),
                        "partial_applied": int(partial_applied),
                        "trail_count": trail_count,
                        "last_action": last_action,
                    }
                )

            self.last_run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            return {
                "checked": len(positions),
                "actions": actions_taken,
                "last_run_at": self.last_run_at,
                "mt5_connected": True,
            }

    async def move_position_to_breakeven(self, ticket: int) -> dict[str, Any]:
        """Manual 1-click button to lock an open position's SL at Breakeven (+ offset points)."""
        positions = await asyncio.to_thread(mt5_service.get_open_positions)
        target = next((p for p in positions if int(p["ticket"]) == int(ticket)), None)
        if target is None:
            raise ValueError(f"ไม่พบออเดอร์ #{ticket} ที่เปิดอยู่ใน MT5")

        symbol = str(target["symbol"])
        side = str(target["side"]).upper()
        is_buy = side.startswith("BUY")
        entry = float(target["price_open"])
        quote = await asyncio.to_thread(mt5_service.get_quote, symbol)
        point = float(quote.get("point") or 0.01)
        digits = int(quote.get("digits") or 2)
        cfg = get_position_manager_config()
        offset_pts = int(cfg.get("be_offset_points", 5))
        be_sl = round(entry + (offset_pts * point if is_buy else -offset_pts * point), digits)

        cur_price = float(quote["bid"] if is_buy else quote["ask"])
        if is_buy and cur_price <= be_sl:
            raise ValueError(f"ราคาปัจจุบัน ({cur_price}) ยังต่ำกว่าจุดบังทุน ({be_sl}) — ต้องรอให้ไม้นี้เป็นบวกก่อน")
        if not is_buy and cur_price >= be_sl:
            raise ValueError(f"ราคาปัจจุบัน ({cur_price}) ยังสูงกว่าจุดบังทุน ({be_sl}) — ต้องรอให้ไม้นี้เป็นบวกก่อน")

        cur_tp = float(target.get("tp") or 0.0)
        res = await asyncio.to_thread(
            mt5_service.modify_position,
            int(ticket),
            be_sl,
            cur_tp if cur_tp > 0 else None,
            False,
        )
        existing_state = get_position_state(int(ticket)) or {
            "ticket": int(ticket),
            "symbol": symbol,
            "side": side,
            "initial_volume": float(target["volume"]),
            "entry_price": entry,
            "initial_sl": float(target.get("sl") or 0.0),
            "initial_tp": cur_tp,
            "risk_distance": compute_initial_risk_distance(entry, float(target.get("sl") or 0.0), side, point),
            "partial_applied": 0,
            "trail_count": 0,
        }
        upsert_position_state(
            {
                **existing_state,
                "be_applied": 1,
                "last_action": f"Manual 1-Click BE -> {be_sl}",
            }
        )
        add_system_log("SIGNAL", "POS_MGR", f"#{ticket} {side} {symbol} | เลื่อน SL บังทุน (1-Click BE) -> {be_sl}", symbol=symbol)
        return res

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "last_run_at": self.last_run_at,
            "actions_taken_count": self.actions_taken_count,
            "config": get_position_manager_config(),
        }


position_manager = SmartPositionManager()
