"""Real-time Supabase PostgreSQL & Auth synchronization for single-owner trading desk."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from app.analytics import compute_trading_stats
from app.config import (
    API_KEY,
    SUPABASE_OWNER_EMAIL,
    SUPABASE_OWNER_ID,
    SUPABASE_OWNER_PASSWORD,
    SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_URL,
)
from app.database import (
    DB_PATH,
    get_connection,
    get_discord_config,
    get_position_manager_config,
    get_watchdog_config,
    get_watchlist,
    list_proposals,
    list_system_logs,
    list_trade_logs,
)

_TOKEN_LOCK = threading.RLock()
_CACHED_ACCESS_TOKEN: str = ""
_CACHED_REFRESH_TOKEN: str = ""
_TOKEN_EXPIRES_AT: float = 0.0

_VERIFIED_JWT_CACHE: dict[str, float] = {}


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY and SUPABASE_OWNER_ID)


def _request_auth_token(payload: dict[str, Any], grant_type: str) -> str:
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type={grant_type}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    global _CACHED_ACCESS_TOKEN, _CACHED_REFRESH_TOKEN, _TOKEN_EXPIRES_AT
    _CACHED_ACCESS_TOKEN = str(data.get("access_token") or "")
    _CACHED_REFRESH_TOKEN = str(data.get("refresh_token") or "")
    expires_in = float(data.get("expires_in") or 3600)
    _TOKEN_EXPIRES_AT = time.monotonic() + max(60.0, expires_in - 120.0)
    return _CACHED_ACCESS_TOKEN


def get_owner_access_token() -> str:
    """Obtain or refresh the owner's Supabase JWT for RLS-authenticated database writes."""
    if not is_supabase_configured():
        return ""
    with _TOKEN_LOCK:
        now = time.monotonic()
        if _CACHED_ACCESS_TOKEN and now < _TOKEN_EXPIRES_AT:
            return _CACHED_ACCESS_TOKEN

        if _CACHED_REFRESH_TOKEN:
            try:
                return _request_auth_token(
                    {"refresh_token": _CACHED_REFRESH_TOKEN},
                    "refresh_token",
                )
            except Exception:
                pass

        if SUPABASE_OWNER_EMAIL and SUPABASE_OWNER_PASSWORD:
            try:
                return _request_auth_token(
                    {
                        "email": SUPABASE_OWNER_EMAIL,
                        "password": SUPABASE_OWNER_PASSWORD,
                    },
                    "password",
                )
            except Exception:
                return ""
        return _CACHED_ACCESS_TOKEN


def verify_supabase_owner_jwt(bearer_token: str) -> bool:
    """Verify a Supabase Auth JWT from the frontend belongs to the sole authorized owner."""
    token = (bearer_token or "").strip()
    if not token or not is_supabase_configured():
        return False

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _TOKEN_LOCK:
        cached_exp = _VERIFIED_JWT_CACHE.get(token_hash, 0.0)
        if cached_exp > now:
            return True

    url = f"{SUPABASE_URL}/auth/v1/user"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            user = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False

    uid = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip().lower()
    if uid != SUPABASE_OWNER_ID:
        return False
    if SUPABASE_OWNER_EMAIL and email != SUPABASE_OWNER_EMAIL.lower():
        return False

    with _TOKEN_LOCK:
        _VERIFIED_JWT_CACHE[token_hash] = now + 120.0
        global _CACHED_ACCESS_TOKEN, _TOKEN_EXPIRES_AT
        if not _CACHED_ACCESS_TOKEN or now >= _TOKEN_EXPIRES_AT:
            _CACHED_ACCESS_TOKEN = token
            _TOKEN_EXPIRES_AT = now + 300.0
    return True


