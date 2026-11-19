import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ExternalLink,
  FlaskConical,
  Newspaper,
  Play,
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
  trainMlModel,
} from "../services/api";
import type {
  BacktestResult,
  GauntletEvaluation,
  MLModelStatus,
  NewsResponse,
  Timeframe,
} from "../types/trading";

interface GauntletPanelProps {
  symbol: string;
  timeframe: Timeframe;
  onProposalQueued: () => void;
}

export function GauntletPanel({ symbol, timeframe, onProposalQueued }: GauntletPanelProps) {
  const [riskPct, setRiskPct] = useState("15");
  const [minConfPct, setMinConfPct] = useState("75");
  const [gauntlet, setGauntlet] = useState<GauntletEvaluation | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [news, setNews] = useState<NewsResponse | null>(null);
  const [mlStatus, setMlStatus] = useState<MLModelStatus | null>(null);

  const [runningGauntlet, setRunningGauntlet] = useState(false);
  const [trainingMl, setTrainingMl] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
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
      const res = await trainMlModel(symbol, timeframe, 10000);
      setMlStatus(res);
      const oos = res.meta?.oos_summary;
      setStatusMsg(
        `เทรนโมเดล LightGBM (${res.symbol} ${res.tf}) สำเร็จ! OOS AUC B:${oos?.auc_buy ?? "-"}/S:${oos?.auc_sell ?? "-"} · Net OOS: ${oos?.net_r_combined ?? 0}R`
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
      const res = await evaluateGauntlet(
        symbol,
        timeframe,
        parseFloat(riskPct) || 15,
        autoQueue,
        confGate
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
      const res = await fetchBacktest(symbol, timeframe, 600);
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

  const ml = gauntlet?.ml;
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
                  step="1"
                  value={minConfPct}
                  onChange={(e) => setMinConfPct(e.target.value)}
                  className="font-mono-num w-14 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-1 text-xs text-[#4fc1ff]"
                />
              </div>
              <div className="flex items-center gap-1 text-xs">
                <span className="text-[#9d9d9d]">Risk%</span>
                <input
                  type="number"
                  min="1"
                  max="40"
                  step="1"
                  value={riskPct}
                  onChange={(e) => setRiskPct(e.target.value)}
                  className="font-mono-num w-14 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-1 text-xs text-[#e1e1e1]"
                />
              </div>
              <button
                type="button"
                disabled={trainingMl}
                onClick={handleTrainMl}
                className="flex items-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1.5 text-xs font-medium text-[#c586c0] hover:bg-[#3c3c3c] disabled:opacity-50"
                title="เทรนโมเดล LightGBM ใหม่จากแท่งเทียน MT5 6,000 แท่ง"
              >
                <Brain className="h-3.5 w-3.5" />
                {trainingMl ? "Training..." : mlStatus?.trained ? "Retrain ML" : "Train ML"}
              </button>
              <button
                type="button"
                disabled={runningGauntlet}
                onClick={() => handleRunGauntlet(false)}
                className="flex items-center gap-1.5 rounded bg-[#007acc] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5" />
                {runningGauntlet ? "Evaluating..." : "Run 9-Gate"}
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

              <div className="font-mono-num grid grid-cols-3 gap-2 rounded border border-[#2b2b2b] bg-[#252526] p-2 text-[11px]">
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
            <button
              type="button"
              disabled={runningBacktest}
              onClick={handleRunBacktest}
              className="flex items-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs font-semibold text-[#e1e1e1] hover:bg-[#3c3c3c] disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5 text-[#c586c0]" />
              {runningBacktest ? "Backtesting..." : "Run Backtest (600 Bars)"}
            </button>
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
