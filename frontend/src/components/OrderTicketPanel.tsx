import { useEffect, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2, Send } from "lucide-react";
import { checkOrder, createProposal } from "../services/api";
import type {
  ChartPreviewLevels,
  OrderCheckResult,
  OrderSide,
  QuoteInfo,
  Timeframe,
} from "../types/trading";

interface OrderTicketPanelProps {
  symbol: string;
  timeframe: Timeframe;
  quote: QuoteInfo | null;
  onPreviewChange: (levels: ChartPreviewLevels | null) => void;
  onProposalCreated: () => void;
}

export function OrderTicketPanel({
  symbol,
  timeframe,
  quote,
  onPreviewChange,
  onProposalCreated,
}: OrderTicketPanelProps) {
  const [side, setSide] = useState<OrderSide>("SELL");
  const [sizingMode, setSizingMode] = useState<"risk" | "lots">("risk");
  const [riskPct, setRiskPct] = useState("15");
  const [lots, setLots] = useState("0.30");
  const [entryPrice, setEntryPrice] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [rationale, setRationale] = useState("");

  const [checking, setChecking] = useState(false);
  const [queuing, setQueuing] = useState(false);
  const [checkResult, setCheckResult] = useState<OrderCheckResult | null>(null);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  const isPending = side !== "BUY" && side !== "SELL";

  useEffect(() => {
    const entryNum = isPending
      ? parseFloat(entryPrice) || null
      : quote
      ? side === "BUY"
        ? quote.ask
        : quote.bid
      : null;
    const slNum = parseFloat(sl) || null;
    const tpNum = parseFloat(tp) || null;

    if (slNum || tpNum || (isPending && entryNum)) {
      onPreviewChange({ entry: entryNum, sl: slNum, tp: tpNum, side });
    } else {
      onPreviewChange(null);
    }
  }, [side, entryPrice, sl, tp, isPending, quote?.bid, quote?.ask]);

  const handleAutoLevels = () => {
    if (!quote) return;
    const isBuy = side.startsWith("BUY");
    const ref =
      isPending && parseFloat(entryPrice) > 0
        ? parseFloat(entryPrice)
        : isBuy
        ? quote.ask
        : quote.bid;
    const d = quote.digits;
    if (!isPending) setEntryPrice("");
    setSl((isBuy ? ref - 12 : ref + 12).toFixed(d));
    setTp((isBuy ? ref + 28 : ref - 28).toFixed(d));
    setCheckResult(null);
    setFeedback(null);
  };

  const validateAndBuildPayload = () => {
    const slVal = parseFloat(sl);
    const tpVal = parseFloat(tp);
    const entryVal = parseFloat(entryPrice);

    if (sizingMode === "risk" && (!Number.isFinite(slVal) || slVal <= 0)) {
      throw new Error("กรุณากรอก Stop Loss (SL) หรือกดปุ่ม เติม ±$12/$28 ก่อนคำนวณตาม Risk %");
    }
    if (isPending && (!Number.isFinite(entryVal) || entryVal <= 0)) {
      throw new Error(`กรุณากรอกราคา Limit Entry สำหรับคำสั่ง ${side}`);
    }

    return {
      symbol,
      side,
      lots: sizingMode === "lots" ? parseFloat(lots) : null,
      risk_pct: sizingMode === "risk" ? parseFloat(riskPct) : null,
      entry_price: isPending && entryVal > 0 ? entryVal : null,
      sl: Number.isFinite(slVal) && slVal > 0 ? slVal : null,
      tp: Number.isFinite(tpVal) && tpVal > 0 ? tpVal : null,
    };
  };

  const handleDryCheck = async () => {
    setChecking(true);
    setFeedback(null);
    try {
      const payload = validateAndBuildPayload();
      const res = await checkOrder(payload);
      setCheckResult(res);
    } catch (err) {
      setCheckResult(null);
      setFeedback({ ok: false, msg: err instanceof Error ? err.message : "ตรวจสอบไม่สำเร็จ" });
    } finally {
      setChecking(false);
    }
  };

  const handleQueueProposal = async () => {
    setQueuing(true);
    setFeedback(null);
    try {
      const payload = validateAndBuildPayload();
      const res = await createProposal({
        ...payload,
        source: "WEB",
        timeframe,
        rationale: rationale.trim() || `${side} setup planned on ${timeframe}`,
      });
      setCheckResult(res.order_check);
      setFeedback({
        ok: true,
        msg: `ส่ง Proposal #${res.proposal.id} (${res.proposal.lots} lots) เข้าคิวรอยืนยันแล้ว`,
      });
      setRationale("");
      onProposalCreated();
    } catch (err) {
      setFeedback({ ok: false, msg: err instanceof Error ? err.message : "ส่งแผนไม่สำเร็จ" });
    } finally {
      setQueuing(false);
    }
  };

  const liveRef = quote ? (side.startsWith("BUY") ? quote.ask : quote.bid) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-2.5">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[#e1e1e1]">
            Manual Order Planner
          </h2>
          <p className="text-[11px] text-[#9d9d9d]">
            ตรวจสอบ Lot / Margin ก่อนส่งเข้าคิวยืนยัน
          </p>
        </div>
        <button
          type="button"
          onClick={handleAutoLevels}
          className="rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1 text-[11px] font-medium text-[#dcdcaa] hover:bg-[#3c3c3c]"
        >
          เติม ±$12/$28
        </button>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {(["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT"] as OrderSide[]).map((s) => {
          const isBuy = s.startsWith("BUY");
          const active = side === s;
          return (
            <button
              key={s}
              type="button"
              onClick={() => {
                setSide(s);
                setCheckResult(null);
                setFeedback(null);
              }}
              className={`rounded border px-2.5 py-1.5 text-xs font-bold transition ${
                active
                  ? isBuy
                    ? "border-[#3fb950] bg-[#3fb950]/15 text-[#3fb950]"
                    : "border-[#f14c4c] bg-[#f14c4c]/15 text-[#f14c4c]"
                  : "border-[#3c3c3c] bg-[#1e1e1e] text-[#9d9d9d] hover:bg-[#2a2d2e] hover:text-[#e1e1e1]"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          );
        })}
      </div>

      <div className="flex items-center rounded border border-[#3c3c3c] bg-[#1e1e1e] p-0.5 text-xs">
        <button
          type="button"
          onClick={() => setSizingMode("risk")}
          className={`flex-1 rounded-sm py-1.5 font-medium transition ${
            sizingMode === "risk" ? "bg-[#007acc] text-white" : "text-[#9d9d9d] hover:text-[#e1e1e1]"
          }`}
        >
          ตาม Risk % (10-20%)
        </button>
        <button
          type="button"
          onClick={() => setSizingMode("lots")}
          className={`flex-1 rounded-sm py-1.5 font-medium transition ${
            sizingMode === "lots" ? "bg-[#007acc] text-white" : "text-[#9d9d9d] hover:text-[#e1e1e1]"
          }`}
        >
          ระบุ Lots เอง
        </button>
      </div>

      {sizingMode === "risk" ? (
        <div>
          <div className="flex items-center justify-between text-xs text-[#cccccc]">
            <span>Risk % of Equity</span>
            <div className="flex gap-1">
              {["10", "15", "20"].map((pct) => (
                <button
                  key={pct}
                  type="button"
                  onClick={() => setRiskPct(pct)}
                  className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                    riskPct === pct
                      ? "bg-[#007acc] text-white"
                      : "border border-[#3c3c3c] bg-[#313131] text-[#cccccc] hover:bg-[#3c3c3c]"
                  }`}
                >
                  {pct}%
                </button>
              ))}
            </div>
          </div>
          <input
            type="number"
            step="0.5"
            min="0.5"
            max="50"
            value={riskPct}
            onChange={(e) => setRiskPct(e.target.value)}
            className="font-mono-num mt-1.5 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
          />
        </div>
      ) : (
        <div>
          <label className="block text-xs text-[#cccccc]">Lot Size</label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={lots}
            onChange={(e) => setLots(e.target.value)}
            className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] focus:border-[#007fd4] focus:outline-none"
          />
        </div>
      )}

      {isPending ? (
        <div>
          <label className="block text-xs text-[#cccccc]">
            Limit Entry Price {liveRef ? `(Now: ${liveRef.toFixed(quote?.digits ?? 2)})` : ""}
          </label>
          <input
            type="number"
            step="0.01"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder={liveRef ? `เช่น ${liveRef.toFixed(2)}` : "เช่น 3736.50"}
            className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
          />
        </div>
      ) : (
        <div className="flex items-center justify-between rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2 text-xs">
          <span className="text-[#9d9d9d]">Market Entry Reference</span>
          <span className="font-mono-num font-bold text-[#e1e1e1]">
            {liveRef ? liveRef.toFixed(quote?.digits ?? 2) : "—"}
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs font-medium text-[#f14c4c]">Stop Loss (SL)</label>
          <input
            type="number"
            step="0.01"
            value={sl}
            onChange={(e) => setSl(e.target.value)}
            placeholder="เช่น 3739.50"
            className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#3fb950]">Take Profit (TP)</label>
          <input
            type="number"
            step="0.01"
            value={tp}
            onChange={(e) => setTp(e.target.value)}
            placeholder="เช่น 3698.00"
            className="font-mono-num mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-sm text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-[#cccccc]">Setup Rationale / Note</label>
        <textarea
          rows={2}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="เหตุผลในการเข้าไม้..."
          className="mt-1 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-1.5 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
        />
      </div>

      {checkResult && (
        <div className="font-mono-num rounded border border-[#3c3c3c] bg-[#1e1e1e] p-2.5 text-xs">
          <div className="flex items-center justify-between font-semibold">
            <span className="text-[#e1e1e1]">
              {checkResult.lots.toFixed(2)} lots{" "}
              {checkResult.margin_capped && (
                <span className="text-[#dcdcaa]">(Margin Capped)</span>
              )}
            </span>
            <span className={checkResult.valid ? "text-[#3fb950]" : "text-[#f14c4c]"}>
              {checkResult.valid ? "VALID (0)" : `ERR ${checkResult.retcode}`}
            </span>
          </div>
          <div className="mt-1.5 grid grid-cols-2 gap-y-1 text-[11px] text-[#9d9d9d]">
            <span>Est. Risk:</span>
            <span className="text-right font-medium text-[#f14c4c]">
              -${checkResult.est_risk_usd.toFixed(2)} ({checkResult.est_risk_pct.toFixed(1)}%)
            </span>
            <span>Est. Reward:</span>
            <span className="text-right font-medium text-[#3fb950]">
              +${checkResult.est_reward_usd.toFixed(2)} (
              {checkResult.rr_ratio ? `1:${checkResult.rr_ratio}` : "—"})
            </span>
            <span>Req. Margin:</span>
            <span className="text-right text-[#cccccc]">
              ${checkResult.required_margin.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {feedback && (
        <div
          className={`flex items-start gap-2 rounded border p-2.5 text-xs break-words whitespace-pre-wrap overflow-hidden ${
            feedback.ok
              ? "border-[#3fb950]/40 bg-[#1e3a29]/40 text-[#3fb950]"
              : "border-[#f14c4c]/40 bg-[#5a1d1d]/40 text-[#f48771]"
          }`}
        >
          {feedback.ok ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <span className="min-w-0 flex-1 break-words">{feedback.msg}</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 pt-1">
        <button
          type="button"
          onClick={handleDryCheck}
          disabled={checking}
          className="flex items-center justify-center gap-1.5 rounded border border-[#3c3c3c] bg-[#313131] px-3 py-2 text-xs font-medium text-[#cccccc] transition hover:bg-[#3c3c3c] hover:text-white disabled:opacity-50"
        >
          <Calculator className="h-3.5 w-3.5" />
          {checking ? "Checking..." : "Check (Dry-Run)"}
        </button>
        <button
          type="button"
          onClick={handleQueueProposal}
          disabled={queuing}
          className="flex items-center justify-center gap-1.5 rounded bg-[#007acc] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#1f8ad2] disabled:opacity-50"
        >
          <Send className="h-3.5 w-3.5" />
          {queuing ? "Queuing..." : "Queue Proposal"}
        </button>
      </div>
    </div>
  );
}
