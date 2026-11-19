import { DollarSign, Layers, Shield, TrendingUp, Wallet } from "lucide-react";
import type { AccountSummary } from "../types/trading";

interface AccountKpiStripProps {
  account: AccountSummary | null;
  openPositionsCount: number;
  pendingOrdersCount: number;
  pendingProposalsCount: number;
}

export function AccountKpiStrip({
  account,
  openPositionsCount,
  pendingOrdersCount,
  pendingProposalsCount,
}: AccountKpiStripProps) {
  const fmtMoney = (v: number | undefined | null) =>
    v === undefined || v === null
      ? "—"
      : `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const pnl = account?.profit ?? 0;
  const pnlColor =
    pnl > 0 ? "text-[#3fb950]" : pnl < 0 ? "text-[#f14c4c]" : "text-[#e1e1e1]";

  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-md border border-[#2b2b2b] bg-[#252526] sm:grid-cols-3 lg:grid-cols-5 lg:divide-x lg:divide-[#2b2b2b]">
      <div className="border-b border-[#2b2b2b] px-3.5 py-2.5 lg:border-b-0">
        <div className="flex items-center justify-between text-[11px] text-[#9d9d9d]">
          <span>Balance</span>
          <Wallet className="h-3.5 w-3.5 text-[#6e6e6e]" />
        </div>
        <div className="font-mono-num mt-1 text-base font-semibold text-[#e1e1e1]">
          {fmtMoney(account?.balance)}
        </div>
        <div className="text-[11px] text-[#6e6e6e]">
          {account ? `${account.currency} · 1:${account.leverage}` : "Not connected"}
        </div>
      </div>

      <div className="border-b border-l border-[#2b2b2b] px-3.5 py-2.5 sm:border-l lg:border-b-0">
        <div className="flex items-center justify-between text-[11px] text-[#9d9d9d]">
          <span>Equity</span>
          <DollarSign className="h-3.5 w-3.5 text-[#4fc1ff]" />
        </div>
        <div className="font-mono-num mt-1 text-base font-semibold text-[#e1e1e1]">
          {fmtMoney(account?.equity)}
        </div>
        <div className="text-[11px] text-[#6e6e6e]">
          Margin Used: {fmtMoney(account?.margin)}
        </div>
      </div>

      <div className="border-b border-[#2b2b2b] px-3.5 py-2.5 sm:border-l lg:border-b-0">
        <div className="flex items-center justify-between text-[11px] text-[#9d9d9d]">
          <span>Floating P/L</span>
          <TrendingUp className="h-3.5 w-3.5 text-[#6e6e6e]" />
        </div>
        <div className={`font-mono-num mt-1 text-base font-semibold ${pnlColor}`}>
          {account ? `${pnl >= 0 ? "+" : ""}${fmtMoney(pnl)}` : "—"}
        </div>
        <div className="text-[11px] text-[#6e6e6e]">Live Open P/L</div>
      </div>

      <div className="border-b border-l border-[#2b2b2b] px-3.5 py-2.5 lg:border-b-0">
        <div className="flex items-center justify-between text-[11px] text-[#9d9d9d]">
          <span>Free Margin</span>
          <Shield className="h-3.5 w-3.5 text-[#4ec9b0]" />
        </div>
        <div className="font-mono-num mt-1 text-base font-semibold text-[#e1e1e1]">
          {fmtMoney(account?.margin_free)}
        </div>
        <div className="text-[11px] text-[#6e6e6e]">
          Level: {account && account.margin > 0 ? `${account.margin_level.toFixed(1)}%` : "∞"}
        </div>
      </div>

      <div className="col-span-2 px-3.5 py-2.5 sm:col-span-1">
        <div className="flex items-center justify-between text-[11px] text-[#9d9d9d]">
          <span>Queue & Exposure</span>
          <Layers className="h-3.5 w-3.5 text-[#dcdcaa]" />
        </div>
        <div className="font-mono-num mt-1 flex items-baseline gap-1.5 text-base font-semibold text-[#e1e1e1]">
          <span>{openPositionsCount} Open</span>
          <span className="text-xs font-normal text-[#9d9d9d]">/ {pendingOrdersCount} Limit</span>
        </div>
        <div
          className={`text-[11px] ${
            pendingProposalsCount > 0 ? "font-medium text-[#4fc1ff]" : "text-[#6e6e6e]"
          }`}
        >
          {pendingProposalsCount} AI proposal{pendingProposalsCount === 1 ? "" : "s"} pending
        </div>
      </div>
    </div>
  );
}
