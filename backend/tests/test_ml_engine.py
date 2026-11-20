"""Institutional Quant Audit & Anti-Leakage Test Suite for ML Engine v2.0."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ml_engine import (
    SCHEMA_VERSION,
    build_causal_htf_table,
    build_feature_frame,
    build_triple_barrier_labels,
    compute_composite_oos_score,
    prob_to_honest_edge_score,
)


def _synthetic_candles(n: int = 400, tf_sec: int = 900, start_ts: int = 1_700_000_000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    times = start_ts + np.arange(n, dtype=np.int64) * tf_sec
    rets = rng.normal(0.0, 0.0015, size=n)
    close = 2500.0 * np.exp(np.cumsum(rets))
    open_p = np.concatenate([[2500.0], close[:-1]])
    wick_hi = rng.uniform(0.5, 4.0, size=n)
    wick_lo = rng.uniform(0.5, 4.0, size=n)
    high = np.maximum(open_p, close) + wick_hi
    low = np.minimum(open_p, close) - wick_lo
    vol = rng.integers(50, 500, size=n)
    return pd.DataFrame(
        {
            "time": times,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": vol,
        }
    )


class TestQuantMLEngineAudit(unittest.TestCase):
    def test_zero_future_leakage_base_and_htf_features(self) -> None:
        """Mutating ANY candle strictly after bar `t` MUST NOT alter feature row `t` by even 1e-12."""
        start_ts = 1_700_000_000 - (1_700_000_000 % 3600)
        m15 = _synthetic_candles(n=360, tf_sec=900, start_ts=start_ts, seed=11)
        h1 = _synthetic_candles(n=100, tf_sec=3600, start_ts=start_ts - 3600 * 10, seed=22)

        t_idx = 260
        t_close_epoch = int(m15.loc[t_idx, "time"]) + 900

        feat_orig = build_feature_frame(m15, base_tf="M15", htf_candles_map={"h1": ("H1", h1)})

        # Aggressively corrupt ALL future M15 bars (> t_idx) and ALL H1 bars closing strictly after t_close_epoch
        m15_mut = m15.copy()
        m15_mut.loc[t_idx + 1 :, ["open", "high", "low", "close"]] *= 5.0
        m15_mut.loc[t_idx + 1 :, "tick_volume"] = 999999

        h1_mut = h1.copy()
        h1_future_mask = (h1_mut["time"] + 3600) > t_close_epoch
        h1_mut.loc[h1_future_mask, ["open", "high", "low", "close"]] *= 5.0

        feat_mut = build_feature_frame(m15_mut, base_tf="M15", htf_candles_map={"h1": ("H1", h1_mut)})

        row_a = feat_orig.iloc[t_idx].to_numpy(dtype=float)
        row_b = feat_mut.iloc[t_idx].to_numpy(dtype=float)
        max_diff = float(np.nanmax(np.abs(row_a - row_b)))
        self.assertEqual(max_diff, 0.0, f"Future leakage detected at bar {t_idx}: max_diff={max_diff}")

    def test_htf_close_time_causality_boundary(self) -> None:
        """An H1 candle opening at T (closing at T+3600) must NOT leak into M15 bars at T, T+900, T+1800."""
        base_start = 1_700_000_000 - (1_700_000_000 % 3600)
        h1 = _synthetic_candles(n=80, tf_sec=3600, start_ts=base_start, seed=3)
        target_h1_idx = 65
        target_open = int(h1.loc[target_h1_idx, "time"])

        # Spike the target H1 candle massively so any leakage is immediately unmistakable
        h1_spike = h1.copy()
        h1_spike.loc[target_h1_idx, "close"] *= 3.0
        h1_spike.loc[target_h1_idx, "high"] = h1_spike.loc[target_h1_idx, "close"] + 10.0

        m15_times = np.array(
            [target_open - 900, target_open, target_open + 900, target_open + 1800, target_open + 2700],
            dtype=np.int64,
        )
        m15 = _synthetic_candles(n=250, tf_sec=900, start_ts=target_open - 246 * 900, seed=5)
        m15.loc[245:, "time"] = m15_times

        f_clean = build_feature_frame(m15, base_tf="M15", htf_candles_map={"h1": ("H1", h1)})
        f_spike = build_feature_frame(m15, base_tf="M15", htf_candles_map={"h1": ("H1", h1_spike)})

        # Bars at target_open (closes +900), +900 (closes +1800), +1800 (closes +2700) MUST NOT see spiked H1 bar!
        for idx in (245, 246, 247, 248):
            diff = abs(float(f_clean.loc[idx, "h1_dist_ema50"]) - float(f_spike.loc[idx, "h1_dist_ema50"]))
            self.assertEqual(diff, 0.0, f"H1 bar leaked early into M15 bar idx={idx} (time={m15.loc[idx, 'time']})")

        # Bar at target_open + 2700 closes at target_open + 3600 == H1 close time -> NOW it may see the closed H1 bar!
        diff_closed = abs(float(f_clean.loc[249, "h1_dist_ema50"]) - float(f_spike.loc[249, "h1_dist_ema50"]))
        self.assertGreater(diff_closed, 0.0, "Closed H1 bar should become available once M15 bar closes at H1 close time")

    def test_spread_adjusted_triple_barrier_and_sl_first(self) -> None:
        """Verify spread penalizes both BUY (ASK entry) and SELL (ASK exit) and SL resolves before TP."""
        # Build flat warm-up candles with ATR ~ 10.0, then a single deterministic test bar
        n = 40
        times = 1_700_000_000 + np.arange(n) * 900
        df = pd.DataFrame(
            {
                "time": times,
                "open": np.full(n, 1000.0),
                "high": np.full(n, 1005.0),
                "low": np.full(n, 995.0),
                "close": np.full(n, 1000.0),
                "tick_volume": np.full(n, 100),
            }
        )
        # Bar 30 is signal bar (ATR = 10.0). Bar 31 is entry bar (open = 1000.0).
        # With tp_atr=2.0 (20.0), sl_atr=1.5 (15.0):
        # Zero-spread BUY: TP=1020, SL=985. With spread=2.0: entry_ask=1002, TP=1022, SL=987.
        df.loc[31, "high"] = 1021.0  # Hits zero-spread TP (1020), MISSES spread=2.0 TP (1022)!
        df.loc[31, "low"] = 999.0
        df.loc[32, "low"] = 986.5    # Hits spread=2.0 SL (987), MISSES zero-spread SL (985)!

        yb0, rb0, _, _ = build_triple_barrier_labels(df, tp_atr=2.0, sl_atr=1.5, horizon=10, spread_price=0.0)
        yb2, rb2, _, _ = build_triple_barrier_labels(df, tp_atr=2.0, sl_atr=1.5, horizon=10, spread_price=2.0)

        self.assertEqual(yb0[30], 1.0, "Zero-spread BUY should hit TP on bar 31")
        self.assertEqual(yb2[30], 0.0, "Spread=$2 BUY must miss TP(1022) and hit SL(987) on bar 32")
        self.assertEqual(rb2[30], -1.0)

        # Conservative SL-first intra-bar tie-breaking: bar 31 hits BOTH SL and TP -> MUST label as LOSS (0.0)
        df_both = df.copy()
        df_both.loc[31, "high"] = 1100.0
        df_both.loc[31, "low"] = 900.0
        yb_both, rb_both, ys_both, rs_both = build_triple_barrier_labels(df_both, tp_atr=2.0, sl_atr=1.5, horizon=5, spread_price=0.5)
        self.assertEqual(yb_both[30], 0.0, "SL-first tie-breaking must mark BUY loss when bar hits both")
        self.assertEqual(ys_both[30], 0.0, "SL-first tie-breaking must mark SELL loss when bar hits both")
        self.assertEqual(rb_both[30], -1.0)
        self.assertEqual(rs_both[30], -1.0)

    def test_honest_ev_and_no_percentile_inflation(self) -> None:
        """Negative-EV probabilities must ALWAYS yield EV <= 0 and edge_score < 50% (never 90%+!)."""
        # For TP=2.5, SL=1.5 -> R=1.6667, Breakeven=37.5%
        neg = prob_to_honest_edge_score(0.35, tp_atr=2.5, sl_atr=1.5)
        self.assertLess(neg["expected_value_r"], 0.0)
        self.assertLess(neg["edge_score_pct"], 50.0)
        self.assertEqual(neg["quarter_kelly_pct"], 0.0)

        be = prob_to_honest_edge_score(0.375, tp_atr=2.5, sl_atr=1.5)
        self.assertAlmostEqual(be["expected_value_r"], 0.0, places=3)
        self.assertLessEqual(be["edge_score_pct"], 50.0)

        pos1 = prob_to_honest_edge_score(0.45, tp_atr=2.5, sl_atr=1.5)
        pos2 = prob_to_honest_edge_score(0.55, tp_atr=2.5, sl_atr=1.5)
        self.assertGreater(pos1["expected_value_r"], 0.0)
        self.assertGreater(pos2["edge_score_pct"], pos1["edge_score_pct"])
        self.assertGreater(pos2["quarter_kelly_pct"], pos1["quarter_kelly_pct"])

    def test_champion_vs_challenger_scoring(self) -> None:
        """Stronger OOS model must strictly outscore weak/failing OOS model and legacy v1."""
        legacy = {"schema_version": "1.0"}
        weak = {
            "schema_version": SCHEMA_VERSION,
            "buy_metrics": {"oos_auc": 0.48, "oos_net_r_ev05": -12.0, "oos_profit_factor": 0.65, "oos_ece": 0.14, "oos_brier": 0.26, "quality_passed": False},
            "sell_metrics": {"oos_auc": 0.49, "oos_net_r_ev05": -5.0, "oos_profit_factor": 0.85, "oos_ece": 0.12, "oos_brier": 0.25, "quality_passed": False},
        }
        strong = {
            "schema_version": SCHEMA_VERSION,
            "buy_metrics": {"oos_auc": 0.54, "oos_net_r_ev05": 11.0, "oos_profit_factor": 1.35, "oos_ece": 0.05, "oos_brier": 0.22, "quality_passed": True},
            "sell_metrics": {"oos_auc": 0.56, "oos_net_r_ev05": 32.0, "oos_profit_factor": 1.60, "oos_ece": 0.03, "oos_brier": 0.23, "quality_passed": True},
        }
        s_leg = compute_composite_oos_score(legacy)
        s_weak = compute_composite_oos_score(weak)
        s_strong = compute_composite_oos_score(strong)
        self.assertGreater(s_weak, s_leg)
        self.assertGreater(s_strong, s_weak + 40.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
