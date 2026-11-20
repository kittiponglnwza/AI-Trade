"""8-Gate Pre-Trade Gauntlet audit and real MT5 historical strategy backtester."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5

from app.day_trader_skill import detect_day_trader_setups, run_time_machine_simulation
from app.indicators import classify_trend
from app.ml_engine import predict_with_news
from app.mt5_service import mt5_service
from app.news_service import fetch_symbol_news


def _fmt_ts(epoch_sec: int) -> str:
    return datetime.fromtimestamp(int(epoch_sec), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def evaluate_gauntlet(
    symbol: str = "XAUUSD",
    tf: str = "M15",
    risk_pct: float = 2.0,
    min_confidence_pct: float = 75.0,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
    min_rr_ratio: float = 1.5,
) -> dict[str, Any]:
    """Run an auditable 9-gate technical + news + ML confidence evaluation on a symbol."""
    tf_u = tf.upper()
    quote = mt5_service.get_quote(symbol)
    resolved = quote["symbol"]
    digits = int(quote["digits"])
    mtf = mt5_service.get_mtf_summary(resolved)
    candle_data = mt5_service.get_candles(resolved, tf_u, bars=240)
    candles = candle_data["candles"]
    news = fetch_symbol_news(resolved)

    gates: list[dict[str, Any]] = []
    last_bar = candles[-1] if candles else None
    atr = float(last_bar["atr14"]) if last_bar and last_bar.get("atr14") else round(quote["bid"] * 0.005, digits)
    if atr <= 0:
        atr = max(quote["point"] * 50, round(quote["bid"] * 0.005, digits))

    # G1: Data freshness & market session open check
    ref_epoch = mt5_service.get_reference_server_epoch() or quote["tick_epoch"]
    tick_age = abs(ref_epoch - quote["tick_epoch"]) if ref_epoch and quote["tick_epoch"] else 0
    is_weekend = datetime.now(timezone.utc).weekday() in (5, 6)
    if quote["bid"] <= 0 or quote["ask"] <= 0 or len(candles) < 50:
        g1_status = "FAIL"
        g1_detail = f"Invalid quote or insufficient bars ({len(candles)} bars)."
    elif is_weekend or tick_age >= 900:
        g1_status = "FAIL"
        g1_detail = f"Market session CLOSED (last tick is {tick_age // 60}m old) — blocked to prevent 10018 Market closed."
    else:
        g1_status = "PASS"
        g1_detail = f"Live quote {quote['bid']:.{digits}f}/{quote['ask']:.{digits}f} with {len(candles)} {tf_u} bars."
    gates.append(
        {
            "id": "G1_DATA_FRESHNESS",
            "label": "Live Data & Bars",
            "status": g1_status,
            "metric": f"{len(candles)} bars · age {tick_age}s",
            "detail": g1_detail,
        }
    )

    # G2: Spread vs ATR cost ratio
    spread = float(quote["spread_price"])
    spread_ratio = (spread / atr) if atr > 0 else 1.0
    if spread_ratio <= 0.25:
        g2_status = "PASS"
    elif spread_ratio <= 0.40:
        g2_status = "WARN"
    else:
        g2_status = "FAIL"
    gates.append(
        {
            "id": "G2_SPREAD_RATIO",
            "label": "Spread / ATR Cost",
            "status": g2_status,
            "metric": f"{spread_ratio * 100:.1f}% ({quote['spread_points']} pts)",
            "detail": f"Spread ${spread:.{digits}f} vs {tf_u} ATR14 ${atr:.{digits}f} (target <= 25%).",
        }
    )

    # G3: Multi-Timeframe Trend Alignment
    bull_tfs = [r["tf"] for r in mtf if "BULL" in r["trend"]]
    bear_tfs = [r["tf"] for r in mtf if "BEAR" in r["trend"]]
    tf_map = {r["tf"]: r for r in mtf}
    h1_trend = tf_map.get("H1", {}).get("trend", "")
    h4_trend = tf_map.get("H4", {}).get("trend", "")

    direction = "WAIT"
    if len(bull_tfs) >= 3 and len(bear_tfs) <= 1 and "BEAR" not in h1_trend:
        direction = "BUY"
        g3_status = "PASS"
        g3_detail = f"Bullish alignment on {len(bull_tfs)}/5 TFs ({', '.join(bull_tfs)}); H4={h4_trend}."
    elif len(bear_tfs) >= 3 and len(bull_tfs) <= 1 and "BULL" not in h1_trend:
        direction = "SELL"
        g3_status = "PASS"
        g3_detail = f"Bearish alignment on {len(bear_tfs)}/5 TFs ({', '.join(bear_tfs)}); H4={h4_trend}."
    else:
        g3_status = "FAIL"
        g3_detail = f"Mixed MTF consensus (Bull: {len(bull_tfs)}/5, Bear: {len(bear_tfs)}/5) — wait for cleaner bias."
    gates.append(
        {
            "id": "G3_MTF_ALIGNMENT",
            "label": "Multi-TF Trend",
            "status": g3_status,
            "metric": f"{direction} (B:{len(bull_tfs)} / S:{len(bear_tfs)})",
            "detail": g3_detail,
        }
    )

    # G4: Momentum & Day-Trader Closed-Bar Entry Timer (/trader-scanner + /trader-entry)
    day_trader = detect_day_trader_setups(candles, direction_hint=direction, tf=tf_u, digits=digits)
    eval_dir = (
        direction
        if direction in ("BUY", "SELL")
        else (
            day_trader["active_setup_side"]
            if day_trader.get("active_setup_side") in ("BUY", "SELL")
            else ("BUY" if len(bull_tfs) >= len(bear_tfs) else "SELL")
        )
    )
    entry_rsi = float(last_bar["rsi14"]) if last_bar and last_bar.get("rsi14") is not None else 50.0
    entry_macd = float(tf_map.get(tf_u, {}).get("macd_hist") or 0.0)
    dt_label = day_trader.get("active_setup_label", "None")
    dt_timer = day_trader.get("entry_timer_state", "WAITING")

    if direction == "BUY":
        if entry_rsi > 76:
            g4_status, g4_detail = "FAIL", f"{tf_u} RSI {entry_rsi:.1f} is heavily overbought (>76) — avoid chasing top."
        elif dt_timer == "FORMING_BAR_POKE_WAIT":
            g4_status, g4_detail = "WARN", f"{day_trader.get('entry_timer_detail')} (RSI {entry_rsi:.1f})."
        elif entry_rsi > 68:
            g4_status, g4_detail = "WARN", f"{tf_u} RSI {entry_rsi:.1f} is stretched (>68) · Setup: {dt_label}."
        else:
            g4_status, g4_detail = "PASS", f"{tf_u} RSI {entry_rsi:.1f} · Setup: {dt_label} ({dt_timer})."
    elif direction == "SELL":
        if entry_rsi < 24:
            g4_status, g4_detail = "FAIL", f"{tf_u} RSI {entry_rsi:.1f} is heavily oversold (<24) — avoid chasing bottom."
        elif dt_timer == "FORMING_BAR_POKE_WAIT":
            g4_status, g4_detail = "WARN", f"{day_trader.get('entry_timer_detail')} (RSI {entry_rsi:.1f})."
        elif entry_rsi < 32:
            g4_status, g4_detail = "WARN", f"{tf_u} RSI {entry_rsi:.1f} is stretched (<32) · Setup: {dt_label}."
        else:
            g4_status, g4_detail = "PASS", f"{tf_u} RSI {entry_rsi:.1f} · Setup: {dt_label} ({dt_timer})."
    else:
        g4_status, g4_detail = "WARN", f"MTF mixed ({tf_u} RSI {entry_rsi:.1f}) · Intraday Scanner: {dt_label}."
    gates.append(
        {
            "id": "G4_MOMENTUM_TIMING",
            "label": "Entry Timer & Setup",
            "status": g4_status,
            "metric": f"{day_trader.get('active_setup', 'WAIT')} · RSI {entry_rsi:.1f}",
            "detail": g4_detail,
        }
    )

    # G5 & G6: Setup-Aware Exit Planner (/trader-exit: OR-Midpoint / Flag / Structural SL & R:R Target)
    recent_12 = candles[-12:] if len(candles) >= 12 else candles
    swing_hi = max(float(c["high"]) for c in recent_12) if recent_12 else quote["ask"]
    swing_lo = min(float(c["low"]) for c in recent_12) if recent_12 else quote["bid"]
    min_stop = float(quote["stops_level_price"])

    sl_price: float | None = None
    tp_price: float | None = None
    entry_ref = float(quote["ask"] if eval_dir == "BUY" else quote["bid"])
    rr_val = 0.0
    stop_rule_used = f"{sl_atr_mult:.1f}xATR"
    rec_sl = day_trader.get("recommended_stop_price")
    rec_rule = day_trader.get("recommended_stop_rule", "atr")

    if eval_dir == "BUY":
        raw_sl = min(swing_lo - 0.3 * atr, entry_ref - sl_atr_mult * atr)
        if rec_sl is not None and (entry_ref - 2.6 * atr) <= float(rec_sl) <= (entry_ref - max(0.5 * atr, min_stop * 1.3)):
            raw_sl = float(rec_sl)
            stop_rule_used = str(rec_rule).upper()
        max_sl = entry_ref - max(sl_atr_mult * 1.7, 2.5) * atr
        min_allowed_sl = entry_ref - max(min(sl_atr_mult * 0.8, 1.1) * atr, min_stop * 1.2)
        sl_price = round(max(max_sl, min(raw_sl, min_allowed_sl)), digits)
        sl_dist = abs(entry_ref - sl_price)
        tp_dist = max(tp_atr_mult * atr, max(min_rr_ratio, 1.1) * sl_dist)
        tp_price = round(entry_ref + tp_dist, digits)
        rr_val = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0
    elif eval_dir == "SELL":
        raw_sl = max(swing_hi + 0.3 * atr, entry_ref + sl_atr_mult * atr)
        if rec_sl is not None and (entry_ref + max(0.5 * atr, min_stop * 1.3)) <= float(rec_sl) <= (entry_ref + 2.6 * atr):
            raw_sl = float(rec_sl)
            stop_rule_used = str(rec_rule).upper()
        max_sl = entry_ref + max(sl_atr_mult * 1.7, 2.5) * atr
        min_allowed_sl = entry_ref + max(min(sl_atr_mult * 0.8, 1.1) * atr, min_stop * 1.2)
        sl_price = round(min(max_sl, max(raw_sl, min_allowed_sl)), digits)
        sl_dist = abs(sl_price - entry_ref)
        tp_dist = max(tp_atr_mult * atr, max(min_rr_ratio, 1.1) * sl_dist)
        tp_price = round(entry_ref - tp_dist, digits)
        rr_val = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0

    # Run 10,000-Session Time Machine (/trader-timemachine) on the planned Entry/SL/TP
    time_machine = (
        run_time_machine_simulation(
            candles,
            eval_dir,
            entry_ref,
            sl_price,
            tp_price,
            tf=tf_u,
            horizon_bars=24,
            replays=10000,
            digits=digits,
        )
        if sl_price is not None and tp_price is not None
        else None
    )

    if direction in ("BUY", "SELL") and sl_price is not None and abs(entry_ref - sl_price) > min_stop:
        g5_status = "PASS"
        g5_detail = f"Exit Planner SL at {sl_price:.{digits}f} (Rule: {stop_rule_used}, dist ${abs(entry_ref - sl_price):.{digits}f})."
    else:
        g5_status = "FAIL"
        g5_detail = (
            f"Candidate {eval_dir} SL {sl_price:.{digits}f} ({stop_rule_used}) — waiting for MTF alignment."
            if sl_price is not None
            else "No valid structural SL level available."
        )
    gates.append(
        {
            "id": "G5_STRUCTURE_SL",
            "label": "Exit Planner (SL)",
            "status": g5_status,
            "metric": f"SL {sl_price:.{digits}f} ({stop_rule_used})" if sl_price else "N/A",
            "detail": g5_detail,
        }
    )

    if direction in ("BUY", "SELL") and rr_val >= min_rr_ratio:
        if time_machine and time_machine.get("verdict") == "LEANS_STOP":
            g6_status = "FAIL"
            g6_detail = (
                f"TP {tp_price:.{digits}f} (1:{rr_val:.2f}) rejected by 10,000-replay Time Machine: "
                f"TP First {time_machine['target_first_pct']}% vs SL First {time_machine['stop_first_pct']}% (EV {time_machine['expected_r']:+.2f}R)."
            )
        else:
            tm_tag = (
                f" · Time Machine 10k: TP {time_machine['target_first_pct']}%/SL {time_machine['stop_first_pct']}% (EV {time_machine['expected_r']:+.2f}R)"
                if time_machine
                else ""
            )
            g6_status = "PASS"
            g6_detail = f"TP {tp_price:.{digits}f} yields R:R 1:{rr_val:.2f} (>= 1:{min_rr_ratio:.2f}){tm_tag}."
    else:
        g6_status = "FAIL"
        g6_detail = f"Risk:Reward below 1:{min_rr_ratio:.2f} threshold or waiting for directional setup."
    gates.append(
        {
            "id": "G6_RISK_REWARD",
            "label": "Risk : Reward",
            "status": g6_status,
            "metric": f"1:{rr_val:.2f}" if rr_val else "N/A",
            "detail": g6_detail,
        }
    )

    # G7: Live News & Macro Event Alignment
    articles = news.get("articles", [])
    sent = news.get("sentiment", "NEUTRAL")
    impacts = news.get("high_impact_keywords", [])
    if not articles:
        g7_status = "WARN"
        g7_detail = "No live RSS headlines reachable right now; rely strictly on price structure."
    elif (direction == "BUY" and sent == "BEARISH") or (direction == "SELL" and sent == "BULLISH"):
        g7_status = "WARN"
        g7_detail = f"News sentiment is {sent} (opposes {direction}); review cited headlines before confirming."
    elif impacts:
        g7_status = "WARN"
        g7_detail = f"High-impact macro/news catalysts detected ({', '.join(impacts[:4])}); sentiment={sent}."
    else:
        g7_status = "PASS"
        g7_detail = f"{len(articles)} live headlines cited; sentiment={sent} aligns safely."
    gates.append(
        {
            "id": "G7_NEWS_EVIDENCE",
            "label": "News & Catalysts",
            "status": g7_status,
            "metric": f"{sent} ({len(articles)} news)",
            "detail": g7_detail,
        }
    )

    # G8: Live MT5 Broker Order Check (Dry-Run)
    broker_check: dict[str, Any] | None = None
    if direction in ("BUY", "SELL") and sl_price is not None and tp_price is not None:
        try:
            broker_check = mt5_service.check_order(
                symbol=resolved,
                side=direction,
                risk_pct=risk_pct,
                sl=sl_price,
                tp=tp_price,
            )
            if broker_check["valid"]:
                g8_status = "PASS"
                g8_detail = (
                    f"MT5 order_check Done (ret=0): {broker_check['lots']:.2f} lots, "
                    f"risk ${broker_check['est_risk_usd']:.2f} ({broker_check['est_risk_pct']:.1f}%), "
                    f"margin ${broker_check['required_margin']:.2f}."
                )
            else:
                g8_status = "FAIL"
                g8_detail = f"MT5 order_check rejected ({broker_check['retcode']}: {broker_check['comment']})."
        except Exception as exc:
            g8_status = "FAIL"
            g8_detail = f"MT5 order_check error: {exc}"
    else:
        g8_status = "WARN"
        g8_detail = "Broker order_check skipped because setup verdict is WAIT."
    gates.append(
        {
            "id": "G8_BROKER_ORDER_CHECK",
            "label": "MT5 Margin & Check",
            "status": g8_status,
            "metric": f"{broker_check['lots']:.2f} lots" if broker_check else "Skipped",
            "detail": g8_detail,
        }
    )

    # G9: Institutional LightGBM + Honest +EV + OOS Quality Gate (>= min_confidence_pct)
    ml_report: dict[str, Any] | None = None
    try:
        ml_report = predict_with_news(
            resolved,
            tf_u,
            direction,
            news,
            mtf,
            min_confidence_pct=min_confidence_pct,
            auto_train=True,
            sl_atr_mult=sl_atr_mult,
            tp_atr_mult=tp_atr_mult,
        )
        dt_bonus = float(day_trader.get("setup_score_bonus_pct") or 0.0)
        tm_bonus = float(time_machine.get("tm_confidence_bonus_pct") or 0.0) if time_machine else 0.0
        ev_r = float(ml_report.get("expected_value_r") or 0.0)
        side_q_pass = bool(ml_report.get("side_quality_passed", False))
        side_q_reason = str(ml_report.get("side_quality_reason") or "OOS check failed")
        true_p = float(ml_report.get("ml_raw_prob_pct") or 0.0)
        be_p = float(ml_report.get("breakeven_prob_pct") or 42.9)

        # Strict honesty: if true ML EV <= 0, bonuses CANNOT inflate score past 49.5%
        if ev_r <= 0.0:
            combined_conf = round(
                min(49.5, max(1.0, float(ml_report["final_confidence_pct"]) + min(0.0, dt_bonus + tm_bonus))),
                2,
            )
        else:
            combined_conf = round(
                min(95.0, max(1.0, float(ml_report["final_confidence_pct"]) + dt_bonus + tm_bonus)),
                2,
            )

        ml_report["day_trader_bonus_pct"] = round(dt_bonus, 2)
        ml_report["time_machine_bonus_pct"] = round(tm_bonus, 2)
        ml_report["final_confidence_pct"] = combined_conf
        ml_report["meets_threshold"] = bool(
            direction in ("BUY", "SELL")
            and side_q_pass
            and ev_r > 0.0
            and combined_conf >= min_confidence_pct
        )

        conf = combined_conf
        if not side_q_pass:
            g9_status = "FAIL"
            g9_metric = f"OOS LOCKED ({direction})"
            g9_detail = (
                f"🔒 OOS Quality Gate BLOCKED {direction}: โมเดลฝั่ง {direction} ({tf_u}) ยังสอบไม่ผ่านเกณฑ์ OOS "
                f"({side_q_reason}) · True P(Win) {true_p:.1f}% vs BE {be_p:.1f}% (EV {ev_r:+.3f}R)."
            )
        elif ev_r <= 0.0:
            g9_status = "FAIL"
            g9_metric = f"EV {ev_r:+.2f}R (P {true_p:.1f}%)"
            g9_detail = (
                f"Negative EV blocked: True Calibrated P(Win) {true_p:.1f}% <= Breakeven {be_p:.1f}% "
                f"(EV {ev_r:+.3f}R, Edge Score {conf:.1f}%)."
            )
        elif ml_report["meets_threshold"]:
            g9_status = "PASS"
            g9_metric = f"EV {ev_r:+.2f}R · {conf:.1f}%"
            g9_detail = (
                f"OOS PASS · True P(Win) {true_p:.1f}% vs BE {be_p:.1f}% (EV {ev_r:+.3f}R) · "
                f"Edge Score {conf:.1f}% >= {min_confidence_pct:.0f}% "
                f"(ML {ml_report['ml_conviction_pct']:.1f}% + News {ml_report['news_adjustment_pct']:+.1f}% "
                f"+ MTF {ml_report['mtf_bonus_pct']:+.1f}% + Setup {dt_bonus:+.1f}% + TM {tm_bonus:+.1f}%)."
            )
        else:
            g9_status = "FAIL"
            g9_metric = f"EV {ev_r:+.2f}R · {conf:.1f}%/{min_confidence_pct:.0f}%"
            g9_detail = (
                f"Edge Score {conf:.1f}% < {min_confidence_pct:.0f}% gate "
                f"(True P(Win) {true_p:.1f}% vs BE {be_p:.1f}%, EV {ev_r:+.3f}R)."
            )
    except Exception as exc:
        g9_status = "FAIL"
        g9_metric = "Model Error"
        g9_detail = f"ML confidence check unavailable: {exc}"

    gates.append(
        {
            "id": "G9_ML_NEWS_CONFIDENCE",
            "label": f"ML + News >= {min_confidence_pct:.0f}%",
            "status": g9_status,
            "metric": g9_metric,
            "detail": g9_detail,
        }
    )

    hard_fails = sum(1 for g in gates if g["status"] == "FAIL")
    warns = sum(1 for g in gates if g["status"] == "WARN")
    passed_count = sum(1 for g in gates if g["status"] == "PASS")

    if hard_fails == 0 and direction in ("BUY", "SELL"):
        verdict = "PASS"
    elif direction == "WAIT" or hard_fails == 1:
        verdict = "WAIT"
    else:
        verdict = "REJECT"

    conf_str = f"{ml_report['final_confidence_pct']:.1f}%" if ml_report else "N/A"
    top_headline = articles[0]["title"] if articles else "No news headlines available"
    rationale = (
        f"Gauntlet {passed_count}/{len(gates)} PASS ({warns} warn, {hard_fails} fail) · "
        f"ML+News Conf {conf_str} (Gate >={min_confidence_pct:.0f}%) · Verdict: {verdict} {direction} | "
        f"MTF B:{len(bull_tfs)}/S:{len(bear_tfs)} | {tf_u} RSI {entry_rsi:.1f} | "
        f"News ({sent}): {top_headline}"
    )

    proposed_order = None
    if direction in ("BUY", "SELL") and broker_check and broker_check.get("valid"):
        proposed_order = {
            "symbol": resolved,
            "side": direction,
            "order_type": "MARKET",
            "entry_price": broker_check["entry_price"],
            "sl": broker_check["sl"],
            "tp": broker_check["tp"],
            "risk_pct": broker_check["est_risk_pct"],
            "lots": broker_check["lots"],
            "est_risk_usd": broker_check["est_risk_usd"],
            "est_risk_pct": broker_check["est_risk_pct"],
            "est_reward_usd": broker_check["est_reward_usd"],
            "rr_ratio": broker_check["rr_ratio"],
            "required_margin": broker_check["required_margin"],
            "timeframe": tf_u,
            "rationale": rationale,
        }

    return {
        "symbol": resolved,
        "timeframe": tf_u,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "direction": direction,
        "passed_count": passed_count,
        "warn_count": warns,
        "fail_count": hard_fails,
        "total_gates": len(gates),
        "rationale": rationale,
        "quote": quote,
        "mtf_snapshot": mtf,
        "gates": gates,
        "ml": ml_report,
        "day_trader": day_trader,
        "time_machine": time_machine,
        "proposed_order": proposed_order,
        "news_summary": {
            "sentiment": news["sentiment"],
            "sentiment_score": news["sentiment_score"],
            "high_impact_event": news["high_impact_event"],
            "high_impact_keywords": news["high_impact_keywords"],
            "sources_used": news["sources_used"],
        },
        "news": articles[:6],
    }


def run_historical_backtest(
    symbol: str = "XAUUSD",
    tf: str = "M15",
    bars: int = 600,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
) -> dict[str, Any]:
    """Simulate a non-lookahead EMA trend + RSI pullback rule on real MT5 historical bars."""
    tf_u = tf.upper()
    res = mt5_service.get_candles(symbol, tf_u, bars=bars)
    resolved = res["symbol"]
    digits = int(res["digits"])
    candles = res["candles"]

    if len(candles) < 60:
        raise ValueError(f"Insufficient historical bars ({len(candles)}) to backtest {resolved} {tf_u}.")

    trades: list[dict[str, Any]] = []
    i = 20
    while i < len(candles) - 2:
        bar = candles[i]
        prev = candles[i - 1]
        next_bar = candles[i + 1]

        ema20 = bar.get("ema20")
        ema50 = bar.get("ema50")
        ema200 = bar.get("ema200")
        rsi = bar.get("rsi14")
        atr = bar.get("atr14")

        if None in (ema20, ema50, ema200, rsi, atr) or atr <= 0:
            i += 1
            continue

        close = float(bar["close"])
        open_p = float(bar["open"])
        signal: str | None = None

        if close > ema50 > ema200 and ema20 >= ema50 and 40.0 <= rsi <= 66.0 and close > ema20 and close > open_p:
            if prev["low"] <= ema20 * 1.003 or close > prev["high"]:
                signal = "BUY"
        elif close < ema50 < ema200 and ema20 <= ema50 and 34.0 <= rsi <= 60.0 and close < ema20 and close < open_p:
            if prev["high"] >= ema20 * 0.997 or close < prev["low"]:
                signal = "SELL"

        if signal is None:
            i += 1
            continue

        entry = float(next_bar["open"])
        risk_dist = float(sl_atr_mult) * float(atr)
        reward_dist = float(tp_atr_mult) * float(atr)
        sl = round(entry - risk_dist if signal == "BUY" else entry + risk_dist, digits)
        tp = round(entry + reward_dist if signal == "BUY" else entry - reward_dist, digits)

        exit_idx: int | None = None
        exit_price: float | None = None
        result_r = 0.0

        for j in range(i + 1, len(candles)):
            c = candles[j]
            hi = float(c["high"])
            lo = float(c["low"])

            # Conservative SL-first assumption on intra-bar ambiguity
            if signal == "BUY":
                if lo <= sl:
                    exit_idx, exit_price, result_r = j, sl, -1.0
                    break
                if hi >= tp:
                    exit_idx, exit_price, result_r = j, tp, round(reward_dist / risk_dist, 2)
                    break
            else:
                if hi >= sl:
                    exit_idx, exit_price, result_r = j, sl, -1.0
                    break
                if lo <= tp:
                    exit_idx, exit_price, result_r = j, tp, round(reward_dist / risk_dist, 2)
                    break

        if exit_idx is None:
            break

        trades.append(
            {
                "side": signal,
                "entry_time": _fmt_ts(next_bar["time"]),
                "exit_time": _fmt_ts(candles[exit_idx]["time"]),
                "entry": round(entry, digits),
                "exit": round(exit_price, digits),
                "sl": sl,
                "tp": tp,
                "result_r": result_r,
                "outcome": "WIN" if result_r > 0 else "LOSS",
            }
        )
        i = exit_idx + 1

    total = len(trades)
    wins = sum(1 for t in trades if t["result_r"] > 0)
    losses = sum(1 for t in trades if t["result_r"] < 0)
    gross_win_r = sum(t["result_r"] for t in trades if t["result_r"] > 0)
    gross_loss_r = abs(sum(t["result_r"] for t in trades if t["result_r"] < 0))
    net_r = round(sum(t["result_r"] for t in trades), 2)
    win_rate = round((wins / total) * 100.0, 2) if total > 0 else 0.0
    pf: float | None = round(gross_win_r / gross_loss_r, 2) if gross_loss_r > 0 else (None if gross_win_r > 0 else 0.0)
    expectancy_r = round(net_r / total, 3) if total > 0 else 0.0

    cum_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    equity_r_curve: list[dict[str, Any]] = []
    for idx, t in enumerate(trades, start=1):
        cum_r = round(cum_r + t["result_r"], 2)
        if cum_r > peak_r:
            peak_r = cum_r
        dd = round(peak_r - cum_r, 2)
        if dd > max_dd_r:
            max_dd_r = dd
        equity_r_curve.append({"trade": idx, "time": t["exit_time"], "cum_r": cum_r})

    return {
        "symbol": resolved,
        "tf": tf_u,
        "bars_tested": len(candles),
        "start_time": _fmt_ts(candles[0]["time"]),
        "end_time": _fmt_ts(candles[-1]["time"]),
        "rule_summary": "EMA20/50/200 Trend + RSI Pullback | SL 1.5x ATR | TP 2.5x ATR (Worst-case SL-first)",
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "net_r": net_r,
        "expectancy_r": expectancy_r,
        "max_drawdown_r": max_dd_r,
        "equity_r_curve": equity_r_curve,
        "recent_trades": trades[-15:][::-1],
    }
