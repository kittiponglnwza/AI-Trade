"""Trading performance analytics computed from logged and synced trades."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _parse_iso_or_epoch(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _extract_date_key(time_str: str) -> str:
    return time_str[:10] if len(time_str) >= 10 else time_str


def compute_trading_stats(
    closed_trades: list[dict[str, Any]],
    current_balance: float | None = None,
) -> dict[str, Any]:
    """Compute win rate, profit factor, drawdown, expectancy, streaks, equity curve, and breakdowns."""
    ordered = sorted(
        closed_trades,
        key=lambda t: str(t.get("close_time") or t.get("created_at") or ""),
    )

    total_trades = len(ordered)
    if total_trades == 0:
        base_eq = round(float(current_balance), 2) if current_balance is not None else 0.0
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate_pct": 0.0,
            "net_profit": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "current_streak": 0,
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "starting_balance": base_eq,
            "equity_curve": [],
            "daily_pnl": [],
            "by_side": {
                "BUY": {"trades": 0, "wins": 0, "win_rate_pct": 0.0, "net_profit": 0.0},
                "SELL": {"trades": 0, "wins": 0, "win_rate_pct": 0.0, "net_profit": 0.0},
            },
        }

    pnls = [float(t.get("net_profit") or 0.0) for t in ordered]
    total_net = sum(pnls)
    starting_balance = (
        round(float(current_balance) - total_net, 2)
        if current_balance is not None
        else 0.0
    )

    wins_list = [p for p in pnls if p > 0]
    losses_list = [p for p in pnls if p < 0]
    breakeven_count = sum(1 for p in pnls if p == 0)

    wins = len(wins_list)
    losses = len(losses_list)
    win_rate_pct = round((wins / total_trades) * 100.0, 2)
    gross_profit = round(sum(wins_list), 2)
    gross_loss = round(abs(sum(losses_list)), 2)

    if gross_loss > 0:
        profit_factor: float | None = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = None
    else:
        profit_factor = 0.0

    avg_win = round(sum(wins_list) / wins, 2) if wins > 0 else 0.0
    avg_loss = round(sum(losses_list) / losses, 2) if losses > 0 else 0.0
    expectancy = round(total_net / total_trades, 2)
    largest_win = round(max(wins_list), 2) if wins_list else 0.0
    largest_loss = round(min(losses_list), 2) if losses_list else 0.0

    # Streaks
    max_win_streak = 0
    max_loss_streak = 0
    run_win = 0
    run_loss = 0
    current_streak = 0
    for p in pnls:
        if p > 0:
            run_win += 1
            run_loss = 0
            max_win_streak = max(max_win_streak, run_win)
            current_streak = run_win
        elif p < 0:
            run_loss += 1
            run_win = 0
            max_loss_streak = max(max_loss_streak, run_loss)
            current_streak = -run_loss

    # Equity curve & max drawdown
    cumulative = 0.0
    peak_equity = starting_balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    equity_curve: list[dict[str, Any]] = []
    daily_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"date": "", "pnl": 0.0, "trades": 0, "wins": 0}
    )

    side_stats: dict[str, dict[str, Any]] = {
        "BUY": {"trades": 0, "wins": 0, "net_profit": 0.0},
        "SELL": {"trades": 0, "wins": 0, "net_profit": 0.0},
    }

    for idx, trade in enumerate(ordered, start=1):
        pnl = float(trade.get("net_profit") or 0.0)
        cumulative += pnl
        equity = starting_balance + cumulative
        if equity > peak_equity:
            peak_equity = equity
        dd_usd = max(0.0, peak_equity - equity)
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd
        if peak_equity > 0:
            dd_pct = (dd_usd / peak_equity) * 100.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        close_str = _parse_iso_or_epoch(trade.get("close_time") or trade.get("created_at"))
        equity_curve.append(
            {
                "index": idx,
                "time": close_str,
                "pnl": round(pnl, 2),
                "cumulative_pnl": round(cumulative, 2),
                "equity": round(equity, 2),
            }
        )

        day_key = _extract_date_key(close_str)
        bucket = daily_buckets[day_key]
        bucket["date"] = day_key
        bucket["pnl"] = round(bucket["pnl"] + pnl, 2)
        bucket["trades"] += 1
        if pnl > 0:
            bucket["wins"] += 1

        side = str(trade.get("side") or "").upper()
        base_side = "BUY" if side.startswith("BUY") else "SELL"
        side_stats[base_side]["trades"] += 1
        side_stats[base_side]["net_profit"] = round(side_stats[base_side]["net_profit"] + pnl, 2)
        if pnl > 0:
            side_stats[base_side]["wins"] += 1

    for key, val in side_stats.items():
        cnt = val["trades"]
        val["win_rate_pct"] = round((val["wins"] / cnt) * 100.0, 2) if cnt > 0 else 0.0

    daily_pnl = sorted(daily_buckets.values(), key=lambda item: item["date"])

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven_count,
        "win_rate_pct": win_rate_pct,
        "net_profit": round(total_net, 2),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "current_streak": current_streak,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "starting_balance": starting_balance,
        "equity_curve": equity_curve,
        "daily_pnl": daily_pnl,
        "by_side": side_stats,
    }