def _postgrest_upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
    if not rows or not is_supabase_configured():
        return 0
    token = get_owner_access_token()
    if not token:
        return 0

    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    req = urllib.request.Request(
        url,
        data=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as _:
        return len(rows)


def sync_bridge_state_to_supabase(
    public_url: str | None = None,
    mt5_connected: bool = False,
    trade_mode: str | None = None,
    account_summary: dict[str, Any] | None = None,
) -> bool:
    """Publish current Cloudflare Tunnel URL and MT5 status so the web UI auto-discovers it on login."""
    if not is_supabase_configured():
        return False
    try:
        discord_cfg = get_discord_config()
        resolved_url = (public_url or discord_cfg.get("public_base_url") or "").strip().rstrip("/")
        row = {
            "owner_id": SUPABASE_OWNER_ID,
            "public_url": resolved_url,
            "api_key": API_KEY,
            "mt5_connected": bool(mt5_connected),
            "trade_mode": trade_mode,
            "account_json": account_summary or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _postgrest_upsert("bridge_state", [row], "owner_id")
        return True
    except Exception:
        return False


def sync_trades_to_supabase(trades: list[dict[str, Any]]) -> int:
    if not trades or not is_supabase_configured():
        return 0
    rows: list[dict[str, Any]] = []
    for t in trades:
        if not t.get("id"):
            continue
        rows.append(
            {
                "id": int(t["id"]),
                "owner_id": SUPABASE_OWNER_ID,
                "mt5_deal_ticket": t.get("mt5_deal_ticket"),
                "mt5_position_id": t.get("mt5_position_id"),
                "proposal_id": t.get("proposal_id"),
                "symbol": str(t.get("symbol") or ""),
                "side": str(t.get("side") or ""),
                "volume": float(t.get("volume") or 0.0),
                "entry_price": float(t.get("entry_price") or 0.0),
                "exit_price": float(t["exit_price"]) if t.get("exit_price") is not None else None,
                "sl": float(t["sl"]) if t.get("sl") is not None else None,
                "tp": float(t["tp"]) if t.get("tp") is not None else None,
                "open_time": t.get("open_time"),
                "close_time": t.get("close_time"),
                "gross_profit": float(t.get("gross_profit") or 0.0),
                "commission": float(t.get("commission") or 0.0),
                "swap": float(t.get("swap") or 0.0),
                "net_profit": float(t.get("net_profit") or 0.0),
                "status": str(t.get("status") or "OPEN"),
                "strategy_tag": str(t.get("strategy_tag") or ""),
                "notes": str(t.get("notes") or ""),
                "source": str(t.get("source") or "MT5"),
                "created_at": str(t.get("created_at") or ""),
                "updated_at": str(t.get("updated_at") or ""),
            }
        )
    try:
        return _postgrest_upsert("trade_logs", rows, "id")
    except Exception:
        return 0


def sync_proposals_to_supabase(proposals: list[dict[str, Any]]) -> int:
    if not proposals or not is_supabase_configured():
        return 0
    rows: list[dict[str, Any]] = []
    for p in proposals:
        if not p.get("id"):
            continue
        gauntlet_val = p.get("gauntlet")
        if not isinstance(gauntlet_val, dict):
            try:
                gauntlet_val = json.loads(p.get("gauntlet_json") or "{}")
            except Exception:
                gauntlet_val = {}
        news_val = p.get("news")
        if not isinstance(news_val, list):
            try:
                news_val = json.loads(p.get("news_json") or "[]")
            except Exception:
                news_val = []
        rows.append(
            {
                "id": int(p["id"]),
                "owner_id": SUPABASE_OWNER_ID,
                "created_at": str(p.get("created_at") or ""),
                "updated_at": str(p.get("updated_at") or ""),
                "source": str(p.get("source") or "WEB"),
                "symbol": str(p.get("symbol") or ""),
                "side": str(p.get("side") or ""),
                "order_type": str(p.get("order_type") or p.get("side") or "MARKET"),
                "entry_price": float(p.get("entry_price") or 0.0),
                "sl": float(p["sl"]) if p.get("sl") is not None else None,
                "tp": float(p["tp"]) if p.get("tp") is not None else None,
                "risk_pct": float(p["risk_pct"]) if p.get("risk_pct") is not None else None,
                "lots": float(p.get("lots") or 0.0),
                "est_risk_usd": float(p.get("est_risk_usd") or 0.0),
                "est_reward_usd": float(p.get("est_reward_usd") or 0.0),
                "rr_ratio": float(p["rr_ratio"]) if p.get("rr_ratio") is not None else None,
                "rationale": str(p.get("rationale") or ""),
                "timeframe": str(p.get("timeframe") or "M15"),
                "status": str(p.get("status") or "PENDING"),
                "mt5_order_ticket": p.get("mt5_order_ticket"),
                "mt5_deal_ticket": p.get("mt5_deal_ticket"),
                "exec_price": float(p["exec_price"]) if p.get("exec_price") is not None else None,
                "exec_comment": p.get("exec_comment"),
                "gauntlet_json": gauntlet_val,
                "news_json": news_val,
            }
        )
    try:
        return _postgrest_upsert("trade_proposals", rows, "id")
    except Exception:
        return 0


def sync_system_logs_to_supabase(logs: list[dict[str, Any]]) -> int:
    if not logs or not is_supabase_configured():
        return 0
    rows: list[dict[str, Any]] = []
    for l in logs:
        if not l.get("id"):
            continue
        details = l.get("details")
        if not isinstance(details, dict):
            try:
                details = json.loads(l.get("details_json") or "{}")
            except Exception:
                details = {}
        rows.append(
            {
                "id": int(l["id"]),
                "owner_id": SUPABASE_OWNER_ID,
                "created_at": str(l.get("created_at") or ""),
                "level": str(l.get("level") or "INFO"),
                "category": str(l.get("category") or "SYSTEM"),
                "symbol": str(l.get("symbol") or ""),
                "message": str(l.get("message") or ""),
                "details_json": details,
            }
        )
    try:
        return _postgrest_upsert("system_logs", rows, "id")
    except Exception:
        return 0


def sync_equity_snapshots_to_supabase(limit: int = 300) -> int:
    if not is_supabase_configured():
        return 0
    try:
        with get_connection(DB_PATH) as conn:
            raw = conn.execute(
                "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        if not raw:
            return 0
        rows = [
            {
                "id": int(r["id"]),
                "owner_id": SUPABASE_OWNER_ID,
                "recorded_at": str(r["recorded_at"]),
                "balance": float(r["balance"]),
                "equity": float(r["equity"]),
                "floating_pnl": float(r["floating_pnl"]),
                "margin_free": float(r["margin_free"]),
            }
            for r in raw
        ]
        return _postgrest_upsert("equity_snapshots", rows, "id")
    except Exception:
        return 0


def sync_settings_to_supabase(stats: dict[str, Any] | None = None) -> int:
    if not is_supabase_configured():
        return 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    items: list[tuple[str, Any]] = [
        ("watchlist", {"symbols": get_watchlist()}),
        ("watchdog_config", get_watchdog_config()),
        ("position_manager_config", get_position_manager_config()),
        ("discord_config", get_discord_config()),
    ]
    if stats is not None:
        items.append(("latest_stats", stats))
    rows = [
        {
            "owner_id": SUPABASE_OWNER_ID,
            "key": k,
            "value_json": v,
            "updated_at": now,
        }
        for k, v in items
    ]
    try:
        return _postgrest_upsert("app_settings", rows, "owner_id,key")
    except Exception:
        return 0


def sync_all_to_supabase(
    current_balance: float | None = None,
    mt5_connected: bool = False,
    trade_mode: str | None = None,
    account_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform a full synchronization of local SQLite state into Supabase PostgreSQL."""
    trades = list_trade_logs(limit=1000)
    proposals = list_proposals(limit=200)
    sys_logs = list_system_logs(limit=200)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    stats = compute_trading_stats(closed, current_balance=current_balance)
    stats["open_logged_count"] = len([t for t in trades if t.get("status") == "OPEN"])

    bridge_ok = sync_bridge_state_to_supabase(
        mt5_connected=mt5_connected,
        trade_mode=trade_mode,
        account_summary=account_summary,
    )
    n_trades = sync_trades_to_supabase(trades)
    n_proposals = sync_proposals_to_supabase(proposals)
    n_logs = sync_system_logs_to_supabase(sys_logs)
    n_equity = sync_equity_snapshots_to_supabase(300)
    n_settings = sync_settings_to_supabase(stats=stats)

    return {
        "ok": True,
        "supabase_url": SUPABASE_URL,
        "owner_email": SUPABASE_OWNER_EMAIL,
        "bridge_state_synced": bridge_ok,
        "written": {
            "trade_logs": n_trades,
            "trade_proposals": n_proposals,
            "system_logs": n_logs,
            "equity_snapshots": n_equity,
            "app_settings": n_settings,
        },
    }
