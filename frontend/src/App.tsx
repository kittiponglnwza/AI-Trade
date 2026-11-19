import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { AccountKpiStrip } from "./components/AccountKpiStrip";
import { HeaderBar } from "./components/HeaderBar";
import { LiveChartPanel } from "./components/LiveChartPanel";
import { OrderTicketPanel } from "./components/OrderTicketPanel";
import { PositionsTable } from "./components/PositionsTable";
import { ProposalsQueue } from "./components/ProposalsQueue";
import { SettingsModal } from "./components/SettingsModal";
import { StatsDashboard } from "./components/StatsDashboard";
import { TradeLogTable } from "./components/TradeLogTable";
import {
  buildWsUrl,
  fetchCandles,
  fetchLogs,
  fetchProposals,
  fetchSnapshot,
  fetchStats,
} from "./services/api";
import type {
  AccountSummary,
  AppTab,
  AuditEvent,
  CandlePoint,
  ChartPreviewLevels,
  MtfSummaryRow,
  OpenPosition,
  PendingOrder,
  QuoteInfo,
  Timeframe,
  TradeLogEntry,
  TradeProposal,
  TradingStats,
  WsLivePacket,
  WsStatus,
} from "./types/trading";

export default function App() {
  const [symbol] = useState("XAUUSD");
  const [timeframe, setTimeframe] = useState<Timeframe>("M15");
  const [activeTab, setActiveTab] = useState<AppTab>("desk");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [wsStatus, setWsStatus] = useState<WsStatus>("OFFLINE");
  const [mt5Connected, setMt5Connected] = useState(false);
  const [bridgeError, setBridgeError] = useState<string | null>(null);

  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [quote, setQuote] = useState<QuoteInfo | null>(null);
  const [positions, setPositions] = useState<OpenPosition[]>([]);
  const [orders, setOrders] = useState<PendingOrder[]>([]);
  const [mtf, setMtf] = useState<MtfSummaryRow[]>([]);
  const [candles, setCandles] = useState<CandlePoint[]>([]);
  const [lastBar, setLastBar] = useState<CandlePoint | null>(null);

  const [proposals, setProposals] = useState<TradeProposal[]>([]);
  const [logs, setLogs] = useState<TradeLogEntry[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [stats, setStats] = useState<TradingStats | null>(null);
  const [previewLevels, setPreviewLevels] = useState<ChartPreviewLevels | null>(null);
  const [reconnectSeed, setReconnectSeed] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const retryDelayRef = useRef<number>(1000);

  const loadRestData = useCallback(async (tf: Timeframe) => {
    try {
      const [snap, candleRes, propRes, logRes, statRes] = await Promise.allSettled([
        fetchSnapshot(symbol),
        fetchCandles(symbol, tf, 250),
        fetchProposals(),
        fetchLogs(),
        fetchStats(false),
      ]);

      let anyBridgeOk = false;
      if (snap.status === "fulfilled") {
        anyBridgeOk = true;
        setMt5Connected(true);
        setAccount(snap.value.account);
        setQuote(snap.value.quote);
        setPositions(snap.value.positions);
        setOrders(snap.value.orders);
        setMtf(snap.value.mtf);
      }
      if (candleRes.status === "fulfilled") {
        anyBridgeOk = true;
        setCandles(candleRes.value.candles);
        setLastBar(null);
      }
      if (propRes.status === "fulfilled") {
        anyBridgeOk = true;
        setProposals(propRes.value.proposals);
      }
      if (logRes.status === "fulfilled") {
        anyBridgeOk = true;
        setLogs(logRes.value.logs);
        setAuditEvents(logRes.value.audit_events);
      }
      if (statRes.status === "fulfilled") {
        anyBridgeOk = true;
        setStats(statRes.value);
      }

      if (!anyBridgeOk) {
        setBridgeError(
          "Cannot reach MT5 Local Bridge. Start backend (uvicorn) or configure Tunnel URL in Settings."
        );
      } else {
        setBridgeError(null);
      }
    } catch (err) {
      setBridgeError(err instanceof Error ? err.message : "Failed to contact bridge");
    }
  }, [symbol]);

  const refreshAllSideData = useCallback(async () => {
    await loadRestData(timeframe);
  }, [loadRestData, timeframe]);

  useEffect(() => {
    loadRestData(timeframe);
  }, [loadRestData, timeframe, reconnectSeed]);

  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", symbol, tf: timeframe }));
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    let closedByEffect = false;
    let reconnectTimer: number | undefined;

    const connectWs = () => {
      if (closedByEffect) return;
      const url = buildWsUrl(symbol, timeframe);
      setWsStatus((prev) => (prev === "LIVE" ? "LIVE" : "RECONNECTING"));

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        retryDelayRef.current = 1000;
        setWsStatus("LIVE");
        setBridgeError(null);
      };

      ws.onmessage = (evt) => {
        try {
          const pkt = JSON.parse(evt.data) as WsLivePacket;
          setMt5Connected(Boolean(pkt.mt5_connected));
          if (pkt.type === "tick" && pkt.mt5_connected) {
            if (pkt.account) setAccount(pkt.account);
            if (pkt.quote) setQuote(pkt.quote);
            if (pkt.positions) setPositions(pkt.positions);
            if (pkt.orders) setOrders(pkt.orders);
            if (pkt.last_bar) setLastBar(pkt.last_bar);
          }
        } catch {
          // ignore malformed frames
        }
      };

      ws.onerror = () => {
        ws.close();
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (closedByEffect) return;
        setWsStatus("OFFLINE");
        const delay = retryDelayRef.current;
        retryDelayRef.current = Math.min(retryDelayRef.current * 1.5, 10000);
        reconnectTimer = window.setTimeout(connectWs, delay);
      };
    };

    connectWs();

    return () => {
      closedByEffect = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [symbol, reconnectSeed]);

  const pendingProposalsCount = proposals.filter((p) => p.status === "PENDING").length;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <HeaderBar
        wsStatus={wsStatus}
        mt5Connected={mt5Connected}
        account={account}
        quote={quote}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        pendingCount={pendingProposalsCount}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="mx-auto max-w-[1600px] space-y-4 px-4 py-4">
        {bridgeError && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
              <span>{bridgeError}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="rounded-lg border border-amber-400/40 bg-amber-500/20 px-3 py-1 font-semibold hover:bg-amber-500/30"
              >
                Bridge Settings
              </button>
              <button
                type="button"
                onClick={() => setReconnectSeed((s) => s + 1)}
                className="flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-1 font-bold text-slate-950 hover:bg-amber-400"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          </div>
        )}

        <AccountKpiStrip
          account={account}
          openPositionsCount={positions.length}
          pendingOrdersCount={orders.length}
          pendingProposalsCount={pendingProposalsCount}
        />

        {activeTab === "desk" && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="space-y-4 xl:col-span-8">
              <LiveChartPanel
                symbol={quote?.symbol ?? symbol}
                timeframe={timeframe}
                onTimeframeChange={setTimeframe}
                candles={candles}
                lastBar={lastBar}
                mtf={mtf}
                positions={positions}
                previewLevels={previewLevels}
              />
              <PositionsTable
                positions={positions}
                orders={orders}
                onUpdated={refreshAllSideData}
              />
            </div>

            <div className="space-y-4 xl:col-span-4">
              <OrderTicketPanel
                symbol={quote?.symbol ?? symbol}
                timeframe={timeframe}
                quote={quote}
                onPreviewChange={setPreviewLevels}
                onProposalCreated={refreshAllSideData}
              />
              <ProposalsQueue
                proposals={proposals}
                account={account}
                onUpdated={refreshAllSideData}
              />
            </div>
          </div>
        )}

        {activeTab === "stats" && (
          <StatsDashboard stats={stats} onRefresh={refreshAllSideData} />
        )}

        {activeTab === "journal" && (
          <TradeLogTable
            logs={logs}
            auditEvents={auditEvents}
            onRefresh={refreshAllSideData}
          />
        )}
      </main>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => setReconnectSeed((s) => s + 1)}
      />
    </div>
  );
}
