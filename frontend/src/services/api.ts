import type {
  AuditEvent,
  BacktestResult,
  CandlesResponse,
  GauntletEvaluation,
  MLModelStatus,
  MarketSnapshot,
  NewsResponse,
  OrderCheckResult,
  OrderSide,
  SheetsConfig,
  SymbolSearchItem,
  SystemLogEntry,
  Timeframe,
  TradeLogEntry,
  TradeProposal,
  TradingStats,
  WatchdogConfig,
  WatchdogStatus,
  WatchlistQuote,
} from "../types/trading";

const STORAGE_URL_KEY = "mt5_bridge_url";
const STORAGE_API_KEY = "mt5_api_key";

export interface BridgeConfig {
  baseUrl: string;
  apiKey: string;
}

export function getBridgeConfig(): BridgeConfig {
  const savedUrl = localStorage.getItem(STORAGE_URL_KEY);
  const savedKey = localStorage.getItem(STORAGE_API_KEY);

  const defaultUrl = import.meta.env.DEV
    ? ""
    : (import.meta.env.VITE_API_URL || "http://localhost:8000");

  return {
    baseUrl: (savedUrl ?? defaultUrl).trim().replace(/\/+$/, ""),
    apiKey: (savedKey ?? import.meta.env.VITE_API_KEY ?? "mt5-local-dev-key").trim(),
  };
}

export function saveBridgeConfig(config: BridgeConfig): void {
  const cleanUrl = config.baseUrl.trim().replace(/\/+$/, "");
  if (cleanUrl) {
    localStorage.setItem(STORAGE_URL_KEY, cleanUrl);
  } else {
    localStorage.removeItem(STORAGE_URL_KEY);
  }

  if (config.apiKey.trim()) {
    localStorage.setItem(STORAGE_API_KEY, config.apiKey.trim());
  } else {
    localStorage.removeItem(STORAGE_API_KEY);
  }
}

export function buildWsUrl(symbol: string, tf: Timeframe): string {
  const { baseUrl } = getBridgeConfig();
  const query = `symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`;

  if (!baseUrl) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/live?${query}`;
  }

  if (baseUrl.startsWith("https://")) {
    return `wss://${baseUrl.slice("https://".length)}/ws/live?${query}`;
  }
  if (baseUrl.startsWith("http://")) {
    return `ws://${baseUrl.slice("http://".length)}/ws/live?${query}`;
  }
  return `ws://${baseUrl}/ws/live?${query}`;
}

