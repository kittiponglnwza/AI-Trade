import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Clock,
  ExternalLink,
  FlaskConical,
  Newspaper,
  Play,
  Radar,
  RefreshCw,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  evaluateGauntlet,
  fetchBacktest,
  fetchMlStatus,
  fetchNews,
  fetchWatchlistScanner,
  trainMlModel,
} from "../services/api";
import type {
  BacktestResult,
  GauntletEvaluation,
  MLModelStatus,
  NewsResponse,
  Timeframe,
  WatchlistScannerItem,
} from "../types/trading";

interface GauntletPanelProps {
  symbol: string;
  timeframe: Timeframe;
  onProposalQueued: () => void;
}

export function GauntletPanel({ symbol, timeframe, onProposalQueued }: GauntletPanelProps) {
  const [riskPct, setRiskPct] = useState("2");
  const [minConfPct, setMinConfPct] = useState("75");
  const [slAtrMult, setSlAtrMult] = useState("1.5");
  const [tpAtrMult, setTpAtrMult] = useState("2.5");
  const [minRrRatio, setMinRrRatio] = useState("1.5");
  const [trainBars, setTrainBars] = useState("10000");
  const [btBars, setBtBars] = useState("600");
  const [gauntlet, setGauntlet] = useState<GauntletEvaluation | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [news, setNews] = useState<NewsResponse | null>(null);
  const [mlStatus, setMlStatus] = useState<MLModelStatus | null>(null);

  const [runningGauntlet, setRunningGauntlet] = useState(false);
  const [trainingMl, setTrainingMl] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [scanningWatchlist, setScanningWatchlist] = useState(false);
  const [scannerItems, setScannerItems] = useState<WatchlistScannerItem[] | null>(null);
  const [loadingNews, setLoadingNews] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingNews(true);
    fetchNews(symbol)
      .then((res) => {
        if (active) setNews(res);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoadingNews(false);
      });

    fetchMlStatus(symbol, timeframe)
      .then((res) => {
        if (active) setMlStatus(res);
      })
      .catch(() => {});

    return () => {
      active = false;
    };
  }, [symbol, timeframe]);

  const handleTrainMl = async () => {
    setTrainingMl(true);
    setErrMsg(null);
    setStatusMsg(null);
    try {
      const barsNum = Math.min(12000, Math.max(1000, parseInt(trainBars, 10) || 10000));
      const res = await trainMlModel(symbol, timeframe, barsNum);
      setMlStatus(res);
      const oos = res.meta?.oos_summary;
      setStatusMsg(
        `เทรนโมเดล LightGBM (${res.symbol} ${res.tf} · ${barsNum} แท่ง) สำเร็จ! OOS AUC B:${oos?.auc_buy ?? "-"}/S:${oos?.auc_sell ?? "-"} · Net OOS: ${oos?.net_r_combined ?? 0}R`
      );
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "เทรน ML ไม่สำเร็จ");
    } finally {
      setTrainingMl(false);
    }
  };

  const handleRunGauntlet = async (autoQueue = false) => {
    setRunningGauntlet(true);
    setErrMsg(null);
    setStatusMsg(null);
    try {
      const confGate = parseFloat(minConfPct) || 75;
      const slM = Math.max(0.4, parseFloat(slAtrMult) || 1.5);
      const tpM = Math.max(0.5, parseFloat(tpAtrMult) || 2.5);
      const rrM = Math.max(0.8, parseFloat(minRrRatio) || 1.5);
      const res = await evaluateGauntlet(
        symbol,
        timeframe,
        parseFloat(riskPct) || 2,
        autoQueue,
        confGate,
        slM,
        tpM,
        rrM
      );
      setGauntlet(res);
      setNews({
        symbol: res.symbol,
        fetched_at: res.evaluated_at,
        sentiment: res.news_summary.sentiment,
        sentiment_score: res.news_summary.sentiment_score,
        high_impact_event: res.news_summary.high_impact_event,
        high_impact_keywords: res.news_summary.high_impact_keywords,
        sources_used: res.news_summary.sources_used,
        articles: res.news,
      });
      if (autoQueue && res.queued_proposal) {
        setStatusMsg(
          `ส่ง Proposal #${res.queued_proposal.id} (${res.queued_proposal.side} ${res.queued_proposal.lots} ${res.symbol}) เข้าคิวรอยืนยันแล้ว!`
        );
        onProposalQueued();
      } else if (autoQueue && res.verdict !== "PASS") {
        const curConf = res.ml?.final_confidence_pct?.toFixed(1) ?? "?";
        setStatusMsg(
          `ยังไม่แนะนำให้ซื้อ/ขาย: Verdict=${res.verdict} (ML+News Confidence=${curConf}%, ต้อง >= ${confGate}%)`
        );
      }
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "รัน Gauntlet ไม่สำเร็จ");
    } finally {
      setRunningGauntlet(false);
    }
  };

  const handleRunBacktest = async () => {
    setRunningBacktest(true);
    setErrMsg(null);
    try {
      const barsNum = Math.min(1500, Math.max(120, parseInt(btBars, 10) || 600));
      const slM = Math.max(0.4, parseFloat(slAtrMult) || 1.5);
      const tpM = Math.max(0.5, parseFloat(tpAtrMult) || 2.5);
      const res = await fetchBacktest(symbol, timeframe, barsNum, slM, tpM);
      setBacktest(res);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "รัน Backtest ไม่สำเร็จ");
    } finally {
      setRunningBacktest(false);
    }
  };

  const handleRefreshNews = async () => {
    setLoadingNews(true);
    try {
      const res = await fetchNews(symbol, true);
      setNews(res);
    } finally {
      setLoadingNews(false);
    }
  };

  const handleScanWatchlistSetups = async () => {
    setScanningWatchlist(true);
    setErrMsg(null);
    try {
      const res = await fetchWatchlistScanner(timeframe);
      setScannerItems(res.items);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "สแกน Watchlist ไม่สำเร็จ");
    } finally {
      setScanningWatchlist(false);
    }
  };

  const ml = gauntlet?.ml;
  const dayTrader = gauntlet?.day_trader;
  const timeMachine = gauntlet?.time_machine;
  const oosSummary = ml?.oos_summary ?? mlStatus?.meta?.oos_summary ?? null;

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className="space-y-3 xl:col-span-7">
        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-[#4fc1ff]" />
              <div>
                <h2 className="text-sm font-semibold text-[#e1e1e1]">
                  9-Gate ML + News Gauntlet ({symbol} · {timeframe})
                </h2>
                <p className="text-[11px] text-[#9d9d9d]">
                  รวม LightGBM + ข่าวสด + MTF — ต้องมั่นใจ ≥ {minConfPct}% ถึงจะแนะนำให้เปิดไม้
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">Min Conf%</span>
                <input
                  type="number"
                  min="50"
                  max="95"
                  step="0.5"
                  value={minConfPct}
                  onChange={(e) => setMinConfPct(e.target.value)}
                  className="font-mono-num w-14 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#4fc1ff]"
                />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">Risk%</span>
                <input
                  type="number"
                  min="0.1"
                  max="50"
                  step="0.1"
                  value={riskPct}
                  onChange={(e) => setRiskPct(e.target.value)}
                  className="font-mono-num w-14 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#e1e1e1]"
                />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">SL/TP×ATR</span>
                <input
                  type="number"
                  min="0.4"
                  max="6"
                  step="0.1"
                  value={slAtrMult}
                  onChange={(e) => setSlAtrMult(e.target.value)}
                  className="font-mono-num w-12 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#f48771]"
                  title="SL × ATR Multiplier"
                />
                <input
                  type="number"
                  min="0.5"
                  max="10"
                  step="0.1"
                  value={tpAtrMult}
                  onChange={(e) => setTpAtrMult(e.target.value)}
                  className="font-mono-num w-12 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#3fb950]"
                  title="TP × ATR Multiplier"
                />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">Min R:R</span>
                <input
                  type="number"
                  min="0.8"
                  max="6"
                  step="0.1"
                  value={minRrRatio}
                  onChange={(e) => setMinRrRatio(e.target.value)}
                  className="font-mono-num w-12 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#dcdcaa]"
                />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">ML Bars</span>
                <input
                  type="number"
                  min="1000"
                  max="12000"
                  step="500"
                  value={trainBars}
                  onChange={(e) => setTrainBars(e.target.value)}
                  className="font-mono-num w-16 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-1.5 py-1 text-xs text-[#c586c0]"
                />
              </div>
              <button
                type="button"
                disabled={trainingMl}
                onClick={handleTrainMl}
                className="flex items-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1.5 text-xs font-medium text-[#c586c0] hover:bg-[#3c3c3c] disabled:opacity-50"
                title={`เทรนโมเดล LightGBM ใหม่จากแท่งเทียน MT5 ${trainBars} แท่ง`}
              >
                <Brain className="h-3.5 w-3.5" />
                {trainingMl ? "Training..." : mlStatus?.trained ? "Retrain ML" : "Train ML"}
              </button>
              <button
                type="button"
                disabled={scanningWatchlist}
                onClick={handleScanWatchlistSetups}
                className="flex items-center gap-1.5 rounded border border-[#4ec9b0]/50 bg-[#4ec9b0]/15 px-2.5 py-1.5 text-xs font-semibold text-[#4ec9b0] hover:bg-[#4ec9b0]/25 disabled:opacity-50"
                title="สแกนหา ORB / Flag / VWAP Reclaim / 20-Bar Breakout บนแท่งเทียนที่ปิดแล้วทุกตัวใน Watchlist (/trader-scanner)"
              >
                <Radar className="h-3.5 w-3.5" />
                {scanningWatchlist ? "Scanning..." : "Scan Setups"}
              </button>
              <button
                type="button"
                disabled={runningGauntlet}
                onClick={() => handleRunGauntlet(false)}
                className="flex items-center gap-1.5 rounded bg-[#007acc] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5" />
                {runningGauntlet ? "Evaluating..." : "Run 9-Gate + TimeMachine"}
              </button>
              <button
                type="button"
                disabled={runningGauntlet}
                onClick={() => handleRunGauntlet(true)}
                className="flex items-center gap-1.5 rounded bg-[#238636] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                Queue if ≥{minConfPct}%
              </button>
            </div>
          </div>

          {errMsg && (
            <div className="mt-3 rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 p-2.5 text-xs text-[#f48771] break-words">
              {errMsg}
            </div>
          )}
          {statusMsg && (
            <div className="mt-3 rounded border border-[#3fb950]/40 bg-[#1e3a29]/40 p-2.5 text-xs text-[#3fb950] break-words">
              {statusMsg}
            </div>
          )}

          {ml && (
            <div className="mt-3 rounded border border-[#007acc]/50 bg-[#1e1e1e] p-3 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-[#c586c0]" />
                  <span className="text-xs font-semibold text-[#e1e1e1]">
                    LightGBM + Live News Confidence
                  </span>
                </div>
                <div className="font-mono-num flex items-center gap-2">
                  <span className="text-lg font-bold text-[#e1e1e1]">
                    {ml.final_confidence_pct.toFixed(1)}%
                  </span>
                  <span
                    className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                      ml.meets_threshold
                        ? "bg-[#3fb950]/20 text-[#3fb950]"
                        : "bg-[#f14c4c]/20 text-[#f14c4c]"
                    }`}
                  >
                    {ml.meets_threshold
                      ? `PASS >= ${ml.min_confidence_pct}%`
                      : `BLOCKED < ${ml.min_confidence_pct}%`}
                  </span>
                </div>
              </div>

              <div className="font-mono-num grid grid-cols-2 gap-2 rounded border border-[#2b2b2b] bg-[#252526] p-2 text-[11px] sm:grid-cols-4">
                <div>
                  <span className="text-[#9d9d9d]">ML Conviction: </span>
                  <strong className="text-[#4fc1ff]">
                    {(ml.ml_conviction_pct ?? ml.ml_raw_prob_pct).toFixed(1)}%
                  </strong>
                  <div className="text-[10px] text-[#6e6e6e]">
                    Raw P(Win): {ml.ml_raw_prob_pct.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <span className="text-[#9d9d9d]">News Fusion: </span>
                  <strong
                    className={
                      ml.news_adjustment_pct >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                    }
                  >
                    {ml.news_adjustment_pct >= 0 ? "+" : ""}
                    {ml.news_adjustment_pct.toFixed(1)}%
                  </strong>
                </div>
                <div>
                  <span className="text-[#9d9d9d]">MTF Bonus: </span>
                  <strong
                    className={ml.mtf_bonus_pct >= 0 ? "text-[#dcdcaa]" : "text-[#f14c4c]"}
                  >
                    {ml.mtf_bonus_pct >= 0 ? "+" : ""}
                    {ml.mtf_bonus_pct.toFixed(1)}%
                  </strong>
                </div>
                <div>
                  <span className="text-[#9d9d9d]">Setup + 10k Sim: </span>
                  <strong
                    className={
                      (ml.day_trader_bonus_pct ?? 0) + (ml.time_machine_bonus_pct ?? 0) >= 0
                        ? "text-[#4ec9b0]"
                        : "text-[#f14c4c]"
                    }
                  >
                    {(ml.day_trader_bonus_pct ?? 0) + (ml.time_machine_bonus_pct ?? 0) >= 0 ? "+" : ""}
                    {((ml.day_trader_bonus_pct ?? 0) + (ml.time_machine_bonus_pct ?? 0)).toFixed(1)}%
                  </strong>
                  <div className="text-[10px] text-[#6e6e6e]">
                    Setup {(ml.day_trader_bonus_pct ?? 0) >= 0 ? "+" : ""}
                    {(ml.day_trader_bonus_pct ?? 0).toFixed(1)}% · TM {(ml.time_machine_bonus_pct ?? 0) >= 0 ? "+" : ""}
                    {(ml.time_machine_bonus_pct ?? 0).toFixed(1)}%
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <div>
                  <div className="font-mono-num mb-1 flex justify-between">
                    <span className="text-[#3fb950]">P(BUY)</span>
                    <span className="text-[#e1e1e1]">{ml.ml_buy_prob_pct.toFixed(1)}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded bg-[#2b2b2b]">
                    <div
                      className="h-full bg-[#3fb950]"
                      style={{ width: `${Math.min(100, ml.ml_buy_prob_pct)}%` }}
                    />
                  </div>
                </div>
                <div>
                  <div className="font-mono-num mb-1 flex justify-between">
                    <span className="text-[#f14c4c]">P(SELL)</span>
                    <span className="text-[#e1e1e1]">{ml.ml_sell_prob_pct.toFixed(1)}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded bg-[#2b2b2b]">
                    <div
                      className="h-full bg-[#f14c4c]"
                      style={{ width: `${Math.min(100, ml.ml_sell_prob_pct)}%` }}
                    />
                  </div>
                </div>
              </div>

              {ml.top_features.length > 0 && (
                <div className="border-t border-[#2b2b2b] pt-2">
                  <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#9d9d9d]">
                    Top TreeSHAP Drivers (เหตุผลที่โมเดล LightGBM ให้คะแนน)
                  </div>
                  <div className="font-mono-num grid grid-cols-1 gap-1 sm:grid-cols-2 text-[11px]">
                    {ml.top_features.slice(0, 6).map((f) => (
                      <div
                        key={f.feature}
                        className="flex items-center justify-between rounded bg-[#252526] px-2 py-1"
                      >
                        <span className="text-[#cccccc]">{f.feature}</span>
                        <span
                          className={
                            f.shap_value >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                          }
                        >
                          {f.shap_value >= 0 ? "+" : ""}
                          {f.shap_value.toFixed(3)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {timeMachine && timeMachine.replays > 0 && (
            <div className="mt-3 rounded border border-[#4ec9b0]/50 bg-[#1e1e1e] p-3 space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-[#4ec9b0]" />
                  <div>
                    <div className="text-xs font-semibold text-[#e1e1e1]">
                      Time Machine ({timeMachine.replays.toLocaleString()} Time-of-Day Replays · Seed {timeMachine.seed})
                    </div>
                    <div className="text-[11px] text-[#9d9d9d]">{timeMachine.verdict_th}</div>
                  </div>
                </div>
                <span
                  className={`font-mono-num rounded px-2 py-0.5 text-[10px] font-bold ${
                    timeMachine.verdict === "STRONGLY_TARGET" || timeMachine.verdict === "LEANS_TARGET"
                      ? "bg-[#3fb950]/20 text-[#3fb950]"
                      : timeMachine.verdict === "COIN_FLIP"
                      ? "bg-[#cca700]/20 text-[#dcdcaa]"
                      : "bg-[#f14c4c]/20 text-[#f14c4c]"
                  }`}
                >
                  {timeMachine.verdict} · EV {timeMachine.expected_r >= 0 ? "+" : ""}
                  {timeMachine.expected_r}R
                </span>
              </div>

              <div className="space-y-1">
                <div className="font-mono-num flex justify-between text-[11px]">
                  <span className="text-[#3fb950]">🎯 ชน TP ก่อน: {timeMachine.target_first_pct}%</span>
                  <span className="text-[#9d9d9d]">⏱️ ยังไม่ชน ({timeMachine.horizon_bars} แท่ง): {timeMachine.neither_pct}%</span>
                  <span className="text-[#f14c4c]">🛑 ชน SL ก่อน: {timeMachine.stop_first_pct}%</span>
                </div>
                <div className="flex h-2 w-full overflow-hidden rounded bg-[#2b2b2b]">
                  <div
                    className="h-full bg-[#3fb950]"
                    style={{ width: `${timeMachine.target_first_pct}%` }}
                  />
                  <div
                    className="h-full bg-[#6e6e6e]"
                    style={{ width: `${timeMachine.neither_pct}%` }}
                  />
                  <div
                    className="h-full bg-[#f14c4c]"
                    style={{ width: `${timeMachine.stop_first_pct}%` }}
                  />
                </div>
              </div>

              <div className="font-mono-num grid grid-cols-2 gap-2 rounded border border-[#2b2b2b] bg-[#252526] p-2 text-[11px] sm:grid-cols-4">
                <div>
                  <div className="text-[10px] text-[#9d9d9d]">Resolved Win Rate</div>
                  <div className="font-bold text-[#e1e1e1]">
                    {timeMachine.resolved_win_rate_pct}%{" "}
                    <span className="text-[10px] font-normal text-[#9d9d9d]">
                      (BE {timeMachine.breakeven_win_rate_pct}%)
                    </span>
                  </div>
                </div>
                <div>
                  <div className="text-[10px] text-[#9d9d9d]">Edge vs Breakeven</div>
                  <div
                    className={`font-bold ${
                      timeMachine.edge_vs_breakeven_pp >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                    }`}
                  >
                    {timeMachine.edge_vs_breakeven_pp >= 0 ? "+" : ""}
                    {timeMachine.edge_vs_breakeven_pp} pp
                  </div>
                </div>
                <div>
                  <div className="text-[10px] text-[#9d9d9d]">Green at Close</div>
                  <div className="font-bold text-[#4ec9b0]">{timeMachine.green_at_close_pct}%</div>
                </div>
                <div>
                  <div className="text-[10px] text-[#9d9d9d]">Price Fan (P5 / P50 / P95)</div>
                  <div className="text-[10px] font-semibold text-[#cccccc]">
                    {timeMachine.price_percentiles.p5} / {timeMachine.price_percentiles.p50_median} /{" "}
                    {timeMachine.price_percentiles.p95}
                  </div>
                </div>
              </div>
            </div>
          )}

          {dayTrader && (
            <div className="mt-3 rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Radar className="h-4 w-4 text-[#dcdcaa]" />
                  <div>
                    <div className="text-xs font-semibold text-[#e1e1e1]">
                      Day-Trader Setup Scanner & Closed-Bar Entry Timer ({dayTrader.active_setup_label})
                    </div>
                    <div className="text-[11px] text-[#9d9d9d]">{dayTrader.entry_timer_detail}</div>
                  </div>
                </div>
                <span
                  className={`font-mono-num rounded px-2 py-0.5 text-[10px] font-bold ${
                    dayTrader.entry_timer_state === "TRIGGERED_ON_CLOSED_BAR"
                      ? "bg-[#3fb950]/20 text-[#3fb950]"
                      : dayTrader.entry_timer_state === "FORMING_BAR_POKE_WAIT"
                      ? "bg-[#cca700]/20 text-[#dcdcaa]"
                      : "bg-[#313131] text-[#9d9d9d]"
                  }`}
                >
                  {dayTrader.entry_timer_state}
                </span>
              </div>

              {dayTrader.opening_range && (
                <div className="font-mono-num flex flex-wrap gap-3 rounded border border-[#2b2b2b] bg-[#252526] px-2.5 py-1.5 text-[11px] text-[#cccccc]">
                  <span>
                    OR High: <strong className="text-[#3fb950]">{dayTrader.opening_range.or_high}</strong>
                  </span>
                  <span>
                    OR Mid (SL): <strong className="text-[#dcdcaa]">{dayTrader.opening_range.or_mid}</strong>
                  </span>
                  <span>
                    OR Low: <strong className="text-[#f14c4c]">{dayTrader.opening_range.or_low}</strong>
                  </span>
                  <span>
                    Session VWAP: <strong className="text-[#4fc1ff]">{dayTrader.opening_range.session_vwap}</strong>
                  </span>
                  <span>
                    Vol Ratio: <strong className="text-[#c586c0]">{dayTrader.opening_range.vol_ratio_x}x</strong>
                  </span>
                </div>
              )}

              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 text-[11px]">
                {dayTrader.setups.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-start justify-between gap-2 rounded border border-[#2b2b2b] bg-[#252526] px-2.5 py-1.5"
                  >
                    <div>
                      <div className="font-semibold text-[#e1e1e1]">{s.label}</div>
                      <div className="text-[10px] text-[#9d9d9d]">{s.detail}</div>
                    </div>
                    <span
                      className={`font-mono-num shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold ${
                        s.status === "TRIGGERED"
                          ? "bg-[#3fb950]/20 text-[#3fb950]"
                          : s.status === "FORMING_POKE"
                          ? "bg-[#cca700]/20 text-[#dcdcaa]"
                          : "bg-[#1e1e1e] text-[#6e6e6e]"
                      }`}
                    >
                      {s.status} {s.side !== "NONE" ? s.side : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scannerItems && (
            <div className="mt-3 rounded border border-[#4ec9b0]/40 bg-[#1e1e1e] p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[#4ec9b0]">
                  Watchlist Multi-Setup Scanner ({timeframe} · Closed-Bar Confirmation)
                </span>
                <button
                  type="button"
                  onClick={() => setScannerItems(null)}
                  className="text-[11px] text-[#9d9d9d] hover:text-white"
                >
                  ซ่อนตาราง
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="font-mono-num w-full text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-[#2b2b2b] text-[#9d9d9d]">
                      <th className="py-1 pr-2">Symbol</th>
                      <th className="py-1 pr-2">Bid</th>
                      <th className="py-1 pr-2">Active Setup</th>
                      <th className="py-1 pr-2">Timer Status</th>
                      <th className="py-1 pr-2">OR Mid / VWAP</th>
                      <th className="py-1 text-right">Vol</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#2b2b2b]">
                    {scannerItems.map((it) => (
                      <tr key={it.symbol} className="hover:bg-[#2a2d2e]">
                        <td className="py-1.5 pr-2 font-bold text-[#e1e1e1]">{it.symbol}</td>
                        <td className="py-1.5 pr-2 text-[#cccccc]">{it.bid}</td>
                        <td className="py-1.5 pr-2 text-[#e1e1e1]">
                          {it.active_setup_label}{" "}
                          {it.active_setup_side !== "NONE" && (
                            <span
                              className={`ml-1 rounded px-1 py-0.5 text-[9px] font-bold ${
                                it.active_setup_side === "BUY"
                                  ? "bg-[#3fb950]/20 text-[#3fb950]"
                                  : "bg-[#f14c4c]/20 text-[#f14c4c]"
                              }`}
                            >
                              {it.active_setup_side}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 pr-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${
                              it.entry_timer_state === "TRIGGERED_ON_CLOSED_BAR"
                                ? "bg-[#3fb950]/20 text-[#3fb950]"
                                : it.entry_timer_state === "FORMING_BAR_POKE_WAIT"
                                ? "bg-[#cca700]/20 text-[#dcdcaa]"
                                : "text-[#6e6e6e]"
                            }`}
                          >
                            {it.entry_timer_state}
                          </span>
                        </td>
                        <td className="py-1.5 pr-2 text-[#9d9d9d]">
                          {it.or_mid} / {it.session_vwap}
                        </td>
                        <td className="py-1.5 text-right text-[#c586c0]">{it.vol_ratio_x}x</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {oosSummary && (
            <div className="font-mono-num mt-2 flex flex-wrap items-center justify-between gap-2 rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2 text-[11px] text-[#9d9d9d]">
              <span>
                Walk-Forward Out-of-Sample Proof ({mlStatus?.meta?.bars_used ?? "5,000+"} bars):
              </span>
              <span className="text-[#e1e1e1]">
                AUC B:{oosSummary.auc_buy ?? "-"} / S:{oosSummary.auc_sell ?? "-"} · High-Conf WR B:
                {oosSummary.win_rate_65_buy_pct ?? "-"}% / S:
                {oosSummary.win_rate_65_sell_pct ?? "-"}% · Net{" "}
                <strong
                  className={
                    oosSummary.net_r_combined >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                  }
                >
                  {oosSummary.net_r_combined >= 0 ? "+" : ""}
                  {oosSummary.net_r_combined}R
                </strong>
              </span>
            </div>
          )}

          {!gauntlet ? (
            <div className="mt-3 rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] px-4 py-8 text-center text-xs text-[#9d9d9d]">
              กด <strong>&ldquo;Run 9-Gate&rdquo;</strong> เพื่อดูผลประเมินครบทั้ง 9 ด่าน (รวม LightGBM + ข่าวสด + TreeSHAP)
            </div>
          ) : (
            <div className="mt-3 space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-bold ${
                      gauntlet.verdict === "PASS"
                        ? "bg-[#3fb950]/20 text-[#3fb950]"
                        : gauntlet.verdict === "WAIT"
                        ? "bg-[#cca700]/20 text-[#dcdcaa]"
                        : "bg-[#f14c4c]/20 text-[#f14c4c]"
                    }`}
                  >
                    VERDICT: {gauntlet.verdict} {gauntlet.direction}
                  </span>
                  <span className="font-mono-num text-xs font-semibold text-[#e1e1e1]">
                    {gauntlet.passed_count}/{gauntlet.total_gates} PASS · {gauntlet.warn_count} WARN ·{" "}
                    {gauntlet.fail_count} FAIL
                  </span>
                </div>
                <span className="font-mono-num text-[11px] text-[#6e6e6e]">
                  {gauntlet.evaluated_at}
                </span>
              </div>

              <div className="space-y-1.5">
                {gauntlet.gates.map((g) => (
                  <div
                    key={g.id}
                    className="flex items-start justify-between gap-3 rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2 text-xs"
                  >
                    <div className="flex items-start gap-2">
                      {g.status === "PASS" ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#3fb950]" />
                      ) : g.status === "WARN" ? (
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#dcdcaa]" />
                      ) : (
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#f14c4c]" />
                      )}
                      <div>
                        <div className="font-semibold text-[#e1e1e1]">{g.label}</div>
                        <div className="text-[11px] text-[#9d9d9d] break-words">{g.detail}</div>
                      </div>
                    </div>
                    <span
                      className={`font-mono-num shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        g.status === "PASS"
                          ? "bg-[#3fb950]/15 text-[#3fb950]"
                          : g.status === "WARN"
                          ? "bg-[#cca700]/15 text-[#dcdcaa]"
                          : "bg-[#f14c4c]/15 text-[#f14c4c]"
                      }`}
                    >
                      {g.status} · {g.metric}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] pb-3">
            <div className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-[#c586c0]" />
              <div>
                <h3 className="text-sm font-semibold text-[#e1e1e1]">
                  MT5 Historical Backtest ({symbol} · {timeframe})
                </h3>
                <p className="text-[11px] text-[#9d9d9d]">
                  ทดสอบย้อนหลัง 600 แท่งจริงจาก MT5 (EMA20/50/200 + RSI · SL 1.5xATR / TP 2.5xATR)
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">Bars</span>
                <input
                  type="number"
                  min="120"
                  max="1500"
                  step="60"
                  value={btBars}
                  onChange={(e) => setBtBars(e.target.value)}
                  className="font-mono-num w-16 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-1 text-xs text-[#e1e1e1]"
                />
              </div>
              <button
                type="button"
                disabled={runningBacktest}
                onClick={handleRunBacktest}
                className="flex items-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs font-semibold text-[#e1e1e1] hover:bg-[#3c3c3c] disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5 text-[#c586c0]" />
                {runningBacktest ? "Backtesting..." : `Run Backtest (${btBars} Bars)`}
              </button>
            </div>
          </div>

          {!backtest ? (
            <div className="mt-3 rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] px-4 py-6 text-center text-xs text-[#9d9d9d]">
              กด <strong>&ldquo;Run Backtest (600 Bars)&rdquo;</strong> เพื่อพิสูจน์สถิติย้อนหลังจริง
            </div>
          ) : (
            <div className="mt-3 space-y-3">
              <div className="font-mono-num grid grid-cols-2 gap-2 sm:grid-cols-5">
                <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2.5">
                  <div className="text-[10px] text-[#9d9d9d]">TRADES</div>
                  <div className="text-base font-bold text-[#e1e1e1]">
                    {backtest.total_trades} ({backtest.wins}W/{backtest.losses}L)
                  </div>
                </div>
                <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2.5">
                  <div className="text-[10px] text-[#9d9d9d]">WIN RATE</div>
                  <div className="text-base font-bold text-[#4fc1ff]">
                    {backtest.win_rate_pct.toFixed(1)}%
                  </div>
                </div>
                <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2.5">
                  <div className="text-[10px] text-[#9d9d9d]">PROFIT FACTOR</div>
                  <div className="text-base font-bold text-[#dcdcaa]">
                    {backtest.profit_factor === null ? "∞" : backtest.profit_factor.toFixed(2)}
                  </div>
                </div>
                <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2.5">
                  <div className="text-[10px] text-[#9d9d9d]">NET RETURN</div>
                  <div
                    className={`text-base font-bold ${
                      backtest.net_r >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                    }`}
                  >
                    {backtest.net_r >= 0 ? "+" : ""}
                    {backtest.net_r.toFixed(2)}R
                  </div>
                </div>
                <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2.5">
                  <div className="text-[10px] text-[#9d9d9d]">MAX DD</div>
                  <div className="text-base font-bold text-[#f14c4c]">
                    -{backtest.max_drawdown_r.toFixed(2)}R
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2">
                <table className="font-mono-num w-full min-w-[540px] text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-[#2b2b2b] text-[#9d9d9d]">
                      <th className="py-1.5 pr-2">Entry Time</th>
                      <th className="py-1.5 pr-2">Side</th>
                      <th className="py-1.5 pr-2">Entry</th>
                      <th className="py-1.5 pr-2">Exit</th>
                      <th className="py-1.5 pr-2 text-right">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#2b2b2b]">
                    {backtest.recent_trades.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="py-4 text-center text-[#6e6e6e]">
                          ไม่พบสัญญาณเข้าเงื่อนไขในช่วง {backtest.bars_tested} แท่งนี้
                        </td>
                      </tr>
                    ) : (
                      backtest.recent_trades.slice(0, 10).map((t, idx) => (
                        <tr key={`${t.entry_time}-${idx}`} className="hover:bg-[#2a2d2e]">
                          <td className="py-1.5 pr-2 text-[#9d9d9d]">{t.entry_time}</td>
                          <td
                            className={`py-1.5 pr-2 font-bold ${
                              t.side === "BUY" ? "text-[#3fb950]" : "text-[#f14c4c]"
                            }`}
                          >
                            {t.side}
                          </td>
                          <td className="py-1.5 pr-2 text-[#cccccc]">{t.entry}</td>
                          <td className="py-1.5 pr-2 text-[#cccccc]">{t.exit}</td>
                          <td
                            className={`py-1.5 text-right font-bold ${
                              t.result_r >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                            }`}
                          >
                            {t.result_r >= 0 ? "+" : ""}
                            {t.result_r.toFixed(2)}R
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="xl:col-span-5">
        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
          <div className="flex items-center justify-between gap-2 border-b border-[#2b2b2b] pb-3">
            <div className="flex items-center gap-2">
              <Newspaper className="h-4 w-4 text-[#dcdcaa]" />
              <div>
                <h2 className="text-sm font-semibold text-[#e1e1e1]">
                  Live News & Citations ({symbol})
                </h2>
                <p className="text-[11px] text-[#9d9d9d]">
                  ข่าวเหล่านี้ถูกนำไปคำนวณคะแนน ML + News Fusion โดยตรง
                </p>
              </div>
            </div>
            <button
              type="button"
              disabled={loadingNews}
              onClick={handleRefreshNews}
              className="flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1 text-xs text-[#cccccc] hover:bg-[#3c3c3c] disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loadingNews ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>

          {news && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2 text-xs">
              <span>
                News Sentiment:{" "}
                <strong
                  className={
                    news.sentiment === "BULLISH"
                      ? "text-[#3fb950]"
                      : news.sentiment === "BEARISH"
                      ? "text-[#f14c4c]"
                      : "text-[#dcdcaa]"
                  }
                >
                  {news.sentiment} ({news.sentiment_score >= 0 ? "+" : ""}
                  {news.sentiment_score})
                </strong>
              </span>
              {news.high_impact_event && (
                <span className="rounded border border-[#cca700]/40 bg-[#cca700]/15 px-2 py-0.5 text-[10px] font-semibold text-[#dcdcaa]">
                  Catalysts: {news.high_impact_keywords.slice(0, 3).join(", ")}
                </span>
              )}
            </div>
          )}

          <div className="mt-3 max-h-[680px] space-y-2 overflow-y-auto pr-1">
            {!news || news.articles.length === 0 ? (
              <div className="rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] px-4 py-8 text-center text-xs text-[#6e6e6e]">
                {loadingNews ? "Loading live news feeds..." : "ไม่พบข่าวสำหรับสัญลักษณ์นี้"}
              </div>
            ) : (
              news.articles.map((art, idx) => (
                <a
                  key={`${art.url}-${idx}`}
                  href={art.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3 transition hover:border-[#007acc] hover:bg-[#2a2d2e]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-medium leading-snug text-[#e1e1e1] break-words">
                      {art.title}
                    </span>
                    <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#4fc1ff]" />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px]">
                    <span className="font-semibold text-[#4fc1ff]">{art.source}</span>
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`rounded px-1.5 py-0.5 font-semibold ${
                          art.sentiment_tag === "BULLISH"
                            ? "bg-[#3fb950]/15 text-[#3fb950]"
                            : art.sentiment_tag === "BEARISH"
                            ? "bg-[#f14c4c]/15 text-[#f14c4c]"
                            : "bg-[#313131] text-[#9d9d9d]"
                        }`}
                      >
                        {art.sentiment_tag}
                      </span>
                      <span className="text-[#6e6e6e]">{art.published.slice(0, 22)}</span>
                    </div>
                  </div>
                </a>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
