"""Smart Day-Trader Skill Engine adapted from Jakeschincariol/day-trader-skill.

Integrates 4 institutional day-trading modules on live MetaTrader 5 data:
1. Multi-Setup Chart Scanner (/trader-scanner): ORB, Bull/Bear Flag, VWAP/EMA20 Reclaim, 20-Bar Breakout, RSI Bounce.
2. Closed-Bar Entry Timer (/trader-entry): Triggers strictly on completed bars, never mid-bar pokes.
3. Setup-Aware Exit Planner (/trader-exit): Opening-Range Midpoint (or-mid), Flag/Swing low/high, or ATR stops.
4. 10,000-Session Time Machine (/trader-timemachine): Time-of-day Monte Carlo replay before risking a dollar.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import numpy as np
import pandas as pd

from app.mt5_service import mt5_service

TF_SECONDS_MAP: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


def compute_opening_range_and_vwap(
    candles: list[dict[str, Any]],
    tf: str = "M15",
    or_bars_count: int = 2,
    digits: int = 2,
) -> dict[str, Any]:
    """Compute current session Opening Range (OR High, OR Low, OR Midpoint) and Session VWAP."""
    if len(candles) < 10:
        return {
            "or_high": 0.0,
            "or_low": 0.0,
            "or_mid": 0.0,
            "or_width": 0.0,
            "session_vwap": 0.0,
            "vol_ratio_x": 1.0,
            "session_bars": 0,
        }

    # Group bars belonging to the latest trading day (or latest NY/London anchor session)
    last_ts = int(candles[-1]["time"])
    last_day = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    session_bars: list[dict[str, Any]] = []
    for c in reversed(candles):
        d_str = datetime.fromtimestamp(int(c["time"]), tz=timezone.utc).strftime("%Y-%m-%d")
        if d_str == last_day:
            session_bars.append(c)
        else:
            break
    session_bars.reverse()

    if len(session_bars) < max(3, or_bars_count + 1):
        # Fallback to most recent 16 bars if a new UTC day just started
        session_bars = candles[-min(20, len(candles)) :]

    k = min(max(1, or_bars_count), max(1, len(session_bars) - 1))
    or_slice = session_bars[:k]
    or_high = round(max(float(c["high"]) for c in or_slice), digits)
    or_low = round(min(float(c["low"]) for c in or_slice), digits)
    or_mid = round((or_high + or_low) / 2.0, digits)
    or_width = round(max(0.0, or_high - or_low), digits)

    # Session VWAP
    tp_vol_sum = 0.0
    vol_sum = 0.0
    for c in session_bars:
        typ = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0
        v = max(1.0, float(c.get("volume") or 1.0))
        tp_vol_sum += typ * v
        vol_sum += v
    session_vwap = round(tp_vol_sum / vol_sum, digits) if vol_sum > 0 else round(float(candles[-1]["close"]), digits)

    # Completed bar volume vs 20-bar average volume
    closed_bar = candles[-2] if len(candles) >= 2 else candles[-1]
    recent_vols = [max(1.0, float(c.get("volume") or 1.0)) for c in candles[-22:-2]] or [1.0]
    avg_vol = sum(recent_vols) / len(recent_vols)
    closed_vol = max(1.0, float(closed_bar.get("volume") or 1.0))
    vol_ratio_x = round(closed_vol / max(1.0, avg_vol), 2)

    return {
        "or_high": or_high,
        "or_low": or_low,
        "or_mid": or_mid,
        "or_width": or_width,
        "session_vwap": session_vwap,
        "vol_ratio_x": vol_ratio_x,
        "session_bars": len(session_bars),
    }


def detect_day_trader_setups(
    candles: list[dict[str, Any]],
    direction_hint: str = "WAIT",
    tf: str = "M15",
    digits: int = 2,
) -> dict[str, Any]:
    """Run /trader-scanner + /trader-entry on completed bars (never mid-bar pokes)."""
    if len(candles) < 30:
        return {
            "active_setup": "NONE",
            "active_setup_label": "Insufficient Bars",
            "entry_timer_state": "WAITING",
            "entry_timer_detail": "Not enough historical bars",
            "recommended_stop_rule": "atr",
            "recommended_stop_price": None,
            "setup_score_bonus_pct": 0.0,
            "opening_range": {},
            "setups": [],
        }

    tf_u = tf.upper()
    or_bars_count = 3 if tf_u in ("M1", "M5") else (2 if tf_u == "M15" else 1)
    or_info = compute_opening_range_and_vwap(candles, tf_u, or_bars_count=or_bars_count, digits=digits)

    # CRITICAL RULE FROM /trader-entry:
    # "A price that pokes above the high in the middle of a bar is not an entry. A bar that CLOSES above it is."
    forming_bar = candles[-1]
    closed_bar = candles[-2]
    prev_bar = candles[-3]

    c_close = float(closed_bar["close"])
    c_open = float(closed_bar["open"])
    c_high = float(closed_bar["high"])
    c_low = float(closed_bar["low"])
    p_close = float(prev_bar["close"])
    f_high = float(forming_bar["high"])
    f_low = float(forming_bar["low"])

    atr = float(closed_bar.get("atr14") or 0.0)
    if atr <= 0:
        atr = max(abs(c_high - c_low), c_close * 0.003)

    ema20 = float(closed_bar.get("ema20") or c_close)
    ema50 = float(closed_bar.get("ema50") or c_close)
    rsi_closed = float(closed_bar.get("rsi14") or 50.0)
    rsi_prev = float(prev_bar.get("rsi14") or 50.0)

    or_high = or_info["or_high"]
    or_low = or_info["or_low"]
    or_mid = or_info["or_mid"]
    vwap = or_info["session_vwap"]
    vol_x = or_info["vol_ratio_x"]

    # 20-bar prior window (excluding closed_bar and forming_bar)
    prior_20 = candles[-22:-2]
    hi_20 = round(max(float(c["high"]) for c in prior_20), digits)
    lo_20 = round(min(float(c["low"]) for c in prior_20), digits)

    setups: list[dict[str, Any]] = []

    # 1. Opening-Range Breakout (ORB)
    orb_buy = or_high > 0 and c_close > or_high and c_close > c_open and or_info["session_bars"] > or_bars_count
    orb_sell = or_low > 0 and c_close < or_low and c_close < c_open and or_info["session_bars"] > or_bars_count
    orb_poke_buy = not orb_buy and or_high > 0 and f_high > or_high
    orb_poke_sell = not orb_sell and or_low > 0 and f_low < or_low

    if orb_buy:
        orb_status, orb_side = "TRIGGERED", "BUY"
        orb_detail = f"Closed bar broke above OR High ({or_high:.{digits}f}) @ {c_close:.{digits}f} · OR-Mid SL {or_mid:.{digits}f} · Vol {vol_x}x"
    elif orb_sell:
        orb_status, orb_side = "TRIGGERED", "SELL"
        orb_detail = f"Closed bar broke below OR Low ({or_low:.{digits}f}) @ {c_close:.{digits}f} · OR-Mid SL {or_mid:.{digits}f} · Vol {vol_x}x"
    elif orb_poke_buy or orb_poke_sell:
        orb_status, orb_side = "FORMING_POKE", ("BUY" if orb_poke_buy else "SELL")
        orb_detail = f"Forming bar poked OR boundary ({or_low:.{digits}f}–{or_high:.{digits}f}) — waiting for bar close (/trader-entry rule)."
    else:
        orb_status, orb_side = "WAIT", "NONE"
        orb_detail = f"Inside Opening Range ({or_low:.{digits}f} – {or_high:.{digits}f}, Mid {or_mid:.{digits}f})."

    setups.append(
        {
            "id": "ORB_BREAKOUT",
            "label": "Opening-Range Breakout (ORB)",
            "status": orb_status,
            "side": orb_side,
            "stop_rule": "or-mid",
            "stop_price": or_mid,
            "detail": orb_detail,
        }
    )

    # 2. 20-Bar Closing High/Low Breakout
    b20_buy = c_close > hi_20 and c_close > c_open
    b20_sell = c_close < lo_20 and c_close < c_open
    b20_poke = not (b20_buy or b20_sell) and (f_high > hi_20 or f_low < lo_20)
    if b20_buy:
        b20_status, b20_side = "TRIGGERED", "BUY"
        b20_detail = f"Closed bar broke 20-bar high ({hi_20:.{digits}f}) @ {c_close:.{digits}f} (Vol {vol_x}x)."
    elif b20_sell:
        b20_status, b20_side = "TRIGGERED", "SELL"
        b20_detail = f"Closed bar broke 20-bar low ({lo_20:.{digits}f}) @ {c_close:.{digits}f} (Vol {vol_x}x)."
    elif b20_poke:
        b20_status, b20_side = "FORMING_POKE", ("BUY" if f_high > hi_20 else "SELL")
        b20_detail = f"Mid-bar poke beyond 20-bar range ({lo_20:.{digits}f}–{hi_20:.{digits}f}) — wait for candle close."
    else:
        b20_status, b20_side = "WAIT", "NONE"
        b20_detail = f"Trading inside 20-bar range ({lo_20:.{digits}f} – {hi_20:.{digits}f})."

    setups.append(
        {
            "id": "BAR20_BREAKOUT",
            "label": "20-Bar Closing Breakout",
            "status": b20_status,
            "side": b20_side,
            "stop_rule": "swing",
            "stop_price": round(min(c_low, float(prev_bar["low"])) - 0.25 * atr, digits)
            if b20_buy
            else (round(max(c_high, float(prev_bar["high"])) + 0.25 * atr, digits) if b20_sell else None),
            "detail": b20_detail,
        }
    )

    # 3. Bull / Bear Flag Continuation (Impulse pole + tight 4-bar flag + breakout close)
    pole_bars = candles[-15:-6]
    flag_bars = candles[-6:-2]
    pole_move = float(pole_bars[-1]["close"]) - float(pole_bars[0]["open"]) if len(pole_bars) >= 4 else 0.0
    flag_hi = max(float(c["high"]) for c in flag_bars) if flag_bars else c_high
    flag_lo = min(float(c["low"]) for c in flag_bars) if flag_bars else c_low
    flag_rng = flag_hi - flag_lo

    bull_flag = pole_move >= 1.6 * atr and flag_rng <= 1.8 * atr and c_close > flag_hi and c_close > c_open
    bear_flag = pole_move <= -1.6 * atr and flag_rng <= 1.8 * atr and c_close < flag_lo and c_close < c_open

    if bull_flag:
        fl_status, fl_side = "TRIGGERED", "BUY"
        fl_stop = round(flag_lo - 0.2 * atr, digits)
        fl_detail = f"Bull Flag breakout above {flag_hi:.{digits}f} after +{pole_move / atr:.1f}xATR impulse (Flag SL {fl_stop:.{digits}f})."
    elif bear_flag:
        fl_status, fl_side = "TRIGGERED", "SELL"
        fl_stop = round(flag_hi + 0.2 * atr, digits)
        fl_detail = f"Bear Flag breakdown below {flag_lo:.{digits}f} after {pole_move / atr:.1f}xATR impulse (Flag SL {fl_stop:.{digits}f})."
    else:
        fl_status, fl_side, fl_stop = "WAIT", "NONE", None
        fl_detail = f"No tight flag breakout (4-bar range {flag_rng / atr:.1f}xATR)."

    setups.append(
        {
            "id": "FLAG_CONTINUATION",
            "label": "Bull / Bear Flag Breakout",
            "status": fl_status,
            "side": fl_side,
            "stop_rule": "flag-bound",
            "stop_price": fl_stop,
            "detail": fl_detail,
        }
    )

    # 4. Session VWAP + EMA20 Reclaim
    reclaim_buy = (
        c_close > ema20
        and c_close >= vwap
        and ema20 >= ema50 * 0.998
        and (p_close <= ema20 or c_low <= ema20)
        and c_close > c_open
    )
    reclaim_sell = (
        c_close < ema20
        and c_close <= vwap
        and ema20 <= ema50 * 1.002
        and (p_close >= ema20 or c_high >= ema20)
        and c_close < c_open
    )
    if reclaim_buy:
        rc_status, rc_side = "TRIGGERED", "BUY"
        rc_stop = round(min(c_low, float(prev_bar["low"])) - 0.3 * atr, digits)
        rc_detail = f"Reclaimed EMA20 ({ema20:.{digits}f}) & Session VWAP ({vwap:.{digits}f}) on closed bar."
    elif reclaim_sell:
        rc_status, rc_side = "TRIGGERED", "SELL"
        rc_stop = round(max(c_high, float(prev_bar["high"])) + 0.3 * atr, digits)
        rc_detail = f"Rejected below EMA20 ({ema20:.{digits}f}) & Session VWAP ({vwap:.{digits}f}) on closed bar."
    else:
        rc_status, rc_side, rc_stop = "WAIT", "NONE", None
        rc_detail = f"Close {c_close:.{digits}f} vs EMA20 {ema20:.{digits}f} / VWAP {vwap:.{digits}f}."

    setups.append(
        {
            "id": "VWAP_EMA20_RECLAIM",
            "label": "VWAP & EMA20 Reclaim",
            "status": rc_status,
            "side": rc_side,
            "stop_rule": "swing",
            "stop_price": rc_stop,
            "detail": rc_detail,
        }
    )

    # 5. Oversold / Overbought Reversal Bounce
    bounce_buy = (rsi_prev < 34.0 or rsi_closed < 36.0) and c_close > c_open and c_close > p_close
    bounce_sell = (rsi_prev > 66.0 or rsi_closed > 64.0) and c_close < c_open and c_close < p_close
    if bounce_buy:
        bn_status, bn_side = "TRIGGERED", "BUY"
        bn_stop = round(min(c_low, float(prev_bar["low"])) - 0.3 * atr, digits)
        bn_detail = f"Oversold RSI bounce ({rsi_prev:.1f} -> {rsi_closed:.1f}) with bullish close."
    elif bounce_sell:
        bn_status, bn_side = "TRIGGERED", "SELL"
        bn_stop = round(max(c_high, float(prev_bar["high"])) + 0.3 * atr, digits)
        bn_detail = f"Overbought RSI rejection ({rsi_prev:.1f} -> {rsi_closed:.1f}) with bearish close."
    else:
        bn_status, bn_side, bn_stop = "WAIT", "NONE", None
        bn_detail = f"RSI {rsi_closed:.1f} is neutral (no extreme reversal bounce)."

    setups.append(
        {
            "id": "EXTREME_RSI_BOUNCE",
            "label": "Oversold / Overbought Bounce",
            "status": bn_status,
            "side": bn_side,
            "stop_rule": "swing",
            "stop_price": bn_stop,
            "detail": bn_detail,
        }
    )

    # Select primary setup aligned with direction_hint (or any triggered setup if direction_hint == WAIT)
    triggered = [
        s for s in setups if s["status"] == "TRIGGERED" and (direction_hint == "WAIT" or s["side"] == direction_hint)
    ]
    forming_pokes = [
        s for s in setups if s["status"] == "FORMING_POKE" and (direction_hint == "WAIT" or s["side"] == direction_hint)
    ]

    if triggered:
        best = triggered[0]
        timer_state = "TRIGGERED_ON_CLOSED_BAR"
        timer_detail = f"{best['label']} confirmed on closed bar ({len(triggered)} setup(s) active · Vol {vol_x}x)."
        # Bonus confidence when multiple setups + volume expansion confirm on a closed bar
        bonus = min(6.0, 2.5 * len(triggered) + (1.5 if vol_x >= 1.25 else 0.0))
        return {
            "active_setup": best["id"],
            "active_setup_label": best["label"],
            "active_setup_side": best["side"],
            "triggered_count": len(triggered),
            "entry_timer_state": timer_state,
            "entry_timer_detail": timer_detail,
            "recommended_stop_rule": best["stop_rule"],
            "recommended_stop_price": best["stop_price"],
            "setup_score_bonus_pct": round(bonus, 2),
            "opening_range": or_info,
            "setups": setups,
        }

    if forming_pokes:
        poke = forming_pokes[0]
        return {
            "active_setup": poke["id"],
            "active_setup_label": f"{poke['label']} (Forming Poke — Wait Close)",
            "active_setup_side": poke["side"],
            "triggered_count": 0,
            "entry_timer_state": "FORMING_BAR_POKE_WAIT",
            "entry_timer_detail": poke["detail"],
            "recommended_stop_rule": poke["stop_rule"],
            "recommended_stop_price": poke["stop_price"],
            "setup_score_bonus_pct": -3.0,
            "opening_range": or_info,
            "setups": setups,
        }

    return {
        "active_setup": "NONE",
        "active_setup_label": "No Closed-Bar Breakout/Reclaim Yet",
        "active_setup_side": "NONE",
        "triggered_count": 0,
        "entry_timer_state": "WAITING",
        "entry_timer_detail": "Waiting for a completed candle to close beyond Opening Range, Flag, or VWAP/EMA20.",
        "recommended_stop_rule": "atr",
        "recommended_stop_price": None,
        "setup_score_bonus_pct": 0.0,
        "opening_range": or_info,
        "setups": setups,
    }


def run_time_machine_simulation(
    candles: list[dict[str, Any]],
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    tf: str = "M15",
    horizon_bars: int = 24,
    replays: int = 10000,
    seed: int = 19,
    window: int = 2,
    digits: int = 2,
) -> dict[str, Any]:
    """Run 10,000 time-of-day Monte Carlo replays (/trader-timemachine) using the symbol's own MT5 bars.

    Vectorized in NumPy to finish 10,000 replays in <25ms while strictly checking Stop Loss before Take Profit.
    """
    is_buy = str(direction).upper().startswith("BUY")
    risk_dist = abs(entry_price - sl_price)
    reward_dist = abs(tp_price - entry_price)
    if risk_dist <= 0 or reward_dist <= 0 or len(candles) < 80:
        return {
            "replays": 0,
            "horizon_bars": horizon_bars,
            "target_first_pct": 0.0,
            "stop_first_pct": 0.0,
            "neither_pct": 100.0,
            "resolved_win_rate_pct": 0.0,
            "breakeven_win_rate_pct": 50.0,
            "edge_vs_breakeven_pp": 0.0,
            "expected_r": 0.0,
            "verdict": "INSUFFICIENT_DATA",
            "verdict_th": "ยังไม่มีจุด SL/TP หรือข้อมูลแท่งเทียนไม่พอจำลอง",
            "price_percentiles": {},
            "fan_chart": [],
        }

    target_r = round(reward_dist / risk_dist, 2)
    breakeven_wr = round(100.0 / (1.0 + target_r), 2)

    tf_sec = TF_SECONDS_MAP.get(tf.upper(), 900)
    slots_per_day = max(1, 86400 // tf_sec)

    # Exclude the currently forming last bar
    hist = candles[:-1]
    n_hist = len(hist)
    closes = np.array([float(c["close"]) for c in hist], dtype=np.float64)
    opens = np.array([float(c["open"]) for c in hist], dtype=np.float64)
    highs = np.array([float(c["high"]) for c in hist], dtype=np.float64)
    lows = np.array([float(c["low"]) for c in hist], dtype=np.float64)
    times = np.array([int(c["time"]) for c in hist], dtype=np.int64)

    # Bar ratios relative to previous bar's close: (open, high, low, close) / prev_close
    prev_closes = closes[:-1]
    valid_mask = prev_closes > 0
    r_open = opens[1:][valid_mask] / prev_closes[valid_mask]
    r_high = highs[1:][valid_mask] / prev_closes[valid_mask]
    r_low = lows[1:][valid_mask] / prev_closes[valid_mask]
    r_close = closes[1:][valid_mask] / prev_closes[valid_mask]
    bar_slots = ((times[1:][valid_mask] % 86400) // tf_sec).astype(np.int32)

    # Clamp extreme data glitches (>15% single-bar spike)
    r_high = np.clip(r_high, 0.85, 1.15)
    r_low = np.clip(r_low, 0.85, 1.15)
    r_close = np.clip(r_close, 0.85, 1.15)

    # Build time-of-day slot index pools so each simulated step draws from the same time-of-day (+/- window)
    start_slot = int(((int(candles[-1]["time"]) % 86400) // tf_sec))
    all_indices = np.arange(len(r_close), dtype=np.int32)
    slot_pools: list[np.ndarray] = []
    for step in range(horizon_bars):
        center_slot = (start_slot + step) % slots_per_day
        # Circular slot distance on [0, slots_per_day)
        diff = np.abs(bar_slots - center_slot)
        circ_diff = np.minimum(diff, slots_per_day - diff)
        pool = all_indices[circ_diff <= window]
        if len(pool) < 15:
            pool = all_indices
        slot_pools.append(pool)

    rng = np.random.default_rng(seed)
    n_rep = min(20000, max(500, int(replays)))
    cur_prices = np.full(n_rep, float(entry_price), dtype=np.float64)
    # 0 = still open, 1 = hit target first, -1 = hit stop first
    outcome = np.zeros(n_rep, dtype=np.int8)

    fan_chart: list[dict[str, Any]] = []
    for step in range(horizon_bars):
        pool = slot_pools[step]
        picked_idx = pool[rng.integers(0, len(pool), size=n_rep)]
        step_hi = cur_prices * r_high[picked_idx]
        step_lo = cur_prices * r_low[picked_idx]
        step_cl = cur_prices * r_close[picked_idx]

        active = outcome == 0
        if is_buy:
            # Conservative rule from timemachine.py: check Stop BEFORE Target in every bar
            hit_stop = active & (step_lo <= sl_price)
            outcome[hit_stop] = -1
            still_active = outcome == 0
            hit_target = still_active & (step_hi >= tp_price)
            outcome[hit_target] = 1
        else:
            hit_stop = active & (step_hi >= sl_price)
            outcome[hit_stop] = -1
            still_active = outcome == 0
            hit_target = still_active & (step_lo <= tp_price)
            outcome[hit_target] = 1

        cur_prices = step_cl
        if step % max(1, horizon_bars // 8) == 0 or step == horizon_bars - 1:
            pcts = np.percentile(cur_prices, [10, 25, 50, 75, 90])
            fan_chart.append(
                {
                    "bar": step + 1,
                    "p10": round(float(pcts[0]), digits),
                    "p25": round(float(pcts[1]), digits),
                    "p50": round(float(pcts[2]), digits),
                    "p75": round(float(pcts[3]), digits),
                    "p90": round(float(pcts[4]), digits),
                }
            )

    target_cnt = int(np.sum(outcome == 1))
    stop_cnt = int(np.sum(outcome == -1))
    neither_cnt = int(np.sum(outcome == 0))

    target_pct = round((target_cnt / n_rep) * 100.0, 2)
    stop_pct = round((stop_cnt / n_rep) * 100.0, 2)
    neither_pct = round((neither_cnt / n_rep) * 100.0, 2)

    resolved_total = target_cnt + stop_cnt
    resolved_wr = round((target_cnt / resolved_total) * 100.0, 2) if resolved_total > 0 else 50.0
    edge_pp = round(resolved_wr - breakeven_wr, 2)

    # Compute R outcome for each replay (including mark-to-market R at horizon close when neither hit)
    r_outcomes = np.empty(n_rep, dtype=np.float64)
    r_outcomes[outcome == 1] = target_r
    r_outcomes[outcome == -1] = -1.0
    neither_mask = outcome == 0
    if np.any(neither_mask):
        if is_buy:
            r_outcomes[neither_mask] = (cur_prices[neither_mask] - entry_price) / risk_dist
        else:
            r_outcomes[neither_mask] = (entry_price - cur_prices[neither_mask]) / risk_dist

    expected_r = round(float(np.mean(r_outcomes)), 2)
    green_cnt = int(np.sum(r_outcomes > 0))
    green_pct = round((green_cnt / n_rep) * 100.0, 2)

    end_pcts = np.percentile(cur_prices, [5, 25, 50, 75, 95])
    price_percentiles = {
        "p5": round(float(end_pcts[0]), digits),
        "p25": round(float(end_pcts[1]), digits),
        "p50_median": round(float(end_pcts[2]), digits),
        "p75": round(float(end_pcts[3]), digits),
        "p95": round(float(end_pcts[4]), digits),
    }

    # Verdict classification matching timemachine.py
    if edge_pp >= 15.0 and expected_r >= 0.15:
        verdict = "STRONGLY_TARGET"
        verdict_th = f"ได้เปรียบฝั่ง TP ชัดเจน (+{edge_pp:.1f}% เหนือจุดคุ้มทุน · EV {expected_r:+.2f}R)"
        tm_bonus = 6.0
    elif edge_pp >= 5.0 and expected_r > 0.0:
        verdict = "LEANS_TARGET"
        verdict_th = f"ได้เปรียบฝั่ง TP (+{edge_pp:.1f}% เหนือจุดคุ้มทุน · EV {expected_r:+.2f}R)"
        tm_bonus = 3.0
    elif abs(edge_pp) < 5.0:
        verdict = "COIN_FLIP"
        verdict_th = f"ใกล้เคียงโยนหัวก้อย (Coin Flip: ห่างจุดคุ้มทุน {edge_pp:+.1f}% · EV {expected_r:+.2f}R)"
        tm_bonus = -3.0 if expected_r <= 0 else 0.0
    else:
        verdict = "LEANS_STOP"
        verdict_th = f"เสียเปรียบ เสี่ยงโดน SL มากกว่า ({edge_pp:+.1f}% ต่ำกว่าจุดคุ้มทุน · EV {expected_r:+.2f}R)"
        tm_bonus = -8.0

    return {
        "replays": n_rep,
        "seed": seed,
        "horizon_bars": horizon_bars,
        "target_r": target_r,
        "target_first_pct": target_pct,
        "stop_first_pct": stop_pct,
        "neither_pct": neither_pct,
        "green_at_close_pct": green_pct,
        "resolved_win_rate_pct": resolved_wr,
        "breakeven_win_rate_pct": breakeven_wr,
        "edge_vs_breakeven_pp": edge_pp,
        "expected_r": expected_r,
        "verdict": verdict,
        "verdict_th": verdict_th,
        "tm_confidence_bonus_pct": tm_bonus,
        "price_percentiles": price_percentiles,
        "fan_chart": fan_chart,
    }


def scan_watchlist_setups(
    symbols: list[str],
    tf: str = "M15",
) -> list[dict[str, Any]]:
    """Run /trader-scanner across a list of MT5 symbols to find active closed-bar setups."""
    tf_u = tf.upper()
    out: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            quote = mt5_service.get_quote(sym)
            resolved = quote["symbol"]
            digits = int(quote["digits"])
            c_res = mt5_service.get_candles(resolved, tf_u, bars=260)
            candles = c_res["candles"]
            setup_res = detect_day_trader_setups(candles, direction_hint="WAIT", tf=tf_u, digits=digits)
            out.append(
                {
                    "symbol": resolved,
                    "tf": tf_u,
                    "bid": quote["bid"],
                    "trend": c_res["trend"],
                    "active_setup": setup_res["active_setup"],
                    "active_setup_label": setup_res["active_setup_label"],
                    "active_setup_side": setup_res["active_setup_side"],
                    "triggered_count": setup_res["triggered_count"],
                    "entry_timer_state": setup_res["entry_timer_state"],
                    "entry_timer_detail": setup_res["entry_timer_detail"],
                    "vol_ratio_x": setup_res["opening_range"].get("vol_ratio_x", 1.0),
                    "or_high": setup_res["opening_range"].get("or_high", 0.0),
                    "or_low": setup_res["opening_range"].get("or_low", 0.0),
                    "or_mid": setup_res["opening_range"].get("or_mid", 0.0),
                    "session_vwap": setup_res["opening_range"].get("session_vwap", 0.0),
                }
            )
        except Exception as exc:
            out.append(
                {
                    "symbol": sym,
                    "tf": tf_u,
                    "bid": 0.0,
                    "trend": "ERROR",
                    "active_setup": "NONE",
                    "active_setup_label": str(exc),
                    "active_setup_side": "NONE",
                    "triggered_count": 0,
                    "entry_timer_state": "WAITING",
                    "entry_timer_detail": str(exc),
                    "vol_ratio_x": 0.0,
                    "or_high": 0.0,
                    "or_low": 0.0,
                    "or_mid": 0.0,
                    "session_vwap": 0.0,
                }
            )
    # Sort triggered setups first, then by volume expansion
    out.sort(key=lambda item: (item["entry_timer_state"] != "TRIGGERED_ON_CLOSED_BAR", -float(item.get("vol_ratio_x") or 0)))
    return out
