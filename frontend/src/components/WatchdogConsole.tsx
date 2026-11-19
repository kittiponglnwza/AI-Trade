import { useState } from "react";
import { Activity, ChevronDown, ChevronUp, Play, Power, Terminal } from "lucide-react";
import { triggerWatchdogScan, updateWatchdogConfig } from "../services/api";
import type { SystemLogEntry, WatchdogStatus } from "../types/trading";

interface WatchdogConsoleProps {
  watchdogStatus: WatchdogStatus | null;
  systemLogs: SystemLogEntry[];
  compact?: boolean;
  onUpdated: () => void;
}

export function WatchdogConsole({
  watchdogStatus,
  systemLogs,
  compact = false,
  onUpdated,
}: WatchdogConsoleProps) {
  const [collapsed, setCollapsed] = useState(compact);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const cfg = watchdogStatus?.config;

  const handleToggleEnabled = async () => {
    if (!cfg) return;
    setBusy(true);
    setErrMsg(null);
    try {
      await updateWatchdogConfig({ enabled: !cfg.enabled });
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Failed to toggle watchdog");
    } finally {
      setBusy(false);
    }
  };

  const handleToggleAutoPropose = async () => {
    if (!cfg) return;
    setBusy(true);
    setErrMsg(null);
    try {
      await updateWatchdogConfig({ auto_propose: !cfg.auto_propose });
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Failed to update auto-propose");
    } finally {
      setBusy(false);
    }
  };

  const handleIntervalChange = async (intervalSec: number) => {
    setBusy(true);
    setErrMsg(null);
    try {
      await updateWatchdogConfig({ interval_sec: intervalSec });
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Failed to update interval");
    } finally {
      setBusy(false);
    }
  };

  const handleScanNow = async () => {
    setBusy(true);
    setErrMsg(null);
    try {
      await triggerWatchdogScan();
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setBusy(false);
    }
  };

  const levelTone = (level: string) => {
    if (level === "SIGNAL") return "text-[#3fb950] font-bold";
    if (level === "WARN") return "text-[#dcdcaa]";
    if (level === "ERROR") return "text-[#f14c4c] font-bold";
    return "text-[#4fc1ff]";
  };

  return (
    <div className="rounded-md border border-[#2b2b2b] bg-[#252526]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] px-3 py-2">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-[#4fc1ff]" />
          <span className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
            24/7 Watchdog & Live Output Console ({systemLogs.length})
          </span>
          {cfg && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                cfg.enabled
                  ? "bg-[#3fb950]/15 text-[#3fb950]"
                  : "bg-[#313131] text-[#9d9d9d]"
              }`}
            >
              {watchdogStatus?.scanning_now
                ? "SCANNING..."
                : cfg.enabled
                ? `ACTIVE · every ${cfg.interval_sec}s`
                : "PAUSED"}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          {cfg && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={handleToggleEnabled}
                className={`flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] font-semibold ${
                  cfg.enabled
                    ? "border-[#3fb950]/40 bg-[#3fb950]/15 text-[#3fb950]"
                    : "border-[#3c3c3c] bg-[#313131] text-[#9d9d9d]"
                }`}
              >
                <Power className="h-3 w-3" />
                {cfg.enabled ? "24/7 ON" : "24/7 OFF"}
              </button>

              <button
                type="button"
                disabled={busy}
                onClick={handleToggleAutoPropose}
                className={`rounded border px-2.5 py-1 text-[11px] font-medium ${
                  cfg.auto_propose
                    ? "border-[#007acc] bg-[#007acc]/20 text-[#4fc1ff]"
                    : "border-[#3c3c3c] bg-[#313131] text-[#9d9d9d]"
                }`}
                title="When ON, 8/8 Gauntlet PASS setups auto-queue into Pending Confirmation"
              >
                Auto-Queue: {cfg.auto_propose ? "ON" : "OFF"}
              </button>

              <select
                value={cfg.interval_sec}
                disabled={busy}
                onChange={(e) => handleIntervalChange(Number(e.target.value))}
                className="rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-1 text-[11px] text-[#cccccc]"
              >
                <option value={60}>60s</option>
                <option value={120}>120s</option>
                <option value={300}>300s</option>
              </select>
            </>
          )}

          <button
            type="button"
            disabled={busy}
            onClick={handleScanNow}
            className="flex items-center gap-1 rounded bg-[#007acc] px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
          >
            <Play className="h-3 w-3" />
            {busy ? "Scanning..." : "Scan All Now"}
          </button>

          {compact && (
            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              className="rounded border border-[#3c3c3c] bg-[#313131] p-1 text-[#cccccc] hover:bg-[#3c3c3c]"
              title={collapsed ? "Expand Console" : "Collapse Console"}
            >
              {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>

      {errMsg && (
        <div className="m-2.5 rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 p-2 text-xs text-[#f48771]">
          {errMsg}
        </div>
      )}

      {!collapsed && (
        <div className="space-y-2.5 bg-[#1e1e1e] p-3">
          {watchdogStatus && watchdogStatus.last_results.length > 0 && (
            <div className="flex flex-wrap gap-1.5 border-b border-[#2b2b2b] pb-2.5">
              {watchdogStatus.last_results.map((item) => (
                <div
                  key={item.symbol}
                  className="font-mono-num flex items-center gap-1.5 rounded border border-[#2b2b2b] bg-[#252526] px-2 py-1 text-[11px]"
                >
                  <Activity className="h-3 w-3 text-[#4fc1ff]" />
                  <span className="font-bold text-[#e1e1e1]">{item.symbol}</span>
                  <span
                    className={
                      item.verdict === "PASS"
                        ? "text-[#3fb950] font-semibold"
                        : item.verdict === "WAIT"
                        ? "text-[#dcdcaa]"
                        : "text-[#f14c4c]"
                    }
                  >
                    {item.verdict} ({item.passed_count}/{item.total_gates})
                  </span>
                </div>
              ))}
            </div>
          )}

          <div
            className={`font-mono-num space-y-1 overflow-y-auto rounded border border-[#2b2b2b] bg-[#181818] p-2.5 text-[11px] ${
              compact ? "max-h-48" : "max-h-96"
            }`}
          >
            {systemLogs.length === 0 ? (
              <div className="py-4 text-center text-[#6e6e6e]">
                ยังไม่มี Log — กด &ldquo;Scan All Now&rdquo; หรือรอ Watchdog สแกนรอบแรก
              </div>
            ) : (
              systemLogs.map((log) => (
                <div key={log.id} className="flex items-start gap-2 leading-relaxed">
                  <span className="shrink-0 text-[#6e6e6e]">{log.created_at.slice(11)}</span>
                  <span className={`w-14 shrink-0 ${levelTone(log.level)}`}>[{log.level}]</span>
                  <span className="w-20 shrink-0 text-[#c586c0]">[{log.category}]</span>
                  <span className="min-w-0 flex-1 text-[#cccccc] break-words">{log.message}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
