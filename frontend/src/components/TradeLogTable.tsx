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
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-base font-semibold text-slate-100">
              Trade Journal & Execution History ({filtered.length})
            </h2>
            <p className="text-xs text-slate-400">
              Every confirmed trade and MT5 closed deal is persisted with notes & strategy tags
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Syncing..." : "Sync MT5"}
            </button>
            <a
              href={getExportCsvUrl()}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-amber-400"
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </a>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search notes, strategy tag, symbol..."
              className="w-full rounded-lg border border-slate-800 bg-slate-950 py-1.5 pl-8 pr-3 text-xs text-slate-100 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-200"
          >
            <option value="ALL">All Status</option>
            <option value="OPEN">OPEN</option>
            <option value="CLOSED">CLOSED</option>
          </select>
          <select
            value={sideFilter}
            onChange={(e) => setSideFilter(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-200"
          >
            <option value="ALL">All Sides</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-xs tabular-nums">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
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
            <tbody className="divide-y divide-slate-800/70">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    No matching trade logs yet.
                  </td>
                </tr>
              ) : (
                filtered.map((row) => (
                  <tr key={row.id} className="hover:bg-slate-800/30">
                    <td className="py-2.5 pr-3 text-slate-400">
                      {row.close_time || row.open_time || row.created_at}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="font-semibold text-slate-100">{row.symbol}</span>{" "}
                      <span
                        className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                          row.side.startsWith("BUY")
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-rose-500/20 text-rose-300"
                        }`}
                      >
                        {row.side}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-slate-200">{row.volume.toFixed(2)}</td>
                    <td className="py-2.5 pr-3 text-slate-300">{row.entry_price}</td>
                    <td className="py-2.5 pr-3 text-slate-300">{row.exit_price ?? "—"}</td>
                    <td
                      className={`py-2.5 pr-3 text-right font-bold ${
                        row.net_profit > 0
                          ? "text-emerald-400"
                          : row.net_profit < 0
                          ? "text-rose-400"
                          : "text-slate-300"
                      }`}
                    >
                      {row.net_profit >= 0 ? "+" : ""}${row.net_profit.toFixed(2)}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          row.status === "CLOSED"
                            ? "bg-slate-800 text-slate-300"
                            : "bg-sky-500/20 text-sky-300"
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 max-w-[260px]">
                      {row.strategy_tag && (
                        <span className="mr-1.5 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">
                          {row.strategy_tag}
                        </span>
                      )}
                      <span className="text-slate-300 line-clamp-1">{row.notes || "—"}</span>
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => openEditor(row)}
                        className="rounded border border-slate-700 bg-slate-800 p-1.5 text-slate-300 hover:bg-slate-700"
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

      <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
        <div className="flex items-center gap-2 border-b border-slate-800 pb-2.5">
          <ShieldCheck className="h-4 w-4 text-sky-400" />
          <h3 className="text-sm font-semibold text-slate-100">
            Execution & Proposal Audit Trail ({auditEvents.length})
          </h3>
        </div>
        <div className="mt-3 max-h-60 space-y-1.5 overflow-y-auto pr-1 text-xs">
          {auditEvents.length === 0 ? (
            <p className="text-slate-500">No audit events recorded yet.</p>
          ) : (
            auditEvents.map((ev) => (
              <div
                key={ev.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-950/70 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                    {ev.event_type}
                  </span>
                  <span className="text-slate-200">{ev.summary}</span>
                </div>
                <span className="text-[11px] text-slate-500 tabular-nums">
                  {ev.actor} · {ev.created_at}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
              <h3 className="text-sm font-semibold text-slate-100">
                Edit Journal Entry #{editing.id}
              </h3>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs text-slate-300">Strategy Tag</label>
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  placeholder="e.g. H1 EMA20 Rejection, News Fade"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-300">Journal Notes</label>
                <textarea
                  rows={4}
                  value={notesInput}
                  onChange={(e) => setNotesInput(e.target.value)}
                  placeholder="What worked? Did you follow plan?"
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
                />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={saveEditor}
                className="rounded-lg bg-amber-500 px-4 py-1.5 text-xs font-bold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
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
