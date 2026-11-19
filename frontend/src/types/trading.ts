export type OrderSide =
  | "BUY"
  | "SELL"
  | "BUY_LIMIT"
  | "SELL_LIMIT"
  | "BUY_STOP"
  | "SELL_STOP";

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

export type AppTab = "desk" | "stats" | "journal";

export type WsStatus = "LIVE" | "RECONNECTING" | "OFFLINE";

export interface AccountSummary {
  login: number;
  server: string;
  name: string;
  company: string;
  currency: string;
  leverage: number;
  balance: number;
  equity: number;
  margin: number;
  margin_free: number;
  margin_level: number;
  profit: number;
  trade_mode: "DEMO" | "CONTEST" | "REAL" | string;
  account_trade_allowed: boolean;
  terminal_trade_allowed: boolean;
  connected: boolean;
}

export interface QuoteInfo {
  symbol: string;
  bid: number;
  ask: number;
  spread_price: number;
  spread_points: number;
  digits: number;
  point: number;
  contract_size: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  stops_level_points: number;
  stops_level_price: number;
  tick_epoch: number;
  tick_time_server: string;
}

export interface OpenPosition {
  ticket: number;
  symbol: string;
  side: "BUY" | "SELL";
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  magic: number;
  comment: string;
  open_time: string;
}

export interface PendingOrder {
  ticket: number;
  symbol: string;
  side: string;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  magic: number;
  comment: string;
  time_setup: string;
}

export interface MtfSummaryRow {
  tf: string;
  time: number;
  close: number;
  ema20: number;
  ema50: number;
  ema200: number;
  rsi14: number;
  macd_hist: number;
  atr14: number;
  high20: number;
  low20: number;
  trend: string;
}

export interface CandlePoint {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20: number | null;
  ema50: number | null;
  ema200: number | null;
  rsi14: number | null;
  atr14: number | null;
}

export interface CandlesResponse {
  symbol: string;
  tf: Timeframe;
  digits: number;
  count: number;
  trend: string;
  candles: CandlePoint[];
}

export interface MarketSnapshot {
  account: AccountSummary;
  quote: QuoteInfo;
  positions: OpenPosition[];
  orders: PendingOrder[];
  mtf: MtfSummaryRow[];
}

export interface OrderCheckResult {
  symbol: string;
  side: OrderSide;
  order_type: "MARKET" | "PENDING";
  entry_price: number;
  sl: number | null;
  tp: number | null;
  lots: number;
  est_risk_usd: number;
  est_risk_pct: number;
  est_reward_usd: number;
  rr_ratio: number | null;
  margin_capped: boolean;
  required_margin: number;
  margin_free_after: number;
  retcode: number;
  comment: string;
  valid: boolean;
}

export interface TradeProposal {
  id: number;
  created_at: string;
  updated_at: string;
  source: string;
  symbol: string;
  side: OrderSide;
  order_type: "MARKET" | "PENDING";
  entry_price: number;
  sl: number | null;
  tp: number | null;
  risk_pct: number | null;
  lots: number;
  est_risk_usd: number;
  est_reward_usd: number;
  rr_ratio: number | null;
  rationale: string;
  timeframe: string;
  status: "PENDING" | "CONFIRMED" | "EXECUTED" | "REJECTED" | "FAILED";
  mt5_order_ticket: number | null;
  mt5_deal_ticket: number | null;
  exec_price: number | null;
  exec_comment: string | null;
}

export interface TradeLogEntry {
  id: number;
  mt5_deal_ticket: number | null;
  mt5_position_id: number | null;
  proposal_id: number | null;
  symbol: string;
  side: string;
  volume: number;
  entry_price: number;
  exit_price: number | null;
  sl: number | null;
  tp: number | null;
  open_time: string | null;
  close_time: string | null;
  gross_profit: number;
  commission: number;
  swap: number;
  net_profit: number;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  strategy_tag: string;
  notes: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: number;
  created_at: string;
  event_type: string;
  actor: string;
  summary: string;
  payload_json: string;
}

export interface EquityPoint {
  index: number;
  time: string;
  pnl: number;
  cumulative_pnl: number;
  equity: number;
}

export interface DailyPnlPoint {
  date: string;
  pnl: number;
  trades: number;
  wins: number;
}

export interface SideBreakdown {
  trades: number;
  wins: number;
  win_rate_pct: number;
  net_profit: number;
}

export interface TradingStats {
  total_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate_pct: number;
  net_profit: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  largest_win: number;
  largest_loss: number;
  current_streak: number;
  max_win_streak: number;
  max_loss_streak: number;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  starting_balance: number;
  equity_curve: EquityPoint[];
  daily_pnl: DailyPnlPoint[];
  by_side: {
    BUY: SideBreakdown;
    SELL: SideBreakdown;
  };
  open_logged_count?: number;
}

export interface WsLivePacket {
  type: "tick" | "error";
  mt5_connected: boolean;
  server_time: string;
  symbol?: string;
  tf?: string;
  pending_proposals_count?: number;
  account?: AccountSummary | null;
  quote?: QuoteInfo | null;
  positions?: OpenPosition[];
  orders?: PendingOrder[];
  last_bar?: CandlePoint | null;
  detail?: string;
}

export interface ChartPreviewLevels {
  entry: number | null;
  sl: number | null;
  tp: number | null;
  side: OrderSide;
}
