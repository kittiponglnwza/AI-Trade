import { useEffect, useRef, useState } from "react";
import { createChart, type UTCTimestamp } from "lightweight-charts";
import { RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { syncLogs } from "../services/api";
import type { TradingStats } from "../types/trading";

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
        background: { color: "#0b1120" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      rightPriceScale: { borderColor: "#1e293b" },
      timeScale: { borderColor: "#1e293b", timeVisible: true },
      width: el.clientWidth,
      height: 260,
    });

    const isPositive = stats.net_profit >= 0;
    const area = chart.addAreaSeries({
      lineColor: isPositive ? "#10b981" : "#f43f5e",
      topColor: isPositive ? "rgba(16, 185, 129, 0.35)" : "rgba(244, 63, 94, 0.35)",
      bottomColor: isPositive ? "rgba(16, 185, 129, 0.02)" : "rgba(244, 63, 94, 0.02)",
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
          tone: stats.net_profit >= 0 ? "text-emerald-400" : "text-rose-400",
        },
        {
          label: "Win Rate",
          value: `${stats.win_rate_pct.toFixed(1)}%`,
          sub: `${stats.wins}W / ${stats.losses}L (${stats.total_trades} closed)`,
          tone: stats.win_rate_pct >= 50 ? "text-emerald-300" : "text-amber-300",
        },
        {
          label: "Profit Factor",
          value: stats.profit_factor === null ? "∞" : stats.profit_factor.toFixed(2),
          sub: `Expectancy $${stats.expectancy.toFixed(2)} / trade`,
          tone: "text-sky-300",
        },
        {
          label: "Max Drawdown",
          value: `-$${stats.max_drawdown_usd.toFixed(2)}`,
          sub: `${stats.max_drawdown_pct.toFixed(2)}% from peak`,
          tone: "text-rose-300",
        },
        {
          label: "Avg Win / Avg Loss",
          value: `+$${stats.avg_win.toFixed(2)} / $${stats.avg_loss.toFixed(2)}`,
          sub: `Best +$${stats.largest_win.toFixed(2)} · Worst $${stats.largest_loss.toFixed(2)}`,
          tone: "text-slate-100",
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
          tone: stats.current_streak >= 0 ? "text-emerald-300" : "text-rose-300",
        },
      ]
    : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Performance Analytics & Stats</h2>
          <p className="text-xs text-slate-400">
            Computed from SQLite trade journal + synced MT5 closed deal history
          </p>
        </div>
        <div className="flex items-center gap-3">
          {syncMsg && <span className="text-xs text-amber-300">{syncMsg}</span>}
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-3.5 py-2 text-xs font-bold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50"
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
            className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4 tabular-nums"
          >
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className={`mt-1.5 text-xl font-bold ${c.tone}`}>{c.value}</div>
            <div className="mt-1 text-[11px] text-slate-500">{c.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4 lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-100">Account Equity Curve</h3>
          {!stats || stats.equity_curve.length === 0 ? (
            <div className="mt-4 flex h-[260px] items-center justify-center rounded-xl border border-dashed border-slate-800 text-xs text-slate-500">
              No closed trades yet. Once trades close (or after Sync MT5 History), your equity curve appears here.
            </div>
          ) : (
            <div ref={chartBoxRef} className="mt-3 w-full overflow-hidden rounded-xl border border-slate-800" />
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
            <h3 className="text-sm font-semibold text-slate-100">BUY vs SELL Breakdown</h3>
            <div className="mt-3 space-y-2.5 text-xs tabular-nums">
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
                    className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/80 p-3"
                  >
                    <div className="flex items-center gap-2">
                      {side === "BUY" ? (
                        <TrendingUp className="h-4 w-4 text-emerald-400" />
                      ) : (
                        <TrendingDown className="h-4 w-4 text-rose-400" />
                      )}
                      <div>
                        <div className="font-bold text-slate-100">{side}</div>
                        <div className="text-[11px] text-slate-400">
                          {item.trades} trades · {item.win_rate_pct.toFixed(1)}% WR
                        </div>
                      </div>
                    </div>
                    <div
                      className={`font-bold ${
                        item.net_profit >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {item.net_profit >= 0 ? "+" : ""}${item.net_profit.toFixed(2)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Daily P/L</h3>
            {!stats || stats.daily_pnl.length === 0 ? (
              <p className="mt-3 text-xs text-slate-500">No daily closed P/L records yet.</p>
            ) : (
              <div className="mt-3 max-h-44 space-y-2 overflow-y-auto pr-1 text-xs tabular-nums">
                {stats.daily_pnl
                  .slice()
                  .reverse()
                  .map((d) => (
                    <div
                      key={d.date}
                      className="flex items-center justify-between rounded-lg bg-slate-950/70 px-3 py-2"
                    >
                      <div>
                        <span className="font-medium text-slate-200">{d.date}</span>
                        <span className="ml-2 text-[11px] text-slate-500">
                          {d.wins}/{d.trades} W
                        </span>
                      </div>
                      <span
                        className={`font-bold ${
                          d.pnl >= 0 ? "text-emerald-400" : "text-rose-400"
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
