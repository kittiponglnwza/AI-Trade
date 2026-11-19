"""Quantitative LightGBM + Native TreeSHAP + News Sentiment Fusion engine."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import threading
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from app.config import DATA_DIR
from app.indicators import compute_indicators, safe_float
from app.mt5_service import mt5_service

MODELS_DIR = DATA_DIR / "models"
_MODEL_LOCK = threading.RLock()
_MODEL_CACHE: dict[str, dict[str, Any]] = {}

MIN_POSITIVE_EV_PROB = 0.45

FEATURE_NAMES: list[str] = [
    "dist_ema20_atr",
    "dist_ema50_atr",
    "dist_ema200_atr",
    "ema20_50_spread_atr",
    "ema50_200_spread_atr",
    "ema_long_spread_atr",
    "ema20_slope_3",
    "ema50_slope_5",
    "rsi14",
    "rsi_slope_3",
    "macd_hist_atr",
    "macd_hist_delta",
    "atr_pct",
    "atr_ratio_50",
    "bb_pos",
    "body_atr",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "ret_1_atr",
    "ret_4_atr",
    "pos_in_20_range",
    "hour_sin",
    "hour_cos",
    "dow",
]


def _model_path(symbol: str, tf: str) -> Path:
    clean_sym = "".join(ch if ch.isalnum() else "_" for ch in symbol.upper())
    return MODELS_DIR / f"{clean_sym}_{tf.upper()}.joblib"


def build_feature_frame(candles: list[dict[str, Any]]) -> pd.DataFrame:
    """Construct 24 strictly causal technical, volatility, candle-geometry, and session features."""
    df = pd.DataFrame(candles).copy()
    if "tick_volume" not in df.columns:
        df["tick_volume"] = df.get("volume", 0)
    df = compute_indicators(df)

    close = df["close"].astype(float)
    open_p = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    atr = df["atr14"].astype(float).clip(lower=1e-6)

    ema20 = df["ema20"].astype(float)
    ema50 = df["ema50"].astype(float)
    ema200 = df["ema200"].astype(float)
    ema80 = close.ewm(span=80, adjust=False).mean()
    ema400 = close.ewm(span=400, adjust=False).mean()

    atr50 = atr.rolling(50, min_periods=10).mean().clip(lower=1e-6)
    sma20 = close.rolling(20, min_periods=10).mean()
    std20 = close.rolling(20, min_periods=10).std().clip(lower=1e-6)
    high20 = high.rolling(20, min_periods=10).max()
    low20 = low.rolling(20, min_periods=10).min()
    rng20 = (high20 - low20).clip(lower=1e-6)
    bar_rng = (high - low).clip(lower=1e-6)

    dt = pd.to_datetime(df["time"], unit="s", utc=True)
    hour_frac = dt.dt.hour + dt.dt.minute / 60.0

    feat = pd.DataFrame(index=df.index)
    feat["dist_ema20_atr"] = (close - ema20) / atr
    feat["dist_ema50_atr"] = (close - ema50) / atr
    feat["dist_ema200_atr"] = (close - ema200) / atr
    feat["ema20_50_spread_atr"] = (ema20 - ema50) / atr
    feat["ema50_200_spread_atr"] = (ema50 - ema200) / atr
    feat["ema_long_spread_atr"] = (ema80 - ema400) / atr
    feat["ema20_slope_3"] = (ema20 - ema20.shift(3)) / atr
    feat["ema50_slope_5"] = (ema50 - ema50.shift(5)) / atr
    feat["rsi14"] = df["rsi14"].astype(float)
    feat["rsi_slope_3"] = df["rsi14"].astype(float) - df["rsi14"].astype(float).shift(3)
    feat["macd_hist_atr"] = df["macd_hist"].astype(float) / atr
    feat["macd_hist_delta"] = (df["macd_hist"].astype(float) - df["macd_hist"].astype(float).shift(1)) / atr
    feat["atr_pct"] = (atr / close.clip(lower=1e-6)) * 100.0
    feat["atr_ratio_50"] = atr / atr50
    feat["bb_pos"] = (close - sma20) / (2.0 * std20)
    feat["body_atr"] = (close - open_p) / atr
    feat["upper_wick_ratio"] = (high - np.maximum(open_p, close)) / bar_rng
    feat["lower_wick_ratio"] = (np.minimum(open_p, close) - low) / bar_rng
    feat["ret_1_atr"] = (close - close.shift(1)) / atr
    feat["ret_4_atr"] = (close - close.shift(4)) / atr
    feat["pos_in_20_range"] = (close - low20) / rng20
    feat["hour_sin"] = np.sin(2.0 * np.pi * hour_frac / 24.0)
    feat["hour_cos"] = np.cos(2.0 * np.pi * hour_frac / 24.0)
    feat["dow"] = dt.dt.dayofweek.astype(float)

    feat = feat[FEATURE_NAMES].replace([np.inf, -np.inf], np.nan)
    return feat


def build_triple_barrier_labels(
    candles: list[dict[str, Any]],
    tp_atr: float = 2.0,
    sl_atr: float = 1.5,
    horizon: int = 24,
) -> tuple[np.ndarray, np.ndarray]:
    """Label each bar with next-bar entry conservative SL-first Triple-Barrier outcomes."""
    df = pd.DataFrame(candles)
    if "tick_volume" not in df.columns:
        df["tick_volume"] = df.get("volume", 0)
    df = compute_indicators(df)

    n = len(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    atrs = df["atr14"].to_numpy(dtype=float)

    y_buy = np.full(n, np.nan, dtype=float)
    y_sell = np.full(n, np.nan, dtype=float)

    for i in range(n - 2):
        atr = atrs[i]
        if not math.isfinite(atr) or atr <= 0:
            continue
        entry = opens[i + 1]
        tp_dist = tp_atr * atr
        sl_dist = sl_atr * atr

        buy_tp = entry + tp_dist
        buy_sl = entry - sl_dist
        sell_tp = entry - tp_dist
        sell_sl = entry + sl_dist

        end_j = min(n, i + 1 + horizon)
        for j in range(i + 1, end_j):
            if lows[j] <= buy_sl:
                y_buy[i] = 0.0
                break
            if highs[j] >= buy_tp:
                y_buy[i] = 1.0
                break

        for j in range(i + 1, end_j):
            if highs[j] >= sell_sl:
                y_sell[i] = 0.0
                break
            if lows[j] <= sell_tp:
                y_sell[i] = 1.0
                break

    return y_buy, y_sell


def _logit(probs: np.ndarray) -> np.ndarray:
    clipped = np.clip(probs, 1e-5, 1.0 - 1e-5)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def _predict_calibrated(
    model: lgb.LGBMClassifier,
    calibrator: LogisticRegression | None,
    X: pd.DataFrame,
) -> np.ndarray:
    raw = model.predict_proba(X)[:, 1]
    if calibrator is None:
        return raw
    return calibrator.predict_proba(_logit(raw))[:, 1]


def _prob_to_conviction(prob: float, cal_sorted: np.ndarray | None) -> float:
    """Convert calibrated win probability into quantile conviction score only when positive-EV."""
    if prob < MIN_POSITIVE_EV_PROB or cal_sorted is None or len(cal_sorted) == 0:
        return round(min(99.0, max(0.0, prob * 100.0)), 2)
    quantile_pct = float(np.searchsorted(cal_sorted, prob, side="right") / len(cal_sorted) * 100.0)
    return round(min(99.0, max(prob * 100.0, quantile_pct)), 2)


def _fit_side_model(
    X: pd.DataFrame,
    y: np.ndarray,
    train_end: int,
    cal_start: int,
    cal_end: int,
    test_start: int,
    tp_atr: float = 2.0,
    sl_atr: float = 1.5,
) -> tuple[lgb.LGBMClassifier, LogisticRegression | None, np.ndarray, dict[str, Any]]:
    tr_mask = ~np.isnan(y[:train_end])
    X_tr = X.iloc[:train_end].loc[tr_mask]
    y_tr = y[:train_end][tr_mask].astype(int)

    cal_mask = ~np.isnan(y[cal_start:cal_end])
    X_cal = X.iloc[cal_start:cal_end].loc[cal_mask]
    y_cal = y[cal_start:cal_end][cal_mask].astype(int)

    te_mask = ~np.isnan(y[test_start:])
    X_te = X.iloc[test_start:].loc[te_mask]
    y_te = y[test_start:][te_mask].astype(int)

    if len(X_tr) < 120 or len(np.unique(y_tr)) < 2:
        raise ValueError("Insufficient balanced training samples for LightGBM.")

    model = lgb.LGBMClassifier(
        n_estimators=220,
        learning_rate=0.04,
        num_leaves=15,
        min_child_samples=40,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_alpha=1.0,
        reg_lambda=2.0,
        random_state=42,
        n_jobs=2,
        verbosity=-1,
    )
    model.fit(X_tr, y_tr)

    calibrator: LogisticRegression | None = None
    if len(X_cal) >= 40 and len(np.unique(y_cal)) >= 2:
        cal_raw = model.predict_proba(X_cal)[:, 1]
        cal = LogisticRegression(C=1.0, solver="lbfgs")
        cal.fit(_logit(cal_raw), y_cal)
        calibrator = cal

    cal_probs = _predict_calibrated(model, calibrator, X_cal) if len(X_cal) > 0 else np.array([0.45])
    cal_sorted = np.sort(cal_probs)

    probs_te = _predict_calibrated(model, calibrator, X_te) if len(X_te) > 0 else np.array([])
    conv_te = np.array([_prob_to_conviction(float(p), cal_sorted) for p in probs_te])

    auc_val: float | None = None
    if len(X_te) >= 10 and len(np.unique(y_te)) >= 2:
        auc_val = round(float(roc_auc_score(y_te, probs_te)), 4)

    base_wr = round(float(np.mean(y_te) * 100.0), 2) if len(y_te) > 0 else 0.0

    # Non-overlapping high-conviction OOS evaluation
    win_r = tp_atr / sl_atr
    hi65_mask = conv_te >= 65.0
    hi75_mask = conv_te >= 75.0
    hi65_cnt = int(np.sum(hi65_mask))
    hi75_cnt = int(np.sum(hi75_mask))
    hi65_wr = round(float(np.mean(y_te[hi65_mask]) * 100.0), 2) if hi65_cnt > 0 else None
    hi75_wr = round(float(np.mean(y_te[hi75_mask]) * 100.0), 2) if hi75_cnt > 0 else None

    net_r_75 = 0.0
    step_idx = 0
    raw_te_indices = X_te.index.to_numpy()
    next_allowed_bar = -1
    for pos_i, bar_idx in enumerate(raw_te_indices):
        if bar_idx < next_allowed_bar:
            continue
        if hi75_mask[pos_i]:
            net_r_75 += win_r if y_te[pos_i] == 1 else -1.0
            next_allowed_bar = int(bar_idx) + 12
            step_idx += 1

    metrics = {
        "train_samples": int(len(X_tr)),
        "oos_samples": int(len(X_te)),
        "oos_auc": auc_val,
        "oos_base_win_rate_pct": base_wr,
        "oos_trades_65": hi65_cnt,
        "oos_win_rate_65_pct": hi65_wr,
        "oos_trades_75": hi75_cnt,
        "oos_win_rate_75_pct": hi75_wr,
        "oos_net_r_75": round(net_r_75, 2),
        "oos_non_overlap_trades_75": step_idx,
    }
    return model, calibrator, cal_sorted, metrics


def train_symbol_model(symbol: str = "XAUUSD", tf: str = "M15", bars: int = 10000) -> dict[str, Any]:
    """Train walk-forward calibrated LightGBM BUY/SELL models on real MT5 historical bars."""
    tf_u = tf.upper()
    res = mt5_service.get_candles(symbol, tf_u, bars=bars)
    resolved = res["symbol"]
    candles = res["candles"]
    if len(candles) < 900:
        raise ValueError(f"Insufficient MT5 bars ({len(candles)}) to train ML model for {resolved} {tf_u}.")

    feat_df = build_feature_frame(candles)
    y_buy, y_sell = build_triple_barrier_labels(candles, tp_atr=2.0, sl_atr=1.5, horizon=24)

    warmup = min(260, len(feat_df) // 5)
    valid_df = feat_df.iloc[warmup:].dropna().copy()
    valid_idx = valid_df.index.to_numpy()
    y_buy_v = y_buy[valid_idx]
    y_sell_v = y_sell[valid_idx]
    valid_df = valid_df.reset_index(drop=True)

    n = len(valid_df)
    embargo = 24
    train_end = int(n * 0.68)
    cal_start = train_end + embargo
    cal_end = int(n * 0.80)
    test_start = cal_end + embargo

    if test_start >= n - 50:
        raise ValueError(f"Not enough valid rows ({n}) after warmup for chronological OOS split.")

    model_buy, cal_buy, cal_sorted_buy, m_buy = _fit_side_model(
        valid_df, y_buy_v, train_end, cal_start, cal_end, test_start
    )
    model_sell, cal_sell, cal_sorted_sell, m_sell = _fit_side_model(
        valid_df, y_sell_v, train_end, cal_start, cal_end, test_start
    )

    trained_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "symbol": resolved,
        "tf": tf_u,
        "trained_at": trained_at,
        "bars_requested": int(bars),
        "bars_used": int(n),
        "barrier_rule": "Triple-Barrier TP=2.0xATR / SL=1.5xATR / Horizon=24 bars (SL-first, Breakeven=42.9%)",
        "buy_metrics": m_buy,
        "sell_metrics": m_sell,
        "oos_summary": {
            "auc_buy": m_buy["oos_auc"],
            "auc_sell": m_sell["oos_auc"],
            "win_rate_65_buy_pct": m_buy["oos_win_rate_75_pct"] or m_buy["oos_win_rate_65_pct"],
            "win_rate_65_sell_pct": m_sell["oos_win_rate_75_pct"] or m_sell["oos_win_rate_65_pct"],
            "net_r_combined": round(m_buy["oos_net_r_75"] + m_sell["oos_net_r_75"], 2),
        },
    }

    bundle = {
        "model_buy": model_buy,
        "cal_buy": cal_buy,
        "cal_sorted_buy": cal_sorted_buy,
        "model_sell": model_sell,
        "cal_sell": cal_sell,
        "cal_sorted_sell": cal_sorted_sell,
        "feature_names": FEATURE_NAMES,
        "meta": meta,
    }

    path = _model_path(resolved, tf_u)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _MODEL_LOCK:
        joblib.dump(bundle, path)
        _MODEL_CACHE[f"{resolved}:{tf_u}"] = bundle

    return meta


def _load_bundle(symbol: str, tf: str, auto_train: bool = True) -> dict[str, Any]:
    key = f"{symbol.upper()}:{tf.upper()}"
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached

    path = _model_path(symbol, tf)
    if path.exists():
        with _MODEL_LOCK:
            bundle = joblib.load(path)
            _MODEL_CACHE[key] = bundle
            return bundle

    if auto_train:
        train_symbol_model(symbol, tf, bars=10000)
        return _load_bundle(symbol, tf, auto_train=False)

    raise FileNotFoundError(f"No trained ML model found for {symbol} {tf}.")


def get_model_status(symbol: str = "XAUUSD", tf: str = "M15") -> dict[str, Any]:
    """Return existence and OOS walk-forward metadata for a trained symbol/tf model."""
    resolved = mt5_service.resolve_symbol(symbol) if mt5_service.is_connected() else symbol.upper()
    path = _model_path(resolved, tf)
    if not path.exists():
        return {"trained": False, "symbol": resolved, "tf": tf.upper(), "meta": None}
    bundle = _load_bundle(resolved, tf, auto_train=False)
    return {"trained": True, "symbol": resolved, "tf": tf.upper(), "meta": bundle["meta"]}


def _compute_treeshap_drivers(
    model: lgb.LGBMClassifier,
    x_row: pd.DataFrame,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    """Compute exact native LightGBM TreeSHAP feature contributions in <1ms."""
    contribs = model.booster_.predict(x_row, pred_contrib=True)[0][:-1]
    drivers: list[dict[str, Any]] = []
    for idx, fname in enumerate(FEATURE_NAMES):
        sv = safe_float(contribs[idx], 4)
        fv = safe_float(x_row.iloc[0, idx], 4)
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
    min_confidence_pct: float = 75.0,
    auto_train: bool = True,
) -> dict[str, Any]:
    """Predict calibrated BUY/SELL probabilities, rank positive-EV conviction, fuse live news & MTF."""
    tf_u = tf.upper()
    res = mt5_service.get_candles(symbol, tf_u, bars=500)
    resolved = res["symbol"]
    candles = res["candles"]

    bundle = _load_bundle(resolved, tf_u, auto_train=auto_train)
    feat_df = build_feature_frame(candles)
    x_last = feat_df.iloc[[-1]].fillna(0.0)

    raw_p_buy = float(_predict_calibrated(bundle["model_buy"], bundle["cal_buy"], x_last)[0])
    raw_p_sell = float(_predict_calibrated(bundle["model_sell"], bundle["cal_sell"], x_last)[0])
    p_buy_pct = round(max(0.0, min(99.0, raw_p_buy * 100.0)), 2)
    p_sell_pct = round(max(0.0, min(99.0, raw_p_sell * 100.0)), 2)

    conv_buy = _prob_to_conviction(raw_p_buy, bundle.get("cal_sorted_buy"))
    conv_sell = _prob_to_conviction(raw_p_sell, bundle.get("cal_sorted_sell"))

    dir_u = direction.upper()
    if dir_u == "BUY":
        ml_raw_prob = p_buy_pct
        ml_conviction = conv_buy
        shap_model = bundle["model_buy"]
    elif dir_u == "SELL":
        ml_raw_prob = p_sell_pct
        ml_conviction = conv_sell
        shap_model = bundle["model_sell"]
    else:
        if conv_buy >= conv_sell:
            ml_raw_prob, ml_conviction, shap_model = p_buy_pct, conv_buy, bundle["model_buy"]
        else:
            ml_raw_prob, ml_conviction, shap_model = p_sell_pct, conv_sell, bundle["model_sell"]

    top_features = _compute_treeshap_drivers(shap_model, x_last, top_k=6)

    # Live news sentiment fusion (-12% to +12%)
    sent_score = float(news.get("sentiment_score") or 0.0)
    articles_cnt = len(news.get("articles") or [])
    high_impact = bool(news.get("high_impact_event"))

    if dir_u == "BUY":
        aligned_sent = sent_score
    elif dir_u == "SELL":
        aligned_sent = -sent_score
    else:
        aligned_sent = 0.0

    news_adj = aligned_sent * 14.0 if articles_cnt > 0 else 0.0
    if high_impact and aligned_sent < 0.15:
        news_adj -= 3.0
    news_adj = round(max(-12.0, min(12.0, news_adj)), 2)

    # MTF alignment confluence adjustment
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

    final_conf = round(max(0.0, min(99.0, ml_conviction + news_adj + mtf_bonus)), 2)
    meets_threshold = (dir_u in ("BUY", "SELL")) and (final_conf >= float(min_confidence_pct))

    return {
        "model_symbol": resolved,
        "model_tf": tf_u,
        "trained_at": bundle["meta"]["trained_at"],
        "ml_buy_prob_pct": p_buy_pct,
        "ml_sell_prob_pct": p_sell_pct,
        "ml_raw_prob_pct": round(ml_raw_prob, 2),
        "ml_conviction_pct": round(ml_conviction, 2),
        "news_adjustment_pct": news_adj,
        "mtf_bonus_pct": mtf_bonus,
        "final_confidence_pct": final_conf,
        "min_confidence_pct": float(min_confidence_pct),
        "meets_threshold": bool(meets_threshold),
        "top_features": top_features,
        "oos_summary": bundle["meta"]["oos_summary"],
    }
