"""Continuous Google Sheets synchronization via Apps Script Webhook or Service Account."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import urllib.request

from app.analytics import compute_trading_stats
from app.database import (
    add_system_log,
    get_sheets_config,
    list_proposals,
    list_system_logs,
    list_trade_logs,
)
from app.supabase_sync import (
    sync_proposals_to_supabase,
    sync_settings_to_supabase,
    sync_system_logs_to_supabase,
    sync_trades_to_supabase,
)

TRADE_COLUMNS = [
    "id",
    "mt5_deal_ticket",
    "mt5_position_id",
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

PROPOSAL_COLUMNS = [
    "id",
    "created_at",
    "source",
    "symbol",
    "side",
    "entry_price",
    "sl",
    "tp",
    "lots",
    "risk_pct",
    "est_risk_usd",
    "rr_ratio",
    "status",
    "timeframe",
    "rationale",
    "exec_price",
    "exec_comment",
]


def _post_webhook(webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "MT5-Trading-Bridge/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace").strip()
    try:
        return json.loads(raw) if raw else {"ok": True, "status": resp.status}
    except Exception:
        return {"ok": True, "raw": raw[:200]}


def _service_account_append(
    sa_file: str,
    sheet_id: str,
    tab: str,
    rows: list[list[Any]],
    replace: bool = False,
) -> dict[str, Any]:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_path = Path(sa_file)
    if not creds_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_file}")

    creds = service_account.Credentials.from_service_account_file(
        str(creds_path),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet_api = service.spreadsheets().values()
    if replace:
        sheet_api.clear(spreadsheetId=sheet_id, range=f"{tab}!A2:Z").execute()
    res = sheet_api.append(
        spreadsheetId=sheet_id,
        range=f"{tab}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    return {"ok": True, "updates": res.get("updates", {})}


def _dispatch(tab: str, rows: list[list[Any]], action: str = "append") -> dict[str, Any]:
    cfg = get_sheets_config()
    if not cfg.get("enabled"):
        return {"skipped": True, "reason": "Google Sheets sync is disabled"}

    webhook_url = (cfg.get("webhook_url") or "").strip()
    sa_file = (cfg.get("service_account_file") or "").strip()
    sheet_id = (cfg.get("sheet_id") or "").strip()

    if webhook_url:
        return _post_webhook(
            webhook_url,
            {"action": action, "sheet": tab, "rows": rows},
        )
    if sa_file and sheet_id:
        return _service_account_append(
            sa_file,
            sheet_id,
            tab,
            rows,
            replace=(action == "replace"),
        )
    return {"skipped": True, "reason": "No Google Sheets Webhook URL or Service Account configured"}


def _trade_to_row(t: dict[str, Any]) -> list[Any]:
    return [t.get(col) if t.get(col) is not None else "" for col in TRADE_COLUMNS]


def _proposal_to_row(p: dict[str, Any]) -> list[Any]:
    return [p.get(col) if p.get(col) is not None else "" for col in PROPOSAL_COLUMNS]


def sync_trade_rows(trades: list[dict[str, Any]]) -> None:
    if not trades:
        return
    try:
        sync_trades_to_supabase(trades)
    except Exception:
        pass
    try:
        res = _dispatch("Trades", [_trade_to_row(t) for t in trades], action="append")
        if not res.get("skipped"):
            add_system_log("INFO", "SHEETS", f"Appended {len(trades)} trade(s) to Google Sheets")
    except Exception as exc:
        add_system_log("WARN", "SHEETS", f"Google Sheets trade sync failed: {exc}")


def sync_proposal_row(proposal: dict[str, Any]) -> None:
    try:
        sync_proposals_to_supabase([proposal])
    except Exception:
        pass
    try:
        res = _dispatch("Proposals", [_proposal_to_row(proposal)], action="append")
        if not res.get("skipped"):
            add_system_log(
                "INFO",
                "SHEETS",
                f"Synced Proposal #{proposal['id']} ({proposal['status']}) to Google Sheets",
                symbol=proposal.get("symbol", ""),
            )
    except Exception as exc:
        add_system_log("WARN", "SHEETS", f"Google Sheets proposal sync failed: {exc}")


def sync_watchdog_log_row(log_entry: dict[str, Any]) -> None:
    try:
        sync_system_logs_to_supabase([log_entry])
    except Exception:
        pass
    try:
        row = [
            log_entry.get("id", ""),
            log_entry.get("created_at", ""),
            log_entry.get("level", "INFO"),
            log_entry.get("category", "WATCHDOG"),
            log_entry.get("symbol", ""),
            log_entry.get("message", ""),
        ]
        _dispatch("WatchdogLogs", [row], action="append")
    except Exception:
        # Keep watchdog log streaming resilient without recursive log loops
        pass


def sync_stats_snapshot(stats: dict[str, Any]) -> None:
    try:
        sync_settings_to_supabase(stats=stats)
    except Exception:
        pass
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = [
            now,
            stats.get("total_trades", 0),
            stats.get("wins", 0),
            stats.get("losses", 0),
            stats.get("win_rate_pct", 0.0),
            stats.get("net_profit", 0.0),
            stats.get("profit_factor") if stats.get("profit_factor") is not None else "INF",
            stats.get("expectancy", 0.0),
            stats.get("max_drawdown_usd", 0.0),
            stats.get("max_drawdown_pct", 0.0),
        ]
        _dispatch("Stats", [row], action="append")
    except Exception as exc:
        add_system_log("WARN", "SHEETS", f"Google Sheets stats sync failed: {exc}")


def test_sheets_connection() -> dict[str, Any]:
    cfg = get_sheets_config()
    webhook_url = (cfg.get("webhook_url") or "").strip()
    sa_file = (cfg.get("service_account_file") or "").strip()
    sheet_id = (cfg.get("sheet_id") or "").strip()

    if webhook_url:
        res = _post_webhook(webhook_url, {"action": "ping"})
        add_system_log("INFO", "SHEETS", "Google Sheets webhook ping succeeded", details=res)
        return {"ok": True, "mode": "webhook", "response": res}

    if sa_file and sheet_id:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            sa_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        title = meta.get("properties", {}).get("title", sheet_id)
        add_system_log("INFO", "SHEETS", f"Connected to Google Sheet '{title}' via Service Account")
        return {"ok": True, "mode": "service_account", "spreadsheet": title}

    raise ValueError("กรุณากรอก Google Apps Script Webhook URL (หรือ Service Account + Sheet ID) ก่อนทดสอบ")


def sync_all_to_sheets(current_balance: float | None = None) -> dict[str, Any]:
    """Push full Trades, Proposals, WatchdogLogs, and Stats snapshot to Google Sheets."""
    cfg = get_sheets_config()
    if not cfg.get("enabled"):
        raise ValueError("Google Sheets sync is disabled in Settings.")

    trades = list_trade_logs(limit=1000)
    proposals = list_proposals(limit=200)
    sys_logs = list_system_logs(limit=200)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    stats = compute_trading_stats(closed, current_balance=current_balance)

    written: dict[str, int] = {}
    _dispatch("Trades", [_trade_to_row(t) for t in trades], action="replace")
    written["Trades"] = len(trades)

    _dispatch("Proposals", [_proposal_to_row(p) for p in proposals], action="replace")
    written["Proposals"] = len(proposals)

    log_rows = [
        [l.get("id"), l.get("created_at"), l.get("level"), l.get("category"), l.get("symbol"), l.get("message")]
        for l in sys_logs
    ]
    _dispatch("WatchdogLogs", log_rows, action="replace")
    written["WatchdogLogs"] = len(log_rows)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    stats_row = [
        now,
        stats.get("total_trades", 0),
        stats.get("wins", 0),
        stats.get("losses", 0),
        stats.get("win_rate_pct", 0.0),
        stats.get("net_profit", 0.0),
        stats.get("profit_factor") if stats.get("profit_factor") is not None else "INF",
        stats.get("expectancy", 0.0),
        stats.get("max_drawdown_usd", 0.0),
        stats.get("max_drawdown_pct", 0.0),
    ]
    _dispatch("Stats", [stats_row], action="append")
    written["Stats"] = 1

    add_system_log("INFO", "SHEETS", f"Full sync to Google Sheets completed: {written}")
    return {"ok": True, "written": written}
