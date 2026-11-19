import { useState } from "react";
import { Edit3, Trash2, X } from "lucide-react";
import { closePosition, modifyPosition } from "../services/api";
import type { OpenPosition, PendingOrder } from "../types/trading";

interface PositionsTableProps {
  positions: OpenPosition[];
  orders: PendingOrder[];
  onUpdated: () => void;
}

export function PositionsTable({ positions, orders, onUpdated }: PositionsTableProps) {
  const [editTarget, setEditTarget] = useState<OpenPosition | null>(null);
  const [slInput, setSlInput] = useState("");
  const [tpInput, setTpInput] = useState("");
  const [closeTarget, setCloseTarget] = useState<{ ticket: number; label: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const openModify = (pos: OpenPosition) => {
    setEditTarget(pos);
    setSlInput(pos.sl > 0 ? String(pos.sl) : "");
    setTpInput(pos.tp > 0 ? String(pos.tp) : "");
    setErrMsg(null);
  };

  const submitModify = async () => {
    if (!editTarget) return;
    setBusy(true);
    setErrMsg(null);
    try {
      const sl = slInput.trim() ? parseFloat(slInput) : 0;
      const tp = tpInput.trim() ? parseFloat(tpInput) : 0;
      await modifyPosition(editTarget.ticket, sl, tp);
      setEditTarget(null);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Modify failed");
    } finally {
      setBusy(false);
    }
  };

  const submitClose = async () => {
    if (!closeTarget) return;
    setBusy(true);
    setErrMsg(null);
    try {
      await closePosition(closeTarget.ticket);
      setCloseTarget(null);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Close failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <h2 className="text-sm font-semibold text-slate-100">
          Open Positions ({positions.length}) & Pending Orders ({orders.length})
        </h2>
        <span className="text-[11px] text-slate-400">Real-time MT5 P/L</span>
      </div>

      {errMsg && (
        <div className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
          {errMsg}
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[680px] text-left text-xs tabular-nums">
          <thead>
            <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
              <th className="py-2 pr-3">Ticket</th>
              <th className="py-2 pr-3">Symbol / Side</th>
              <th className="py-2 pr-3">Lots</th>
              <th className="py-2 pr-3">Open</th>
              <th className="py-2 pr-3">Current</th>
              <th className="py-2 pr-3">SL</th>
              <th className="py-2 pr-3">TP</th>
              <th className="py-2 pr-3 text-right">P/L</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {positions.length === 0 && orders.length === 0 && (
              <tr>
                <td colSpan={9} className="py-6 text-center text-slate-500">
                  No open positions or pending orders in MT5.
                </td>
              </tr>
            )}

            {positions.map((pos) => (
              <tr key={`pos-${pos.ticket}`} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 text-slate-300">#{pos.ticket}</td>
                <td className="py-2.5 pr-3">
                  <span className="font-semibold text-slate-100">{pos.symbol}</span>{" "}
                  <span
                    className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      pos.side === "BUY"
                        ? "bg-emerald-500/20 text-emerald-300"
                        : "bg-rose-500/20 text-rose-300"
                    }`}
                  >
                    {pos.side}
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-slate-200">{pos.volume.toFixed(2)}</td>
                <td className="py-2.5 pr-3 text-slate-300">{pos.price_open}</td>
                <td className="py-2.5 pr-3 text-slate-100 font-medium">{pos.price_current}</td>
                <td className="py-2.5 pr-3 text-rose-300">{pos.sl > 0 ? pos.sl : "—"}</td>
                <td className="py-2.5 pr-3 text-emerald-300">{pos.tp > 0 ? pos.tp : "—"}</td>
                <td
                  className={`py-2.5 pr-3 text-right font-bold ${
                    pos.profit >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {pos.profit >= 0 ? "+" : ""}${pos.profit.toFixed(2)}
                </td>
                <td className="py-2.5 text-right">
                  <div className="inline-flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => openModify(pos)}
                      className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] text-slate-200 hover:bg-slate-700"
                      title="Edit SL/TP"
                    >
                      <Edit3 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setCloseTarget({
                          ticket: pos.ticket,
                          label: `Close ${pos.side} ${pos.volume} ${pos.symbol} (#${pos.ticket})`,
                        })
                      }
                      className="rounded border border-rose-500/30 bg-rose-500/15 px-2 py-1 text-[11px] font-medium text-rose-300 hover:bg-rose-500/25"
                    >
                      Close
                    </button>
                  </div>
                </td>
              </tr>
            ))}

            {orders.map((ord) => (
              <tr key={`ord-${ord.ticket}`} className="bg-slate-950/30 hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 text-slate-400">#{ord.ticket}</td>
                <td className="py-2.5 pr-3">
                  <span className="font-semibold text-slate-200">{ord.symbol}</span>{" "}
                  <span className="ml-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">
                    {ord.side}
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-slate-300">{ord.volume.toFixed(2)}</td>
                <td className="py-2.5 pr-3 text-amber-200">{ord.price_open}</td>
                <td className="py-2.5 pr-3 text-slate-400">{ord.price_current}</td>
                <td className="py-2.5 pr-3 text-rose-300">{ord.sl > 0 ? ord.sl : "—"}</td>
                <td className="py-2.5 pr-3 text-emerald-300">{ord.tp > 0 ? ord.tp : "—"}</td>
                <td className="py-2.5 pr-3 text-right text-slate-500">PENDING</td>
                <td className="py-2.5 text-right">
                  <button
                    type="button"
                    onClick={() =>
                      setCloseTarget({
                        ticket: ord.ticket,
                        label: `Cancel ${ord.side} #${ord.ticket}`,
                      })
                    }
                    className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-700"
                  >
                    <Trash2 className="h-3 w-3" />
                    Cancel
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <h3 className="text-sm font-semibold text-slate-100">
                Modify #{editTarget.ticket} ({editTarget.side} {editTarget.symbol})
              </h3>
              <button
                type="button"
                onClick={() => setEditTarget(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs text-rose-300">Stop Loss (0 to clear)</label>
                <input
                  type="number"
                  step="0.01"
                  value={slInput}
                  onChange={(e) => setSlInput(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                />
              </div>
              <div>
                <label className="block text-xs text-emerald-300">Take Profit (0 to clear)</label>
                <input
                  type="number"
                  step="0.01"
                  value={tpInput}
                  onChange={(e) => setTpInput(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditTarget(null)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={submitModify}
                className="rounded-lg bg-amber-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
              >
                {busy ? "Saving..." : "Save SL/TP"}
              </button>
            </div>
          </div>
        </div>
      )}

      {closeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-rose-500/40 bg-slate-900 p-5 shadow-2xl">
            <h3 className="text-sm font-bold text-rose-300">Confirm Close / Cancel</h3>
            <p className="mt-2 text-xs text-slate-300">{closeTarget.label}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCloseTarget(null)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300"
              >
                Back
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={submitClose}
                className="rounded-lg bg-rose-500 px-4 py-1.5 text-xs font-bold text-white hover:bg-rose-400 disabled:opacity-50"
              >
                {busy ? "Closing..." : "Confirm Close"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
