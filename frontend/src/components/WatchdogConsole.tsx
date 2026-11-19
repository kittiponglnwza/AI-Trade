import { useEffect, useState } from "react";
import { Activity, Bot, ChevronDown, ChevronUp, Play, Power, Save, Sliders, Terminal } from "lucide-react";
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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const cfg = watchdogStatus?.config;

  const [minConfInput, setMinConfInput] = useState("75");
  const [intervalInput, setIntervalInput] = useState("120");
  const [tfInput, setTfInput] = useState("M15");
  const [riskInput, setRiskInput] = useState("2.0");
  const [cooldownInput, setCooldownInput] = useState("30");
  const [ttlInput, setTtlInput] = useState("45");
  const [maxDailyLossInput, setMaxDailyLossInput] = useState("5.0");
  const [maxOpenRiskInput, setMaxOpenRiskInput] = useState("15.0");
  const [apMinConfInput, setApMinConfInput] = useState("80");
  const [apSizingMode, setApSizingMode] = useState<"FIXED_LOT" | "RISK_PCT">("FIXED_LOT");
  const [apLotsInput, setApLotsInput] = useState("0.01");
  const [apRiskInput, setApRiskInput] = useState("1.0");
  const [apMaxOpenInput, setApMaxOpenInput] = useState("3");

  useEffect(() => {
    if (!cfg) return;
    setMinConfInput(String(cfg.min_confidence_pct ?? 75));
    setIntervalInput(String(cfg.interval_sec ?? 120));
    setTfInput(String(cfg.timeframe ?? "M15"));
    setRiskInput(String(cfg.risk_pct ?? 2.0));
    setCooldownInput(String(cfg.cooldown_min ?? 30));
    setTtlInput(String(cfg.proposal_ttl_min ?? 45));
    setMaxDailyLossInput(String(cfg.max_daily_loss_pct ?? 5.0));
    setMaxOpenRiskInput(String(cfg.max_open_risk_pct ?? 15.0));
    setApMinConfInput(String(cfg.autopilot_min_confidence_pct ?? 80));
    setApSizingMode((cfg.autopilot_sizing_mode as "FIXED_LOT" | "RISK_PCT") || "FIXED_LOT");
    setApLotsInput(String(cfg.autopilot_fixed_lots ?? 0.01));
    setApRiskInput(String(cfg.autopilot_risk_pct ?? 1.0));
    setApMaxOpenInput(String(cfg.autopilot_max_open_positions ?? 3));
  }, [cfg]);

  const handlePatch = async (patch: Record<string, unknown>, msg?: string) => {
    setBusy(true);
    setErrMsg(null);
    setSaveMsg(null);
    try {
      await updateWatchdogConfig(patch);
      if (msg) setSaveMsg(msg);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Failed to update watchdog");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveAdvanced = async () => {
    await handlePatch(
      {
        min_confidence_pct: Math.min(95, Math.max(50, parseFloat(minConfInput) || 75)),
        interval_sec: Math.min(3600, Math.max(30, parseInt(intervalInput, 10) || 120)),
        timeframe: tfInput,
        risk_pct: Math.min(50, Math.max(0.1, parseFloat(riskInput) || 2.0)),
        cooldown_min: Math.min(1440, Math.max(1, parseInt(cooldownInput, 10) || 30)),
        proposal_ttl_min: Math.min(1440, Math.max(5, parseInt(ttlInput, 10) || 45)),
        max_daily_loss_pct: Math.min(50, Math.max(0.5, parseFloat(maxDailyLossInput) || 5.0)),
        max_open_risk_pct: Math.min(100, Math.max(1, parseFloat(maxOpenRiskInput) || 15.0)),
        autopilot_min_confidence_pct: Math.min(95, Math.max(55, parseFloat(apMinConfInput) || 80)),
        autopilot_sizing_mode: apSizingMode,
        autopilot_fixed_lots: Math.min(5, Math.max(0.01, parseFloat(apLotsInput) || 0.01)),
        autopilot_risk_pct: Math.min(50, Math.max(0.1, parseFloat(apRiskInput) || 1.0)),
        autopilot_max_open_positions: Math.min(10, Math.max(1, parseInt(apMaxOpenInput, 10) || 3)),
      },
      "บันทึกการตั้งค่า Watchdog & Risk Guard เรียบร้อยแล้ว"
    );
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
                ? `ACTIVE · ${cfg.timeframe} · every ${cfg.interval_sec}s · Gate ≥${cfg.min_confidence_pct}%`
                : "PAUSED"}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {cfg && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => handlePatch({ enabled: !cfg.enabled })}
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
                onClick={() => handlePatch({ auto_propose: !cfg.auto_propose })}
                className={`rounded border px-2.5 py-1 text-[11px] font-medium ${
                  cfg.auto_propose
                    ? "border-[#007acc] bg-[#007acc]/20 text-[#4fc1ff]"
                    : "border-[#3c3c3c] bg-[#313131] text-[#9d9d9d]"
                }`}
              >
                Auto-Queue: {cfg.auto_propose ? "ON" : "OFF"}
              </button>

              <div className="flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-0.5 text-[11px]">
                <span className="text-[#9d9d9d]">Gate ≥</span>
                <input
                  type="number"
                  min="50"
                  max="95"
                  step="1"
                  value={minConfInput}
                  onChange={(e) => setMinConfInput(e.target.value)}
                  onBlur={() =>
                    handlePatch({
                      min_confidence_pct: Math.min(95, Math.max(50, parseFloat(minConfInput) || 75)),
                    })
                  }
                  className="font-mono-num w-10 bg-transparent text-center font-bold text-[#4fc1ff] focus:outline-none"
                  title="พิมพ์ปรับเกณฑ์ความมั่นใจขั้นต่ำได้อิสระ (50% - 95%)"
                />
                <span className="text-[#4fc1ff]">%</span>
              </div>

              <button
                type="button"
                disabled={busy}
                onClick={() => handlePatch({ autopilot_enabled: !cfg.autopilot_enabled })}
                className={`flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] font-semibold ${
                  cfg.autopilot_enabled
                    ? "border-[#c586c0] bg-[#c586c0]/20 text-[#e5a6e0]"
                    : "border-[#3c3c3c] bg-[#313131] text-[#9d9d9d]"
                }`}
                title="โหมดปล่อยบอทยิงพอร์ต DEMO อัตโนมัติเมื่อความมั่นใจถึงเกณฑ์"
              >
                <Bot className="h-3 w-3" />
                Auto-Pilot Demo: {cfg.autopilot_enabled ? "ON" : "OFF"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setShowAdvanced((v) => !v);
                  if (collapsed) setCollapsed(false);
                }}
                className={`flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] font-medium ${
                  showAdvanced
                    ? "border-[#007acc] bg-[#007acc]/20 text-white"
                    : "border-[#3c3c3c] bg-[#313131] text-[#cccccc] hover:bg-[#3c3c3c]"
                }`}
                title="ตั้งค่าความยืดหยุ่น Watchdog, Auto-Pilot และลิมิตป้องกันพอร์ต"
              >
                <Sliders className="h-3 w-3 text-[#dcdcaa]" />
                <span>ตั้งค่า Flex</span>
              </button>
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
      {saveMsg && (
        <div className="m-2.5 rounded border border-[#3fb950]/40 bg-[#1e3a29]/40 p-2 text-xs text-[#3fb950]">
          {saveMsg}
        </div>
      )}

      {showAdvanced && (
        <div className="border-b border-[#2b2b2b] bg-[#1e1e1e] p-3 text-xs space-y-3">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">Gate ขั้นต่ำ (%)</label>
              <input
                type="number"
                min="50"
                max="95"
                step="0.5"
                value={minConfInput}
                onChange={(e) => setMinConfInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#4fc1ff]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">รอบสแกน (วินาที)</label>
              <input
                type="number"
                min="30"
                max="3600"
                step="10"
                value={intervalInput}
                onChange={(e) => setIntervalInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">Timeframe สแกน</label>
              <select
                value={tfInput}
                onChange={(e) => setTfInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              >
                {["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">Risk % ต่อไม้</label>
              <input
                type="number"
                min="0.1"
                max="50"
                step="0.1"
                value={riskInput}
                onChange={(e) => setRiskInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">Cooldown (นาที)</label>
              <input
                type="number"
                min="1"
                max="1440"
                value={cooldownInput}
                onChange={(e) => setCooldownInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">หมดอายุโพย TTL (นาที)</label>
              <input
                type="number"
                min="5"
                max="1440"
                value={ttlInput}
                onChange={(e) => setTtlInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#dcdcaa]"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6 border-t border-[#2b2b2b] pt-2.5">
            <div>
              <label className="block text-[11px] text-[#f48771]">Daily Max Loss (%)</label>
              <input
                type="number"
                min="0.5"
                max="50"
                step="0.5"
                value={maxDailyLossInput}
                onChange={(e) => setMaxDailyLossInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#f14c4c]/40 bg-[#252526] px-2 py-1 text-xs text-[#f48771]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#dcdcaa]">Max Portfolio Risk (%)</label>
              <input
                type="number"
                min="1"
                max="100"
                step="0.5"
                value={maxOpenRiskInput}
                onChange={(e) => setMaxOpenRiskInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#dcdcaa]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#e5a6e0]">Auto-Pilot Gate (%)</label>
              <input
                type="number"
                min="55"
                max="95"
                step="0.5"
                value={apMinConfInput}
                onChange={(e) => setApMinConfInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#c586c0]/50 bg-[#252526] px-2 py-1 text-xs text-[#e5a6e0]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#e5a6e0]">Auto-Pilot โหมดคำนวณ</label>
              <select
                value={apSizingMode}
                onChange={(e) => setApSizingMode(e.target.value as "FIXED_LOT" | "RISK_PCT")}
                className="mt-1 w-full rounded border border-[#c586c0]/50 bg-[#252526] px-2 py-1 text-xs text-[#e5a6e0]"
              >
                <option value="FIXED_LOT">Fixed Lot</option>
                <option value="RISK_PCT">ตาม Risk %</option>
              </select>
            </div>
            {apSizingMode === "FIXED_LOT" ? (
              <div>
                <label className="block text-[11px] text-[#e5a6e0]">Auto-Pilot Lot</label>
                <input
                  type="number"
                  min="0.01"
                  max="5"
                  step="0.01"
                  value={apLotsInput}
                  onChange={(e) => setApLotsInput(e.target.value)}
                  className="font-mono-num mt-1 w-full rounded border border-[#c586c0]/50 bg-[#252526] px-2 py-1 text-xs text-[#e5a6e0]"
                />
              </div>
            ) : (
              <div>
                <label className="block text-[11px] text-[#e5a6e0]">Auto-Pilot Risk (%)</label>
                <input
                  type="number"
                  min="0.1"
                  max="50"
                  step="0.1"
                  value={apRiskInput}
                  onChange={(e) => setApRiskInput(e.target.value)}
                  className="font-mono-num mt-1 w-full rounded border border-[#c586c0]/50 bg-[#252526] px-2 py-1 text-xs text-[#e5a6e0]"
                />
              </div>
            )}
            <div>
              <label className="block text-[11px] text-[#e5a6e0]">Auto-Pilot ถือสูงสุด (ไม้)</label>
              <input
                type="number"
                min="1"
                max="10"
                value={apMaxOpenInput}
                onChange={(e) => setApMaxOpenInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#c586c0]/50 bg-[#252526] px-2 py-1 text-xs text-[#e5a6e0]"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={busy}
              onClick={handleSaveAdvanced}
              className="flex items-center gap-1.5 rounded bg-[#238636] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              บันทึกค่า Flex Config ทั้งหมด
            </button>
          </div>
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
                        ? "font-semibold text-[#3fb950]"
                        : item.verdict === "WAIT"
                        ? "text-[#dcdcaa]"
                        : "text-[#f14c4c]"
                    }
                  >
                    {item.verdict} ({item.passed_count}/{item.total_gates})
                  </span>
                  {typeof item.confidence_pct === "number" && (
                    <span className="text-[#c586c0]">{item.confidence_pct.toFixed(0)}%</span>
                  )}
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