async function requestJson<T>(path: string, init: RequestInit = {}, includeApiKey = false): Promise<T> {
  const { baseUrl, apiKey } = getBridgeConfig();
  const url = `${baseUrl}${path}`;
  const headers = new Headers(init.headers || {});
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (includeApiKey && apiKey) {
    headers.set("X-API-Key", apiKey);
  }

  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      if (typeof errBody?.detail === "string") {
        message = errBody.detail;
      } else if (Array.isArray(errBody?.detail)) {
        const items = errBody.detail
          .map((item: { msg?: string; loc?: unknown[] }) => {
            const raw = String(item?.msg ?? "").replace(/^Value error,\s*/i, "").trim();
            if (/sl is required when sizing by risk_pct/i.test(raw)) {
              return "กรุณากรอก Stop Loss (SL) ก่อนคำนวณ Lot ตาม Risk %";
            }
            if (raw) return raw;
            const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : "";
            return field ? `ข้อมูลไม่ถูกต้อง: ${String(field)}` : "";
          })
          .filter(Boolean);
        if (items.length > 0) message = items.join(" · ");
      }
    } catch {
      const txt = await res.text();
      if (txt) message = txt;
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export function fetchHealth() {
  return requestJson<{
    status: string;
    mt5_connected: boolean;
    trade_mode: string | null;
    server_time: string;
    api_key_required: boolean;
  }>("/api/health");
}

export function fetchSnapshot(symbol = "XAUUSD") {
  return requestJson<MarketSnapshot>(`/api/market/snapshot?symbol=${encodeURIComponent(symbol)}`);
}

export function fetchCandles(symbol = "XAUUSD", tf: Timeframe = "M15", bars = 250) {
  return requestJson<CandlesResponse>(
    `/api/candles?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}&bars=${bars}`
  );
}

export interface OrderPayload {
  symbol: string;
  side: OrderSide;
  lots?: number | null;
  risk_pct?: number | null;
  entry_price?: number | null;
  sl?: number | null;
  tp?: number | null;
}

export function checkOrder(payload: OrderPayload) {
  return requestJson<OrderCheckResult>("/api/order/check", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchProposals(status?: string) {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return requestJson<{ proposals: TradeProposal[]; count: number }>(`/api/proposals${q}`);
}

export function createProposal(
  payload: OrderPayload & { source?: string; timeframe?: string; rationale?: string }
) {
  return requestJson<{ proposal: TradeProposal; order_check: OrderCheckResult }>(
    "/api/proposals",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    true
  );
}

export function confirmProposal(id: number, allowReal = false) {
  return requestJson<{ proposal: TradeProposal; execution: Record<string, unknown> }>(
    `/api/proposals/${id}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ allow_real: allowReal }),
    },
    true
  );
}

export function rejectProposal(id: number, reason = "") {
  return requestJson<{ proposal: TradeProposal }>(
    `/api/proposals/${id}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
    true
  );
}

export function modifyPosition(ticket: number, sl: number | null, tp: number | null, allowReal = false) {
  return requestJson<Record<string, unknown>>(
    `/api/positions/${ticket}`,
    {
      method: "PATCH",
      body: JSON.stringify({ sl, tp, allow_real: allowReal }),
    },
    true
  );
}

export function closePosition(ticket: number, lots?: number | null, allowReal = false) {
  return requestJson<Record<string, unknown>>(
    `/api/positions/${ticket}/close`,
    {
      method: "POST",
      body: JSON.stringify({ lots: lots ?? null, allow_real: allowReal }),
    },
    true
  );
}

export function fetchLogs(params?: { status?: string; side?: string; search?: string }) {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.side) sp.set("side", params.side);
  if (params?.search) sp.set("search", params.search);
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return requestJson<{ logs: TradeLogEntry[]; count: number; audit_events: AuditEvent[] }>(`/api/logs${qs}`);
}

export function syncLogs(days = 90) {
  return requestJson<{ inserted: number; updated: number; total: number }>(
    `/api/logs/sync?days=${days}`,
    { method: "POST" },
    true
  );
}

export function updateLogNotes(id: number, strategy_tag: string, notes: string) {
  return requestJson<{ log: TradeLogEntry }>(
    `/api/logs/${id}`,
    {
      method: "PATCH",
      body: JSON.stringify({ strategy_tag, notes }),
    },
    true
  );
}

export function fetchStats(sync = false) {
  return requestJson<TradingStats>(`/api/stats?sync=${sync}`);
}

export function getExportCsvUrl(): string {
  const { baseUrl } = getBridgeConfig();
  return `${baseUrl}/api/logs/export.csv`;
}

export function searchSymbols(q: string, category?: string, limit = 40) {
  const sp = new URLSearchParams({ q, limit: String(limit) });
  if (category && category !== "all") sp.set("category", category);
  return requestJson<{ symbols: SymbolSearchItem[]; count: number }>(`/api/symbols?${sp.toString()}`);
}

export function fetchWatchlist() {
  return requestJson<{ symbols: string[]; quotes: WatchlistQuote[] }>("/api/watchlist");
}

export function updateWatchlist(symbols: string[]) {
  return requestJson<{ symbols: string[]; quotes: WatchlistQuote[] }>(
    "/api/watchlist",
    {
      method: "PUT",
      body: JSON.stringify({ symbols }),
    },
    true
  );
}

export function fetchNews(symbol: string, refresh = false) {
  return requestJson<NewsResponse>(
    `/api/news?symbol=${encodeURIComponent(symbol)}&refresh=${refresh}`
  );
}

export function evaluateGauntlet(
  symbol: string,
  tf: Timeframe,
  riskPct = 15,
  autoQueue = false,
  minConfidencePct = 75
) {
  return requestJson<GauntletEvaluation>(
    "/api/gauntlet/evaluate",
    {
      method: "POST",
      body: JSON.stringify({
        symbol,
        tf,
        risk_pct: riskPct,
        min_confidence_pct: minConfidencePct,
        auto_queue: autoQueue,
      }),
    },
    autoQueue
  );
}

export function fetchMlStatus(symbol: string, tf: Timeframe) {
  return requestJson<MLModelStatus>(
    `/api/ml/status?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`
  );
}

export function trainMlModel(symbol: string, tf: Timeframe, bars = 10000) {
  return requestJson<MLModelStatus>(
    "/api/ml/train",
    {
      method: "POST",
      body: JSON.stringify({ symbol, tf, bars }),
    },
    true
  );
}

export function fetchBacktest(symbol: string, tf: Timeframe, bars = 600) {
  return requestJson<BacktestResult>(
    `/api/backtest?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}&bars=${bars}`
  );
}

export function fetchWatchdogStatus() {
  return requestJson<WatchdogStatus>("/api/watchdog/status");
}

export function updateWatchdogConfig(patch: Partial<WatchdogConfig>) {
  return requestJson<WatchdogStatus>(
    "/api/watchdog/config",
    {
      method: "PATCH",
      body: JSON.stringify(patch),
    },
    true
  );
}

export function triggerWatchdogScan(symbol?: string) {
  const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  return requestJson<{ scan: Record<string, unknown>; status: WatchdogStatus }>(
    `/api/watchdog/scan${q}`,
    { method: "POST" },
    true
  );
}

export function fetchSystemLogs(params?: { category?: string; level?: string; limit?: number }) {
  const sp = new URLSearchParams();
  if (params?.category) sp.set("category", params.category);
  if (params?.level) sp.set("level", params.level);
  if (params?.limit) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return requestJson<{ logs: SystemLogEntry[]; count: number }>(`/api/system-logs${qs}`);
}

export function fetchSheetsConfig() {
  return requestJson<SheetsConfig>("/api/sheets/config");
}

export function saveSheetsConfig(cfg: Partial<SheetsConfig>) {
  return requestJson<SheetsConfig>(
    "/api/sheets/config",
    {
      method: "PUT",
      body: JSON.stringify(cfg),
    },
    true
  );
}

export function testSheetsConnection() {
  return requestJson<{ ok: boolean; mode?: string; response?: unknown }>(
    "/api/sheets/test",
    { method: "POST" },
    true
  );
}

export function syncAllSheets() {
  return requestJson<{ ok: boolean; written: Record<string, number> }>(
    "/api/sheets/sync-all",
    { method: "POST" },
    true
  );
}
