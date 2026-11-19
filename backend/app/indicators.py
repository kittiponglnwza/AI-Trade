"""Technical indicators and timeframe mappings for MT5 market data."""

from __future__ import annotations

import math
from typing import Any

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

TIMEFRAME_MAP: dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

MTF_ORDER: tuple[str, ...] = ("D1", "H4", "H1", "M15", "M5")


def safe_float(value: Any, digits: int | None = None) -> float | None:
    """Convert numeric value to finite float (or None if NaN/Inf)."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return round(num, digits) if digits is not None else num


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute EMA(20,50,200), Wilder RSI(14), MACD(12,26,9), and Wilder ATR(14)."""
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)

    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    out["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out["rsi14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
    return out


def classify_trend(row: pd.Series) -> str:
    """Classify trend bias from close price relative to EMA20/50/200."""
    c = float(row["close"])
    e20 = float(row["ema20"])
    e50 = float(row["ema50"])
    e200 = float(row["ema200"])

    if c > e20 > e50 > e200:
        return "STRONG BULL"
    if c < e20 < e50 < e200:
        return "STRONG BEAR"
    if c > e50 and e20 > e50:
        return "BULLISH"
    if c < e50 and e20 < e50:
        return "BEARISH"
    if c > e200:
        return "PULLBACK (ABOVE EMA200)"
    if c < e200:
        return "BOUNCE (BELOW EMA200)"
    return "SIDEWAYS"
