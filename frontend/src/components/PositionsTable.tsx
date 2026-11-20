import { useEffect, useState } from "react";
import { AlertOctagon, Edit3, History, RefreshCw, Save, ShieldCheck, Sliders, Trash2, X } from "lucide-react";
import {
  closePosition,
  fetchPositionManagerStatus,
  modifyPosition,
  movePositionToBreakeven,
  panicCloseAll,
  syncLogs,
  updatePositionManagerConfig,
} from "../services/api";
import type { OpenPosition, PendingOrder, PositionManagerConfig, TradeLogEntry } from "../types/trading";

interface PositionsTableProps {
  positions: OpenPosition[];
  orders: PendingOrder[];
  tradeHistory?: TradeLogEntry[];
  bridgeLive?: boolean;
  reconnectSeed?: number;
  onOpenFullJournal?: () => void;
  onUpdated: () => void;
}

export function PositionsTable({
  positions,
  orders,
  tradeHistory = [],
  bridgeLive = true,
  reconnectSeed = 0,
  onOpenFullJournal,
  onUpdated,
}: PositionsTableProps) {
  const [subTab, setSubTab] = useState<"positions" | "orders" | "history">("positions");
  const [syncingHistory, setSyncingHistory] = useState(false);
  const [showPmTuning, setShowPmTuning] = useState(false);
  const [editTarget, setEditTarget] = useState<{
    ticket: number;
    symbol: string;
    side: string;
    isOrder: boolean;
    price_open: number;
    sl: number;
    tp: number;
  } | null>(null);
  const [priceInput, setPriceInput] = useState("");
  const [slInput, setSlInput] = useState("");
  const [tpInput, setTpInput] = useState("");

  const [closeTarget, setCloseTarget] = useState<{
    ticket: number;
    label: string;
    maxVolume: number | null;
  } | null>(null);
  const [closeLotsInput, setCloseLotsInput] = useState("");
  const [showPanicModal, setShowPanicModal] = useState(false);

  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);
  const [pmCfg, setPmCfg] = useState<PositionManagerConfig | null>(null);

  const [beTriggerInput, setBeTriggerInput] = useState("1.0");
  const [beOffsetInput, setBeOffsetInput] = useState("5");
  const [partialTriggerInput, setPartialTriggerInput] = useState("1.5");
  const [partialPctInput, setPartialPctInput] = useState("50");
  const [trailStartInput, setTrailStartInput] = useState("1.5");
  const [trailDistInput, setTrailDistInput] = useState("0.8");
  const [pollSecInput, setPollSecInput] = useState("5");

  useEffect(() => {
    let active = true;
    let retryTimer: number | undefined;

    const loadPm = () => {
      fetchPositionManagerStatus()
        .then((res) => {
          if (!active) return;
          setPmCfg(res.config);
          setBeTriggerInput(String(res.config.be_trigger_r ?? 1.0));
          setBeOffsetInput(String(res.config.be_offset_points ?? 5));
          setPartialTriggerInput(String(res.config.partial_trigger_r ?? 1.5));
          setPartialPctInput(String(res.config.partial_close_pct ?? 50));
          setTrailStartInput(String(res.config.trail_start_r ?? 1.5));
          setTrailDistInput(String(res.config.trail_distance_r ?? 0.8));
          setPollSecInput(String(res.config.poll_interval_sec ?? 5));
        })
        .catch(() => {
          if (active && bridgeLive) {
            retryTimer = window.setTimeout(loadPm, 3000);
          }
        });
    };

    loadPm();
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [bridgeLive, reconnectSeed]);

  const handleTogglePmFlag = async (patch: Partial<PositionManagerConfig>, msg?: string) => {
    setBusy(true);
    setErrMsg(null);
    setInfoMsg(null);
    try {
      const res = await updatePositionManagerConfig(patch);
      setPmCfg(res.config);
      if (msg) setInfoMsg(msg);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "อัปเดต Smart Position Manager ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const handleSavePmNumbers = async () => {
    await handleTogglePmFlag(
      {
        be_trigger_r: Math.min(5, Math.max(0.3, parseFloat(beTriggerInput) || 1.0)),
        be_offset_points: Math.min(100, Math.max(0, parseInt(beOffsetInput, 10) || 5)),
        partial_trigger_r: Math.min(10, Math.max(0.5, parseFloat(partialTriggerInput) || 1.5)),
        partial_close_pct: Math.min(90, Math.max(10, parseFloat(partialPctInput) || 50)),
        trail_start_r: Math.min(10, Math.max(0.5, parseFloat(trailStartInput) || 1.5)),
        trail_distance_r: Math.min(5, Math.max(0.2, parseFloat(trailDistInput) || 0.8)),
        poll_interval_sec: Math.min(120, Math.max(2, parseInt(pollSecInput, 10) || 5)),
      },
      "บันทึกค่าตัวเลข Auto-Guard เรียบร้อยแล้ว"
    );
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

  const openModifyPosition = (pos: OpenPosition) => {
    setEditTarget({
      ticket: pos.ticket,
      symbol: pos.symbol,
      side: pos.side,
      isOrder: false,
      price_open: pos.price_open,
      sl: pos.sl,
      tp: pos.tp,
    });
    setPriceInput(String(pos.price_open));
    setSlInput(pos.sl > 0 ? String(pos.sl) : "");
    setTpInput(pos.tp > 0 ? String(pos.tp) : "");
    setErrMsg(null);
  };

  const openModifyOrder = (ord: PendingOrder) => {
    setEditTarget({
      ticket: ord.ticket,
      symbol: ord.symbol,
      side: ord.side,
      isOrder: true,
      price_open: ord.price_open,
      sl: ord.sl,
      tp: ord.tp,
    });
    setPriceInput(String(ord.price_open));
    setSlInput(ord.sl > 0 ? String(ord.sl) : "");
    setTpInput(ord.tp > 0 ? String(ord.tp) : "");
    setErrMsg(null);
  };

  const submitModify = async () => {
    if (!editTarget) return;
    setBusy(true);
    setErrMsg(null);
    try {
      const sl = slInput.trim() ? parseFloat(slInput) : 0;
      const tp = tpInput.trim() ? parseFloat(tpInput) : 0;
      const priceOpen = editTarget.isOrder && priceInput.trim() ? parseFloat(priceInput) : null;
      await modifyPosition(editTarget.ticket, sl, tp, priceOpen);
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
      let lotsToClose: number | null = null;
      if (closeTarget.maxVolume !== null && closeLotsInput.trim()) {
        const parsed = parseFloat(closeLotsInput);
        if (Number.isFinite(parsed) && parsed > 0 && parsed < closeTarget.maxVolume) {
          lotsToClose = Number(parsed.toFixed(2));
        }
      }
      await closePosition(closeTarget.ticket, lotsToClose);
      setCloseTarget(null);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "ปิดออเดอร์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const submitPanicCloseAll = async () => {
    setBusy(true);
    setErrMsg(null);
    setInfoMsg(null);
    try {
      const res = await panicCloseAll(false);
      setShowPanicModal(false);
      setInfoMsg(res.message);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Panic Close All ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const setPartialPreset = (pct: number) => {
    if (!closeTarget || closeTarget.maxVolume === null) return;
    if (pct >= 100) {
      setCloseLotsInput(closeTarget.maxVolume.toFixed(2));
      return;
    }
    const raw = Math.max(0.01, Math.floor(closeTarget.maxVolume * (pct / 100) * 100) / 100);
    setCloseLotsInput(raw.toFixed(2));
  };

  const handleSyncHistory = async () => {
    setSyncingHistory(true);
    setErrMsg(null);
    setInfoMsg(null);
    try {
      const res = await syncLogs(365);
      setInfoMsg(`ซิงก์ประวัติ MT5 แล้ว ${res.total} ไม้ (ใหม่ ${res.inserted}, อัปเดต ${res.updated})`);
      onUpdated();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "ซิงก์ประวัติ MT5 ไม่สำเร็จ");
    } finally {
      setSyncingHistory(false);
    }
  };

  const closedHistory = tradeHistory.filter((t) => t.status === "CLOSED");

  return (
    <div className="rounded-md border border-[#2b2b2b] bg-[#252526]">
      {/* Row 1: Primary Tabs + Emergency Panic Kill-Switch */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] px-3 pt-1">
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            onClick={() => setSubTab("positions")}
            className={`border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
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
            className={`border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
              subTab === "orders"
                ? "border-[#007acc] text-[#e1e1e1]"
                : "border-transparent text-[#9d9d9d] hover:text-[#cccccc]"
            }`}
          >
            Pending Orders ({orders.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("history")}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
              subTab === "history"
                ? "border-[#007acc] text-[#e1e1e1]"
                : "border-transparent text-[#9d9d9d] hover:text-[#cccccc]"
            }`}
          >
            <History className="h-3.5 w-3.5" />
            History ({tradeHistory.length})
          </button>
        </div>

        {(positions.length > 0 || orders.length > 0) && (
          <div className="pb-1">
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowPanicModal(true)}
              className="flex items-center gap-1.5 rounded border border-[#f14c4c] bg-[#c72e2e] px-2.5 py-1 text-[11px] font-bold text-white transition hover:bg-[#f14c4c] disabled:opacity-50"
              title="ปิดทุกไม้ที่เปิดอยู่ + ยกเลิก Pending ทั้งหมด + หยุด Auto-Accept / Auto-Pilot ทันที"
            >
              <AlertOctagon className="h-3.5 w-3.5" />
              PANIC CLOSE ALL
            </button>
          </div>
        )}
      </div>

      {/* Row 2: Dedicated Smart Position Guard Control Strip */}
      {pmCfg && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] bg-[#1f1f20] px-3 py-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => handleTogglePmFlag({ enabled: !pmCfg.enabled })}
              className={`flex items-center gap-1.5 rounded border px-2.5 py-1 font-semibold transition ${
                pmCfg.enabled
                  ? "border-[#4ec9b0]/50 bg-[#4ec9b0]/15 text-[#4ec9b0] hover:bg-[#4ec9b0]/25"
                  : "border-[#3c3c3c] bg-[#2a2a2b] text-[#9d9d9d] hover:bg-[#333334]"
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Auto-Guard: {pmCfg.enabled ? "ON" : "OFF"}
            </button>

            <div className="hidden h-4 w-px bg-[#333333] sm:block" />

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_breakeven: !pmCfg.auto_breakeven })}
              className={`rounded border px-2.5 py-1 font-medium transition ${
                pmCfg.enabled && pmCfg.auto_breakeven
                  ? "border-[#3fb950]/40 bg-[#3fb950]/15 text-[#3fb950] hover:bg-[#3fb950]/25"
                  : "border-[#333333] bg-[#181818] text-[#6e6e6e]"
              }`}
            >
              Auto-BE (+{pmCfg.be_trigger_r}R)
            </button>

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_partial_tp: !pmCfg.auto_partial_tp })}
              className={`rounded border px-2.5 py-1 font-medium transition ${
                pmCfg.enabled && pmCfg.auto_partial_tp
                  ? "border-[#007acc]/50 bg-[#007acc]/15 text-[#4fc1ff] hover:bg-[#007acc]/25"
                  : "border-[#333333] bg-[#181818] text-[#6e6e6e]"
              }`}
            >
              Partial {pmCfg.partial_close_pct}% (+{pmCfg.partial_trigger_r}R)
            </button>

            <button
              type="button"
              disabled={busy || !pmCfg.enabled}
              onClick={() => handleTogglePmFlag({ auto_trailing_sl: !pmCfg.auto_trailing_sl })}
              className={`rounded border px-2.5 py-1 font-medium transition ${
                pmCfg.enabled && pmCfg.auto_trailing_sl
                  ? "border-[#c586c0]/50 bg-[#c586c0]/15 text-[#e5a6e0] hover:bg-[#c586c0]/25"
                  : "border-[#333333] bg-[#181818] text-[#6e6e6e]"
              }`}
            >
              Trail SL (+{pmCfg.trail_start_r}R)
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowPmTuning((v) => !v)}
            className={`flex items-center gap-1.5 rounded border px-2.5 py-1 font-medium transition ${
              showPmTuning
                ? "border-[#007acc] bg-[#007acc]/20 text-white"
                : "border-[#3c3c3c] bg-[#2a2a2b] text-[#cccccc] hover:bg-[#353536]"
            }`}
            title="ปรับตัวเลข +R และ % ของระบบ Auto-Guard"
          >
            <Sliders className="h-3.5 w-3.5 text-[#dcdcaa]" />
            <span>ตั้งค่า Guard</span>
          </button>
        </div>
      )}

      {showPmTuning && (
        <div className="border-b border-[#2b2b2b] bg-[#1e1e1e] p-3 text-xs space-y-2.5">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
            <div>
              <label className="block text-[11px] text-[#3fb950]">ทริกเกอร์บังทุน (+R)</label>
              <input
                type="number"
                step="0.1"
                min="0.3"
                max="5"
                value={beTriggerInput}
                onChange={(e) => setBeTriggerInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#3fb950]">เผื่อค่าคอม BE (Points)</label>
              <input
                type="number"
                min="0"
                max="100"
                value={beOffsetInput}
                onChange={(e) => setBeOffsetInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#4fc1ff]">ทริกเกอร์แบ่งปิด (+R)</label>
              <input
                type="number"
                step="0.1"
                min="0.5"
                max="10"
                value={partialTriggerInput}
                onChange={(e) => setPartialTriggerInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#4fc1ff]">สัดส่วนแบ่งปิด (%)</label>
              <input
                type="number"
                step="5"
                min="10"
                max="90"
                value={partialPctInput}
                onChange={(e) => setPartialPctInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#e5a6e0]">เริ่มลาก Trail SL (+R)</label>
              <input
                type="number"
                step="0.1"
                min="0.5"
                max="10"
                value={trailStartInput}
                onChange={(e) => setTrailStartInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#e5a6e0]">ระยะห่าง Trail (R)</label>
              <input
                type="number"
                step="0.1"
                min="0.2"
                max="5"
                value={trailDistInput}
                onChange={(e) => setTrailDistInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
            <div>
              <label className="block text-[11px] text-[#9d9d9d]">รอบเช็ก (วินาที)</label>
              <input
                type="number"
                min="2"
                max="120"
                value={pollSecInput}
                onChange={(e) => setPollSecInput(e.target.value)}
                className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#252526] px-2 py-1 text-xs text-[#e1e1e1]"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={busy}
              onClick={handleSavePmNumbers}
              className="flex items-center gap-1.5 rounded bg-[#238636] px-3 py-1 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              บันทึกค่าตัวเลข Auto-Guard
            </button>
          </div>
        </div>
      )}

      {errMsg && (
        <div className="m-3 rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 p-2.5 text-xs text-[#f48771] break-words">
          {errMsg}
        </div>
      )}
      {infoMsg && (
        <div className="m-3 rounded border border-[#3fb950]/40 bg-[#1e3a29]/40 p-2.5 text-xs text-[#3fb950] break-words">
          {infoMsg}
        </div>
      )}

      <div className="overflow-x-auto bg-[#1e1e1e] p-3">
        {subTab === "history" ? (
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-[#9d9d9d]">
                ประวัติเทรดล่าสุด ({tradeHistory.length} รายการ · ปิดแล้ว {closedHistory.length} ไม้)
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={syncingHistory}
                  onClick={handleSyncHistory}
                  className="flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1 text-[11px] font-medium text-[#e1e1e1] hover:bg-[#3c3c3c] disabled:opacity-50"
                >
                  <RefreshCw className={`h-3 w-3 ${syncingHistory ? "animate-spin" : ""}`} />
                  {syncingHistory ? "กำลังซิงก์..." : "Sync MT5 History"}
                </button>
                {onOpenFullJournal && (
                  <button
                    type="button"
                    onClick={onOpenFullJournal}
                    className="rounded bg-[#007acc] px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-[#1f8ad2]"
                  >
                    ดูประวัติทั้งหมด →
                  </button>
                )}
              </div>
            </div>

            <table className="font-mono-num w-full min-w-[680px] text-left text-xs">
              <thead>
                <tr className="border-b border-[#2b2b2b] text-[11px] uppercase tracking-wider text-[#9d9d9d]">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Symbol / Side</th>
                  <th className="py-2 pr-3">Lots</th>
                  <th className="py-2 pr-3">Entry → Exit</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Source</th>
                  <th className="py-2 text-right">Net P/L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2b2b2b]">
                {tradeHistory.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-[#6e6e6e]">
                      ยังไม่มีประวัติเทรดในบัญชีนี้ — กด &ldquo;Sync MT5 History&rdquo; เพื่อดึงข้อมูลล่าสุดจาก MT5
                    </td>
                  </tr>
                ) : (
                  tradeHistory.slice(0, 15).map((row) => {
                    const vol = Number(row.volume ?? 0);
                    const net = Number(row.net_profit ?? 0);
                    const sideStr = String(row.side || "");
                    return (
                      <tr key={`hist-${row.id}`} className="hover:bg-[#2a2d2e]">
                        <td className="py-2 pr-3 text-[#9d9d9d]">
                          {row.close_time || row.open_time || row.created_at}
                        </td>
                        <td className="py-2 pr-3">
                          <span className="font-semibold text-[#e1e1e1]">{row.symbol}</span>{" "}
                          <span
                            className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                              sideStr.startsWith("BUY")
                                ? "bg-[#3fb950]/15 text-[#3fb950]"
                                : "bg-[#f14c4c]/15 text-[#f14c4c]"
                            }`}
                          >
                            {sideStr}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-[#cccccc]">{vol.toFixed(2)}</td>
                        <td className="py-2 pr-3 text-[#cccccc]">
                          {row.entry_price} → {row.exit_price ?? "—"}
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
                        <td className="py-2 pr-3 text-[#9d9d9d]">{row.source || "MT5"}</td>
                        <td
                          className={`py-2 text-right font-bold ${
                            net > 0 ? "text-[#3fb950]" : net < 0 ? "text-[#f14c4c]" : "text-[#cccccc]"
                          }`}
                        >
                          {net >= 0 ? "+" : ""}${net.toFixed(2)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        ) : (
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
                          PARTIAL
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
                        onClick={() => openModifyPosition(pos)}
                        className="rounded border border-[#3c3c3c] bg-[#313131] px-2 py-1 text-[11px] text-[#cccccc] hover:bg-[#3c3c3c]"
                        title="Edit SL/TP"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setCloseTarget({
                            ticket: pos.ticket,
                            label: `${pos.side} ${pos.volume.toFixed(2)} Lot ${pos.symbol} (#${pos.ticket})`,
                            maxVolume: pos.volume,
                          });
                          setCloseLotsInput(pos.volume.toFixed(2));
                        }}
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
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => openModifyOrder(ord)}
                        className="rounded border border-[#3c3c3c] bg-[#313131] px-2 py-1 text-[11px] text-[#cccccc] hover:bg-[#3c3c3c]"
                        title="แก้ไขราคาเข้า / SL / TP ของ Pending Order"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setCloseTarget({
                            ticket: ord.ticket,
                            label: `Cancel ${ord.side} #${ord.ticket}`,
                            maxVolume: null,
                          });
                          setCloseLotsInput("");
                        }}
                        className="inline-flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2 py-1 text-[11px] text-[#cccccc] hover:bg-[#3c3c3c]"
                      >
                        <Trash2 className="h-3 w-3" />
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
        )}
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
              {editTarget.isOrder && (
                <div>
                  <label className="block text-xs text-[#dcdcaa]">Pending Entry Price</label>
                  <input
                    type="number"
                    step="0.01"
                    value={priceInput}
                    onChange={(e) => setPriceInput(e.target.value)}
                    className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                  />
                </div>
              )}
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
                {busy ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {closeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-sm rounded-md border border-[#f14c4c]/40 bg-[#252526] p-5 shadow-2xl">
            <h3 className="text-sm font-bold text-[#f14c4c]">
              {closeTarget.maxVolume !== null ? "Close / Partial Close Position" : "Cancel Pending Order"}
            </h3>
            <p className="mt-1.5 text-xs text-[#cccccc]">{closeTarget.label}</p>

            {closeTarget.maxVolume !== null && (
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between text-xs text-[#cccccc]">
                  <span>จำนวน Lot ที่จะปิด</span>
                  <div className="flex gap-1">
                    {[25, 50, 75, 100].map((pct) => (
                      <button
                        key={pct}
                        type="button"
                        onClick={() => setPartialPreset(pct)}
                        className="rounded border border-[#3c3c3c] bg-[#313131] px-1.5 py-0.5 text-[10px] font-semibold text-[#e1e1e1] hover:bg-[#3c3c3c]"
                      >
                        {pct}%
                      </button>
                    ))}
                  </div>
                </div>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  max={closeTarget.maxVolume}
                  value={closeLotsInput}
                  onChange={(e) => setCloseLotsInput(e.target.value)}
                  className="font-mono-num w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
            )}

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

      {showPanicModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
          <div className="w-full max-w-md rounded-md border border-[#f14c4c] bg-[#252526] p-5 shadow-2xl">
            <div className="flex items-center gap-2 text-[#f14c4c]">
              <AlertOctagon className="h-5 w-5" />
              <h3 className="text-base font-bold">🚨 ยืนยัน PANIC CLOSE ALL (ล้างพอร์ตฉุกเฉิน)</h3>
            </div>
            <p className="mt-2.5 text-xs leading-relaxed text-[#cccccc]">
              ระบบจะทำการ <strong>ปิดทุกออเดอร์ที่เปิดอยู่ ({positions.length} ไม้)</strong>,{" "}
              <strong>ยกเลิก Pending Order ทั้งหมด ({orders.length} รายการ)</strong> และ{" "}
              <strong>ปิดสวิตช์ Auto-Pilot ทันที</strong>
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowPanicModal(false)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3.5 py-1.5 text-xs text-[#cccccc]"
              >
                ยกเลิก
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={submitPanicCloseAll}
                className="rounded bg-[#c72e2e] px-4 py-1.5 text-xs font-bold text-white hover:bg-[#f14c4c] disabled:opacity-50"
              >
                {busy ? "กำลังปิดทุกไม้..." : "🚨 ยืนยันปิดทุกไม้ทันที"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
