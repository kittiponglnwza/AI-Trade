import { useEffect, useState } from "react";
import { Edit3, ShieldCheck, Trash2, X } from "lucide-react";
import {
  closePosition,
  fetchPositionManagerStatus,
  modifyPosition,
  movePositionToBreakeven,
  updatePositionManagerConfig,
} from "../services/api";
import type { OpenPosition, PendingOrder, PositionManagerConfig } from "../types/trading";

interface PositionsTableProps {
  positions: OpenPosition[];
  orders: PendingOrder[];
  onUpdated: () => void;
}

export function PositionsTable({ positions, orders, onUpdated }: PositionsTableProps) {
  const [subTab, setSubTab] = useState<"positions" | "orders">("positions");
  const [editTarget, setEditTarget] = useState<OpenPosition | null>(null);
  const [slInput, setSlInput] = useState("");
  const [tpInput, setTpInput] = useState("");
  const [closeTarget, setCloseTarget] = useState<{ ticket: number; label: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [pmCfg, setPmCfg] = useState<PositionManagerConfig | null>(null);

  useEffect(() => {
    fetchPositionManagerStatus()
      .then((res) => setPmCfg(res.config))
      .catch(() => {});
  }, []);

  const handleTogglePmFlag = async (patch: Partial<PositionManagerConfig>) => {
    setBusy(true);
    setErrMsg(null);
    try {
      const res = await updatePositionManagerConfig(patch);
      setPmCfg(res.config);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "อัปเดต Smart Position Manager ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const handleOneClickBe = async (ticket: number) => {
    setBusy(true);
    setErrMsg(null);
    try {
      await movePositionToBreakeven(ticket);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "เลื่อน SL บังทุนไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

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
      setErrMsg(err instanceof Error ? err.message : "แก้ไข SL/TP ไม่สำเร็จ");
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
      setErrMsg(err instanceof Error ? err.message : "ปิดออเดอร์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-md border border-[#2b2b2b] bg-[#252526]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] px-3 py-1.5">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setSubTab("positions")}
            className={`border-b-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition ${
              subTab === "positions"
                ? "border-[#007acc] text-[#e1e1e1]"
                : "border-transparent text-[#9d9d9d] hover:text-[#cccccc]"
            }`}
          >
            Open Positions ({positions.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("orders")}
            className={`border-b-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition ${
              subTab === "orders"
                ? "border-[#007acc] text-[#e1e1e1]"
                : "border-transparent text-[#9d9d9d] hover:text-[#cccccc]"
            }`}
          >
            Pending Orders ({orders.length})
          </button>
        </div>

        {pmCfg && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <button
              type="button"
              disabled={busy}
              onClick={() => handleTogglePmFlag({ enabled: !pmCfg.enabled })}
              className={`flex items-center gap-1 rounded border px-2 py-0.5 font-semibold ${
                pmCfg.enabled
                  ? "border-[#4ec9b0]/50 bg-[#4ec9b0]/15 text-[#4ec9b0]"
                  : "border-[#3c3c3c] bg-[#313131] text-[#9d9d9d]"
              }`}
              title="ระบบดูแลไม้หลังเข้าออเดอร์อัตโนมัติ (ตรวจสอบทุก 5 วินาที)"
            >
              <ShieldCheck className="h-3 w-3" />
              Auto-Guard: {pmCfg.enabled ? "ON" : "OFF"}
            </button>

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_breakeven: !pmCfg.auto_breakeven })}
              className={`rounded border px-2 py-0.5 ${
                pmCfg.enabled && pmCfg.auto_breakeven
                  ? "border-[#3fb950]/40 bg-[#3fb950]/15 text-[#3fb950]"
                  : "border-[#3c3c3c] bg-[#1e1e1e] text-[#6e6e6e]"
              }`}
              title="เมื่อกำไรถึง +1.0R จะขยับ SL มาบังทุนให้อัตโนมัติ"
            >
              Auto-BE (+{pmCfg.be_trigger_r}R)
            </button>

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_partial_tp: !pmCfg.auto_partial_tp })}
              className={`rounded border px-2 py-0.5 ${
                pmCfg.enabled && pmCfg.auto_partial_tp
                  ? "border-[#007acc]/50 bg-[#007acc]/15 text-[#4fc1ff]"
                  : "border-[#3c3c3c] bg-[#1e1e1e] text-[#6e6e6e]"
              }`}
              title="เมื่อกำไรถึง +1.5R จะแบ่งปิด 50% ล็อกกำไรเข้ากระเป๋า"
            >
              Partial {pmCfg.partial_close_pct}% (+{pmCfg.partial_trigger_r}R)
            </button>

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_trailing_sl: !pmCfg.auto_trailing_sl })}
              className={`rounded border px-2 py-0.5 ${
                pmCfg.enabled && pmCfg.auto_trailing_sl
                  ? "border-[#c586c0]/50 bg-[#c586c0]/15 text-[#e5a6e0]"
                  : "border-[#3c3c3c] bg-[#1e1e1e] text-[#6e6e6e]"
              }`}
              title="เมื่อกำไรถึง +1.5R จะลาก SL ตามกราฟอัตโนมัติ"
            >
              Trail SL (+{pmCfg.trail_start_r}R)
            </button>
          </div>
        )}
      </div>

      {errMsg && (
        <div className="m-3 rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 p-2.5 text-xs text-[#f48771] break-words">
          {errMsg}
        </div>
      )}

      <div className="overflow-x-auto bg-[#1e1e1e] p-3">
        <table className="font-mono-num w-full min-w-[680px] text-left text-xs">
          <thead>
            <tr className="border-b border-[#2b2b2b] text-[11px] uppercase tracking-wider text-[#9d9d9d]">
              <th className="py-2 pr-3">Ticket</th>
              <th className="py-2 pr-3">Symbol / Side</th>
              <th className="py-2 pr-3">Lots</th>
              <th className="py-2 pr-3">Open</th>
              <th className="py-2 pr-3">Current</th>
              <th className="py-2 pr-3">SL</th>
              <th className="py-2 pr-3">TP</th>
              <th className="py-2 pr-3">R / Guard</th>
              <th className="py-2 pr-3 text-right">P/L</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2b2b2b]">
            {subTab === "positions" && positions.length === 0 && (
              <tr>
                <td colSpan={10} className="py-6 text-center text-[#6e6e6e]">
                  ไม่มีออเดอร์ที่เปิดอยู่ใน MT5
                </td>
              </tr>
            )}
            {subTab === "orders" && orders.length === 0 && (
              <tr>
                <td colSpan={10} className="py-6 text-center text-[#6e6e6e]">
                  ไม่มี Pending Order ที่ตั้งค้างไว้
                </td>
              </tr>
            )}

            {subTab === "positions" &&
              positions.map((pos) => (
                <tr key={`pos-${pos.ticket}`} className="hover:bg-[#2a2d2e]">
                  <td className="py-2 pr-3 text-[#9d9d9d]">#{pos.ticket}</td>
                  <td className="py-2 pr-3">
                    <span className="font-semibold text-[#e1e1e1]">{pos.symbol}</span>{" "}
                    <span
                      className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        pos.side === "BUY"
                          ? "bg-[#3fb950]/15 text-[#3fb950]"
                          : "bg-[#f14c4c]/15 text-[#f14c4c]"
                      }`}
                    >
                      {pos.side}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-[#cccccc]">{pos.volume.toFixed(2)}</td>
                  <td className="py-2 pr-3 text-[#9d9d9d]">{pos.price_open}</td>
                  <td className="py-2 pr-3 font-medium text-[#e1e1e1]">{pos.price_current}</td>
                  <td className="py-2 pr-3 text-[#f14c4c]">{pos.sl > 0 ? pos.sl : "—"}</td>
                  <td className="py-2 pr-3 text-[#3fb950]">{pos.tp > 0 ? pos.tp : "—"}</td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap items-center gap-1">
                      {typeof pos.current_r === "number" && (
                        <span
                          className={`font-semibold ${
                            pos.current_r >= 1
                              ? "text-[#3fb950]"
                              : pos.current_r >= 0
                              ? "text-[#4fc1ff]"
                              : "text-[#f14c4c]"
                          }`}
                        >
                          {pos.current_r >= 0 ? "+" : ""}
                          {pos.current_r.toFixed(2)}R
                        </span>
                      )}
                      {pos.be_applied && (
                        <span className="rounded bg-[#3fb950]/20 px-1 py-0.5 text-[9px] font-bold text-[#3fb950]">
                          BE
                        </span>
                      )}
                      {pos.partial_applied && (
                        <span className="rounded bg-[#007acc]/20 px-1 py-0.5 text-[9px] font-bold text-[#4fc1ff]">
                          50% TP
                        </span>
                      )}
                      {(pos.trail_count ?? 0) > 0 && (
                        <span className="rounded bg-[#c586c0]/20 px-1 py-0.5 text-[9px] font-bold text-[#e5a6e0]">
                          TRAIL
                        </span>
                      )}
                    </div>
                  </td>
                  <td
                    className={`py-2 pr-3 text-right font-bold ${
                      pos.profit >= 0 ? "text-[#3fb950]" : "text-[#f14c4c]"
                    }`}
                  >
                    {pos.profit >= 0 ? "+" : ""}${pos.profit.toFixed(2)}
                  </td>
                  <td className="py-2 text-right">
                    <div className="inline-flex items-center gap-1.5">
                      {!pos.be_applied && pos.profit > 0 && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleOneClickBe(pos.ticket)}
                          className="rounded border border-[#4ec9b0]/40 bg-[#4ec9b0]/15 px-2 py-1 text-[10px] font-semibold text-[#4ec9b0] hover:bg-[#4ec9b0]/25"
                          title="เลื่อน SL มาบังทุนทันที (1-Click Breakeven)"
                        >
                          บังทุน (BE)
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => openModify(pos)}
                        className="rounded border border-[#3c3c3c] bg-[#313131] px-2 py-1 text-[11px] text-[#cccccc] hover:bg-[#3c3c3c]"
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
                        className="rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/50 px-2 py-1 text-[11px] font-medium text-[#f48771] hover:bg-[#5a1d1d]"
                      >
                        Close
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

            {subTab === "orders" &&
              orders.map((ord) => (
                <tr key={`ord-${ord.ticket}`} className="hover:bg-[#2a2d2e]">
                  <td className="py-2 pr-3 text-[#9d9d9d]">#{ord.ticket}</td>
                  <td className="py-2 pr-3">
                    <span className="font-semibold text-[#e1e1e1]">{ord.symbol}</span>{" "}
                    <span className="ml-1 rounded bg-[#007acc]/20 px-1.5 py-0.5 text-[10px] font-bold text-[#4fc1ff]">
                      {ord.side}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-[#cccccc]">{ord.volume.toFixed(2)}</td>
                  <td className="py-2 pr-3 text-[#dcdcaa]">{ord.price_open}</td>
                  <td className="py-2 pr-3 text-[#9d9d9d]">{ord.price_current}</td>
                  <td className="py-2 pr-3 text-[#f14c4c]">{ord.sl > 0 ? ord.sl : "—"}</td>
                  <td className="py-2 pr-3 text-[#3fb950]">{ord.tp > 0 ? ord.tp : "—"}</td>
                  <td className="py-2 pr-3 text-[#6e6e6e]">—</td>
                  <td className="py-2 pr-3 text-right text-[#6e6e6e]">PENDING</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        setCloseTarget({
                          ticket: ord.ticket,
                          label: `Cancel ${ord.side} #${ord.ticket}`,
                        })
                      }
                      className="inline-flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2 py-1 text-[11px] text-[#cccccc] hover:bg-[#3c3c3c]"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-sm rounded-md border border-[#3c3c3c] bg-[#252526] p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-2.5">
              <h3 className="text-sm font-semibold text-[#e1e1e1]">
                Modify #{editTarget.ticket} ({editTarget.side} {editTarget.symbol})
              </h3>
              <button
                type="button"
                onClick={() => setEditTarget(null)}
                className="text-[#9d9d9d] hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs text-[#f14c4c]">Stop Loss (0 = Clear)</label>
                <input
                  type="number"
                  step="0.01"
                  value={slInput}
                  onChange={(e) => setSlInput(e.target.value)}
                  className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-[#3fb950]">Take Profit (0 = Clear)</label>
                <input
                  type="number"
                  step="0.01"
                  value={tpInput}
                  onChange={(e) => setTpInput(e.target.value)}
                  className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditTarget(null)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs text-[#cccccc]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={submitModify}
                className="rounded bg-[#007acc] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                {busy ? "Saving..." : "Save SL/TP"}
              </button>
            </div>
          </div>
        </div>
      )}

      {closeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-sm rounded-md border border-[#f14c4c]/40 bg-[#252526] p-5 shadow-2xl">
            <h3 className="text-sm font-bold text-[#f14c4c]">Confirm Close / Cancel</h3>
            <p className="mt-2 text-xs text-[#cccccc]">{closeTarget.label}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCloseTarget(null)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs text-[#cccccc]"
              >
                Back
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={submitClose}
                className="rounded bg-[#c72e2e] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#f14c4c] disabled:opacity-50"
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
