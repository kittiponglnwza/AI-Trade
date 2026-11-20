"""Institutional-Grade Quantitative ML Engine (v2.0):
- Strictly Causal Base-TF + Higher-Timeframe (H1/H4/D1) Feature Engineering (Zero Future Leakage)
- Exact BID/ASK Spread-Adjusted Triple-Barrier Labeling (Conservative SL-First + Time-Expiry R)
- 5-Fold Purged & Embargoed Rolling Walk-Forward CV with In-Fold Feature Selection
- Multi-Seed Bagged Shallow Regularized LightGBM + Native TreeSHAP Explainability
- Honest Platt Probability Calibration with Bayesian Shrinkage (Brier + ECE Verified, Zero Percentile Inflation)
- True Mathematical Expected Value (+EV in R) & Fractional Kelly Sizing
- Strict Per-Side OOS Quality Gate (Blocks Failing BUY/SELL Sides Automatically)
- Champion vs Challenger Auto-Retrain Guard & Multi-Timeframe Walk-Forward Benchmark
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import threading
import time
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from app.config import DATA_DIR
from app.indicators import TIMEFRAME_MAP, compute_indicators, safe_float
from app.mt5_service import mt5_service

SCHEMA_VERSION = "2.0"
MODELS_DIR = DATA_DIR / "models"
_MODEL_LOCK = threading.RLock()
_MODEL_CACHE: dict[str, dict[str, Any]] = {}

TF_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

HTF_PLAN: dict[str, list[tuple[str, str, int]]] = {
    "M1": [("h1", "H1", 2000), ("h4", "H4", 1000)],
    "M5": [("h1", "H1", 4000), ("h4", "H4", 1800)],
    "M15": [("h1", "H1", 6000), ("h4", "H4", 2500), ("d1", "D1", 600)],
    "M30": [("h1", "H1", 6000), ("h4", "H4", 2500), ("d1", "D1", 600)],
    "H1": [("h4", "H4", 2500), ("d1", "D1", 600)],
    "H4": [("d1", "D1", 900)],
    "D1": [],
}

# Default OOS Quality Gate thresholds (institutional minimum edge)
DEFAULT_MIN_OOS_AUC = 0.52
DEFAULT_MIN_OOS_PF = 1.05
DEFAULT_MIN_OOS_TRADES = 10
DEFAULT_TP_ATR = 2.5
DEFAULT_SL_ATR = 1.5
DEFAULT_HORIZON_BARS = 24
DEFAULT_TOP_K_FEATURES = 24
DEFAULT_N_SEEDS = 5
DEFAULT_PRIOR_SHRINK = 0.20

BASE_FEATURE_NAMES: list[str] = [
    "dist_ema20_atr",
    "dist_ema50_atr",
    "dist_ema200_atr",
    "ema20_50_spread_atr",
    "ema50_200_spread_atr",
    "ema20_slope_3",
    "ema50_slope_5",
    "adx14",
    "di_spread",
    "rsi14",
    "rsi_slope_3",
    "macd_hist_atr",
    "macd_hist_delta",
    "bb_pos",
    "bb_width_atr",
    "zscore_50",
    "atr_pct",
    "atr_ratio_50",
    "atr_ratio_200",
    "parkinson_vol_20",
    "body_atr",
    "range_atr",
    "clv",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "ret_1_atr",
    "ret_4_atr",
    "ret_12_atr",
    "pos_in_20_range",
    "pos_in_60_range",
    "dist_vwap_atr",
    "vol_ratio_20",
    "hour_sin",
    "hour_cos",
    "dow",
]

HTF_SUFFIXES: tuple[str, ...] = (
    "dist_ema50",
    "ema20_50",
    "ema50_200",
    "rsi14",
    "adx14",
    "di_spread",
    "atr_ratio",
    "ret_3",
)


def _model_path(symbol: str, tf: str) -> Path:
    clean_sym = "".join(ch if ch.isalnum() else "_" for ch in symbol.upper())
    return MODELS_DIR / f"{clean_sym}_{tf.upper()}.joblib"


def _backup_model_path(symbol: str, tf: str) -> Path:
    clean_sym = "".join(ch if ch.isalnum() else "_" for ch in symbol.upper())
    return MODELS_DIR / f"{clean_sym}_{tf.upper()}.prev.joblib"


def _compute_adx_and_base(df: pd.DataFrame) -> pd.DataFrame:
    """Compute base EMA/RSI/MACD/ATR plus strictly causal Wilder ADX(14) and DI spread."""
    out = compute_indicators(df)
    c = out["close"].astype(float)
    h = out["high"].astype(float)
    l = out["low"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=out.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=out.index,
        dtype=float,
    )
    tr_s = tr.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean().clip(lower=1e-6)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean() / tr_s
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean() / tr_s
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).clip(lower=1e-6)
    out["adx14"] = dx.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean().fillna(20.0)
    out["di_spread"] = (plus_di - minus_di).fillna(0.0)
    return out


def build_causal_htf_table(
    htf_candles: list[dict[str, Any]] | pd.DataFrame,
    tf_name: str,
    prefix: str,
) -> pd.DataFrame:
    """Build strictly causal HTF feature rows indexed by `avail_time = open_time + tf_seconds`.

    An HTF candle stamped with open time `T` is NOT known until it closes at `T + tf_seconds`.
    Merging with `avail_time <= base_close_time` mathematically guarantees zero future leakage.
    """
    raw = htf_candles.copy() if isinstance(htf_candles, pd.DataFrame) else pd.DataFrame(htf_candles)
    if raw.empty:
        cols = ["avail_time"] + [f"{prefix}_{s}" for s in HTF_SUFFIXES]
        return pd.DataFrame(columns=cols)
    if "tick_volume" not in raw.columns:
        raw["tick_volume"] = raw.get("volume", 0)
    raw = raw.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    d = _compute_adx_and_base(raw)
    c = d["close"].astype(float)
    atr = d["atr14"].astype(float).clip(lower=1e-6)
    atr50 = atr.rolling(50, min_periods=10).mean().clip(lower=1e-6)

    tf_sec = TF_SECONDS.get(tf_name.upper(), 3600)
    out = pd.DataFrame()
    out["avail_time"] = d["time"].astype(np.int64) + tf_sec
    out[f"{prefix}_dist_ema50"] = ((c - d["ema50"]) / atr).clip(-10.0, 10.0)
    out[f"{prefix}_ema20_50"] = ((d["ema20"] - d["ema50"]) / atr).clip(-10.0, 10.0)
    out[f"{prefix}_ema50_200"] = ((d["ema50"] - d["ema200"]) / atr).clip(-15.0, 15.0)
    out[f"{prefix}_rsi14"] = d["rsi14"].astype(float)
    out[f"{prefix}_adx14"] = d["adx14"].astype(float)
    out[f"{prefix}_di_spread"] = d["di_spread"].astype(float)
    out[f"{prefix}_atr_ratio"] = (atr / atr50).clip(0.1, 5.0)
    out[f"{prefix}_ret_3"] = ((c - c.shift(3)) / atr).clip(-10.0, 10.0)
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def build_feature_frame(
    candles: list[dict[str, Any]] | pd.DataFrame,
    base_tf: str = "M15",
    htf_candles_map: dict[str, tuple[str, list[dict[str, Any]] | pd.DataFrame]] | None = None,
) -> pd.DataFrame:
    """Construct strictly causal base-TF + Multi-Timeframe features (zero look-ahead)."""
    raw = candles.copy() if isinstance(candles, pd.DataFrame) else pd.DataFrame(candles)
    if "tick_volume" not in raw.columns:
        raw["tick_volume"] = raw.get("volume", 0)
    raw = raw.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    df = _compute_adx_and_base(raw)

    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["tick_volume"].astype(float)
    atr = df["atr14"].astype(float).clip(lower=1e-6)
    atr50 = atr.rolling(50, min_periods=10).mean().clip(lower=1e-6)
    atr200 = atr.rolling(200, min_periods=20).mean().clip(lower=1e-6)

    sma20 = c.rolling(20, min_periods=10).mean()
    std20 = c.rolling(20, min_periods=10).std().clip(lower=1e-6)
    sma50 = c.rolling(50, min_periods=20).mean()
    std50 = c.rolling(50, min_periods=20).std().clip(lower=1e-6)

    h20 = h.rolling(20, min_periods=10).max()
    l20 = l.rolling(20, min_periods=10).min()
    h60 = h.rolling(60, min_periods=20).max()
    l60 = l.rolling(60, min_periods=20).min()
    bar_rng = (h - l).clip(lower=1e-6)

    dt = pd.to_datetime(df["time"], unit="s", utc=True)
    hour_frac = dt.dt.hour + dt.dt.minute / 60.0

    # Strictly causal intraday session VWAP (resets at 00:00 UTC)
    day_key = dt.dt.floor("D")
    tp = (h + l + c) / 3.0
    v_safe = v.clip(lower=1.0)
    sess_vwap = (tp * v_safe).groupby(day_key).cumsum() / v_safe.groupby(day_key).cumsum().clip(lower=1.0)

    # Parkinson High-Low Range Volatility Estimator (20-bar)
    hl_log_sq = np.log((h / l.clip(lower=1e-6)).clip(lower=1.0)) ** 2
    park_vol = np.sqrt(hl_log_sq.rolling(20, min_periods=10).mean() / (4.0 * np.log(2.0)))

    feat = pd.DataFrame(index=df.index)
    feat["dist_ema20_atr"] = ((c - df["ema20"]) / atr).clip(-10.0, 10.0)
    feat["dist_ema50_atr"] = ((c - df["ema50"]) / atr).clip(-12.0, 12.0)
    feat["dist_ema200_atr"] = ((c - df["ema200"]) / atr).clip(-20.0, 20.0)
    feat["ema20_50_spread_atr"] = ((df["ema20"] - df["ema50"]) / atr).clip(-10.0, 10.0)
    feat["ema50_200_spread_atr"] = ((df["ema50"] - df["ema200"]) / atr).clip(-15.0, 15.0)
    feat["ema20_slope_3"] = ((df["ema20"] - df["ema20"].shift(3)) / atr).clip(-6.0, 6.0)
    feat["ema50_slope_5"] = ((df["ema50"] - df["ema50"].shift(5)) / atr).clip(-6.0, 6.0)
    feat["adx14"] = df["adx14"].astype(float)
    feat["di_spread"] = df["di_spread"].astype(float)

    feat["rsi14"] = df["rsi14"].astype(float)
    feat["rsi_slope_3"] = df["rsi14"].astype(float) - df["rsi14"].astype(float).shift(3)
    feat["macd_hist_atr"] = (df["macd_hist"].astype(float) / atr).clip(-6.0, 6.0)
    feat["macd_hist_delta"] = ((df["macd_hist"] - df["macd_hist"].shift(1)) / atr).clip(-4.0, 4.0)
    feat["bb_pos"] = ((c - sma20) / (2.0 * std20)).clip(-4.0, 4.0)
    feat["bb_width_atr"] = ((4.0 * std20) / atr).clip(0.0, 15.0)
    feat["zscore_50"] = ((c - sma50) / std50).clip(-5.0, 5.0)

    feat["atr_pct"] = (atr / c.clip(lower=1e-6)) * 100.0
    feat["atr_ratio_50"] = (atr / atr50).clip(0.1, 5.0)
    feat["atr_ratio_200"] = (atr / atr200).clip(0.1, 5.0)
    feat["parkinson_vol_20"] = (park_vol * 100.0).clip(0.0, 20.0)

    feat["body_atr"] = ((c - o) / atr).clip(-5.0, 5.0)
    feat["range_atr"] = (bar_rng / atr).clip(0.0, 8.0)
    feat["clv"] = (((c - l) - (h - c)) / bar_rng).clip(-1.0, 1.0)
    feat["upper_wick_ratio"] = ((h - np.maximum(o, c)) / bar_rng).clip(0.0, 1.0)
    feat["lower_wick_ratio"] = ((np.minimum(o, c) - l) / bar_rng).clip(0.0, 1.0)

    feat["ret_1_atr"] = ((c - c.shift(1)) / atr).clip(-6.0, 6.0)
    feat["ret_4_atr"] = ((c - c.shift(4)) / atr).clip(-10.0, 10.0)
    feat["ret_12_atr"] = ((c - c.shift(12)) / atr).clip(-15.0, 15.0)
    feat["pos_in_20_range"] = ((c - l20) / (h20 - l20).clip(lower=1e-6)).clip(0.0, 1.0)
    feat["pos_in_60_range"] = ((c - l60) / (h60 - l60).clip(lower=1e-6)).clip(0.0, 1.0)
    feat["dist_vwap_atr"] = ((c - sess_vwap) / atr).clip(-12.0, 12.0)
    feat["vol_ratio_20"] = (v / v.rolling(20, min_periods=5).mean().clip(lower=1.0)).clip(0.0, 10.0)
    feat["hour_sin"] = np.sin(2.0 * np.pi * hour_frac / 24.0)
    feat["hour_cos"] = np.cos(2.0 * np.pi * hour_frac / 24.0)
    feat["dow"] = dt.dt.dayofweek.astype(float)

    # Strictly causal HTF merge: base bar closing at `time + base_tf_sec` only sees HTF bars with `avail_time <= base_close_time`
    if htf_candles_map:
        base_tf_sec = TF_SECONDS.get(base_tf.upper(), 900)
        base_close_ts = pd.DataFrame(
            {"base_close_time": df["time"].astype(np.int64) + base_tf_sec},
            index=df.index,
        )
        for prefix, (htf_name, htf_raw) in htf_candles_map.items():
            htf_tbl = build_causal_htf_table(htf_raw, htf_name, prefix)
            if htf_tbl.empty:
                for suf in HTF_SUFFIXES:
                    feat[f"{prefix}_{suf}"] = 0.0
                continue
            merged = pd.merge_asof(
                base_close_ts,
                htf_tbl.sort_values("avail_time"),
                left_on="base_close_time",
                right_on="avail_time",
                direction="backward",
            )
            for suf in HTF_SUFFIXES:
                col = f"{prefix}_{suf}"
                feat[col] = merged[col].to_numpy()

    return feat.replace([np.inf, -np.inf], np.nan)


def build_triple_barrier_labels(
    candles: list[dict[str, Any]] | pd.DataFrame,
    tp_atr: float = DEFAULT_TP_ATR,
    sl_atr: float = DEFAULT_SL_ATR,
    horizon: int = DEFAULT_HORIZON_BARS,
    spread_price: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Exact BID/ASK spread-adjusted Triple-Barrier labeling with conservative SL-first resolution.

    Returns:
      y_buy, r_buy, y_sell, r_sell
    where y_* in {0.0, 1.0, NaN} (binary TP-before-SL hit) and r_* is exact realized R-multiple
    (including time-barrier mark-to-market exit after `horizon` bars if neither barrier hit).
    """
    df = candles.copy() if isinstance(candles, pd.DataFrame) else pd.DataFrame(candles)
    if "tick_volume" not in df.columns:
        df["tick_volume"] = df.get("volume", 0)
    df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    df = compute_indicators(df)

    n = len(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    atrs = df["atr14"].to_numpy(dtype=float)
    win_r = tp_atr / sl_atr
    spread = max(0.0, float(spread_price))

    y_buy = np.full(n, np.nan, dtype=float)
    r_buy = np.full(n, np.nan, dtype=float)
    y_sell = np.full(n, np.nan, dtype=float)
    r_sell = np.full(n, np.nan, dtype=float)

    for i in range(n - 2):
        atr = atrs[i]
        if not math.isfinite(atr) or atr <= 0:
            continue
        tp_dist = tp_atr * atr
        sl_dist = sl_atr * atr
        end_j = min(n, i + 1 + horizon)

        # BUY: enter at ASK = open_bid[i+1] + spread; exit at BID
        entry_buy_ask = opens[i + 1] + spread
        buy_tp_bid = entry_buy_ask + tp_dist
        buy_sl_bid = entry_buy_ask - sl_dist
        hit_buy = False
        for j in range(i + 1, end_j):
            if lows[j] <= buy_sl_bid:
                y_buy[i] = 0.0
                r_buy[i] = -1.0
                hit_buy = True
                break
            if highs[j] >= buy_tp_bid:
                y_buy[i] = 1.0
                r_buy[i] = win_r
                hit_buy = True
                break
        if not hit_buy and end_j > i + 1:
            exit_bid = closes[end_j - 1]
            r_buy[i] = float(np.clip((exit_bid - entry_buy_ask) / sl_dist, -1.0, win_r))

        # SELL: enter at BID = open_bid[i+1]; exit at ASK = bid + spread
        entry_sell_bid = opens[i + 1]
        sell_tp_bid = entry_sell_bid - tp_dist - spread
        sell_sl_bid = entry_sell_bid + sl_dist - spread
        hit_sell = False
        for j in range(i + 1, end_j):
            if highs[j] >= sell_sl_bid:
                y_sell[i] = 0.0
                r_sell[i] = -1.0
                hit_sell = True
                break
            if lows[j] <= sell_tp_bid:
                y_sell[i] = 1.0
                r_sell[i] = win_r
                hit_sell = True
                break
        if not hit_sell and end_j > i + 1:
            exit_ask = closes[end_j - 1] + spread
            r_sell[i] = float(np.clip((entry_sell_bid - exit_ask) / sl_dist, -1.0, win_r))

    return y_buy, r_buy, y_sell, r_sell


def _logit(probs: np.ndarray) -> np.ndarray:
    clipped = np.clip(probs, 1e-5, 1.0 - 1e-5)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def _compute_ece(y_true: np.ndarray, probs: np.ndarray, n_bins: int = 10) -> float:
    """Compute Expected Calibration Error (ECE) across uniform probability bins."""
    if len(y_true) == 0:
        return 0.0
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = float(len(y_true))
    for b0, b1 in zip(bins[:-1], bins[1:]):
        mask = (probs >= b0) & (probs < b1 if b1 < 1.0 else probs <= b1)
        if np.any(mask):
            ece += (float(np.sum(mask)) / n) * abs(float(np.mean(probs[mask])) - float(np.mean(y_true[mask])))
    return round(float(ece), 4)


def prob_to_honest_edge_score(
    prob: float,
    tp_atr: float = DEFAULT_TP_ATR,
    sl_atr: float = DEFAULT_SL_ATR,
) -> dict[str, float]:
    """Convert true calibrated win probability into exact +EV (R), Breakeven, Kelly, and monotonic Edge Score.

    Strictly transparent and honest (ZERO percentile inflation):
      - R_reward = tp_atr / sl_atr
      - breakeven_prob = 1 / (1 + R_reward)
      - EV_R = p * R_reward - (1 - p)
      - If EV_R <= 0: edge_score is strictly < 50.0%
      - If EV_R > 0: edge_score = 50.0 + min(45.0, EV_R * 90.0)
    """
    p = float(min(0.99, max(0.01, prob)))
    win_r = max(0.25, float(tp_atr) / max(0.1, float(sl_atr)))
    be_p = 1.0 / (1.0 + win_r)
    ev_r = p * win_r - (1.0 - p)
    edge_pp = (p - be_p) * 100.0
    # Quarter-Kelly fraction for conservative sizing reference
    full_kelly = (p * win_r - (1.0 - p)) / win_r if win_r > 0 else 0.0
    quarter_kelly_pct = round(max(0.0, min(5.0, full_kelly * 25.0)), 2)

    if ev_r <= 0.0:
        edge_score = round(max(1.0, min(49.9, 50.0 * (p / be_p))), 2)
    else:
        edge_score = round(min(95.0, 50.0 + min(45.0, ev_r * 90.0)), 2)

    return {
        "true_win_prob_pct": round(p * 100.0, 2),
        "breakeven_prob_pct": round(be_p * 100.0, 2),
        "expected_value_r": round(ev_r, 4),
        "edge_vs_breakeven_pp": round(edge_pp, 2),
        "quarter_kelly_pct": quarter_kelly_pct,
        "edge_score_pct": edge_score,
    }


def _fit_bagged_lgbm(
    X_tr: pd.DataFrame,
    y_tr: np.ndarray,
    X_cal: pd.DataFrame,
    y_cal: np.ndarray,
    top_k_features: int = DEFAULT_TOP_K_FEATURES,
    n_seeds: int = DEFAULT_N_SEEDS,
) -> tuple[list[lgb.LGBMClassifier], LogisticRegression | None, list[str], float]:
    """Fit in-fold feature-selected, time-decay-weighted, multi-seed shallow regularized LightGBM + Platt calibrator."""
    age = np.linspace(1.0, 0.0, len(X_tr))
    sample_weights = np.exp(-np.log(2.0) * age / 0.50)

    cols = list(X_tr.columns)
    if top_k_features and top_k_features < len(cols):
        selector = lgb.LGBMClassifier(
            n_estimators=120,
            learning_rate=0.04,
            max_depth=3,
            num_leaves=7,
            min_child_samples=80,
            subsample=0.75,
            subsample_freq=1,
            colsample_bytree=0.60,
            reg_alpha=3.0,
            reg_lambda=10.0,
            random_state=17,
            n_jobs=2,
            verbosity=-1,
        )
        selector.fit(X_tr, y_tr, sample_weight=sample_weights)
        gains = selector.booster_.feature_importance(importance_type="gain")
        top_idx = np.argsort(gains)[::-1][:top_k_features]
        cols = [cols[i] for i in top_idx]

    X_tr_s = X_tr[cols]
    X_cal_s = X_cal[cols]

    models: list[lgb.LGBMClassifier] = []
    cal_preds_list: list[np.ndarray] = []
    for s_idx in range(n_seeds):
        model = lgb.LGBMClassifier(
            n_estimators=350,
            learning_rate=0.02,
            max_depth=3,
            num_leaves=7,
            min_child_samples=100,
            subsample=0.70,
            subsample_freq=1,
            colsample_bytree=0.55,
            reg_alpha=4.0,
            reg_lambda=12.0,
            random_state=42 + s_idx * 31,
            n_jobs=2,
            verbosity=-1,
        )
        model.fit(
            X_tr_s,
            y_tr,
            sample_weight=sample_weights,
            eval_set=[(X_cal_s, y_cal)],
            callbacks=[lgb.early_stopping(25, verbose=False)],
        )
        models.append(model)
        cal_preds_list.append(model.predict_proba(X_cal_s)[:, 1])

    p_cal_raw = np.mean(cal_preds_list, axis=0)
    calibrator: LogisticRegression | None = None
    if len(X_cal_s) >= 40 and len(np.unique(y_cal)) >= 2:
        cal = LogisticRegression(C=0.35, solver="lbfgs")
        cal.fit(_logit(p_cal_raw), y_cal)
        calibrator = cal

    cal_base = float(np.mean(y_cal)) if len(y_cal) > 0 else 0.40
    return models, calibrator, cols, cal_base


def _predict_bagged_calibrated(
    models: list[lgb.LGBMClassifier],
    calibrator: LogisticRegression | None,
    X: pd.DataFrame,
    selected_features: list[str],
    cal_base: float,
    breakeven_p: float,
    prior_shrink: float = DEFAULT_PRIOR_SHRINK,
) -> np.ndarray:
    """Predict shrinkage-calibrated true win probabilities from the bagged ensemble."""
    X_s = X.reindex(columns=selected_features, fill_value=0.0)
    raw = np.mean([m.predict_proba(X_s)[:, 1] for m in models], axis=0)
    if calibrator is not None:
        cal_p = calibrator.predict_proba(_logit(raw))[:, 1]
    else:
        cal_p = raw
    anchor = min(float(cal_base), float(breakeven_p))
    shrunk = (1.0 - prior_shrink) * cal_p + prior_shrink * anchor
    return np.clip(shrunk, 0.01, 0.99)


def _simulate_oos_trades(
    idxs: np.ndarray,
    probs: np.ndarray,
    realized_r: np.ndarray,
    win_r: float,
    horizon: int,
    min_ev: float = 0.05,
    gate_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Non-overlapping chronological OOS trade simulation with real Drawdown, PF, and Sharpe/trade."""
    ev = probs * win_r - (1.0 - probs)
    next_allowed = -1
    trades_r: list[float] = []
    cooldown = max(8, horizon // 2)
    for k in range(len(idxs)):
        if idxs[k] < next_allowed:
            continue
        if gate_mask is not None and not gate_mask[k]:
            continue
        if ev[k] >= min_ev:
            trades_r.append(float(realized_r[k]))
            next_allowed = int(idxs[k]) + cooldown

    if not trades_r:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "net_r": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "max_dd_r": 0.0,
            "sharpe_per_trade": 0.0,
        }

    arr = np.array(trades_r, dtype=float)
    wins = int(np.sum(arr > 0))
    gp = float(arr[arr > 0].sum())
    gl = float(abs(arr[arr < 0].sum()))
    pf = round(gp / gl, 2) if gl > 0 else (9.99 if gp > 0 else 0.0)
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    max_dd = float(np.max(peak - cum)) if len(cum) > 0 else 0.0
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    sharpe = round(float(np.mean(arr) / std), 3) if std > 1e-6 else 0.0

    return {
        "trades": int(len(arr)),
        "win_rate_pct": round((wins / len(arr)) * 100.0, 2),
        "net_r": round(float(arr.sum()), 2),
        "profit_factor": pf,
        "expectancy_r": round(float(np.mean(arr)), 3),
        "max_dd_r": round(max_dd, 2),
        "sharpe_per_trade": sharpe,
    }


def _evaluate_side_walk_forward(
    X: pd.DataFrame,
    y: np.ndarray,
    realized_r: np.ndarray,
    trend_gate: np.ndarray,
    tp_atr: float = DEFAULT_TP_ATR,
    sl_atr: float = DEFAULT_SL_ATR,
    horizon: int = DEFAULT_HORIZON_BARS,
    min_oos_auc: float = DEFAULT_MIN_OOS_AUC,
    min_oos_pf: float = DEFAULT_MIN_OOS_PF,
    min_oos_trades: int = DEFAULT_MIN_OOS_TRADES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run 5-Fold Purged & Embargoed Walk-Forward CV, then fit final production ensemble on latest window."""
    n = len(X)
    win_r = tp_atr / sl_atr
    be_p = 1.0 / (1.0 + win_r)
    embargo = horizon + 2

    cal_bars = min(420, max(200, int(n * 0.045)))
    rolling_train_bars = min(3600, max(1600, int(n * 0.42)))

    fold_bounds = [
        (int(n * 0.60), int(n * 0.68)),
        (int(n * 0.68), int(n * 0.76)),
        (int(n * 0.76), int(n * 0.84)),
        (int(n * 0.84), int(n * 0.92)),
        (int(n * 0.92), n),
    ]

    all_probs: list[np.ndarray] = []
    all_y: list[np.ndarray] = []
    all_r: list[np.ndarray] = []
    all_idx: list[np.ndarray] = []
    all_gate: list[np.ndarray] = []
    folds_detail: list[dict[str, Any]] = []

    for f_num, (test_start, test_end) in enumerate(fold_bounds, start=1):
        cal_end = test_start - embargo
        cal_start = max(120, cal_end - cal_bars)
        train_end = cal_start - embargo
        train_start = max(0, train_end - rolling_train_bars)
        if train_end - train_start < 300:
            continue

        tr_sl = slice(train_start, train_end)
        cal_sl = slice(cal_start, cal_end)
        te_sl = slice(test_start, test_end)

        tr_m = ~np.isnan(y[tr_sl])
        cal_m = ~np.isnan(y[cal_sl])
        te_m = ~np.isnan(y[te_sl])

        X_tr, y_tr = X.iloc[tr_sl].loc[tr_m], y[tr_sl][tr_m].astype(int)
        X_cal, y_cal = X.iloc[cal_sl].loc[cal_m], y[cal_sl][cal_m].astype(int)
        X_te = X.iloc[te_sl].loc[te_m]
        y_te = y[te_sl][te_m].astype(int)
        r_te = realized_r[te_sl][te_m]
        idx_te = X_te.index.to_numpy()
        g_te = trend_gate[te_sl][te_m]

        if len(X_tr) < 200 or len(X_cal) < 50 or len(X_te) < 25:
            continue
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_cal)) < 2 or len(np.unique(y_te)) < 2:
            continue

        models, cal, cols, cal_base = _fit_bagged_lgbm(X_tr, y_tr, X_cal, y_cal)
        p_te = _predict_bagged_calibrated(models, cal, X_te, cols, cal_base, be_p)

        f_auc = round(float(roc_auc_score(y_te, p_te)), 4)
        f_brier = round(float(brier_score_loss(y_te, p_te)), 4)
        f_sim = _simulate_oos_trades(idx_te, p_te, r_te, win_r, horizon, min_ev=0.05)

        folds_detail.append(
            {
                "fold": f_num,
                "samples": int(len(y_te)),
                "auc": f_auc,
                "brier": f_brier,
                "trades": f_sim["trades"],
                "net_r": f_sim["net_r"],
                "pf": f_sim["profit_factor"],
            }
        )
        all_probs.append(p_te)
        all_y.append(y_te)
        all_r.append(r_te)
        all_idx.append(idx_te)
        all_gate.append(g_te)

    if not all_probs:
        raise ValueError("Insufficient valid samples across chronological purged walk-forward folds.")

    probs = np.concatenate(all_probs)
    ys = np.concatenate(all_y)
    rs = np.concatenate(all_r)
    idxs = np.concatenate(all_idx)
    gates = np.concatenate(all_gate)

    pooled_auc = round(float(roc_auc_score(ys, probs)), 4)
    mean_fold_auc = round(float(np.mean([f["auc"] for f in folds_detail])), 4)
    gated_auc = (
        round(float(roc_auc_score(ys[gates], probs[gates])), 4)
        if int(np.sum(gates)) >= 30 and len(np.unique(ys[gates])) >= 2
        else None
    )
    brier = round(float(brier_score_loss(ys, probs)), 4)
    ece = _compute_ece(ys, probs)
    base_wr = round(float(np.mean(ys) * 100.0), 2)

    sim_all = _simulate_oos_trades(idxs, probs, rs, win_r, horizon, min_ev=0.05, gate_mask=None)
    sim_gated = _simulate_oos_trades(idxs, probs, rs, win_r, horizon, min_ev=0.03, gate_mask=gates)
    sim_hi = _simulate_oos_trades(idxs, probs, rs, win_r, horizon, min_ev=0.12, gate_mask=None)

    # Strict Per-Side OOS Quality Gate (zero compromise!)
    # Passes if pooled AUC >= threshold AND real spread-adjusted OOS trades have positive Net R & PF >= threshold
    best_sim = sim_all if sim_all["trades"] >= min_oos_trades else sim_gated
    effective_auc = max(pooled_auc, gated_auc or 0.0)
    quality_reasons: list[str] = []
    if pooled_auc < min_oos_auc:
        quality_reasons.append(f"OOS AUC {pooled_auc:.4f} < {min_oos_auc:.2f}")
    if best_sim["trades"] < min_oos_trades:
        quality_reasons.append(f"OOS trades {best_sim['trades']} < {min_oos_trades}")
    if best_sim["net_r"] <= 0.0:
        quality_reasons.append(f"OOS Net {best_sim['net_r']:+.2f}R <= 0")
    if best_sim["profit_factor"] < min_oos_pf:
        quality_reasons.append(f"OOS PF {best_sim['profit_factor']:.2f} < {min_oos_pf:.2f}")
    if ece > 0.12:
        quality_reasons.append(f"Calibration ECE {ece:.3f} > 0.12")

    quality_passed = len(quality_reasons) == 0
    quality_reason = (
        f"PASS (AUC {pooled_auc:.4f}, PF {best_sim['profit_factor']:.2f}, Net {best_sim['net_r']:+.2f}R, ECE {ece:.3f})"
        if quality_passed
        else "; ".join(quality_reasons)
    )

    # Fit FINAL production model on the most recent window (strictly purged train + latest calibration slice)
    final_cal_end = n - embargo
    final_cal_start = max(120, final_cal_end - cal_bars)
    final_train_end = final_cal_start - embargo
    final_train_start = max(0, final_train_end - rolling_train_bars)

    f_tr_m = ~np.isnan(y[final_train_start:final_train_end])
    f_cal_m = ~np.isnan(y[final_cal_start:final_cal_end])
    X_ftr = X.iloc[final_train_start:final_train_end].loc[f_tr_m]
    y_ftr = y[final_train_start:final_train_end][f_tr_m].astype(int)
    X_fcal = X.iloc[final_cal_start:final_cal_end].loc[f_cal_m]
    y_fcal = y[final_cal_start:final_cal_end][f_cal_m].astype(int)

    if len(X_ftr) < 200 or len(X_fcal) < 40 or len(np.unique(y_ftr)) < 2 or len(np.unique(y_fcal)) < 2:
        raise ValueError("Insufficient samples in final production window.")

    prod_models, prod_cal, prod_cols, prod_cal_base = _fit_bagged_lgbm(X_ftr, y_ftr, X_fcal, y_fcal)

    metrics = {
        "train_samples": int(len(X_ftr)),
        "oos_samples": int(len(ys)),
        "oos_auc": pooled_auc,
        "oos_mean_fold_auc": mean_fold_auc,
        "oos_gated_auc": gated_auc,
        "oos_effective_auc": round(effective_auc, 4),
        "oos_brier": brier,
        "oos_ece": ece,
        "oos_base_win_rate_pct": base_wr,
        "oos_trades_ev05": sim_all["trades"],
        "oos_win_rate_ev05_pct": sim_all["win_rate_pct"],
        "oos_net_r_ev05": sim_all["net_r"],
        "oos_profit_factor": sim_all["profit_factor"],
        "oos_expectancy_r": sim_all["expectancy_r"],
        "oos_max_dd_r": sim_all["max_dd_r"],
        "oos_sharpe_per_trade": sim_all["sharpe_per_trade"],
        "oos_gated_trades": sim_gated["trades"],
        "oos_gated_win_rate_pct": sim_gated["win_rate_pct"],
        "oos_gated_net_r": sim_gated["net_r"],
        "oos_gated_pf": sim_gated["profit_factor"],
        # Legacy aliases kept for full backward compatibility
        "oos_trades_65": sim_all["trades"],
        "oos_win_rate_65_pct": sim_all["win_rate_pct"],
        "oos_trades_75": sim_hi["trades"],
        "oos_win_rate_75_pct": sim_hi["win_rate_pct"],
        "oos_net_r_75": sim_all["net_r"],
        "oos_non_overlap_trades_75": sim_all["trades"],
        "quality_passed": quality_passed,
        "quality_reason": quality_reason,
        "folds": folds_detail,
    }
    artifact = {
        "models": prod_models,
        "calibrator": prod_cal,
        "selected_features": prod_cols,
        "cal_base": prod_cal_base,
    }
    return artifact, metrics


