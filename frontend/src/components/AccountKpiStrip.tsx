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
    pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-rose-400" : "text-slate-200";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <div className="rounded-xl border border-slate-800/90 bg-slate-900/70 p-3.5">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Balance</span>
          <Wallet className="h-4 w-4 text-slate-500" />
        </div>
        <div className="mt-1.5 text-lg font-bold text-slate-100 tabular-nums">
          {fmtMoney(account?.balance)}
        </div>
        <div className="mt-0.5 text-[11px] text-slate-500">
          {account ? `${account.currency} · 1:${account.leverage}` : "Not connected"}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800/90 bg-slate-900/70 p-3.5">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Equity</span>
          <DollarSign className="h-4 w-4 text-amber-400/70" />
        </div>
        <div className="mt-1.5 text-lg font-bold text-slate-100 tabular-nums">
          {fmtMoney(account?.equity)}
        </div>
        <div className="mt-0.5 text-[11px] text-slate-500">
          Margin Used: {fmtMoney(account?.margin)}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800/90 bg-slate-900/70 p-3.5">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Floating P/L</span>
          <TrendingUp className="h-4 w-4 text-slate-500" />
        </div>
        <div className={`mt-1.5 text-lg font-bold tabular-nums ${pnlColor}`}>
          {account ? `${pnl >= 0 ? "+" : ""}${fmtMoney(pnl)}` : "—"}
        </div>
        <div className="mt-0.5 text-[11px] text-slate-500">
          Live Open P/L
        </div>
      </div>

      <div className="rounded-xl border border-slate-800/90 bg-slate-900/70 p-3.5">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Free Margin</span>
          <Shield className="h-4 w-4 text-sky-400/70" />
        </div>
        <div className="mt-1.5 text-lg font-bold text-slate-100 tabular-nums">
          {fmtMoney(account?.margin_free)}
        </div>
        <div className="mt-0.5 text-[11px] text-slate-500">
          Level: {account && account.margin > 0 ? `${account.margin_level.toFixed(1)}%` : "∞"}
        </div>
      </div>

      <div className="col-span-2 rounded-xl border border-slate-800/90 bg-slate-900/70 p-3.5 sm:col-span-1">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Queue & Exposure</span>
          <Layers className="h-4 w-4 text-amber-400/80" />
        </div>
        <div className="mt-1.5 flex items-baseline gap-2 text-lg font-bold text-slate-100 tabular-nums">
          <span>{openPositionsCount} Open</span>
          <span className="text-xs font-medium text-slate-400">
            / {pendingOrdersCount} Limit
          </span>
        </div>
        <div className="mt-0.5 text-[11px] text-amber-300/90">
          {pendingProposalsCount} pending confirmation{pendingProposalsCount === 1 ? "" : "s"}
        </div>
      </div>
    </div>
  );
}
