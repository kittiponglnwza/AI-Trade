"""10-Gate Engineering Gauntlet automated verification script for the live MT5 Bridge."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.request

import websockets

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import API_KEY
from app.database import DB_PATH, get_connection, get_sheets_config, init_db, list_proposals, set_sheets_config

BASE = "http://127.0.0.1:8000"
TUNNEL_BASE = "https://mod-brokers-invite-thus.trycloudflare.com"
TUNNEL_WSS = "wss://mod-brokers-invite-thus.trycloudflare.com/ws/live?symbol=NVDA&tf=M15"


def http_json(method: str, url: str, body: dict | None = None, api_key: str | None = None) -> dict:
    headers: dict[str, str] = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    results: list[tuple[str, bool, str]] = []

    def record(gate: str, ok: bool, detail: str) -> None:
        results.append((gate, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {gate}: {detail}")

    # Gate 1: DB migration & preservation
    init_db()
    with get_connection(DB_PATH) as conn:
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        prop_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(trade_proposals)").fetchall()
        }
    props = list_proposals()
    g1_ok = (
        {"system_logs", "app_settings", "trade_proposals", "trade_logs"}.issubset(tables)
        and {"gauntlet_json", "news_json"}.issubset(prop_cols)
        and len(props) >= 1
    )
    record("G1_DB_MIGRATION", g1_ok, f"tables={len(tables)}, prop_cols={len(prop_cols)}, existing_proposals={len(props)}")

    # Gate 2: Health & Live MT5 Quote
    health = http_json("GET", f"{BASE}/api/health")
    snap = http_json("GET", f"{BASE}/api/market/snapshot?symbol=XAUUSD")
    g2_ok = (
        health.get("mt5_connected") is True
        and health.get("trade_mode") == "DEMO"
        and snap["quote"]["bid"] > 0
        and isinstance(snap["positions"], list)
    )
    record(
        "G2_HEALTH_AND_QUOTE",
        g2_ok,
        f"bid={snap['quote']['bid']}, open_positions={len(snap['positions'])}, algo={snap['account']['terminal_trade_allowed']}",
    )

    # Gate 3: Multi-symbol search, Watchlist quotes, US Stock candles
    sym_search = http_json("GET", f"{BASE}/api/symbols?q=NVDA&limit=10")
    watchlist = http_json("GET", f"{BASE}/api/watchlist")
    nvda_candles = http_json("GET", f"{BASE}/api/candles?symbol=NVDA&tf=M15&bars=60")
    times = [c["time"] for c in nvda_candles["candles"]]
    g3_ok = (
        any(s["name"] == "NVDA" for s in sym_search["symbols"])
        and len(watchlist["symbols"]) >= 1
        and len(watchlist["quotes"]) == len(watchlist["symbols"])
        and len(times) == 60
        and times == sorted(set(times))
    )
    record(
        "G3_MULTI_SYMBOL_STOCKS",
        g3_ok,
        f"watchlist={len(watchlist['symbols'])}, nvda_bars={len(times)}, last_nvda_close={nvda_candles['candles'][-1]['close']}",
    )

    # Gate 4: Live RSS News & Clickable Citations (XAUUSD + NVDA)
    gold_news = http_json("GET", f"{BASE}/api/news?symbol=XAUUSD")
    nvda_news = http_json("GET", f"{BASE}/api/news?symbol=NVDA")
    g4_ok = (
        len(gold_news["articles"]) > 0
        and len(nvda_news["articles"]) > 0
        and all(a["url"].startswith("http") and a["title"] for a in gold_news["articles"])
        and all(a["url"].startswith("http") and a["title"] for a in nvda_news["articles"])
    )
    record(
        "G4_LIVE_NEWS_CITATIONS",
        g4_ok,
        f"XAUUSD={len(gold_news['articles'])} ({gold_news['sentiment']}), NVDA={len(nvda_news['articles'])} ({nvda_news['sentiment']})",
    )

    # Gate 5: 9-Gate ML + News Trading Gauntlet Evaluation (No auto_queue)
    gauntlet = http_json(
        "POST",
        f"{BASE}/api/gauntlet/evaluate",
        {
            "symbol": "XAUUSD",
            "tf": "M15",
            "risk_pct": 15.0,
            "min_confidence_pct": 75.0,
            "auto_queue": False,
        },
    )
    g5_ok = (
        gauntlet["total_gates"] == 9
        and len(gauntlet["gates"]) == 9
        and gauntlet["verdict"] in ("PASS", "WAIT", "REJECT")
        and len(gauntlet["mtf_snapshot"]) == 5
    )
    record(
        "G5_9GATE_GAUNTLET",
        g5_ok,
        f"verdict={gauntlet['verdict']} {gauntlet['direction']} ({gauntlet['passed_count']}/9 PASS)",
    )

    # Gate 6: Real MT5 Historical Backtest (600 bars)
    bt = http_json("GET", f"{BASE}/api/backtest?symbol=XAUUSD&tf=M15&bars=600")
    g6_ok = bt["bars_tested"] == 600 and "win_rate_pct" in bt and "net_r" in bt
    record(
        "G6_HISTORICAL_BACKTEST",
        g6_ok,
        f"bars={bt['bars_tested']}, trades={bt['total_trades']}, wr={bt['win_rate_pct']}%, net_r={bt['net_r']}R, max_dd={bt['max_drawdown_r']}R",
    )

    # Gate 7: 24/7 Watchdog Scan & Web System Logs
    wd_before = http_json("GET", f"{BASE}/api/watchdog/status")
    scan_res = http_json("POST", f"{BASE}/api/watchdog/scan?symbol=XAUUSD", api_key=API_KEY)
    sys_logs = http_json("GET", f"{BASE}/api/system-logs?limit=20")
    g7_ok = (
        wd_before["running"] is True
        and scan_res["scan"]["scanned"] >= 1
        and len(sys_logs["logs"]) >= 1
    )
    record(
        "G7_WATCHDOG_AND_LOGS",
        g7_ok,
        f"running={wd_before['running']}, scanned={scan_res['scan']['scanned']}, logs_count={len(sys_logs['logs'])}",
    )

    # Gate 8: Continuous Google Sheets Webhook Verification via Local Mock Receiver
    orig_sheets = get_sheets_config()
    captured_payloads: list[dict] = []

    class MockSheetHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            captured_payloads.append(json.loads(raw))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), MockSheetHandler)
    port = server.server_address[1]
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    try:
        http_json(
            "PUT",
            f"{BASE}/api/sheets/config",
            {"enabled": True, "webhook_url": f"http://127.0.0.1:{port}/exec"},
            api_key=API_KEY,
        )
        ping_res = http_json("POST", f"{BASE}/api/sheets/test", api_key=API_KEY)
        sync_res = http_json("POST", f"{BASE}/api/sheets/sync-all", api_key=API_KEY)
        tabs_received = {p.get("sheet") for p in captured_payloads if p.get("sheet")}
        actions_received = {p.get("action") for p in captured_payloads}
        g8_ok = (
            ping_res.get("ok") is True
            and sync_res.get("ok") is True
            and "ping" in actions_received
            and {"Trades", "Proposals", "WatchdogLogs", "Stats"}.issubset(tabs_received)
        )
        record("G8_GOOGLE_SHEETS_SYNC", g8_ok, f"actions={actions_received}, tabs={sorted(tabs_received)}")
    finally:
        server.shutdown()
        server.server_close()
        set_sheets_config(orig_sheets)

    # Gate 9: Public Cloudflare Tunnel HTTPS + WSS Live Stream
    tunnel_health = http_json("GET", f"{TUNNEL_BASE}/api/health")

    async def check_wss() -> dict:
        async with websockets.connect(TUNNEL_WSS) as ws:
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

    ws_frame = asyncio.run(check_wss())
    g9_ok = (
        tunnel_health.get("mt5_connected") is True
        and ws_frame.get("mt5_connected") is True
        and "watchdog_running" in ws_frame
        and "latest_log_id" in ws_frame
    )
    record(
        "G9_PUBLIC_HTTPS_WSS",
        g9_ok,
        f"tunnel={tunnel_health['trade_mode']}, ws_symbol={ws_frame.get('symbol')}, watchdog_running={ws_frame.get('watchdog_running')}",
    )

    # Gate 10: LightGBM + Live News Fusion Training & >=75% Confidence Gate Enforcement
    train_res = http_json(
        "POST",
        f"{BASE}/api/ml/train",
        {"symbol": "XAUUSD", "tf": "M15", "bars": 10000},
        api_key=API_KEY,
    )
    ml_eval_75 = http_json(
        "POST",
        f"{BASE}/api/gauntlet/evaluate",
        {
            "symbol": "XAUUSD",
            "tf": "M15",
            "risk_pct": 15.0,
            "min_confidence_pct": 75.0,
            "auto_queue": False,
        },
    )
    ml_eval_95 = http_json(
        "POST",
        f"{BASE}/api/gauntlet/evaluate",
        {
            "symbol": "XAUUSD",
            "tf": "M15",
            "risk_pct": 15.0,
            "min_confidence_pct": 95.0,
            "auto_queue": False,
        },
    )
    ml_info = ml_eval_75.get("ml") or {}
    gate9_75 = next((g for g in ml_eval_75["gates"] if g["id"] == "G9_ML_NEWS_CONFIDENCE"), None)
    gate9_95 = next((g for g in ml_eval_95["gates"] if g["id"] == "G9_ML_NEWS_CONFIDENCE"), None)
    g10_ml_ok = (
        train_res.get("trained") is True
        and train_res["meta"]["bars_used"] >= 4000
        and gate9_75 is not None
        and len(ml_info.get("top_features", [])) >= 3
        and "news_adjustment_pct" in ml_info
        and gate9_95 is not None
        and gate9_95["status"] == "FAIL"
        and ml_eval_95["verdict"] != "PASS"
    )
    oos = train_res["meta"]["oos_summary"]
    record(
        "G10_ML_NEWS_CONFIDENCE_75",
        g10_ml_ok,
        (
            f"bars={train_res['meta']['bars_used']}, oos_auc=B:{oos['auc_buy']}/S:{oos['auc_sell']}, "
            f"oos_net={oos['net_r_combined']}R, live_conf={ml_info.get('final_confidence_pct')}% "
            f"(news_adj={ml_info.get('news_adjustment_pct'):+.1f}%, gate75={gate9_75['status'] if gate9_75 else None}, gate95={gate9_95['status'] if gate9_95 else None})"
        ),
    )

    # Gate 11: Cleanup temporary synthetic Sheets config/ping log rows & verify zero new orders
    with get_connection(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM system_logs WHERE category = 'SHEETS' AND (message LIKE '%webhook%' OR message LIKE '%Google Sheets%')"
        )
    snap_after = http_json("GET", f"{BASE}/api/market/snapshot?symbol=XAUUSD")
    g11_ok = len(snap_after["positions"]) == len(snap["positions"])
    record("G11_CLEANUP_AND_SAFETY", g11_ok, f"open_positions_unchanged={len(snap_after['positions'])}")

    failed = [r for r in results if not r[1]]
    print(f"\n=== GAUNTLET SUMMARY: {len(results) - len(failed)}/{len(results)} PASSED ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