def compute_composite_oos_score(meta: dict[str, Any]) -> float:
    """Deterministic Champion vs Challenger OOS quality score (higher is strictly better)."""
    if not meta or meta.get("schema_version") != SCHEMA_VERSION:
        return -999.0
    mb = meta.get("buy_metrics") or {}
    ms = meta.get("sell_metrics") or {}
    auc_b = float(mb.get("oos_auc") or 0.5)
    auc_s = float(ms.get("oos_auc") or 0.5)
    mean_auc = 0.5 * (auc_b + auc_s)
    net_r = float(mb.get("oos_net_r_ev05") or 0.0) + float(ms.get("oos_net_r_ev05") or 0.0)
    pf_b = min(3.0, float(mb.get("oos_profit_factor") or 0.0))
    pf_s = min(3.0, float(ms.get("oos_profit_factor") or 0.0))
    avg_pf = 0.5 * (pf_b + pf_s)
    avg_ece = 0.5 * (float(mb.get("oos_ece") or 0.15) + float(ms.get("oos_ece") or 0.15))
    avg_brier = 0.5 * (float(mb.get("oos_brier") or 0.25) + float(ms.get("oos_brier") or 0.25))
    pass_b = bool(mb.get("quality_passed", False))
    pass_s = bool(ms.get("quality_passed", False))

    score = (
        (mean_auc - 0.50) * 120.0
        + max(-30.0, min(60.0, net_r)) * 0.45
        + (avg_pf - 1.0) * 10.0
        - avg_ece * 45.0
        - avg_brier * 20.0
        + (10.0 if (pass_b or pass_s) else -15.0)
        + (10.0 if (pass_b and pass_s) else 0.0)
    )
    return round(float(score), 3)


