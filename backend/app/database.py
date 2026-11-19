"""SQLite persistence layer for trade proposals, trade journal logs, equity history, and audit trail."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from app.config import (
    DB_PATH,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEETS_WEBHOOK_URL,
    GOOGLE_SHEET_ID,
)

_DB_LOCK = threading.RLock()

DEFAULT_WATCHLIST: list[str] = [
    "XAUUSD",
    "NVDA",
    "AAPL",
    "TSLA",
    "MSFT",
    "US500",
    "USTEC",
    "EURUSD",
    "USDJPY",
]

DEFAULT_WATCHDOG_CONFIG: dict[str, Any] = {
    "enabled": True,
    "interval_sec": 120,
    "timeframe": "M15",
    "risk_pct": 15.0,
    "min_confidence_pct": 75.0,
    "auto_propose": True,
    "cooldown_min": 30,
    "autopilot_enabled": False,
    "autopilot_min_confidence_pct": 80.0,
    "autopilot_fixed_lots": 0.01,
    "autopilot_max_open_positions": 3,
}

DEFAULT_POSITION_MANAGER_CONFIG: dict[str, Any] = {
    "enabled": True,
    "poll_interval_sec": 5,
    "auto_breakeven": True,
    "be_trigger_r": 1.0,
    "be_offset_points": 5,
    "auto_partial_tp": True,
    "partial_trigger_r": 1.5,
    "partial_close_pct": 50.0,
    "auto_trailing_sl": True,
    "trail_start_r": 1.5,
    "trail_distance_r": 0.8,
}

DEFAULT_DISCORD_CONFIG: dict[str, Any] = {
    "enabled": False,
    "webhook_url": "",
    "public_base_url": "https://mod-brokers-invite-thus.trycloudflare.com",
    "notify_proposals": True,
    "notify_autopilot": True,
    "notify_position_manager": True,
}


def utc_now_iso() -> str:
    """Return ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a WAL-enabled SQLite connection with row dictionary mapping."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create database tables and indexes if they do not exist."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trade_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'WEB',
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    sl REAL,
                    tp REAL,
                    risk_pct REAL,
                    lots REAL NOT NULL,
                    est_risk_usd REAL NOT NULL DEFAULT 0.0,
                    est_reward_usd REAL NOT NULL DEFAULT 0.0,
                    rr_ratio REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    timeframe TEXT NOT NULL DEFAULT 'M15',
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    mt5_order_ticket INTEGER,
                    mt5_deal_ticket INTEGER,
                    exec_price REAL,
                    exec_comment TEXT
                );

                CREATE TABLE IF NOT EXISTS trade_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mt5_deal_ticket INTEGER UNIQUE,
                    mt5_position_id INTEGER,
                    proposal_id INTEGER REFERENCES trade_proposals(id) ON DELETE SET NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    sl REAL,
                    tp REAL,
                    open_time TEXT,
                    close_time TEXT,
                    gross_profit REAL NOT NULL DEFAULT 0.0,
                    commission REAL NOT NULL DEFAULT 0.0,
                    swap REAL NOT NULL DEFAULT 0.0,
                    net_profit REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    strategy_tag TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'MT5',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    floating_pnl REAL NOT NULL,
                    margin_free REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'SYSTEM',
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'INFO',
                    category TEXT NOT NULL DEFAULT 'SYSTEM',
                    symbol TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS position_states (
                    ticket INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    initial_volume REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    initial_sl REAL,
                    initial_tp REAL,
                    risk_distance REAL NOT NULL,
                    be_applied INTEGER NOT NULL DEFAULT 0,
                    partial_applied INTEGER NOT NULL DEFAULT 0,
                    trail_count INTEGER NOT NULL DEFAULT 0,
                    last_action TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_proposals_status ON trade_proposals(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_status ON trade_logs(status, close_time DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_pos ON trade_logs(mt5_position_id);
                CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_syslogs_id ON system_logs(id DESC);
                CREATE INDEX IF NOT EXISTS idx_syslogs_cat ON system_logs(category, id DESC);
                """
            )
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(trade_proposals)").fetchall()
            }
            if "gauntlet_json" not in cols:
                conn.execute(
                    "ALTER TABLE trade_proposals ADD COLUMN gauntlet_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "news_json" not in cols:
                conn.execute(
                    "ALTER TABLE trade_proposals ADD COLUMN news_json TEXT NOT NULL DEFAULT '[]'"
                )


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _hydrate_proposal(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    try:
        item["gauntlet"] = json.loads(item.get("gauntlet_json") or "{}")
    except Exception:
        item["gauntlet"] = {}
    try:
        item["news"] = json.loads(item.get("news_json") or "[]")
    except Exception:
        item["news"] = []
    return item


def log_audit(
    event_type: str,
    summary: str,
    actor: str = "USER",
    payload: dict[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Record an immutable audit event."""
    now = utc_now_iso()
    payload_str = json.dumps(payload or {}, ensure_ascii=False)
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_events (created_at, event_type, actor, summary, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, event_type, actor, summary, payload_str),
            )
            row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row) if row else {}


def list_audit_events(limit: int = 50, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return latest audit events."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return _rows_to_dicts(rows)


def create_proposal(data: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    """Insert a new trade proposal waiting for user confirmation."""
    now = utc_now_iso()
    gauntlet_str = json.dumps(data.get("gauntlet") or {}, ensure_ascii=False)
    news_str = json.dumps(data.get("news") or [], ensure_ascii=False)
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO trade_proposals (
                    created_at, updated_at, source, symbol, side, order_type,
                    entry_price, sl, tp, risk_pct, lots, est_risk_usd,
                    est_reward_usd, rr_ratio, rationale, timeframe, status,
                    gauntlet_json, news_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (
                    now,
                    now,
                    data.get("source", "WEB"),
                    data["symbol"],
                    data["side"],
                    data.get("order_type", data["side"]),
                    data["entry_price"],
                    data.get("sl"),
                    data.get("tp"),
                    data.get("risk_pct"),
                    data["lots"],
                    data.get("est_risk_usd", 0.0),
                    data.get("est_reward_usd", 0.0),
                    data.get("rr_ratio"),
                    data.get("rationale", ""),
                    data.get("timeframe", "M15"),
                    gauntlet_str,
                    news_str,
                ),
            )
            row = conn.execute("SELECT * FROM trade_proposals WHERE id = ?", (cur.lastrowid,)).fetchone()
            return _hydrate_proposal(row)


def list_proposals(status: str | None = None, limit: int = 50, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """List proposals, optionally filtered by status."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM trade_proposals WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trade_proposals ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [_hydrate_proposal(r) for r in rows]


def get_proposal(proposal_id: int, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    """Fetch one proposal by ID."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT * FROM trade_proposals WHERE id = ?", (proposal_id,)).fetchone()
            return _hydrate_proposal(row) if row else None


def update_proposal_status(
    proposal_id: int,
    status: str,
    mt5_order_ticket: int | None = None,
    mt5_deal_ticket: int | None = None,
    exec_price: float | None = None,
    exec_comment: str | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Update proposal status and execution metadata."""
    now = utc_now_iso()
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE trade_proposals
                SET updated_at = ?,
                    status = ?,
                    mt5_order_ticket = COALESCE(?, mt5_order_ticket),
                    mt5_deal_ticket = COALESCE(?, mt5_deal_ticket),
                    exec_price = COALESCE(?, exec_price),
                    exec_comment = COALESCE(?, exec_comment)
                WHERE id = ?
                """,
                (now, status.upper(), mt5_order_ticket, mt5_deal_ticket, exec_price, exec_comment, proposal_id),
            )
            row = conn.execute("SELECT * FROM trade_proposals WHERE id = ?", (proposal_id,)).fetchone()
            return _hydrate_proposal(row) if row else None


def delete_proposal(proposal_id: int, db_path: Path = DB_PATH) -> None:
    """Delete a proposal record (used for test cleanup)."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM trade_proposals WHERE id = ?", (proposal_id,))


def create_execution_log(data: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    """Record a trade log entry when an order is executed via the bridge."""
    now = utc_now_iso()
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO trade_logs (
                    mt5_deal_ticket, mt5_position_id, proposal_id, symbol, side, volume,
                    entry_price, exit_price, sl, tp, open_time, close_time,
                    gross_profit, commission, swap, net_profit, status,
                    strategy_tag, notes, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mt5_deal_ticket) DO UPDATE SET
                    mt5_position_id = COALESCE(excluded.mt5_position_id, trade_logs.mt5_position_id),
                    proposal_id = COALESCE(excluded.proposal_id, trade_logs.proposal_id),
                    updated_at = excluded.updated_at
                """,
                (
                    data.get("mt5_deal_ticket"),
                    data.get("mt5_position_id"),
                    data.get("proposal_id"),
                    data["symbol"],
                    data["side"],
                    data["volume"],
                    data["entry_price"],
                    data.get("exit_price"),
                    data.get("sl"),
                    data.get("tp"),
                    data.get("open_time", now),
                    data.get("close_time"),
                    data.get("gross_profit", 0.0),
                    data.get("commission", 0.0),
                    data.get("swap", 0.0),
                    data.get("net_profit", 0.0),
                    data.get("status", "OPEN"),
                    data.get("strategy_tag", ""),
                    data.get("notes", ""),
                    data.get("source", "WEB"),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM trade_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row) if row else {}


def upsert_mt5_deals(deals: list[dict[str, Any]], db_path: Path = DB_PATH) -> dict[str, int]:
    """Upsert closed MT5 history deals into trade_logs while preserving user notes & strategy tags."""
    now = utc_now_iso()
    inserted = 0
    updated = 0

    with _DB_LOCK:
        with get_connection(db_path) as conn:
            for d in deals:
                deal_ticket = d.get("mt5_deal_ticket")
                pos_id = d.get("mt5_position_id")

                existing = None
                if deal_ticket is not None:
                    existing = conn.execute(
                        "SELECT id FROM trade_logs WHERE mt5_deal_ticket = ?",
                        (deal_ticket,),
                    ).fetchone()
                if existing is None and pos_id is not None:
                    existing = conn.execute(
                        "SELECT id FROM trade_logs WHERE mt5_position_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1",
                        (pos_id,),
                    ).fetchone()

                if existing is not None:
                    conn.execute(
                        """
                        UPDATE trade_logs
                        SET mt5_deal_ticket = COALESCE(?, mt5_deal_ticket),
                            mt5_position_id = COALESCE(?, mt5_position_id),
                            symbol = ?,
                            side = ?,
                            volume = ?,
                            entry_price = ?,
                            exit_price = ?,
                            open_time = COALESCE(?, open_time),
                            close_time = ?,
                            gross_profit = ?,
                            commission = ?,
                            swap = ?,
                            net_profit = ?,
                            status = 'CLOSED',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            deal_ticket,
                            pos_id,
                            d["symbol"],
                            d["side"],
                            d["volume"],
                            d["entry_price"],
                            d["exit_price"],
                            d.get("open_time"),
                            d["close_time"],
                            d["gross_profit"],
                            d["commission"],
                            d["swap"],
                            d["net_profit"],
                            now,
                            existing["id"],
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO trade_logs (
                            mt5_deal_ticket, mt5_position_id, symbol, side, volume,
                            entry_price, exit_price, open_time, close_time,
                            gross_profit, commission, swap, net_profit, status,
                            strategy_tag, notes, source, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?, ?, ?, ?, ?)
                        """,
                        (
                            deal_ticket,
                            pos_id,
                            d["symbol"],
                            d["side"],
                            d["volume"],
                            d["entry_price"],
                            d["exit_price"],
                            d.get("open_time"),
                            d["close_time"],
                            d["gross_profit"],
                            d["commission"],
                            d["swap"],
                            d["net_profit"],
                            d.get("strategy_tag", ""),
                            d.get("notes", ""),
                            d.get("source", "MT5_SYNC"),
                            now,
                            now,
                        ),
                    )
                    inserted += 1

    return {"inserted": inserted, "updated": updated, "total": len(deals)}


def list_trade_logs(
    status: str | None = None,
    side: str | None = None,
    search: str | None = None,
    limit: int = 200,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Query trade logs with optional status, side, and keyword filtering."""
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        clauses.append("UPPER(status) = ?")
        params.append(status.upper())
    if side:
        clauses.append("UPPER(side) LIKE ?")
        params.append(f"{side.upper()}%")
    if search:
        clauses.append("(LOWER(symbol) LIKE ? OR LOWER(notes) LIKE ? OR LOWER(strategy_tag) LIKE ?)")
        q = f"%{search.lower()}%"
        params.extend([q, q, q])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM trade_logs {where_sql} ORDER BY COALESCE(close_time, created_at) DESC, id DESC LIMIT ?"
    params.append(limit)

    with _DB_LOCK:
        with get_connection(db_path) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return _rows_to_dicts(rows)


def update_trade_log_notes(
    log_id: int,
    strategy_tag: str | None,
    notes: str | None,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Update strategy tag and journal notes on a logged trade."""
    now = utc_now_iso()
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            existing = conn.execute("SELECT * FROM trade_logs WHERE id = ?", (log_id,)).fetchone()
            if not existing:
                return None

            new_tag = existing["strategy_tag"] if strategy_tag is None else strategy_tag
            new_notes = existing["notes"] if notes is None else notes
            conn.execute(
                "UPDATE trade_logs SET strategy_tag = ?, notes = ?, updated_at = ? WHERE id = ?",
                (new_tag, new_notes, now, log_id),
            )
            row = conn.execute("SELECT * FROM trade_logs WHERE id = ?", (log_id,)).fetchone()
            return dict(row) if row else None


def record_equity_snapshot(
    balance: float,
    equity: float,
    floating_pnl: float,
    margin_free: float,
    min_interval_sec: int = 300,
    db_path: Path = DB_PATH,
) -> bool:
    """Persist an equity snapshot if min_interval_sec has elapsed since the previous one."""
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            if min_interval_sec > 0:
                last = conn.execute(
                    "SELECT recorded_at FROM equity_snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if last:
                    try:
                        last_dt = datetime.strptime(last["recorded_at"], "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                        if (now_dt - last_dt).total_seconds() < min_interval_sec:
                            return False
                    except ValueError:
                        pass

            conn.execute(
                """
                INSERT INTO equity_snapshots (recorded_at, balance, equity, floating_pnl, margin_free)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now_str, balance, equity, floating_pnl, margin_free),
            )
            return True


def export_trade_logs_csv(db_path: Path = DB_PATH) -> str:
    """Render all trade journal entries as a UTF-8 CSV string."""
    rows = list_trade_logs(limit=5000, db_path=db_path)
    buf = io.StringIO()
    fieldnames = [
        "id",
        "mt5_deal_ticket",
        "mt5_position_id",
        "proposal_id",
        "symbol",
        "side",
        "volume",
        "entry_price",
        "exit_price",
        "sl",
        "tp",
        "open_time",
        "close_time",
        "gross_profit",
        "commission",
        "swap",
        "net_profit",
        "status",
        "strategy_tag",
        "notes",
        "source",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) for k in fieldnames})
    return buf.getvalue()


def get_setting(key: str, default: Any = None, db_path: Path = DB_PATH) -> Any:
    """Read a JSON-encoded setting from app_settings."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return default


def set_setting(key: str, value: Any, db_path: Path = DB_PATH) -> None:
    """Persist a JSON-encoded setting into app_settings."""
    now = utc_now_iso()
    encoded = json.dumps(value, ensure_ascii=False)
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, encoded, now),
            )


def get_watchlist(db_path: Path = DB_PATH) -> list[str]:
    val = get_setting("watchlist", DEFAULT_WATCHLIST, db_path=db_path)
    if isinstance(val, list) and val:
        return [str(s).strip().upper() for s in val if str(s).strip()]
    return list(DEFAULT_WATCHLIST)


def set_watchlist(symbols: list[str], db_path: Path = DB_PATH) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        s = str(sym).strip().upper()
        if s and s not in seen:
            seen.add(s)
            clean.append(s)
    if not clean:
        clean = ["XAUUSD"]
    set_setting("watchlist", clean, db_path=db_path)
    return clean


def get_watchdog_config(db_path: Path = DB_PATH) -> dict[str, Any]:
    val = get_setting("watchdog_config", {}, db_path=db_path)
    cfg = dict(DEFAULT_WATCHDOG_CONFIG)
    if isinstance(val, dict):
        cfg.update(val)
    return cfg


def set_watchdog_config(patch: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    cfg = get_watchdog_config(db_path=db_path)
    for k, v in patch.items():
        if k in DEFAULT_WATCHDOG_CONFIG and v is not None:
            cfg[k] = v
    set_setting("watchdog_config", cfg, db_path=db_path)
    return cfg


def get_sheets_config(db_path: Path = DB_PATH) -> dict[str, Any]:
    default_cfg = {
        "enabled": bool(GOOGLE_SHEETS_WEBHOOK_URL or (GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEET_ID)),
        "webhook_url": GOOGLE_SHEETS_WEBHOOK_URL,
        "service_account_file": GOOGLE_SERVICE_ACCOUNT_FILE,
        "sheet_id": GOOGLE_SHEET_ID,
    }
    val = get_setting("sheets_config", {}, db_path=db_path)
    if isinstance(val, dict):
        default_cfg.update({k: v for k, v in val.items() if v is not None})
    return default_cfg


def set_sheets_config(patch: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    cfg = get_sheets_config(db_path=db_path)
    for k in ("enabled", "webhook_url", "service_account_file", "sheet_id"):
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    set_setting("sheets_config", cfg, db_path=db_path)
    return cfg


def get_position_manager_config(db_path: Path = DB_PATH) -> dict[str, Any]:
    val = get_setting("position_manager_config", {}, db_path=db_path)
    cfg = dict(DEFAULT_POSITION_MANAGER_CONFIG)
    if isinstance(val, dict):
        cfg.update({k: v for k, v in val.items() if k in DEFAULT_POSITION_MANAGER_CONFIG and v is not None})
    return cfg


def set_position_manager_config(patch: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    cfg = get_position_manager_config(db_path=db_path)
    for k, v in patch.items():
        if k in DEFAULT_POSITION_MANAGER_CONFIG and v is not None:
            cfg[k] = v
    set_setting("position_manager_config", cfg, db_path=db_path)
    return cfg


def get_discord_config(db_path: Path = DB_PATH) -> dict[str, Any]:
    val = get_setting("discord_config", {}, db_path=db_path)
    cfg = dict(DEFAULT_DISCORD_CONFIG)
    if isinstance(val, dict):
        cfg.update({k: v for k, v in val.items() if k in DEFAULT_DISCORD_CONFIG and v is not None})
    return cfg


def set_discord_config(patch: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    cfg = get_discord_config(db_path=db_path)
    for k, v in patch.items():
        if k in DEFAULT_DISCORD_CONFIG and v is not None:
            cfg[k] = v
    set_setting("discord_config", cfg, db_path=db_path)
    return cfg


def get_position_state(ticket: int, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT * FROM position_states WHERE ticket = ?", (ticket,)).fetchone()
            return dict(row) if row else None


def upsert_position_state(data: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    now = utc_now_iso()
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                INSERT INTO position_states (
                    ticket, symbol, side, initial_volume, entry_price,
                    initial_sl, initial_tp, risk_distance,
                    be_applied, partial_applied, trail_count, last_action, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket) DO UPDATE SET
                    be_applied = excluded.be_applied,
                    partial_applied = excluded.partial_applied,
                    trail_count = excluded.trail_count,
                    last_action = excluded.last_action,
                    risk_distance = CASE
                        WHEN position_states.risk_distance > 0 THEN position_states.risk_distance
                        ELSE excluded.risk_distance
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    int(data["ticket"]),
                    str(data["symbol"]),
                    str(data["side"]),
                    float(data["initial_volume"]),
                    float(data["entry_price"]),
                    data.get("initial_sl"),
                    data.get("initial_tp"),
                    float(data["risk_distance"]),
                    int(bool(data.get("be_applied", 0))),
                    int(bool(data.get("partial_applied", 0))),
                    int(data.get("trail_count", 0)),
                    str(data.get("last_action", "")),
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM position_states WHERE ticket = ?", (int(data["ticket"]),)).fetchone()
            return dict(row) if row else {}


def list_position_states(db_path: Path = DB_PATH) -> dict[int, dict[str, Any]]:
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM position_states").fetchall()
            return {int(r["ticket"]): dict(r) for r in rows}


def prune_position_states(active_tickets: set[int], db_path: Path = DB_PATH) -> None:
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            rows = conn.execute("SELECT ticket FROM position_states").fetchall()
            for r in rows:
                t = int(r["ticket"])
                if t not in active_tickets:
                    conn.execute("DELETE FROM position_states WHERE ticket = ?", (t,))


def add_system_log(
    level: str,
    category: str,
    message: str,
    symbol: str = "",
    details: dict[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Append a structured log entry for the live Web Console & Watchdog stream."""
    now = utc_now_iso()
    details_str = json.dumps(details or {}, ensure_ascii=False)
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO system_logs (created_at, level, category, symbol, message, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, level.upper(), category.upper(), symbol.upper(), message, details_str),
            )
            row = conn.execute("SELECT * FROM system_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
            item = dict(row) if row else {}
            try:
                item["details"] = json.loads(item.get("details_json") or "{}")
            except Exception:
                item["details"] = {}
            return item


def list_system_logs(
    category: str | None = None,
    level: str | None = None,
    limit: int = 120,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Query recent system/watchdog logs."""
    clauses: list[str] = []
    params: list[Any] = []
    if category:
        clauses.append("UPPER(category) = ?")
        params.append(category.upper())
    if level:
        clauses.append("UPPER(level) = ?")
        params.append(level.upper())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM system_logs {where_sql} ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                try:
                    item["details"] = json.loads(item.get("details_json") or "{}")
                except Exception:
                    item["details"] = {}
                out.append(item)
            return out


def get_latest_system_log_id(db_path: Path = DB_PATH) -> int:
    """Return the highest system_logs.id for lightweight WebSocket change detection."""
    with _DB_LOCK:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT MAX(id) AS max_id FROM system_logs").fetchone()
            return int(row["max_id"]) if row and row["max_id"] is not None else 0
