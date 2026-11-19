import { useEffect, useState } from "react";
import { Calculator, CheckCircle2, Send, AlertTriangle } from "lucide-react";
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
    const ref = isPending && parseFloat(entryPrice) > 0
      ? parseFloat(entryPrice)
      : isBuy
      ? quote.ask
      : quote.bid;
    const d = quote.digits;
    if (!isPending) setEntryPrice("");
    setSl((isBuy ? ref - 12 : ref + 12).toFixed(d));
    setTp((isBuy ? ref + 28 : ref - 28).toFixed(d));
    setCheckResult(null);
  };

  const buildPayload = () => {
    const slVal = parseFloat(sl);
    const tpVal = parseFloat(tp);
    const entryVal = parseFloat(entryPrice);

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
      const res = await checkOrder(buildPayload());
      setCheckResult(res);
    } catch (err) {
      setCheckResult(null);
      setFeedback({ ok: false, msg: err instanceof Error ? err.message : "Check failed" });
    } finally {
      setChecking(false);
    }
  };

  const handleQueueProposal = async () => {
    setQueuing(true);
    setFeedback(null);
    try {
      const res = await createProposal({
        ...buildPayload(),
        source: "WEB",
        timeframe,
        rationale: rationale.trim() || `${side} setup planned on ${timeframe}`,
      });
      setCheckResult(res.order_check);
      setFeedback({
        ok: true,
        msg: `Queued Proposal #${res.proposal.id} (${res.proposal.lots} lots). Confirm in queue to execute.`,
      });
      setRationale("");
      onProposalCreated();
    } catch (err) {
      setFeedback({ ok: false, msg: err instanceof Error ? err.message : "Failed to queue proposal" });
    } finally {
      setQueuing(false);
    }
  };

  const liveRef = quote ? (side.startsWith("BUY") ? quote.ask : quote.bid) : null;

  return (
    <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">Order Planner & Risk Ticket</h2>
          <p className="text-[11px] text-slate-400">
            Dry-run check & queue for confirmation (never fires immediately)
          </p>
        </div>
        <button
          type="button"
          onClick={handleAutoLevels}
          className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-[11px] font-medium text-amber-300 hover:bg-slate-700"
        >
          Fill ±$12/$28
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-1.5">
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
              }}
              className={`rounded-lg border px-2.5 py-2 text-xs font-bold transition ${
                active
                  ? isBuy
                    ? "border-emerald-400 bg-emerald-500/20 text-emerald-300"
                    : "border-rose-400 bg-rose-500/20 text-rose-300"
                  : "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-200"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          );
        })}
      </div>

      <div className="mt-3 space-y-3">
        <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 p-1 text-xs">
          <button
            type="button"
            onClick={() => setSizingMode("risk")}
            className={`flex-1 rounded-md py-1.5 font-medium transition ${
              sizingMode === "risk" ? "bg-slate-800 text-amber-300" : "text-slate-400"
            }`}
          >
            By Risk % (10-20%)
          </button>
          <button
            type="button"
            onClick={() => setSizingMode("lots")}
            className={`flex-1 rounded-md py-1.5 font-medium transition ${
              sizingMode === "lots" ? "bg-slate-800 text-amber-300" : "text-slate-400"
            }`}
          >
            Fixed Lots
          </button>
        </div>

        {sizingMode === "risk" ? (
          <div>
            <div className="flex items-center justify-between text-xs text-slate-300">
              <span>Risk % of Equity</span>
              <div className="flex gap-1">
                {["10", "15", "20"].map((pct) => (
                  <button
                    key={pct}
                    type="button"
                    onClick={() => setRiskPct(pct)}
                    className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                      riskPct === pct
                        ? "bg-amber-500 text-slate-950"
                        : "bg-slate-800 text-slate-300 hover:bg-slate-700"
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
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 tabular-nums focus:border-amber-500 focus:outline-none"
            />
          </div>
        ) : (
          <div>
            <label className="block text-xs text-slate-300">Lot Size</label>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={lots}
              onChange={(e) => setLots(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 tabular-nums focus:border-amber-500 focus:outline-none"
            />
          </div>
        )}

        {isPending ? (
          <div>
            <label className="block text-xs text-slate-300">
              Limit Entry Price {liveRef ? `(Now: ${liveRef.toFixed(quote?.digits ?? 2)})` : ""}
            </label>
            <input
              type="number"
              step="0.01"
              value={entryPrice}
              onChange={(e) => setEntryPrice(e.target.value)}
              placeholder={liveRef ? liveRef.toFixed(2) : "3736.50"}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 tabular-nums focus:border-amber-500 focus:outline-none"
            />
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs">
            <span className="text-slate-400">Market Entry Reference</span>
            <span className="font-bold text-slate-100 tabular-nums">
              {liveRef ? liveRef.toFixed(quote?.digits ?? 2) : "—"}
            </span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="block text-xs text-rose-300">Stop Loss (SL)</label>
            <input
              type="number"
              step="0.01"
              value={sl}
              onChange={(e) => setSl(e.target.value)}
              placeholder="3745.00"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 tabular-nums focus:border-rose-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-emerald-300">Take Profit (TP)</label>
            <input
              type="number"
              step="0.01"
              value={tp}
              onChange={(e) => setTp(e.target.value)}
              placeholder="3700.00"
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 tabular-nums focus:border-emerald-500 focus:outline-none"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-slate-300">Setup Rationale / Note</label>
          <textarea
            rows={2}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="e.g. Rejection at H1 EMA20 + hawkish FOMC bias..."
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
          />
        </div>

        {checkResult && (
          <div className="rounded-xl border border-slate-700/80 bg-slate-950/90 p-3 text-xs tabular-nums">
            <div className="flex items-center justify-between font-semibold">
              <span className="text-slate-200">
                Order Check: {checkResult.lots.toFixed(2)} lots{" "}
                {checkResult.margin_capped && (
                  <span className="text-amber-400">(Margin Capped)</span>
                )}
              </span>
              <span className={checkResult.valid ? "text-emerald-400" : "text-rose-400"}>
                {checkResult.valid ? "VALID (retcode 0)" : `ERR ${checkResult.retcode}`}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-y-1 text-[11px] text-slate-400">
              <span>Est. Risk:</span>
              <span className="text-right font-medium text-rose-300">
                -${checkResult.est_risk_usd.toFixed(2)} ({checkResult.est_risk_pct.toFixed(1)}%)
              </span>
              <span>Est. Reward:</span>
              <span className="text-right font-medium text-emerald-300">
                +${checkResult.est_reward_usd.toFixed(2)} (
                {checkResult.rr_ratio ? `1:${checkResult.rr_ratio}` : "—"})
              </span>
              <span>Required Margin:</span>
              <span className="text-right font-medium text-slate-200">
                ${checkResult.required_margin.toFixed(2)}
              </span>
            </div>
          </div>
        )}

        {feedback && (
          <div
            className={`flex items-start gap-2 rounded-lg border p-2.5 text-xs ${
              feedback.ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-rose-500/30 bg-rose-500/10 text-rose-300"
            }`}
          >
            {feedback.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <span>{feedback.msg}</span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 pt-1">
          <button
            type="button"
            onClick={handleDryCheck}
            disabled={checking}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-slate-700 disabled:opacity-50"
          >
            <Calculator className="h-3.5 w-3.5" />
            {checking ? "Checking..." : "Check (Dry-Run)"}
          </button>
          <button
            type="button"
            onClick={handleQueueProposal}
            disabled={queuing}
            className="flex items-center justify-center gap-1.5 rounded-xl bg-amber-500 px-3 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" />
            {queuing ? "Queuing..." : "Queue Proposal"}
          </button>
        </div>
      </div>
    </div>
  );
}