def _fetch_mt5_htf_map(resolved_symbol: str, base_tf: str) -> dict[str, tuple[str, list[dict[str, Any]]]]:
    """Fetch higher-timeframe candles from MT5 for strictly causal MTF context."""
    plan = HTF_PLAN.get(base_tf.upper(), [])
    out: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for prefix, htf_name, count in plan:
        try:
            res = mt5_service.get_candles(resolved_symbol, htf_name, bars=count)
            out[prefix] = (htf_name, res["candles"])
        except Exception:
            continue
    return out


def _get_live_spread_price(resolved_symbol: str) -> float:
    """Read live broker spread in price units for realistic cost-adjusted labeling."""
    try:
        q = mt5_service.get_quote(resolved_symbol)
        return max(0.0, float(q.get("spread_price") or 0.0))
    except Exception:
        return 0.0


def train_symbol_model(
    symbol: str = "XAUUSD",
    tf: str = "M30",
    bars: int = 8000,
    tp_atr: float = DEFAULT_TP_ATR,
    sl_atr: float = DEFAULT_SL_ATR,
    horizon: int = DEFAULT_HORIZON_BARS,
    champion_guard: bool = True,
    force_promote: bool = False,
) -> dict[str, Any]:
    """Train Institutional v2.0 5-Fold Purged Walk-Forward model with Champion vs Challenger Guard."""
    tf_u = tf.upper()
    if tf_u not in TIMEFRAME_MAP:
        raise ValueError(f"Unsupported timeframe: {tf_u}")

    res = mt5_service.get_candles(symbol, tf_u, bars=bars)
    resolved = res["symbol"]
    candles = res["candles"]
    if len(candles) < 1200:
        raise ValueError(f"Insufficient MT5 bars ({len(candles)}) to train v2.0 Purged Walk-Forward ML for {resolved} {tf_u}.")

    spread_price = _get_live_spread_price(resolved)
    htf_map = _fetch_mt5_htf_map(resolved, tf_u)

    feat_df = build_feature_frame(candles, base_tf=tf_u, htf_candles_map=htf_map)
    y_buy, r_buy, y_sell, r_sell = build_triple_barrier_labels(
        candles,
        tp_atr=tp_atr,
        sl_atr=sl_atr,
        horizon=horizon,
        spread_price=spread_price,
    )

    warmup = min(220, len(feat_df) // 6)
    valid_df = feat_df.iloc[warmup:].dropna().copy()
    valid_idx = valid_df.index.to_numpy()
    yb_v, rb_v = y_buy[valid_idx], r_buy[valid_idx]
    ys_v, rs_v = y_sell[valid_idx], r_sell[valid_idx]
    valid_df = valid_df.reset_index(drop=True)

    # Causal directional trend mask (matches live Gauntlet G3 regime context)
    if "h1_ema20_50" in valid_df.columns:
        buy_gate = ((valid_df["ema20_50_spread_atr"] > 0) & (valid_df["h1_ema20_50"] > -0.2)).to_numpy()
        sell_gate = ((valid_df["ema20_50_spread_atr"] < 0) & (valid_df["h1_ema20_50"] < 0.2)).to_numpy()
    elif "h4_ema20_50" in valid_df.columns:
        buy_gate = ((valid_df["ema20_50_spread_atr"] > 0) & (valid_df["h4_ema20_50"] > -0.2)).to_numpy()
        sell_gate = ((valid_df["ema20_50_spread_atr"] < 0) & (valid_df["h4_ema20_50"] < 0.2)).to_numpy()
    else:
        buy_gate = (valid_df["ema20_50_spread_atr"] > 0).to_numpy()
        sell_gate = (valid_df["ema20_50_spread_atr"] < 0).to_numpy()

    art_buy, m_buy = _evaluate_side_walk_forward(
        valid_df, yb_v, rb_v, buy_gate, tp_atr=tp_atr, sl_atr=sl_atr, horizon=horizon
    )
    art_sell, m_sell = _evaluate_side_walk_forward(
        valid_df, ys_v, rs_v, sell_gate, tp_atr=tp_atr, sl_atr=sl_atr, horizon=horizon
    )

    win_r = tp_atr / sl_atr
    be_pct = round((1.0 / (1.0 + win_r)) * 100.0, 1)
    trained_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    htf_used = [htf_name for _, (htf_name, _) in htf_map.items()]
    net_r_combined = round(m_buy["oos_net_r_ev05"] + m_sell["oos_net_r_ev05"], 2)

    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "symbol": resolved,
        "tf": tf_u,
        "trained_at": trained_at,
        "bars_requested": int(bars),
        "bars_used": int(len(valid_df)),
        "feature_count": int(valid_df.shape[1]),
        "htf_context": htf_used,
        "spread_cost_price": round(spread_price, 5),
        "tp_atr": float(tp_atr),
        "sl_atr": float(sl_atr),
        "horizon_bars": int(horizon),
        "barrier_rule": (
            f"Spread-Adjusted (${spread_price:.2f}) Triple-Barrier TP={tp_atr}xATR / SL={sl_atr}xATR / "
            f"Horizon={horizon} bars (SL-first, Breakeven={be_pct}%)"
        ),
        "validation_method": "5-Fold Purged & Embargoed Rolling Walk-Forward CV (5-seed Bagged LGBM + Shrinkage Platt)",
        "buy_metrics": m_buy,
        "sell_metrics": m_sell,
        "oos_summary": {
            "auc_buy": m_buy["oos_auc"],
            "auc_sell": m_sell["oos_auc"],
            "mean_fold_auc_buy": m_buy["oos_mean_fold_auc"],
            "mean_fold_auc_sell": m_sell["oos_mean_fold_auc"],
            "brier_buy": m_buy["oos_brier"],
            "brier_sell": m_sell["oos_brier"],
            "ece_buy": m_buy["oos_ece"],
            "ece_sell": m_sell["oos_ece"],
            "pf_buy": m_buy["oos_profit_factor"],
            "pf_sell": m_sell["oos_profit_factor"],
            "win_rate_65_buy_pct": m_buy["oos_win_rate_ev05_pct"],
            "win_rate_65_sell_pct": m_sell["oos_win_rate_ev05_pct"],
            "net_r_buy": m_buy["oos_net_r_ev05"],
            "net_r_sell": m_sell["oos_net_r_ev05"],
            "net_r_combined": net_r_combined,
            "buy_quality_passed": m_buy["quality_passed"],
            "sell_quality_passed": m_sell["quality_passed"],
            "buy_quality_reason": m_buy["quality_reason"],
            "sell_quality_reason": m_sell["quality_reason"],
        },
    }
    challenger_score = compute_composite_oos_score(meta)
    meta["composite_oos_score"] = challenger_score

    challenger_bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "buy_artifact": art_buy,
        "sell_artifact": art_sell,
        "all_features": list(valid_df.columns),
        "meta": meta,
    }

    # Champion vs Challenger Guard
    path = _model_path(resolved, tf_u)
    backup_path = _backup_model_path(resolved, tf_u)
    path.parent.mkdir(parents=True, exist_ok=True)

    promoted = True
    decision_reason = "New v2.0 Champion promoted (first v2.0 model)."
    champion_score: float | None = None

    if champion_guard and not force_promote and path.exists():
        try:
            existing_bundle = joblib.load(path)
            existing_meta = existing_bundle.get("meta") or {}
            if existing_meta.get("schema_version") == SCHEMA_VERSION:
                champion_score = compute_composite_oos_score(existing_meta)
                if challenger_score > champion_score + 0.25:
                    promoted = True
                    decision_reason = (
                        f"PROMOTED Challenger (Score {challenger_score:.2f} > Champion {champion_score:.2f} + 0.25)"
                    )
                else:
                    promoted = False
                    decision_reason = (
                        f"KEPT Champion (Champion {champion_score:.2f} >= Challenger {challenger_score:.2f})"
                    )
            else:
                promoted = True
                decision_reason = "UPGRADED legacy v1 model -> Institutional v2.0 (Purged Walk-Forward + Spread-Adjusted)"
        except Exception:
            promoted = True
            decision_reason = "Replaced unreadable legacy model with v2.0 Champion."

    meta["champion_guard"] = {
        "promoted": promoted,
        "challenger_score": challenger_score,
        "champion_score": champion_score,
        "decision_reason": decision_reason,
    }

    if promoted:
        with _MODEL_LOCK:
            if path.exists():
                try:
                    shutil.copy2(path, backup_path)
                except Exception:
                    pass
            joblib.dump(challenger_bundle, path)
            _MODEL_CACHE[f"{resolved}:{tf_u}"] = challenger_bundle
    else:
        # Return metadata including rejected challenger audit stats while keeping Champion active
        with _MODEL_LOCK:
            champ = joblib.load(path)
            _MODEL_CACHE[f"{resolved}:{tf_u}"] = champ
            champ_meta = dict(champ.get("meta") or {})
            champ_meta["champion_guard"] = meta["champion_guard"]
            champ_meta["rejected_challenger_oos"] = meta["oos_summary"]
            return champ_meta

    return meta


