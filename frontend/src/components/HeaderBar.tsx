import { useEffect, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  CandlestickChart,
  Settings,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { AccountSummary, AppTab, QuoteInfo, WsStatus } from "../types/trading";

interface HeaderBarProps {
  wsStatus: WsStatus;
  mt5Connected: boolean;
  account: AccountSummary | null;
  quote: QuoteInfo | null;
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
  pendingCount: number;
  onOpenSettings: () => void;
}

export function HeaderBar({
  wsStatus,
  mt5Connected,
  account,
  quote,
  activeTab,
  onTabChange,
  pendingCount,
  onOpenSettings,
}: HeaderBarProps) {
  const prevBidRef = useRef<number | null>(null);
  const [priceDir, setPriceDir] = useState<"up" | "down" | "flat">("flat");

  useEffect(() => {
    if (!quote) return;
    if (prevBidRef.current !== null && quote.bid !== prevBidRef.current) {
      setPriceDir(quote.bid > prevBidRef.current ? "up" : "down");
    }
    prevBidRef.current = quote.bid;
  }, [quote?.bid]);

  const statusColor =
    wsStatus === "LIVE" && mt5Connected
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : wsStatus === "RECONNECTING"
      ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
      : "bg-rose-500/15 text-rose-300 border-rose-500/30";

  const dotColor =
    wsStatus === "LIVE" && mt5Connected
      ? "bg-emerald-400 animate-pulse"
      : wsStatus === "RECONNECTING"
      ? "bg-amber-400 animate-pulse"
      : "bg-rose-400";

  const statusLabel =
    wsStatus === "LIVE" && mt5Connected
      ? "LIVE MT5"
      : wsStatus === "LIVE" && !mt5Connected
      ? "BRIDGE ONLY"
      : wsStatus;

  const bidColor =
    priceDir === "up"
      ? "text-emerald-400"
      : priceDir === "down"
      ? "text-rose-400"
      : "text-slate-100";

  const tabs: { id: AppTab; label: string; icon: typeof CandlestickChart }[] = [
    { id: "desk", label: "Trading Desk", icon: CandlestickChart },
    { id: "stats", label: "Analytics & Stats", icon: BarChart3 },
    { id: "journal", label: "Trade Journal", icon: BookOpen },
  ];

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/90 bg-slate-950/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-400">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-tight text-slate-100 sm:text-base">
                XAUUSD AI Trading Desk
              </h1>
              {account && (
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${
                    account.trade_mode === "DEMO"
                      ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                      : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                  }`}
                >
                  {account.trade_mode}
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-400">
              {account ? `${account.server} · #${account.login}` : "Waiting for MT5 Bridge"}
            </p>
          </div>
        </div>

        {quote && (
          <div className="flex items-center gap-4 rounded-lg border border-slate-800 bg-slate-900/90 px-3.5 py-1.5 tabular-nums">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400">
                {quote.symbol} Bid
              </div>
              <div className={`text-sm font-bold sm:text-base ${bidColor}`}>
                {quote.bid.toFixed(quote.digits)}
              </div>
            </div>
            <div className="h-6 w-px bg-slate-800" />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Ask</div>
              <div className="text-sm font-semibold text-slate-200 sm:text-base">
                {quote.ask.toFixed(quote.digits)}
              </div>
            </div>
            <div className="hidden h-6 w-px bg-slate-800 sm:block" />
            <div className="hidden sm:block">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Spread</div>
              <div className="text-xs font-medium text-amber-300">
                {quote.spread_points} pts (${quote.spread_price.toFixed(quote.digits)})
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <nav className="flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange(tab.id)}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition ${
                    active
                      ? "bg-amber-500 text-slate-950 shadow-sm"
                      : "text-slate-300 hover:bg-slate-800 hover:text-white"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{tab.label}</span>
                  {tab.id === "desk" && pendingCount > 0 && (
                    <span
                      className={`ml-0.5 rounded-full px-1.5 py-0.2 text-[10px] font-bold ${
                        active ? "bg-slate-950 text-amber-400" : "bg-amber-500/20 text-amber-300"
                      }`}
                    >
                      {pendingCount}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {account && (
            <div
              className={`hidden items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium xl:flex ${
                account.terminal_trade_allowed
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : "border-amber-500/40 bg-amber-500/15 text-amber-300"
              }`}
              title={
                account.terminal_trade_allowed
                  ? "MT5 Algo Trading is ON"
                  : "Enable Algo Trading in MT5 toolbar before confirming orders"
              }
            >
              {account.terminal_trade_allowed ? (
                <ShieldCheck className="h-3.5 w-3.5" />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5" />
              )}
              <span>Algo: {account.terminal_trade_allowed ? "ON" : "OFF"}</span>
            </div>
          )}

          <div
            className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${statusColor}`}
          >
            <span className={`h-2 w-2 rounded-full ${dotColor}`} />
            <span>{statusLabel}</span>
          </div>

          <button
            type="button"
            onClick={onOpenSettings}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-800 bg-slate-900 text-slate-300 transition hover:border-slate-700 hover:bg-slate-800 hover:text-white"
            title="Bridge Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
