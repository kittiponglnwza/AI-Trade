import { useEffect, useRef, useState } from "react";
import { createChart, type UTCTimestamp } from "lightweight-charts";
import { Bot, RefreshCw, Sparkles, TrendingDown, TrendingUp, UserCheck } from "lucide-react";
import { syncLogs } from "../services/api";
import type { ActorBreakdown, TradingStats } from "../types/trading";

interface StatsDashboardProps {
  stats: TradingStats | null;
  onRefresh: () => void;
}

export function StatsDashboard({ stats, onRefresh }: StatsDashboardProps) {
  const chartBoxRef = useRef<HTMLDivElement | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await syncLogs(90);
      setSyncMsg(`Synced ${res.total} MT5 closed deals (New: ${res.inserted}, Updated: ${res.updated})`);
      onRefresh();
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : "Failed to sync MT5 history");
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    const el = chartBoxRef.current;
    if (!el || !stats || stats.equity_curve.length === 0) return;

    const chart = createChart(el, {
      layout: {
        background: { color: "#1e1e1e" },
        textColor: "#9d9d9d",
      },
      grid: {
        vertLines: { color: "#282828" },
        horzLines: { color: "#282828" },
      },
      rightPriceScale: { borderColor: "#2b2b2b" },
      timeScale: { borderColor: "#2b2b2b", timeVisible: true },
      width: el.clientWidth,
      height: 260,
    });

    const isPositive = stats.net_profit >= 0;
    const area = chart.addAreaSeries({
      lineColor: isPositive ? "#3fb950" : "#f14c4c",
      topColor: isPositive ? "rgba(63, 185, 80, 0.3)" : "rgba(241, 76, 76, 0.3)",
      bottomColor: isPositive ? "rgba(63, 185, 80, 0.02)" : "rgba(241, 76, 76, 0.02)",
      lineWidth: 2,
    });

    let prevTs = 0;
    const seriesData = stats.equity_curve.map((pt) => {
      const parsed = Date.parse(pt.time.replace(" ", "T") + "Z");
      let ts = Number.isFinite(parsed) ? Math.floor(parsed / 1000) : prevTs + 60;
      if (ts <= prevTs) ts = prevTs + 1;
      prevTs = ts;
      return { time: ts as UTCTimestamp, value: pt.equity };
    });

    area.setData(seriesData);
    chart.timeScale().fitContent();

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      }
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [stats]);

  const cards = stats
    ? [
        {
          label: "Net Profit",
          value: `${stats.net_profit >= 0 ? "+" : ""}$${stats.net_profit.toFixed(2)}`,
          sub: `Gross +$${stats.gross_profit.toFixed(2)} / -$${stats.gross_loss.toFixed(2)}`,
          tone: stats.net_profit >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]",
        },
        {
          label: "Win Rate",
          value: `${stats.win_rate_pct.toFixed(1)}%`,
          sub: `${stats.wins}W / ${stats.losses}L (${stats.total_trades} closed)`,
          tone: stats.win_rate_pct >= 50 ? "text-[#3fb950]" : "text-[#dcdcaa]",
        },
        {
          label: "Profit Factor",
          value: stats.profit_factor === null ? "∞" : stats.profit_factor.toFixed(2),
          sub: `Expectancy $${stats.expectancy.toFixed(2)} / trade`,
          tone: "text-[#4fc1ff]",
        },
        {
          label: "Max Drawdown",
          value: `-$${stats.max_drawdown_usd.toFixed(2)}`,
          sub: `${stats.max_drawdown_pct.toFixed(2)}% from peak`,
          tone: "text-[#f14c4c]",
        },
        {
          label: "Avg Win / Avg Loss",
          value: `+$${stats.avg_win.toFixed(2)} / $${stats.avg_loss.toFixed(2)}`,
          sub: `Best +$${stats.largest_win.toFixed(2)} · Worst $${stats.largest_loss.toFixed(2)}`,
          tone: "text-[#e1e1e1]",
        },
        {
          label: "Streaks",
          value:
            stats.current_streak > 0
              ? `${stats.current_streak} Win Streak`
              : stats.current_streak < 0
              ? `${Math.abs(stats.current_streak)} Loss Streak`
              : "Neutral",
          sub: `Max Win ${stats.max_win_streak} · Max Loss ${stats.max_loss_streak}`,
          tone: stats.current_streak >= 0 ? "text-[#4ec9b0]" : "text-[#f14c4c]",
        },
      ]
    : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
        <div>
          <h2 className="text-sm font-semibold text-[#e1e1e1]">Performance Analytics & Stats</h2>
          <p className="text-xs text-[#9d9d9d]">
            คำนวณจาก SQLite Trade Journal + ประวัติปิดออเดอร์จริงใน MT5
          </p>
        </div>
        <div className="flex items-center gap-3">
          {syncMsg && <span className="text-xs text-[#4fc1ff] break-words">{syncMsg}</span>}
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-1.5 rounded bg-[#007acc] px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-[#1f8ad2] disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing MT5..." : "Sync MT5 History"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-md border border-[#2b2b2b] bg-[#252526] p-3.5"
          >
            <div className="text-xs text-[#9d9d9d]">{c.label}</div>
            <div className={`font-mono-num mt-1.5 text-xl font-bold ${c.tone}`}>{c.value}</div>
            <div className="font-mono-num mt-1 text-[11px] text-[#6e6e6e]">{c.sub}</div>
          </div>
        ))}
      </div>

      {stats?.by_actor && (
        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
                Head-to-Head: 🤖 AI Auto-Pilot Demo vs ✨ AI แนะนำ (คนกดยืนยัน) vs 👤 เทรดมือ (Manual)
              </h3>
              <p className="text-[11px] text-[#9d9d9d]">
                เปรียบเทียบความแม่นยำและกำไรสุทธิแยกตามแหล่งที่มาของออเดอร์
              </p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            {(
              [
                {
                  key: "AUTOPILOT" as const,
                  title: "🤖 AI Auto-Pilot (ยิงเอง ≥80%)",
                  badge: "border-[#c586c0]/40 bg-[#c586c0]/15 text-[#e5a6e0]",
                  icon: <Bot className="h-4 w-4 text-[#e5a6e0]" />,
                },
                {
                  key: "AI_CONFIRMED" as const,
                  title: "✨ AI แนะนำ + คนกดยืนยัน (≥75%)",
                  badge: "border-[#007acc]/40 bg-[#007acc]/15 text-[#4fc1ff]",
                  icon: <Sparkles className="h-4 w-4 text-[#4fc1ff]" />,
                },
                {
                  key: "MANUAL" as const,
                  title: "👤 เทรดมือ / ซิงก์จาก MT5 (Manual)",
                  badge: "border-[#4ec9b0]/40 bg-[#4ec9b0]/15 text-[#4ec9b0]",
                  icon: <UserCheck className="h-4 w-4 text-[#4ec9b0]" />,
                },
              ] as const
            ).map((bucket) => {
              const item: ActorBreakdown = stats.by_actor?.[bucket.key] ?? {
                trades: 0,
                wins: 0,
                losses: 0,
                win_rate_pct: 0,
                net_profit: 0,
                expectancy: 0,
                profit_factor: 0,
              };
              return (
                <div
                  key={bucket.key}
                  className="font-mono-num rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3.5 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 font-sans font-semibold text-[#e1e1e1]">
                      {bucket.icon}
                      <span>{bucket.title}</span>
                    </div>
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${bucket.badge}`}>
                      {item.trades} ไม้
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[#2b2b2b] pt-2.5">
                    <div>
                      <div className="text-[10px] text-[#9d9d9d]">Net Profit</div>
                      <div
                        className={`text-sm font-bold ${
                          item.net_profit >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                        }`}
                      >
                        {item.net_profit >= 0 ? "+" : ""}${item.net_profit.toFixed(2)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-[#9d9d9d]">Win Rate</div>
                      <div className="text-sm font-bold text-[#e1e1e1]">
                        {item.win_rate_pct.toFixed(1)}%{" "}
                        <span className="text-[10px] font-normal text-[#9d9d9d]">
                          ({item.wins}W/{item.losses}L)
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-[#9d9d9d]">Expectancy</div>
                      <div className="text-xs font-semibold text-[#cccccc]">
                        ${item.expectancy.toFixed(2)} / ไม้
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-[#9d9d9d]">Profit Factor</div>
                      <div className="text-xs font-semibold text-[#4fc1ff]">
                        {item.profit_factor === null ? "∞" : item.profit_factor.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4 lg:col-span-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
            Account Equity Curve
          </h3>
          {!stats || stats.equity_curve.length === 0 ? (
            <div className="mt-3 flex h-[260px] items-center justify-center rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] text-xs text-[#6e6e6e]">
              ยังไม่มีไม้ที่ปิดแล้ว — เมื่อปิดออเดอร์หรือกด Sync MT5 History กราฟจะแสดงที่นี่
            </div>
          ) : (
            <div ref={chartBoxRef} className="mt-3 w-full overflow-hidden rounded border border-[#2b2b2b]" />
          )}
        </div>

        <div className="space-y-3">
          <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
              BUY vs SELL Breakdown
            </h3>
            <div className="font-mono-num mt-3 space-y-2 text-xs">
              {(["BUY", "SELL"] as const).map((side) => {
                const item = stats?.by_side[side] ?? {
                  trades: 0,
                  wins: 0,
                  win_rate_pct: 0,
                  net_profit: 0,
                };
                return (
                  <div
                    key={side}
                    className="flex items-center justify-between rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3"
                  >
                    <div className="flex items-center gap-2">
                      {side === "BUY" ? (
                        <TrendingUp className="h-4 w-4 text-[#3fb950]" />
                      ) : (
                        <TrendingDown className="h-4 w-4 text-[#f14c4c]" />
                      )}
                      <div>
                        <div className="font-bold text-[#e1e1e1]">{side}</div>
                        <div className="text-[11px] text-[#9d9d9d]">
                          {item.trades} trades · {item.win_rate_pct.toFixed(1)}% WR
                        </div>
                      </div>
                    </div>
                    <div
                      className={`font-bold ${
                        item.net_profit >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                      }`}
                    >
                      {item.net_profit >= 0 ? "+" : ""}${item.net_profit.toFixed(2)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
              Daily P/L
            </h3>
            {!stats || stats.daily_pnl.length === 0 ? (
              <p className="mt-3 text-xs text-[#6e6e6e]">ยังไม่มีข้อมูล P/L รายวัน</p>
            ) : (
              <div className="font-mono-num mt-3 max-h-44 space-y-1.5 overflow-y-auto pr-1 text-xs">
                {stats.daily_pnl
                  .slice()
                  .reverse()
                  .map((d) => (
                    <div
                      key={d.date}
                      className="flex items-center justify-between rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2"
                    >
                      <div>
                        <span className="font-medium text-[#cccccc]">{d.date}</span>
                        <span className="ml-2 text-[11px] text-[#6e6e6e]">
                          {d.wins}/{d.trades} W
                        </span>
                      </div>
                      <span
                        className={`font-bold ${
                          d.pnl >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                        }`}
                      >
                        {d.pnl >= 0 ? "+" : ""}${d.pnl.toFixed(2)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
