"""Multi-timeframe MT5 analyzer and chart generator using shared backend bridge services."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.indicators import MTF_ORDER, classify_trend
from app.mt5_service import mt5_service

ICT_TZ = timezone(timedelta(hours=7))


def plot_timeframe_pair(
    symbol: str,
    live_bid: float,
    digits: int,
    top_label: str,
    top_df: pd.DataFrame,
    bottom_label: str,
    bottom_df: pd.DataFrame,
    plot_bars: int,
    output_path: Path,
) -> None:
    """Render a 2-timeframe dark candlestick + EMA + RSI PNG chart."""
    fig = plt.figure(figsize=(14, 10), facecolor="#0e1117", dpi=130)
    gs = GridSpec(
        4,
        1,
        height_ratios=[3.6, 1.1, 3.6, 1.1],
        hspace=0.22,
        left=0.06,
        right=0.92,
        top=0.94,
        bottom=0.06,
    )

    pairs = [
        (top_label, top_df, fig.add_subplot(gs[0]), fig.add_subplot(gs[1])),
        (bottom_label, bottom_df, fig.add_subplot(gs[2]), fig.add_subplot(gs[3])),
    ]

    for label, full_df, ax_price, ax_rsi in pairs:
        df = full_df.tail(plot_bars).reset_index(drop=True)
        x = np.arange(len(df))
        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()

        ax_price.set_facecolor("#161b22")
        ax_rsi.set_facecolor("#161b22")

        up = closes >= opens
        down = ~up
        colors = np.where(up, "#26a69a", "#ef5350")
        ax_price.vlines(x, lows, highs, color=colors, linewidth=1.0, zorder=2)

        body_bottom = np.minimum(opens, closes)
        body_height = np.maximum(np.abs(closes - opens), max((highs.max() - lows.min()) * 0.002, 10 ** (-digits)))
        ax_price.bar(x[up], body_height[up], bottom=body_bottom[up], width=0.62, color="#26a69a", zorder=3)
        ax_price.bar(x[down], body_height[down], bottom=body_bottom[down], width=0.62, color="#ef5350", zorder=3)

        ax_price.plot(x, df["ema20"], color="#ffd54f", linewidth=1.2, label="EMA 20", zorder=4)
        ax_price.plot(x, df["ema50"], color="#4dd0e1", linewidth=1.2, label="EMA 50", zorder=4)
        ax_price.plot(x, df["ema200"], color="#ce93d8", linewidth=1.4, label="EMA 200", zorder=4)

        w50 = full_df.tail(50)
        swing_hi = float(w50["high"].max())
        swing_lo = float(w50["low"].min())
        ax_price.axhline(swing_hi, color="#ef9a9a", linestyle="--", linewidth=0.9, alpha=0.75)
        ax_price.axhline(swing_lo, color="#80cbc4", linestyle="--", linewidth=0.9, alpha=0.75)
        ax_price.axhline(live_bid, color="#ffffff", linestyle=":", linewidth=1.1, alpha=0.85)

        last_row = df.iloc[-1]
        ax_price.set_title(
            f"{symbol} {label} | Close: {last_row['close']:.{digits}f} | "
            f"RSI14: {last_row['rsi14']:.1f} | ATR14: {last_row['atr14']:.{digits}f} | {classify_trend(last_row)}",
            color="#e6edf3",
            fontsize=9.5,
            loc="left",
            pad=6,
        )
        ax_price.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", fontsize=8, ncol=3)
        ax_price.grid(True, color="#2a2f3a", linewidth=0.5, alpha=0.6)
        ax_price.yaxis.tick_right()
        ax_price.tick_params(axis="y", colors="#c9d1d9", labelsize=8)
        ax_price.tick_params(axis="x", labelbottom=False)
        ax_price.set_xlim(-1, len(df) + 7)

        ax_rsi.plot(x, df["rsi14"], color="#64b5f6", linewidth=1.2)
        ax_rsi.axhline(70, color="#ef5350", linestyle="--", linewidth=0.8, alpha=0.8)
        ax_rsi.axhline(30, color="#26a69a", linestyle="--", linewidth=0.8, alpha=0.8)
        ax_rsi.set_ylim(10, 90)
        ax_rsi.set_yticks([30, 50, 70])
        ax_rsi.yaxis.tick_right()
        ax_rsi.tick_params(axis="y", colors="#c9d1d9", labelsize=8)
        ax_rsi.grid(True, color="#2a2f3a", linewidth=0.5, alpha=0.6)
        ax_rsi.set_xlim(-1, len(df) + 7)

        tick_step = max(1, len(df) // 7)
        tick_idx = list(range(0, len(df), tick_step))
        tick_labels = [
            datetime.fromtimestamp(int(df.loc[i, "time"]), tz=timezone.utc).strftime("%m-%d %H:%M")
            for i in tick_idx
        ]
        ax_rsi.set_xticks(tick_idx)
        ax_rsi.set_xticklabels(tick_labels, color="#c9d1d9", fontsize=8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    default_out = Path(__file__).resolve().parent / "charts"
    parser = argparse.ArgumentParser(description="Analyze MT5 symbol across multiple timeframes.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--bars", type=int, default=250)
    parser.add_argument("--plot-bars", type=int, default=80)
    parser.add_argument("--out-dir", type=Path, default=default_out)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not mt5_service.connect():
        raise RuntimeError("Failed to connect to MetaTrader 5 terminal.")

    try:
        snapshot = mt5_service.get_market_snapshot(args.symbol)
        resolved = snapshot["quote"]["symbol"]
        tf_dfs: dict[str, pd.DataFrame] = {}
        for tf_name in MTF_ORDER:
            res = mt5_service.get_candles(resolved, tf_name, bars=args.bars)
            tf_dfs[tf_name] = pd.DataFrame(res["candles"])

        digits = snapshot["quote"]["digits"]
        bid = snapshot["quote"]["bid"]
        chart_h4_h1 = args.out_dir / "xauusd_h4_h1.png"
        chart_m15_m5 = args.out_dir / "xauusd_m15_m5.png"

        plot_timeframe_pair(resolved, bid, digits, "H4", tf_dfs["H4"], "H1", tf_dfs["H1"], args.plot_bars, chart_h4_h1)
        plot_timeframe_pair(resolved, bid, digits, "M15", tf_dfs["M15"], "M5", tf_dfs["M5"], args.plot_bars, chart_m15_m5)
        snapshot["charts"] = [str(chart_h4_h1), str(chart_m15_m5)]

        if args.json:
            print(json.dumps(snapshot, indent=2))
        else:
            acc = snapshot["account"]
            q = snapshot["quote"]
            print(f"Account: {acc['login']} ({acc['trade_mode']}) | Balance: {acc['balance']:,.2f} | Equity: {acc['equity']:,.2f}")
            print(f"Symbol : {q['symbol']} | Bid: {q['bid']} | Ask: {q['ask']} | Spread: {q['spread_points']} pts")
            print("\nMTF Summary:")
            for row in snapshot["mtf"]:
                print(
                    f"  {row['tf']:<4} Close={row['close']} | EMA20={row['ema20']} | "
                    f"RSI={row['rsi14']} | ATR={row['atr14']} | {row['trend']}"
                )
            print(f"\nCharts saved: {chart_h4_h1}, {chart_m15_m5}")
    finally:
        mt5_service.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
