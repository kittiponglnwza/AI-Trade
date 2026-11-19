import { useEffect, useState } from "react";
import {
  AlertTriangle,
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
import { evaluateGauntlet, fetchBacktest, fetchNews } from "../services/api";
import type {
  BacktestResult,
  GauntletEvaluation,
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
  const [gauntlet, setGauntlet] = useState<GauntletEvaluation | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [news, setNews] = useState<NewsResponse | null>(null);

  const [runningGauntlet, setRunningGauntlet] = useState(false);
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
    return () => {
      active = false;
    };
  }, [symbol]);

  const handleRunGauntlet = async (autoQueue = false) => {
    setRunningGauntlet(true);
    setErrMsg(null);
    setStatusMsg(null);
    try {
      const res = await evaluateGauntlet(symbol, timeframe, parseFloat(riskPct) || 15, autoQueue);
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
          `ส่ง Proposal #${res.queued_proposal.id} (${res.queued_proposal.side} ${res.queued_proposal.lots} ${res.symbol}) เข้าคิวรอยืนยันแล้ว`
        );
        onProposalQueued();
      } else if (autoQueue && res.verdict !== "PASS") {
        setStatusMsg(`ยังไม่ส่งเข้าคิว: Verdict คือ ${res.verdict} (ไม่ผ่านครบ 8 ด่านแบบไร้ Hard Fail)`);
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

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className="space-y-3 xl:col-span-7">
        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-[#4fc1ff]" />
              <div>
                <h2 className="text-sm font-semibold text-[#e1e1e1]">
                  8-Gate Trading Gauntlet ({symbol} · {timeframe})
                </h2>
                <p className="text-[11px] text-[#9d9d9d]">
                  ตรวจสอบ 8 ด่านทั้งเทคนิค สเปรด ข่าว และ Margin จริงจาก MT5 ก่อนเสนอออเดอร์
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
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
                disabled={runningGauntlet}
                onClick={() => handleRunGauntlet(false)}
                className="flex items-center gap-1.5 rounded bg-[#007acc] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5" />
                {runningGauntlet ? "Evaluating..." : "Run 8-Gate Gauntlet"}
              </button>
              <button
                type="button"
                disabled={runningGauntlet}
                onClick={() => handleRunGauntlet(true)}
                className="flex items-center gap-1.5 rounded bg-[#238636] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                Queue if Passed
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

          {!gauntlet ? (
            <div className="mt-3 rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] px-4 py-8 text-center text-xs text-[#9d9d9d]">
              กด <strong>&ldquo;Run 8-Gate Gauntlet&rdquo;</strong> เพื่อตรวจสอบ {symbol} ครบทั้ง 8 ด่านแบบโปร่งใส
            </div>
          ) : (
            <div className="mt-3 space-y-3">
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
                    {gauntlet.passed_count}/{gauntlet.total_gates} PASS · {gauntlet.warn_count} WARN · {gauntlet.fail_count} FAIL
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
              กด <strong>&ldquo;Run Backtest (600 Bars)&rdquo;</strong> เพื่อพิสูจน์สถิติย้อนหลังจริงของกลยุทธ์นี้
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
                  คลิกที่พาดหัวเพื่อเปิดอ่านข่าวต้นฉบับได้ทุกชิ้น
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

          <div className="mt-3 max-h-[650px] space-y-2 overflow-y-auto pr-1">
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
