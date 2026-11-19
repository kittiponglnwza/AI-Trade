import { useState } from "react";
import { AlertCircle, Check, Clock, ShieldAlert, X } from "lucide-react";
import { confirmProposal, rejectProposal } from "../services/api";
import type { AccountSummary, TradeProposal } from "../types/trading";

interface ProposalsQueueProps {
  proposals: TradeProposal[];
  account: AccountSummary | null;
  onUpdated: () => void;
}

export function ProposalsQueue({ proposals, account, onUpdated }: ProposalsQueueProps) {
  const [confirmTarget, setConfirmTarget] = useState<TradeProposal | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pending = proposals.filter((p) => p.status === "PENDING");
  const recent = proposals.filter((p) => p.status !== "PENDING").slice(0, 4);

  const handleConfirm = async () => {
    if (!confirmTarget) return;
    setBusyId(confirmTarget.id);
    setErrorMsg(null);
    try {
      await confirmProposal(confirmTarget.id, false);
      setConfirmTarget(null);
      onUpdated();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to execute proposal");
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (id: number) => {
    setBusyId(id);
    setErrorMsg(null);
    try {
      await rejectProposal(id, "Rejected from Web Dashboard");
      onUpdated();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to reject proposal");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-slate-100">
            Pending Confirmation Queue ({pending.length})
          </h2>
        </div>
        <span className="text-[11px] text-slate-400">Requires your approval</span>
      </div>

      {errorMsg && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {pending.length === 0 ? (
        <div className="mt-3 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 px-4 py-6 text-center text-xs text-slate-500">
          No pending proposals right now. Queue one from the Order Planner or push from AI/CLI.
        </div>
      ) : (
        <div className="mt-3 space-y-2.5">
          {pending.map((p) => {
            const isBuy = p.side.startsWith("BUY");
            return (
              <div
                key={p.id}
                className="rounded-xl border border-amber-500/30 bg-slate-950/90 p-3 shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-[11px] font-bold ${
                        isBuy ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                      }`}
                    >
                      {p.side}
                    </span>
                    <span className="text-sm font-bold text-slate-100 tabular-nums">
                      {p.lots.toFixed(2)} {p.symbol}
                    </span>
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
                      {p.source} · {p.timeframe}
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-500">#{p.id}</span>
                </div>

                <div className="mt-2 grid grid-cols-3 gap-2 rounded-lg bg-slate-900/90 px-2.5 py-1.5 text-[11px] tabular-nums">
                  <div>
                    <span className="text-slate-500">Entry </span>
                    <strong className="text-slate-200">{p.entry_price}</strong>
                  </div>
                  <div>
                    <span className="text-slate-500">SL </span>
                    <strong className="text-rose-300">{p.sl ?? "—"}</strong>
                  </div>
                  <div>
                    <span className="text-slate-500">TP </span>
                    <strong className="text-emerald-300">{p.tp ?? "—"}</strong>
                  </div>
                </div>

                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400 tabular-nums">
                  <span>
                    Risk:{" "}
                    <strong className="text-rose-300">
                      ${p.est_risk_usd.toFixed(2)} ({p.risk_pct?.toFixed(1) ?? "?"}%)
                    </strong>
                  </span>
                  <span>
                    R:R <strong className="text-amber-300">{p.rr_ratio ? `1:${p.rr_ratio}` : "—"}</strong>
                  </span>
                </div>

                {p.rationale && (
                  <p className="mt-1.5 text-[11px] text-slate-300 line-clamp-2">{p.rationale}</p>
                )}

                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => handleReject(p.id)}
                    className="flex items-center justify-center gap-1 rounded-lg border border-slate-700 bg-slate-800 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700 disabled:opacity-50"
                  >
                    <X className="h-3.5 w-3.5" />
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => setConfirmTarget(p)}
                    className="flex items-center justify-center gap-1 rounded-lg bg-emerald-500 py-1.5 text-xs font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                  >
                    <Check className="h-3.5 w-3.5" />
                    Confirm & Execute
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {recent.length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <div className="mb-1.5 text-[11px] font-medium text-slate-400">Recent Proposal Activity</div>
          <div className="space-y-1">
            {recent.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between rounded-lg bg-slate-950/60 px-2.5 py-1.5 text-[11px] text-slate-400"
              >
                <span>
                  #{p.id} {p.side} {p.lots} {p.symbol}
                </span>
                <span
                  className={
                    p.status === "EXECUTED"
                      ? "text-emerald-400 font-semibold"
                      : p.status === "REJECTED"
                      ? "text-slate-500"
                      : "text-rose-400"
                  }
                >
                  {p.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {confirmTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-amber-500/40 bg-slate-900 p-5 shadow-2xl">
            <div className="flex items-center gap-2 text-amber-300">
              <ShieldAlert className="h-5 w-5" />
              <h3 className="text-base font-bold">Confirm MT5 Order Execution</h3>
            </div>
            <p className="mt-2 text-xs text-slate-300">
              You are about to send a live order to MetaTrader 5:
            </p>
            <div className="mt-3 space-y-1.5 rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs tabular-nums">
              <div className="flex justify-between">
                <span className="text-slate-400">Account Mode:</span>
                <strong className="text-sky-300">{account?.trade_mode ?? "UNKNOWN"}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Order:</span>
                <strong className="text-slate-100">
                  {confirmTarget.side} {confirmTarget.lots.toFixed(2)} {confirmTarget.symbol} @{" "}
                  {confirmTarget.entry_price}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">SL / TP:</span>
                <strong className="text-slate-200">
                  {confirmTarget.sl ?? "—"} / {confirmTarget.tp ?? "—"}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Estimated Risk:</span>
                <strong className="text-rose-300">
                  ${confirmTarget.est_risk_usd.toFixed(2)} (
                  {confirmTarget.risk_pct?.toFixed(1) ?? "?"}%)
                </strong>
              </div>
            </div>

            {account && !account.terminal_trade_allowed && (
              <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/15 p-2.5 text-xs text-amber-200">
                Warning: MT5 Terminal <strong>Algo Trading</strong> is currently OFF. Please toggle it ON in MT5 before clicking Execute.
              </div>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmTarget(null)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busyId === confirmTarget.id}
                onClick={handleConfirm}
                className="rounded-lg bg-emerald-500 px-4 py-2 text-xs font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
              >
                {busyId === confirmTarget.id ? "Sending..." : "Execute in MT5"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
