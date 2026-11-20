import type {
  AccountSummary,
  SystemLogEntry,
  TradeLogEntry,
  TradeProposal,
  TradingStats,
} from "../types/trading";

export const SUPABASE_URL = (
  import.meta.env.VITE_SUPABASE_URL || "https://igdrxqpxbfvaeagppnus.supabase.co"
)
  .trim()
  .replace(/\/+$/, "");

export const SUPABASE_PUBLISHABLE_KEY = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  "sb_publishable__Bc0V-v4EV0VJ0hZ_aV-9w_rd3uvyK1"
).trim();

export const SUPABASE_OWNER_ID = "20c1e655-72e7-4f18-ad5e-16b54794fee5";

const SESSION_STORAGE_KEY = "mt5_supabase_session_v1";

export interface SupabaseUser {
  id: string;
  email: string;
}

export interface SupabaseSession {
  access_token: string;
  refresh_token: string;
  expires_at: number; // epoch ms
  user: SupabaseUser;
}

export interface SupabaseBridgeState {
  owner_id: string;
  public_url: string;
  api_key: string;
  mt5_connected: boolean;
  trade_mode: string | null;
  account_json: AccountSummary | null;
  updated_at: string;
}

export function getStoredSupabaseSession(): SupabaseSession | null {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SupabaseSession;
    if (!parsed?.access_token || !parsed?.user?.id) return null;
    if (parsed.user.id !== SUPABASE_OWNER_ID) {
      localStorage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function saveSupabaseSession(session: SupabaseSession | null): void {
  if (!session) {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export async function signInWithSupabase(
  email: string,
  password: string
): Promise<SupabaseSession> {
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: {
      apikey: SUPABASE_PUBLISHABLE_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: email.trim(),
      password,
    }),
  });

  if (!res.ok) {
    let msg = "อีเมลหรือรหัสผ่านไม่ถูกต้อง";
    try {
      const err = await res.json();
      if (err?.msg || err?.error_description) {
        msg = String(err.msg || err.error_description);
      }
    } catch {
      // ignore
    }
    throw new Error(msg);
  }

  const data = await res.json();
  const uid = String(data?.user?.id || "");
  const userEmail = String(data?.user?.email || email.trim());
  if (uid !== SUPABASE_OWNER_ID) {
    throw new Error("บัญชีนี้ไม่ได้รับอนุญาตให้เข้าถึงพอร์ตเทรดนี้ (Single-Owner Locked)");
  }

  const expiresInSec = Number(data?.expires_in || 3600);
  const session: SupabaseSession = {
    access_token: String(data.access_token),
    refresh_token: String(data.refresh_token),
    expires_at: Date.now() + expiresInSec * 1000,
    user: {
      id: uid,
      email: userEmail,
    },
  };
  saveSupabaseSession(session);
  return session;
}

export async function getValidSupabaseAccessToken(): Promise<string | null> {
  const session = getStoredSupabaseSession();
  if (!session) return null;

  if (Date.now() < session.expires_at - 90_000) {
    return session.access_token;
  }

  if (!session.refresh_token) {
    saveSupabaseSession(null);
    return null;
  }

  try {
    const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });
    if (!res.ok) {
      saveSupabaseSession(null);
      return null;
    }
    const data = await res.json();
    const uid = String(data?.user?.id || session.user.id);
    if (uid !== SUPABASE_OWNER_ID) {
      saveSupabaseSession(null);
      return null;
    }
    const updated: SupabaseSession = {
      access_token: String(data.access_token),
      refresh_token: String(data.refresh_token || session.refresh_token),
      expires_at: Date.now() + Number(data.expires_in || 3600) * 1000,
      user: {
        id: uid,
        email: String(data?.user?.email || session.user.email),
      },
    };
    saveSupabaseSession(updated);
    return updated.access_token;
  } catch {
    return session.access_token;
  }
}

export async function signOutSupabase(): Promise<void> {
  const session = getStoredSupabaseSession();
  saveSupabaseSession(null);
  if (!session?.access_token) return;
  try {
    await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        Authorization: `Bearer ${session.access_token}`,
      },
    });
  } catch {
    // ignore
  }
}