def benchmark_timeframes(
    symbol: str = "XAUUSD",
    timeframes: list[str] | None = None,
    tp_atr: float = DEFAULT_TP_ATR,
    sl_atr: float = DEFAULT_SL_ATR,
    promote_best: bool = True,
) -> dict[str, Any]:
    """Benchmark M15, M30, and H1 via 5-Fold Purged Walk-Forward CV and identify the strongest timeframe."""
    tfs = [t.upper() for t in (timeframes or ["M15", "M30", "H1"]) if t.upper() in TIMEFRAME_MAP]
    bars_map = {"M15": 10000, "M30": 8000, "H1": 6000, "M5": 10000, "H4": 2500}
    results: list[dict[str, Any]] = []
    for tf_u in tfs:
        try:
            meta = train_symbol_model(
                symbol=symbol,
                tf=tf_u,
                bars=bars_map.get(tf_u, 8000),
                tp_atr=tp_atr,
                sl_atr=sl_atr,
                champion_guard=True,
                force_promote=False,
            )
            oos = meta.get("oos_summary") or {}
            results.append(
                {
                    "tf": tf_u,
                    "symbol": meta.get("symbol", symbol),
                    "bars_used": meta.get("bars_used", 0),
                    "composite_score": meta.get("composite_oos_score", -999.0),
                    "auc_buy": oos.get("auc_buy"),
                    "auc_sell": oos.get("auc_sell"),
                    "pf_buy": oos.get("pf_buy"),
                    "pf_sell": oos.get("pf_sell"),
                    "ece_buy": oos.get("ece_buy"),
                    "ece_sell": oos.get("ece_sell"),
                    "net_r_buy": oos.get("net_r_buy"),
                    "net_r_sell": oos.get("net_r_sell"),
                    "net_r_combined": oos.get("net_r_combined"),
                    "buy_quality_passed": bool(oos.get("buy_quality_passed", False)),
                    "sell_quality_passed": bool(oos.get("sell_quality_passed", False)),
                    "promoted": bool((meta.get("champion_guard") or {}).get("promoted", False)),
                    "decision_reason": (meta.get("champion_guard") or {}).get("decision_reason", ""),
                }
            )
        except Exception as exc:
            results.append({"tf": tf_u, "error": str(exc), "composite_score": -999.0})

    ranked = sorted(results, key=lambda r: float(r.get("composite_score", -999.0)), reverse=True)
    best = ranked[0] if ranked and "error" not in ranked[0] else None
    return {
        "symbol": best["symbol"] if best else symbol,
        "recommended_tf": best["tf"] if best else None,
        "recommended_reason": (
            f"{best['tf']} ทำคะแนน OOS สูงสุด ({best['composite_score']:.1f}) · "
            f"AUC B:{best['auc_buy']}/S:{best['auc_sell']} · Net {best['net_r_combined']:+.2f}R"
            if best
            else "ไม่มี TF ที่ผ่านเกณฑ์"
        ),
        "results": ranked,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _load_bundle(symbol: str, tf: str, auto_train: bool = True) -> dict[str, Any]:
    key = f"{symbol.upper()}:{tf.upper()}"
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None and cached.get("schema_version") == SCHEMA_VERSION:
            return cached

    path = _model_path(symbol, tf)
    if path.exists():
        with _MODEL_LOCK:
            bundle = joblib.load(path)
            if bundle.get("schema_version") == SCHEMA_VERSION:
                _MODEL_CACHE[key] = bundle
                return bundle
            # Legacy v1 bundle detected: automatically upgrade if auto_train is True
            if not auto_train:
                _MODEL_CACHE[key] = bundle
                return bundle

    if auto_train:
        bars_default = 8000 if tf.upper() in ("M30", "H1") else 10000
        train_symbol_model(symbol, tf, bars=bars_default, champion_guard=True)
        return _load_bundle(symbol, tf, auto_train=False)

    raise FileNotFoundError(f"No trained ML model found for {symbol} {tf}.")


def get_model_status(symbol: str = "XAUUSD", tf: str = "M15") -> dict[str, Any]:
    """Return existence and OOS walk-forward metadata for a trained symbol/tf model."""
    resolved = mt5_service.resolve_symbol(symbol) if mt5_service.is_connected() else symbol.upper()
    path = _model_path(resolved, tf)
    if not path.exists():
        return {"trained": False, "symbol": resolved, "tf": tf.upper(), "meta": None}
    bundle = _load_bundle(resolved, tf, auto_train=False)
    return {
        "trained": True,
        "schema_version": bundle.get("schema_version", "1.0"),
        "symbol": resolved,
        "tf": tf.upper(),
        "meta": bundle["meta"],
    }


def _compute_treeshap_drivers(
    models: list[lgb.LGBMClassifier],
    x_row: pd.DataFrame,
    selected_features: list[str],
    top_k: int = 6,
) -> list[dict[str, Any]]:
    """Compute exact averaged native LightGBM TreeSHAP feature contributions across the bagged ensemble."""
    X_s = x_row.reindex(columns=selected_features, fill_value=0.0)
    contribs_sum = np.zeros(len(selected_features), dtype=float)
    for m in models:
        contribs_sum += m.booster_.predict(X_s, pred_contrib=True)[0][:-1]
    contribs_avg = contribs_sum / max(1, len(models))

    drivers: list[dict[str, Any]] = []
    for idx, fname in enumerate(selected_features):
        sv = safe_float(contribs_avg[idx], 4)
        fv = safe_float(X_s.iloc[0, idx], 4)
        if sv is None:
            continue
        drivers.append(
            {
                "feature": fname,
                "shap_value": sv,
                "value": fv if fv is not None else 0.0,
                "direction": "UP" if sv >= 0 else "DOWN",
            }
        )
    drivers.sort(key=lambda item: abs(item["shap_value"]), reverse=True)
    return drivers[:top_k]


def predict_with_news(
    symbol: str,
    tf: str,
    direction: str,
    news: dict[str, Any],
    mtf: list[dict[str, Any]],
    min_confidence_pct: float = 65.0,
    auto_train: bool = True,
    sl_atr_mult: float = DEFAULT_SL_ATR,
    tp_atr_mult: float = DEFAULT_TP_ATR,
) -> dict[str, Any]:
    """Predict honest shrinkage-calibrated BUY/SELL win probabilities, true +EV (R), and OOS Quality Gate."""
    tf_u = tf.upper()
    res = mt5_service.get_candles(symbol, tf_u, bars=500)
    resolved = res["symbol"]
    candles = res["candles"]

    bundle = _load_bundle(resolved, tf_u, auto_train=auto_train)
    meta = bundle.get("meta") or {}
    model_tp = float(meta.get("tp_atr") or tp_atr_mult)
    model_sl = float(meta.get("sl_atr") or sl_atr_mult)
    win_r_model = model_tp / max(0.1, model_sl)
    be_p_model = 1.0 / (1.0 + win_r_model)

    htf_map = _fetch_mt5_htf_map(resolved, tf_u)
    feat_df = build_feature_frame(candles, base_tf=tf_u, htf_candles_map=htf_map)
    x_last = feat_df.iloc[[-1]].fillna(0.0)

    art_buy = bundle["buy_artifact"]
    art_sell = bundle["sell_artifact"]

    p_buy = float(
        _predict_bagged_calibrated(
            art_buy["models"],
            art_buy["calibrator"],
            x_last,
            art_buy["selected_features"],
            art_buy["cal_base"],
            be_p_model,
        )[0]
    )
    p_sell = float(
        _predict_bagged_calibrated(
            art_sell["models"],
            art_sell["calibrator"],
            x_last,
            art_sell["selected_features"],
            art_sell["cal_base"],
            be_p_model,
        )[0]
    )

    buy_ev_info = prob_to_honest_edge_score(p_buy, tp_atr=tp_atr_mult, sl_atr=sl_atr_mult)
    sell_ev_info = prob_to_honest_edge_score(p_sell, tp_atr=tp_atr_mult, sl_atr=sl_atr_mult)

    oos = meta.get("oos_summary") or {}
    buy_q_pass = bool(oos.get("buy_quality_passed", False))
    sell_q_pass = bool(oos.get("sell_quality_passed", False))
    buy_q_reason = str(oos.get("buy_quality_reason") or "Not evaluated")
    sell_q_reason = str(oos.get("sell_quality_reason") or "Not evaluated")

    dir_u = direction.upper()
    if dir_u == "BUY":
        chosen_ev = buy_ev_info
        shap_art = art_buy
        side_q_pass = buy_q_pass
        side_q_reason = buy_q_reason
    elif dir_u == "SELL":
        chosen_ev = sell_ev_info
        shap_art = art_sell
        side_q_pass = sell_q_pass
        side_q_reason = sell_q_reason
    else:
        if buy_ev_info["expected_value_r"] >= sell_ev_info["expected_value_r"]:
            chosen_ev, shap_art = buy_ev_info, art_buy
            side_q_pass, side_q_reason = buy_q_pass, buy_q_reason
        else:
            chosen_ev, shap_art = sell_ev_info, art_sell
            side_q_pass, side_q_reason = sell_q_pass, sell_q_reason

    top_features = _compute_treeshap_drivers(
        shap_art["models"], x_last, shap_art["selected_features"], top_k=6
    )

    # Conservative Live News Sentiment Fusion (-8% to +8%)
    sent_score = float(news.get("sentiment_score") or 0.0)
    articles_cnt = len(news.get("articles") or [])
    high_impact = bool(news.get("high_impact_event"))
    aligned_sent = sent_score if dir_u == "BUY" else (-sent_score if dir_u == "SELL" else 0.0)
    news_adj = aligned_sent * 10.0 if articles_cnt > 0 else 0.0
    if high_impact and aligned_sent < 0.15:
        news_adj -= 3.0
    news_adj = round(max(-8.0, min(8.0, news_adj)), 2)

    # MTF alignment confluence adjustment (-8% to +5%)
    if dir_u == "BUY":
        aligned_tfs = sum(1 for r in mtf if "BULL" in r.get("trend", ""))
    elif dir_u == "SELL":
        aligned_tfs = sum(1 for r in mtf if "BEAR" in r.get("trend", ""))
    else:
        aligned_tfs = 0

    if aligned_tfs >= 5:
        mtf_bonus = 5.0
    elif aligned_tfs == 4:
        mtf_bonus = 2.5
    elif aligned_tfs == 3:
        mtf_bonus = 0.0
    else:
        mtf_bonus = -8.0

    # Honest EV-anchored final score (NEVER inflated above 49% if true ML EV <= 0!)
    base_edge_score = chosen_ev["edge_score_pct"]
    if chosen_ev["expected_value_r"] <= 0.0:
        final_conf = round(max(1.0, min(49.5, base_edge_score + min(0.0, news_adj + mtf_bonus))), 2)
    else:
        final_conf = round(max(1.0, min(95.0, base_edge_score + news_adj + mtf_bonus)), 2)

    meets_threshold = bool(
        dir_u in ("BUY", "SELL")
        and side_q_pass
        and chosen_ev["expected_value_r"] > 0.0
        and final_conf >= float(min_confidence_pct)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "model_symbol": resolved,
        "model_tf": tf_u,
        "trained_at": meta.get("trained_at", ""),
        "ml_buy_prob_pct": buy_ev_info["true_win_prob_pct"],
        "ml_sell_prob_pct": sell_ev_info["true_win_prob_pct"],
        "ml_raw_prob_pct": chosen_ev["true_win_prob_pct"],
        "breakeven_prob_pct": chosen_ev["breakeven_prob_pct"],
        "expected_value_r": chosen_ev["expected_value_r"],
        "edge_vs_breakeven_pp": chosen_ev["edge_vs_breakeven_pp"],
        "quarter_kelly_pct": chosen_ev["quarter_kelly_pct"],
        "ml_conviction_pct": base_edge_score,
        "news_adjustment_pct": news_adj,
        "mtf_bonus_pct": mtf_bonus,
        "final_confidence_pct": final_conf,
        "min_confidence_pct": float(min_confidence_pct),
        "side_quality_passed": side_q_pass,
        "side_quality_reason": side_q_reason,
        "buy_quality_passed": buy_q_pass,
        "sell_quality_passed": sell_q_pass,
        "composite_oos_score": meta.get("composite_oos_score"),
        "meets_threshold": meets_threshold,
        "top_features": top_features,
        "oos_summary": oos,
    }


class AutoRetrainer:
    """Background Champion vs Challenger auto-retraining loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self.running_now = False
        self.last_run_at: str | None = None
        self._last_run_mono: float = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop(), name="ml-auto-retrainer")

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
        from app.database import get_ml_retrain_config

        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=25.0)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            cfg = get_ml_retrain_config()
            interval_sec = max(3600, int(float(cfg.get("interval_hours", 24)) * 3600))
            if cfg.get("enabled", True):
                now_mono = time.monotonic()
                if self._last_run_mono > 0.0 and (now_mono - self._last_run_mono) >= interval_sec:
                    try:
                        await self.run_retrain_cycle()
                    except Exception:
                        pass
                elif self._last_run_mono == 0.0:
                    # Wait full interval from startup unless an active model is stale (> interval_hours)
                    self._last_run_mono = now_mono
                    try:
                        if await self._any_active_model_stale(interval_sec):
                            await self.run_retrain_cycle()
                    except Exception:
                        pass

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass

    async def _any_active_model_stale(self, max_age_sec: int) -> bool:
        from app.database import get_watchdog_config, get_watchlist

        if not await asyncio.to_thread(mt5_service.is_connected):
            return False
        wd = get_watchdog_config()
        tf = str(wd.get("timeframe", "M30")).upper()
        for sym in get_watchlist()[:5]:
            try:
                st = await asyncio.to_thread(get_model_status, sym, tf)
                if not st.get("trained") or st.get("schema_version") != SCHEMA_VERSION:
                    return True
                t_str = (st.get("meta") or {}).get("trained_at")
                if t_str:
                    dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - dt).total_seconds() >= max_age_sec:
                        return True
            except Exception:
                continue
        return False

    async def run_retrain_cycle(
        self,
        symbols_override: list[str] | None = None,
        tf_override: str | None = None,
    ) -> dict[str, Any]:
        """Train Challengers on watchlist symbols and promote ONLY those beating Champion OOS score."""
        from app.database import (
            add_system_log,
            append_ml_retrain_history,
            get_ml_retrain_config,
            get_watchdog_config,
            get_watchlist,
            log_audit,
        )

        async with self._lock:
            self.running_now = True
            try:
                if not await asyncio.to_thread(mt5_service.is_connected):
                    return {"ok": False, "reason": "MT5 not connected", "results": []}

                cfg = get_ml_retrain_config()
                wd = get_watchdog_config()
                tf_u = str(tf_override or cfg.get("timeframe") or wd.get("timeframe", "M30")).upper()
                symbols = symbols_override or get_watchlist()
                tp_atr = float(wd.get("tp_atr_mult", DEFAULT_TP_ATR))
                sl_atr = float(wd.get("sl_atr_mult", DEFAULT_SL_ATR))
                bars_default = 8000 if tf_u in ("M30", "H1") else 10000
                guard_on = bool(cfg.get("champion_guard", True))

                results: list[dict[str, Any]] = []
                for sym in symbols[:6]:
                    try:
                        meta = await asyncio.to_thread(
                            train_symbol_model,
                            sym,
                            tf_u,
                            bars_default,
                            tp_atr,
                            sl_atr,
                            DEFAULT_HORIZON_BARS,
                            guard_on,
                            False,
                        )
                        cg = meta.get("champion_guard") or {}
                        oos = meta.get("oos_summary") or {}
                        entry = {
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "symbol": meta.get("symbol", sym),
                            "tf": tf_u,
                            "promoted": bool(cg.get("promoted", False)),
                            "challenger_score": cg.get("challenger_score"),
                            "champion_score": cg.get("champion_score"),
                            "decision_reason": cg.get("decision_reason", ""),
                            "auc_buy": oos.get("auc_buy"),
                            "auc_sell": oos.get("auc_sell"),
                            "net_r_combined": oos.get("net_r_combined"),
                            "buy_quality_passed": bool(oos.get("buy_quality_passed", False)),
                            "sell_quality_passed": bool(oos.get("sell_quality_passed", False)),
                        }
                        append_ml_retrain_history(entry)
                        results.append(entry)
                        add_system_log(
                            "INFO",
                            "ML_RETRAIN",
                            (
                                f"{entry['symbol']} {tf_u}: {entry['decision_reason']} | "
                                f"AUC B:{entry['auc_buy']}/S:{entry['auc_sell']} | Net {entry['net_r_combined']}R"
                            ),
                            symbol=entry["symbol"],
                            details=entry,
                        )
                        log_audit(
                            event_type="ML_RETRAIN_EVALUATED",
                            actor="ML_RETRAINER",
                            summary=f"ML Auto-Retrain {entry['symbol']} {tf_u}: {entry['decision_reason']}",
                            payload=entry,
                        )
                    except Exception as exc:
                        err_entry = {
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "symbol": sym,
                            "tf": tf_u,
                            "error": str(exc),
                            "promoted": False,
                        }
                        results.append(err_entry)
                        add_system_log("WARN", "ML_RETRAIN", f"{sym} {tf_u} retrain skipped: {exc}", symbol=sym)

                self.last_run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                self._last_run_mono = time.monotonic()
                return {"ok": True, "last_run_at": self.last_run_at, "results": results}
            finally:
                self.running_now = False

    def get_status(self) -> dict[str, Any]:
        from app.database import get_ml_retrain_config, get_ml_retrain_history

        return {
            "running": self._task is not None and not self._task.done(),
            "running_now": self.running_now,
            "last_run_at": self.last_run_at,
            "config": get_ml_retrain_config(),
            "history": get_ml_retrain_history(limit=20),
        }


ml_retrainer = AutoRetrainer()
