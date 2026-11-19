export type OrderSide =
  | "BUY"
  | "SELL"
  | "BUY_LIMIT"
  | "SELL_LIMIT"
  | "BUY_STOP"
  | "SELL_STOP";

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

export type AppTab = "desk" | "gauntlet" | "stats" | "journal";

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
  description?: string;
  category?: string;
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
  current_r?: number;
  risk_distance?: number;
  be_applied?: boolean;
  partial_applied?: boolean;
  trail_count?: number;
  last_action?: string;
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

export interface PortfolioRiskStatus {
  equity: number;
  daily_realized_pnl_usd: number;
  floating_pnl_usd: number;
  daily_total_pnl_usd: number;
  daily_total_pnl_pct: number;
  open_positions_count: number;
  open_risk_usd: number;
  open_risk_pct: number;
  max_daily_loss_pct?: number;
  max_open_risk_pct?: number;
  proposal_ttl_min?: number;
  max_drift_atr?: number;
}

export interface MarketSnapshot {
  account: AccountSummary;
  quote: QuoteInfo;
  positions: OpenPosition[];
  orders: PendingOrder[];
  mtf: MtfSummaryRow[];
  risk_status?: PortfolioRiskStatus | null;
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

export interface NewsArticle {
  title: string;
  source: string;
  url: string;
  published: string;
  sentiment_tag: "BULLISH" | "BEARISH" | "NEUTRAL" | string;
  matched_terms: string[];
}

export interface NewsResponse {
  symbol: string;
  fetched_at: string;
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL" | string;
  sentiment_score: number;
  high_impact_event: boolean;
  high_impact_keywords: string[];
  sources_used: string[];
  articles: NewsArticle[];
}

export interface MLFeatureDriver {
  feature: string;
  shap_value: number;
  value: number;
  direction: "UP" | "DOWN";
}

export interface MLReport {
  model_symbol: string;
  model_tf: string;
  trained_at: string;
  ml_buy_prob_pct: number;
  ml_sell_prob_pct: number;
  ml_raw_prob_pct: number;
  ml_conviction_pct?: number;
  news_adjustment_pct: number;
  mtf_bonus_pct: number;
  final_confidence_pct: number;
  min_confidence_pct: number;
  meets_threshold: boolean;
  top_features: MLFeatureDriver[];
  oos_summary: {
    auc_buy: number | null;
    auc_sell: number | null;
    win_rate_65_buy_pct: number | null;
    win_rate_65_sell_pct: number | null;
    net_r_combined: number;
  };
}

export interface MLModelStatus {
  trained: boolean;
  symbol: string;
  tf: string;
  meta: {
    symbol: string;
    tf: string;
    trained_at: string;
    bars_requested: number;
    bars_used: number;
    barrier_rule: string;
    buy_metrics: Record<string, unknown>;
    sell_metrics: Record<string, unknown>;
    oos_summary: MLReport["oos_summary"];
  } | null;
}

export interface GauntletGate {
  id: string;
  label: string;
  status: "PASS" | "WARN" | "FAIL";
  metric: string;
  detail: string;
}

export interface GauntletEvaluation {
  symbol: string;
  timeframe: string;
  evaluated_at: string;
  verdict: "PASS" | "WAIT" | "REJECT";
  direction: "BUY" | "SELL" | "WAIT";
  passed_count: number;
  warn_count: number;
  fail_count: number;
  total_gates: number;
  rationale: string;
  quote: QuoteInfo;
  mtf_snapshot: MtfSummaryRow[];
  gates: GauntletGate[];
  ml?: MLReport | null;
  proposed_order: {
    symbol: string;
    side: OrderSide;
    order_type: "MARKET" | "PENDING";
    entry_price: number;
    sl: number;
    tp: number;
    risk_pct: number;
    lots: number;
    est_risk_usd: number;
    est_risk_pct: number;
    est_reward_usd: number;
    rr_ratio: number;
    required_margin: number;
    timeframe: string;
    rationale: string;
  } | null;
  news_summary: {
    sentiment: string;
    sentiment_score: number;
    high_impact_event: boolean;
    high_impact_keywords: string[];
    sources_used: string[];
  };
  news: NewsArticle[];
  queued_proposal?: TradeProposal | null;
}

export interface BacktestTrade {
  side: "BUY" | "SELL";
  entry_time: string;
  exit_time: string;
  entry: number;
  exit: number;
  sl: number;
  tp: number;
  result_r: number;
  outcome: "WIN" | "LOSS";
}

export interface BacktestResult {
  symbol: string;
  tf: string;
  bars_tested: number;
  start_time: string;
  end_time: string;
  rule_summary: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  profit_factor: number | null;
  net_r: number;
  expectancy_r: number;
  max_drawdown_r: number;
  equity_r_curve: { trade: number; time: string; cum_r: number }[];
  recent_trades: BacktestTrade[];
}

export interface SymbolSearchItem {
  name: string;
  description: string;
  category: string;
  digits: number;
}

export interface WatchlistQuote {
  symbol: string;
  description: string;
  category: string;
  bid: number;
  ask: number;
  digits: number;
  spread_points: number;
  change_pct: number;
  market_open: boolean;
  tick_time_server?: string;
  error?: string;
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
  gauntlet?: {
    verdict?: string;
    passed_count?: number;
    total_gates?: number;
    confidence_pct?: number | null;
    gates?: GauntletGate[];
    ml?: MLReport | null;
  };
  news?: NewsArticle[];
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

export interface SystemLogEntry {
  id: number;
  created_at: string;
  level: "INFO" | "SIGNAL" | "WARN" | "ERROR" | string;
  category: string;
  symbol: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface WatchdogConfig {
  enabled: boolean;
  interval_sec: number;
  timeframe: string;
  risk_pct: number;
  min_confidence_pct: number;
  auto_propose: boolean;
  cooldown_min: number;
  autopilot_enabled?: boolean;
  autopilot_min_confidence_pct?: number;
  autopilot_sizing_mode?: "FIXED_LOT" | "RISK_PCT";
  autopilot_fixed_lots?: number;
  autopilot_risk_pct?: number;
  autopilot_max_open_positions?: number;
  proposal_ttl_min?: number;
  max_drift_atr?: number;
  max_daily_loss_pct?: number;
  max_open_risk_pct?: number;
  sl_atr_mult?: number;
  tp_atr_mult?: number;
  min_rr_ratio?: number;
}

export interface PositionManagerConfig {
  enabled: boolean;
  poll_interval_sec: number;
  auto_breakeven: boolean;
  be_trigger_r: number;
  be_offset_points: number;
  auto_partial_tp: boolean;
  partial_trigger_r: number;
  partial_close_pct: number;
  auto_trailing_sl: boolean;
  trail_start_r: number;
  trail_distance_r: number;
}

export interface PositionManagerStatus {
  running: boolean;
  last_run_at: string | null;
  actions_taken_count: number;
  config: PositionManagerConfig;
}

export interface DiscordConfig {
  enabled: boolean;
  webhook_url: string;
  public_base_url: string;
  notify_proposals: boolean;
  notify_autopilot: boolean;
  notify_position_manager: boolean;
}

export interface WatchdogScanItem {
  symbol: string;
  timeframe: string;
  verdict: string;
  direction: string;
  passed_count: number;
  total_gates: number;
  confidence_pct?: number | null;
  min_confidence_pct?: number;
  evaluated_at: string;
  bid: number;
  sentiment: string;
}

export interface WatchdogStatus {
  running: boolean;
  scanning_now: boolean;
  last_scan_at: string | null;
  config: WatchdogConfig;
  last_results: WatchdogScanItem[];
}

export interface SheetsConfig {
  enabled: boolean;
  webhook_url: string;
  service_account_file: string;
  sheet_id: string;
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

export interface ActorBreakdown {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  net_profit: number;
  expectancy: number;
  profit_factor: number | null;
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
  by_actor?: {
    AUTOPILOT: ActorBreakdown;
    AI_CONFIRMED: ActorBreakdown;
    MANUAL: ActorBreakdown;
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
  latest_log_id?: number;
  watchdog_running?: boolean;
  watchdog_scanning?: boolean;
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