export async function changeSupabasePassword(newPassword: string): Promise<void> {
  const token = await getValidSupabaseAccessToken();
  if (!token) throw new Error("กรุณา Login ใหม่ก่อนเปลี่ยนรหัสผ่าน");

  const res = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    method: "PUT",
    headers: {
      apikey: SUPABASE_PUBLISHABLE_KEY,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password: newPassword }),
  });

  if (!res.ok) {
    let msg = "เปลี่ยนรหัสผ่านไม่สำเร็จ";
    try {
      const err = await res.json();
      msg = String(err?.msg || err?.message || msg);
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
}

async function fetchPostgrest<T>(queryPath: string): Promise<T> {
  const token = await getValidSupabaseAccessToken();
  if (!token) throw new Error("Not authenticated with Supabase");

  const res = await fetch(`${SUPABASE_URL}/rest/v1/${queryPath}`, {
    method: "GET",
    headers: {
      apikey: SUPABASE_PUBLISHABLE_KEY,
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
    },
  });

  if (!res.ok) {
    throw new Error(`Supabase HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function discoverBridgeStateFromSupabase(): Promise<SupabaseBridgeState | null> {
  try {
    const rows = await fetchPostgrest<SupabaseBridgeState[]>(
      "bridge_state?select=*&limit=1"
    );
    if (!rows || rows.length === 0) return null;
    return rows[0];
  } catch {
    return null;
  }
}

export interface SupabaseCloudFallbackData {
  bridgeState: SupabaseBridgeState | null;
  proposals: TradeProposal[];
  logs: TradeLogEntry[];
  systemLogs: SystemLogEntry[];
  watchlist: string[];
  stats: TradingStats | null;
}

export async function fetchSupabaseCloudFallback(): Promise<SupabaseCloudFallbackData | null> {
  const token = await getValidSupabaseAccessToken();
  if (!token) return null;

  try {
    const [bridgeRows, propRows, logRows, sysRows, settingRows] = await Promise.all([
      fetchPostgrest<SupabaseBridgeState[]>("bridge_state?select=*&limit=1").catch(() => []),
      fetchPostgrest<Array<Record<string, unknown>>>(
        "trade_proposals?select=*&order=id.desc&limit=50"
      ).catch(() => []),
      fetchPostgrest<TradeLogEntry[]>(
        "trade_logs?select=*&order=id.desc&limit=200"
      ).catch(() => []),
      fetchPostgrest<Array<Record<string, unknown>>>(
        "system_logs?select=*&order=id.desc&limit=120"
      ).catch(() => []),
      fetchPostgrest<Array<{ key: string; value_json: unknown }>>(
        "app_settings?select=key,value_json"
      ).catch(() => []),
    ]);

    const proposals: TradeProposal[] = propRows.map((r) => ({
      id: Number(r.id),
      created_at: String(r.created_at || ""),
      updated_at: String(r.updated_at || ""),
      source: String(r.source || "WEB"),
      symbol: String(r.symbol || ""),
      side: (r.side as TradeProposal["side"]) || "BUY",
      order_type: (r.order_type as TradeProposal["order_type"]) || "MARKET",
      entry_price: Number(r.entry_price || 0),
      sl: r.sl !== null && r.sl !== undefined ? Number(r.sl) : null,
      tp: r.tp !== null && r.tp !== undefined ? Number(r.tp) : null,
      risk_pct: r.risk_pct !== null && r.risk_pct !== undefined ? Number(r.risk_pct) : null,
      lots: Number(r.lots || 0),
      est_risk_usd: Number(r.est_risk_usd || 0),
      est_reward_usd: Number(r.est_reward_usd || 0),
      rr_ratio: r.rr_ratio !== null && r.rr_ratio !== undefined ? Number(r.rr_ratio) : null,
      rationale: String(r.rationale || ""),
      timeframe: String(r.timeframe || "M15"),
      status: (r.status as TradeProposal["status"]) || "PENDING",
      mt5_order_ticket: r.mt5_order_ticket ? Number(r.mt5_order_ticket) : null,
      mt5_deal_ticket: r.mt5_deal_ticket ? Number(r.mt5_deal_ticket) : null,
      exec_price: r.exec_price !== null && r.exec_price !== undefined ? Number(r.exec_price) : null,
      exec_comment: r.exec_comment ? String(r.exec_comment) : null,
      gauntlet: (r.gauntlet_json as TradeProposal["gauntlet"]) || undefined,
      news: (r.news_json as TradeProposal["news"]) || undefined,
    }));

    const systemLogs: SystemLogEntry[] = sysRows.map((s) => ({
      id: Number(s.id),
      created_at: String(s.created_at || ""),
      level: String(s.level || "INFO"),
      category: String(s.category || "SYSTEM"),
      symbol: String(s.symbol || ""),
      message: String(s.message || ""),
      details: (s.details_json as Record<string, unknown>) || {},
    }));

    let watchlist: string[] = ["XAUUSD"];
    let stats: TradingStats | null = null;
    for (const st of settingRows) {
      if (st.key === "watchlist" && st.value_json && typeof st.value_json === "object") {
        const syms = (st.value_json as { symbols?: string[] }).symbols;
        if (Array.isArray(syms) && syms.length > 0) {
          watchlist = syms;
        }
      } else if (st.key === "latest_stats" && st.value_json && typeof st.value_json === "object") {
        stats = st.value_json as TradingStats;
      }
    }

    return {
      bridgeState: bridgeRows[0] || null,
      proposals,
      logs: logRows,
      systemLogs,
      watchlist,
      stats,
    };
  } catch {
    return null;
  }
}
