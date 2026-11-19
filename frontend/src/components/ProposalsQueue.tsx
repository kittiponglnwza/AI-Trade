import { useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  ExternalLink,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { confirmProposal, rejectProposal } from "../services/api";
import type { AccountSummary, TradeProposal } from "../types/trading";

interface ProposalsQueueProps {
  proposals: TradeProposal[];
  account: AccountSummary | null;
  onUpdated: () => void;
}

export function ProposalsQueue({ proposals, account, onUpdated }: ProposalsQueueProps) {
  const [confirmTarget, setConfirmTarget] = useState<TradeProposal | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pending = proposals.filter((p) => p.status === "PENDING");
  const recent = proposals.filter((p) => p.status !== "PENDING").slice(0, 5);

  const handleConfirm = async () => {
    if (!confirmTarget) return;
    setBusyId(confirmTarget.id);
    setErrorMsg(null);
    try {
      await confirmProposal(confirmTarget.id, false);
      setConfirmTarget(null);
      onUpdated();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "ส่งคำสั่งไม่สำเร็จ");
      setConfirmTarget(null);
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
      setErrorMsg(err instanceof Error ? err.message : "ปฏิเสธแผนไม่สำเร็จ");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-2.5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[#4fc1ff]" />
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
            AI Confirmation Queue ({pending.length})
          </h2>
        </div>
        <span className="text-[11px] text-[#9d9d9d]">กดยืนยันเพื่อยิงเข้า MT5</span>
      </div>

      {account && !account.terminal_trade_allowed && pending.length > 0 && (
        <div className="flex items-start gap-2 rounded border border-[#cca700]/50 bg-[#cca700]/10 p-2.5 text-xs text-[#dcdcaa] break-words">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[#dcdcaa]" />
          <span>
            ปุ่ม <strong>Algo Trading</strong> บน MT5 ยังปิดอยู่ (`OFF`) — กรุณากดเปิดเป็นสีเขียวบน MT5 ก่อนกด{" "}
            <strong>Confirm & Execute</strong>
          </span>
        </div>
      )}

      {errorMsg && (
        <div className="flex items-start gap-2 rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 p-2.5 text-xs text-[#f48771] break-words whitespace-pre-wrap overflow-hidden">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#f14c4c]" />
          <span className="min-w-0 flex-1 break-words">{errorMsg}</span>
        </div>
      )}

      {pending.length === 0 ? (
        <div className="rounded border border-dashed border-[#3c3c3c] bg-[#1e1e1e] px-4 py-7 text-center text-xs text-[#9d9d9d]">
          <Clock className="mx-auto mb-2 h-5 w-5 text-[#6e6e6e]" />
          <p className="text-[#cccccc]">ยังไม่มีแผนเทรดรอกดยืนยัน</p>
          <p className="mt-1 text-[11px] text-[#6e6e6e]">
            Watchdog กำลังเฝ้าตลาดให้ 24/7 หรือไปที่แท็บ &ldquo;Gauntlet & News&rdquo; เพื่อสแกนทันที
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {pending.map((p) => {
            const isBuy = p.side.startsWith("BUY");
            const gates = p.gauntlet?.gates ?? [];
            const newsList = p.news ?? [];
            const hasEvidence = gates.length > 0 || newsList.length > 0;
            const isExpanded = expandedId === p.id;

            return (
              <div
                key={p.id}
                className="rounded border border-[#007acc]/70 bg-[#1e1e1e] p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={`rounded px-2 py-0.5 text-[11px] font-bold ${
                        isBuy
                          ? "border border-[#3fb950]/30 bg-[#3fb950]/15 text-[#3fb950]"
                          : "border border-[#f14c4c]/30 bg-[#f14c4c]/15 text-[#f14c4c]"
                      }`}
                    >
                      {p.side}
                    </span>
                    <span className="font-mono-num text-sm font-bold text-[#e1e1e1]">
                      {p.lots.toFixed(2)} {p.symbol}
                    </span>
                    <span className="rounded border border-[#3c3c3c] bg-[#252526] px-1.5 py-0.5 text-[10px] font-medium text-[#4fc1ff]">
                      {p.source} · {p.timeframe}
                    </span>
                    {p.gauntlet?.total_gates ? (
                      <span className="inline-flex items-center gap-1 rounded border border-[#3fb950]/40 bg-[#3fb950]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#3fb950]">
                        <ShieldCheck className="h-3 w-3" />
                        Gauntlet {p.gauntlet.passed_count}/{p.gauntlet.total_gates}
                      </span>
                    ) : null}
                    {typeof p.gauntlet?.confidence_pct === "number" ? (
                      <span className="font-mono-num rounded border border-[#c586c0]/40 bg-[#c586c0]/15 px-1.5 py-0.5 text-[10px] font-bold text-[#c586c0]">
                        Conf {p.gauntlet.confidence_pct.toFixed(1)}%
                      </span>
                    ) : null}
                  </div>
                  <span className="font-mono-num text-[11px] text-[#6e6e6e]">#{p.id}</span>
                </div>

                <div className="font-mono-num mt-2.5 grid grid-cols-3 gap-2 rounded border border-[#2b2b2b] bg-[#252526] px-2.5 py-2 text-[11px]">
                  <div>
                    <div className="text-[10px] text-[#9d9d9d]">ENTRY</div>
                    <strong className="text-[#e1e1e1]">{p.entry_price}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#9d9d9d]">SL</div>
                    <strong className="text-[#f14c4c]">{p.sl ?? "—"}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#9d9d9d]">TP</div>
                    <strong className="text-[#3fb950]">{p.tp ?? "—"}</strong>
                  </div>
                </div>

                <div className="font-mono-num mt-2 flex items-center justify-between text-[11px] text-[#9d9d9d]">
                  <span>
                    Risk:{" "}
                    <strong className="text-[#f14c4c]">
                      -${p.est_risk_usd.toFixed(2)} ({p.risk_pct?.toFixed(1) ?? "?"}%)
                    </strong>
                  </span>
                  <span>
                    Reward:{" "}
                    <strong className="text-[#3fb950]">+${p.est_reward_usd.toFixed(2)}</strong>
                  </span>
                  <span>
                    R:R <strong className="text-[#dcdcaa]">{p.rr_ratio ? `1:${p.rr_ratio}` : "—"}</strong>
                  </span>
                </div>

                {p.rationale && (
                  <p className="mt-2 rounded border border-[#2b2b2b] bg-[#181818] p-2 text-[11px] leading-relaxed text-[#cccccc] break-words">
                    {p.rationale}
                  </p>
                )}

                {hasEvidence && (
                  <div className="mt-2">
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : p.id)}
                      className="flex w-full items-center justify-between rounded border border-[#2b2b2b] bg-[#252526] px-2.5 py-1.5 text-[11px] font-medium text-[#4fc1ff] hover:bg-[#2a2d2e]"
                    >
                      <span>หลักฐาน Gauntlet & ลิงก์ข่าวอ้างอิง ({newsList.length} ข่าว)</span>
                      {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>

                    {isExpanded && (
                      <div className="mt-1.5 space-y-2 rounded border border-[#2b2b2b] bg-[#181818] p-2 text-[11px]">
                        {gates.length > 0 && (
                          <div className="space-y-1">
                            {gates.map((g) => (
                              <div key={g.id} className="flex items-center justify-between gap-2">
                                <span className="text-[#9d9d9d]">{g.label}</span>
                                <span
                                  className={`font-mono-num font-semibold ${
                                    g.status === "PASS"
                                      ? "text-[#3fb950]"
                                      : g.status === "WARN"
                                      ? "text-[#dcdcaa]"
                                      : "text-[#f14c4c]"
                                  }`}
                                >
                                  {g.status} ({g.metric})
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                        {newsList.length > 0 && (
                          <div className="border-t border-[#2b2b2b] pt-1.5 space-y-1">
                            {newsList.slice(0, 4).map((n, idx) => (
                              <a
                                key={`${n.url}-${idx}`}
                                href={n.url}
                                target="_blank"
                                rel="noreferrer"
                                className="flex items-start justify-between gap-1.5 text-[#4fc1ff] hover:underline"
                              >
                                <span className="line-clamp-2 break-words">
                                  [{n.source}] {n.title}
                                </span>
                                <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => handleReject(p.id)}
                    className="flex items-center justify-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] py-2 text-xs font-medium text-[#cccccc] transition hover:bg-[#3c3c3c] hover:text-white disabled:opacity-50"
                  >
                    <X className="h-3.5 w-3.5" />
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    onClick={() => setConfirmTarget(p)}
                    className="flex items-center justify-center gap-1.5 rounded bg-[#238636] py-2 text-xs font-semibold text-white transition hover:bg-[#2ea043] disabled:opacity-50"
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
        <div className="border-t border-[#2b2b2b] pt-2.5">
          <div className="mb-1.5 text-[11px] font-medium text-[#9d9d9d]">
            Recent Proposal Activity
          </div>
          <div className="space-y-1">
            {recent.map((p) => (
              <div
                key={p.id}
                className="rounded border border-[#2b2b2b] bg-[#1e1e1e] px-2.5 py-1.5 text-[11px] text-[#9d9d9d]"
              >
                <div className="font-mono-num flex items-center justify-between">
                  <span>
                    #{p.id} {p.side} {p.lots} {p.symbol}
                  </span>
                  <span
                    className={
                      p.status === "EXECUTED"
                        ? "font-semibold text-[#3fb950]"
                        : p.status === "REJECTED"
                        ? "text-[#6e6e6e]"
                        : "font-semibold text-[#f14c4c]"
                    }
                  >
                    {p.status}
                  </span>
                </div>
                {p.exec_comment && (
                  <p
                    className={`mt-1 text-[10px] break-words ${
                      p.status === "FAILED" ? "text-[#f48771]" : "text-[#6e6e6e]"
                    }`}
                  >
                    {p.exec_comment}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {confirmTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-md rounded-md border border-[#3c3c3c] bg-[#252526] p-5 shadow-2xl">
            <div className="flex items-center gap-2 text-[#4fc1ff]">
              <ShieldAlert className="h-5 w-5" />
              <h3 className="text-sm font-semibold text-[#e1e1e1]">
                ยืนยันส่งคำสั่งเข้า MetaTrader 5
              </h3>
            </div>
            <p className="mt-2 text-xs text-[#9d9d9d]">
              กรุณาตรวจสอบรายละเอียดก่อนกด Execute:
            </p>
            <div className="font-mono-num mt-3 space-y-1.5 rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3 text-xs">
              <div className="flex justify-between">
                <span className="text-[#9d9d9d]">Account Mode:</span>
                <strong className="text-[#4fc1ff]">{account?.trade_mode ?? "UNKNOWN"}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-[#9d9d9d]">Order:</span>
                <strong className="text-[#e1e1e1]">
                  {confirmTarget.side} {confirmTarget.lots.toFixed(2)} {confirmTarget.symbol} @{" "}
                  {confirmTarget.entry_price}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-[#9d9d9d]">SL / TP:</span>
                <strong className="text-[#e1e1e1]">
                  <span className="text-[#f14c4c]">{confirmTarget.sl ?? "—"}</span> /{" "}
                  <span className="text-[#3fb950]">{confirmTarget.tp ?? "—"}</span>
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-[#9d9d9d]">Estimated Risk:</span>
                <strong className="text-[#f14c4c]">
                  -${confirmTarget.est_risk_usd.toFixed(2)} (
                  {confirmTarget.risk_pct?.toFixed(1) ?? "?"}%)
                </strong>
              </div>
            </div>

            {account && !account.terminal_trade_allowed && (
              <div className="mt-3 rounded border border-[#cca700]/50 bg-[#cca700]/10 p-2.5 text-xs text-[#dcdcaa] break-words">
                คำเตือน: กดปุ่ม <strong>&ldquo;Algo Trading&rdquo;</strong> บนแถบเครื่องมือ MT5 ด้านบน (หรือกด{" "}
                <strong>Ctrl+E</strong>) ให้เป็นสีเขียว หรือ{" "}
                <strong>Tools → Options → Expert Advisors → ติ๊ก Allow algorithmic trading</strong> ก่อนกด Execute
              </div>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmTarget(null)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3.5 py-1.5 text-xs font-medium text-[#cccccc] hover:bg-[#3c3c3c]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busyId === confirmTarget.id}
                onClick={handleConfirm}
                className="rounded bg-[#238636] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
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
