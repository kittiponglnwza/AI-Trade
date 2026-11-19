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
      ? "bg-[#3fb950]/10 text-[#3fb950] border-[#3fb950]/30"
      : wsStatus === "RECONNECTING"
      ? "bg-[#cca700]/15 text-[#dcdcaa] border-[#cca700]/30"
      : "bg-[#f14c4c]/15 text-[#f14c4c] border-[#f14c4c]/30";

  const dotColor =
    wsStatus === "LIVE" && mt5Connected
      ? "bg-[#3fb950] animate-pulse"
      : wsStatus === "RECONNECTING"
      ? "bg-[#dcdcaa] animate-pulse"
      : "bg-[#f14c4c]";

  const statusLabel =
    wsStatus === "LIVE" && mt5Connected
      ? "LIVE MT5"
      : wsStatus === "LIVE" && !mt5Connected
      ? "BRIDGE ONLY"
      : wsStatus;

  const bidColor =
    priceDir === "up"
      ? "text-[#3fb950]"
      : priceDir === "down"
      ? "text-[#f14c4c]"
      : "text-[#e1e1e1]";

  const tabs: { id: AppTab; label: string; icon: typeof CandlestickChart }[] = [
    { id: "desk", label: "Trading Desk", icon: CandlestickChart },
    { id: "stats", label: "Analytics & Stats", icon: BarChart3 },
    { id: "journal", label: "Trade Journal", icon: BookOpen },
  ];

  return (
    <header className="sticky top-0 z-30 border-b border-[#2b2b2b] bg-[#181818]">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3 px-3 py-1.5 sm:px-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded border border-[#3c3c3c] bg-[#252526] text-[#4fc1ff]">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-tight text-[#e1e1e1]">
                XAUUSD AI Trading Desk
              </h1>
              {account && (
                <span
                  className={`rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${
                    account.trade_mode === "DEMO"
                      ? "border-[#007acc]/50 bg-[#007acc]/15 text-[#4fc1ff]"
                      : "border-[#f14c4c]/50 bg-[#f14c4c]/15 text-[#f14c4c]"
                  }`}
                >
                  {account.trade_mode}
                </span>
              )}
            </div>
            <p className="text-[11px] text-[#9d9d9d]">
              {account ? `${account.server} · #${account.login}` : "Waiting for MT5 Bridge"}
            </p>
          </div>
        </div>

        {quote && (
          <div className="font-mono-num flex items-center gap-3.5 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[#9d9d9d]">
                {quote.symbol} Bid
              </div>
              <div className={`text-sm font-bold sm:text-base ${bidColor}`}>
                {quote.bid.toFixed(quote.digits)}
              </div>
            </div>
            <div className="h-6 w-px bg-[#2b2b2b]" />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[#9d9d9d]">Ask</div>
              <div className="text-sm font-semibold text-[#e1e1e1] sm:text-base">
                {quote.ask.toFixed(quote.digits)}
              </div>
            </div>
            <div className="hidden h-6 w-px bg-[#2b2b2b] sm:block" />
            <div className="hidden sm:block">
              <div className="text-[10px] uppercase tracking-wider text-[#9d9d9d]">Spread</div>
              <div className="text-xs font-medium text-[#dcdcaa]">
                {quote.spread_points} pts (${quote.spread_price.toFixed(quote.digits)})
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <nav className="flex items-center border-b border-transparent bg-[#181818]">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange(tab.id)}
                  className={`relative flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition ${
                    active
                      ? "border-[#007acc] bg-[#1e1e1e] text-white"
                      : "border-transparent text-[#9d9d9d] hover:bg-[#2a2d2e] hover:text-[#e1e1e1]"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{tab.label}</span>
                  {tab.id === "desk" && pendingCount > 0 && (
                    <span className="ml-0.5 rounded-full bg-[#007acc] px-1.5 py-0.2 text-[10px] font-bold text-white">
                      {pendingCount}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {account && (
            <div
              className={`hidden items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-medium xl:flex ${
                account.terminal_trade_allowed
                  ? "border-[#3fb950]/30 bg-[#3fb950]/10 text-[#3fb950]"
                  : "border-[#cca700]/40 bg-[#cca700]/15 text-[#dcdcaa]"
              }`}
              title={
                account.terminal_trade_allowed
                  ? "MT5 Algo Trading is ON"
                  : "เปิดปุ่ม Algo Trading บน MT5 ก่อนกดยืนยันออเดอร์"
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
            className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-medium ${statusColor}`}
          >
            <span className={`h-2 w-2 rounded-full ${dotColor}`} />
            <span>{statusLabel}</span>
          </div>

          <button
            type="button"
            onClick={onOpenSettings}
            className="flex h-7 w-7 items-center justify-center rounded border border-[#3c3c3c] bg-[#252526] text-[#cccccc] transition hover:bg-[#313131] hover:text-white"
            title="Bridge Settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
}
