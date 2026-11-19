import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, BellRing, RefreshCw } from "lucide-react";
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
  const [rightTab, setRightTab] = useState<"proposals" | "planner">("proposals");
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
  const lastPendingCountRef = useRef<number | null>(null);

  const loadRestData = useCallback(
    async (tf: Timeframe) => {
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
            "ยังไม่สามารถเชื่อม MT5 Bridge ได้ — กด Settings มุมขวาบนเพื่อใส่ Bridge URL และ API Key"
          );
        } else {
          setBridgeError(null);
        }
      } catch (err) {
        setBridgeError(err instanceof Error ? err.message : "Failed to contact bridge");
      }
    },
    [symbol]
  );

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

          if (typeof pkt.pending_proposals_count === "number") {
            const nextCount = pkt.pending_proposals_count;
            if (lastPendingCountRef.current !== null && nextCount !== lastPendingCountRef.current) {
              fetchProposals()
                .then((res) => setProposals(res.proposals))
                .catch(() => {});
              if (nextCount > lastPendingCountRef.current) {
                setRightTab("proposals");
              }
            }
            lastPendingCountRef.current = nextCount;
          }

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
    <div className="flex min-h-screen flex-col bg-[#181818] text-[#cccccc]">
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

      <main className="mx-auto w-full max-w-[1680px] flex-1 space-y-3 px-3 py-3 sm:px-4">
        {bridgeError && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-[#cca700]/40 bg-[#cca700]/10 px-3.5 py-2.5 text-xs text-[#dcdcaa]">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-[#dcdcaa]" />
              <span>{bridgeError}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1 font-medium text-[#e1e1e1] hover:bg-[#3c3c3c]"
              >
                Bridge Settings
              </button>
              <button
                type="button"
                onClick={() => setReconnectSeed((s) => s + 1)}
                className="flex items-center gap-1 rounded bg-[#007acc] px-3 py-1 font-semibold text-white hover:bg-[#1f8ad2]"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          </div>
        )}

        {pendingProposalsCount > 0 && (activeTab !== "desk" || rightTab !== "proposals") && (
          <button
            type="button"
            onClick={() => {
              setActiveTab("desk");
              setRightTab("proposals");
            }}
            className="flex w-full items-center justify-between rounded border border-[#007acc]/60 bg-[#007acc]/15 px-3.5 py-2 text-left text-xs text-[#e1e1e1] transition hover:bg-[#007acc]/25"
          >
            <span className="flex items-center gap-2">
              <BellRing className="h-4 w-4 text-[#4fc1ff]" />
              <span>
                มีแผนเทรดจาก AI รอยืนยัน <strong>{pendingProposalsCount} รายการ</strong> — คลิกเพื่อดูและกด{" "}
                <strong>Confirm & Execute</strong>
              </span>
            </span>
            <span className="font-semibold text-[#4fc1ff]">เปิดดู →</span>
          </button>
        )}

        <AccountKpiStrip
          account={account}
          openPositionsCount={positions.length}
          pendingOrdersCount={orders.length}
          pendingProposalsCount={pendingProposalsCount}
        />

        {activeTab === "desk" && (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
            <div className="space-y-3 xl:col-span-8">
              <LiveChartPanel
                symbol={quote?.symbol ?? symbol}
                timeframe={timeframe}
                onTimeframeChange={setTimeframe}
                candles={candles}
                lastBar={lastBar}
                mtf={mtf}
                positions={positions}
                previewLevels={rightTab === "planner" ? previewLevels : null}
              />
              <PositionsTable
                positions={positions}
                orders={orders}
                onUpdated={refreshAllSideData}
              />
            </div>

            <div className="xl:col-span-4">
              <div className="rounded-md border border-[#2b2b2b] bg-[#252526]">
                <div className="flex border-b border-[#2b2b2b] bg-[#181818]">
                  <button
                    type="button"
                    onClick={() => setRightTab("proposals")}
                    className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 px-3 py-2.5 text-xs font-semibold transition ${
                      rightTab === "proposals"
                        ? "border-[#007acc] bg-[#252526] text-white"
                        : "border-transparent text-[#9d9d9d] hover:bg-[#2a2d2e] hover:text-[#cccccc]"
                    }`}
                  >
                    <span>AI รอยืนยัน</span>
                    <span
                      className={`rounded-full px-1.5 py-0.2 text-[10px] font-bold ${
                        pendingProposalsCount > 0
                          ? "bg-[#007acc] text-white"
                          : "bg-[#313131] text-[#9d9d9d]"
                      }`}
                    >
                      {pendingProposalsCount}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setRightTab("planner")}
                    className={`flex-1 border-b-2 px-3 py-2.5 text-xs font-semibold transition ${
                      rightTab === "planner"
                        ? "border-[#007acc] bg-[#252526] text-white"
                        : "border-transparent text-[#9d9d9d] hover:bg-[#2a2d2e] hover:text-[#cccccc]"
                    }`}
                  >
                    วางแผนเอง (Manual)
                  </button>
                </div>

                <div className="p-3.5">
                  {rightTab === "proposals" ? (
                    <ProposalsQueue
                      proposals={proposals}
                      account={account}
                      onUpdated={refreshAllSideData}
                    />
                  ) : (
                    <OrderTicketPanel
                      symbol={quote?.symbol ?? symbol}
                      timeframe={timeframe}
                      quote={quote}
                      onPreviewChange={setPreviewLevels}
                      onProposalCreated={() => {
                        refreshAllSideData();
                        setRightTab("proposals");
                      }}
                    />
                  )}
                </div>
              </div>
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

      <footer
        className={`font-mono-num flex h-6 items-center justify-between px-3 text-[11px] text-white ${
          wsStatus === "LIVE" && mt5Connected ? "bg-[#007acc]" : "bg-[#6c2022]"
        }`}
      >
        <div className="flex items-center gap-3">
          <span>
            {wsStatus === "LIVE" && mt5Connected ? "● MT5 Connected" : `○ ${wsStatus}`}
          </span>
          {account && (
            <span className="hidden sm:inline">
              {account.server} · #{account.login} ({account.trade_mode})
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {account && (
            <span>Algo Trading: {account.terminal_trade_allowed ? "ON" : "OFF"}</span>
          )}
          <span>{quote?.symbol ?? symbol}</span>
        </div>
      </footer>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => setReconnectSeed((s) => s + 1)}
      />
    </div>
  );
}
