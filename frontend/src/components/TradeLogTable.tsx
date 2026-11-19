import { useState } from "react";
import { Download, Edit2, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { getExportCsvUrl, syncLogs, updateLogNotes } from "../services/api";
import type { AuditEvent, TradeLogEntry } from "../types/trading";

interface TradeLogTableProps {
  logs: TradeLogEntry[];
  auditEvents: AuditEvent[];
  onRefresh: () => void;
}

export function TradeLogTable({ logs, auditEvents, onRefresh }: TradeLogTableProps) {
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [sideFilter, setSideFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [syncing, setSyncing] = useState(false);

  const [editing, setEditing] = useState<TradeLogEntry | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [notesInput, setNotesInput] = useState("");
  const [saving, setSaving] = useState(false);

  const filtered = logs.filter((item) => {
    if (statusFilter !== "ALL" && item.status !== statusFilter) return false;
    if (sideFilter !== "ALL" && !item.side.startsWith(sideFilter)) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      const hay = `${item.symbol} ${item.strategy_tag} ${item.notes} ${item.source}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncLogs(90);
      onRefresh();
    } finally {
      setSyncing(false);
    }
  };

  const openEditor = (row: TradeLogEntry) => {
    setEditing(row);
    setTagInput(row.strategy_tag || "");
    setNotesInput(row.notes || "");
  };

  const saveEditor = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateLogNotes(editing.id, tagInput, notesInput);
      setEditing(null);
      onRefresh();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2b2b2b] pb-3">
          <div>
            <h2 className="text-sm font-semibold text-[#e1e1e1]">
              Trade Journal & Execution History ({filtered.length})
            </h2>
            <p className="text-xs text-[#9d9d9d]">
              บันทึกประวัติการเทรดทุกไม้พร้อม Tag กลยุทธ์และบันทึกโน้ต
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs font-medium text-[#cccccc] hover:bg-[#3c3c3c] disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Syncing..." : "Sync MT5"}
            </button>
            <a
              href={getExportCsvUrl()}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded bg-[#007acc] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2]"
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </a>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-[#6e6e6e]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ค้นหา Tag, Note, Symbol..."
              className="w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] py-1.5 pl-8 pr-3 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2.5 py-1.5 text-xs text-[#cccccc]"
          >
            <option value="ALL">All Status</option>
            <option value="OPEN">OPEN</option>
            <option value="CLOSED">CLOSED</option>
          </select>
          <select
            value={sideFilter}
            onChange={(e) => setSideFilter(e.target.value)}
            className="rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2.5 py-1.5 text-xs text-[#cccccc]"
          >
            <option value="ALL">All Sides</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>

        <div className="mt-3 overflow-x-auto rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2">
          <table className="font-mono-num w-full min-w-[820px] text-left text-xs">
            <thead>
              <tr className="border-b border-[#2b2b2b] text-[11px] uppercase tracking-wider text-[#9d9d9d]">
                <th className="py-2 pr-3">Close / Open Time</th>
                <th className="py-2 pr-3">Symbol / Side</th>
                <th className="py-2 pr-3">Lots</th>
                <th className="py-2 pr-3">Entry</th>
                <th className="py-2 pr-3">Exit</th>
                <th className="py-2 pr-3 text-right">Net P/L</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Tag & Notes</th>
                <th className="py-2 text-right">Edit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2b2b2b]">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-[#6e6e6e]">
                    ยังไม่มีรายการเทรดที่ตรงกับเงื่อนไข
                  </td>
                </tr>
              ) : (
                filtered.map((row) => (
                  <tr key={row.id} className="hover:bg-[#2a2d2e]">
                    <td className="py-2 pr-3 text-[#9d9d9d]">
                      {row.close_time || row.open_time || row.created_at}
                    </td>
                    <td className="py-2 pr-3">
                      <span className="font-semibold text-[#e1e1e1]">{row.symbol}</span>{" "}
                      <span
                        className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                          row.side.startsWith("BUY")
                            ? "bg-[#3fb950]/15 text-[#3fb950]"
                            : "bg-[#f14c4c]/15 text-[#f14c4c]"
                        }`}
                      >
                        {row.side}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-[#cccccc]">{row.volume.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-[#cccccc]">{row.entry_price}</td>
                    <td className="py-2 pr-3 text-[#cccccc]">{row.exit_price ?? "—"}</td>
                    <td
                      className={`py-2 pr-3 text-right font-bold ${
                        row.net_profit > 0
                          ? "text-[#3fb950]"
                          : row.net_profit < 0
                          ? "text-[#f14c4c]"
                          : "text-[#cccccc]"
                      }`}
                    >
                      {row.net_profit >= 0 ? "+" : ""}${row.net_profit.toFixed(2)}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          row.status === "CLOSED"
                            ? "bg-[#313131] text-[#cccccc]"
                            : "bg-[#007acc]/20 text-[#4fc1ff]"
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="max-w-[260px] py-2 pr-3">
                      {row.strategy_tag && (
                        <span className="mr-1.5 rounded bg-[#007acc]/20 px-1.5 py-0.5 text-[10px] text-[#4fc1ff]">
                          {row.strategy_tag}
                        </span>
                      )}
                      <span className="text-[#cccccc] line-clamp-1">{row.notes || "—"}</span>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => openEditor(row)}
                        className="rounded border border-[#3c3c3c] bg-[#313131] p-1.5 text-[#cccccc] hover:bg-[#3c3c3c]"
                        title="Edit Notes & Tag"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-4">
        <div className="flex items-center gap-2 border-b border-[#2b2b2b] pb-2.5">
          <ShieldCheck className="h-4 w-4 text-[#4fc1ff]" />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
            Execution & Proposal Audit Trail ({auditEvents.length})
          </h3>
        </div>
        <div className="mt-3 max-h-60 space-y-1.5 overflow-y-auto pr-1 text-xs">
          {auditEvents.length === 0 ? (
            <p className="text-[#6e6e6e]">ยังไม่มี Audit Log</p>
          ) : (
            auditEvents.map((ev) => (
              <div
                key={ev.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 rounded bg-[#313131] px-1.5 py-0.5 text-[10px] font-semibold text-[#dcdcaa]">
                    {ev.event_type}
                  </span>
                  <span className="break-words text-[#cccccc]">{ev.summary}</span>
                </div>
                <span className="font-mono-num text-[11px] text-[#6e6e6e]">
                  {ev.actor} · {ev.created_at}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-md rounded-md border border-[#3c3c3c] bg-[#252526] p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-2.5">
              <h3 className="text-sm font-semibold text-[#e1e1e1]">
                Edit Journal Entry #{editing.id}
              </h3>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="text-[#9d9d9d] hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs text-[#cccccc]">Strategy Tag</label>
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  placeholder="เช่น H1 EMA20 Rejection, News Fade"
                  className="mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-xs text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-[#cccccc]">Journal Notes</label>
                <textarea
                  rows={4}
                  value={notesInput}
                  onChange={(e) => setNotesInput(e.target.value)}
                  placeholder="บันทึกเหตุผล/ผลลัพธ์หลังจบไม้..."
                  className="mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-xs text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs text-[#cccccc]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={saveEditor}
                className="rounded bg-[#007acc] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Journal"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
