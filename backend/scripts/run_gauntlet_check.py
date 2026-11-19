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

    # Gate 5: 9-Gate ML + News + Day-Trader Skill + 10,000-Replay Time Machine Gauntlet Evaluation
    gauntlet = http_json(
        "POST",
        f"{BASE}/api/gauntlet/evaluate",
        {
            "symbol": "XAUUSD",
            "tf": "M15",
            "risk_pct": 2.0,
            "min_confidence_pct": 75.0,
            "auto_queue": False,
        },
    )
    scanner_res = http_json("GET", f"{BASE}/api/scanner/watchlist?tf=M15")
    dt_rep = gauntlet.get("day_trader") or {}
    tm_rep = gauntlet.get("time_machine") or {}
    g5_ok = (
        gauntlet["total_gates"] == 9
        and len(gauntlet["gates"]) == 9
        and gauntlet["verdict"] in ("PASS", "WAIT", "REJECT")
        and len(gauntlet["mtf_snapshot"]) == 5
        and len(dt_rep.get("setups", [])) == 5
        and tm_rep.get("replays") == 10000
        and scanner_res.get("count", 0) >= 1
    )
    record(
        "G5_9GATE_GAUNTLET",
        g5_ok,
        (
            f"verdict={gauntlet['verdict']} {gauntlet['direction']} ({gauntlet['passed_count']}/9 PASS), "
            f"setup={dt_rep.get('active_setup')} ({dt_rep.get('entry_timer_state')}), "
            f"tm10k={tm_rep.get('verdict')} (TP:{tm_rep.get('target_first_pct')}%/SL:{tm_rep.get('stop_first_pct')}%, EV:{tm_rep.get('expected_r')}R)"
        ),
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

    # Gate 11: Discord 1-Click Notify + Smart Position Manager + Risk Guard + Word-Boundary Sentiment
    from app.discord_notify import (
        build_proposal_discord_payload,
        sign_discord_action_token,
        verify_discord_action_token,
    )
    from app.news_service import _score_article
    from app.position_manager import evaluate_position_plan

    pm_status = http_json("GET", f"{BASE}/api/position-manager/status")
    pm_cycle = http_json("POST", f"{BASE}/api/position-manager/run", api_key=API_KEY)
    discord_cfg = http_json("GET", f"{BASE}/api/discord/config", api_key=API_KEY)
    risk_st = http_json("GET", f"{BASE}/api/risk-status")
    stats_res = http_json("GET", f"{BASE}/api/stats")

    # Verify unauthenticated GET /api/discord/config is blocked with 401
    unauth_blocked = False
    try:
        http_json("GET", f"{BASE}/api/discord/config")
    except urllib.error.HTTPError as exc:
        unauth_blocked = exc.code == 401

    # Verify word-boundary regex does NOT false-match 'again'/'against' as 'gain' or 'commission' as 'miss'
    false_tag, false_score, false_matched, _ = _score_article(
        "Traders again stand against high commission waterfall",
        "Followers watch unbeatable levels",
    )

    # Test Discord HMAC & Embed builder
    sample_prop = {
        "id": 999,
        "symbol": "XAUUSD",
        "side": "BUY",
        "lots": 0.02,
        "entry_price": 3700.0,
        "sl": 3690.0,
        "tp": 3720.0,
        "rr_ratio": 2.0,
        "est_risk_usd": 20.0,
        "timeframe": "M15",
        "gauntlet": {"confidence_pct": 82.5, "passed_count": 9, "total_gates": 9, "ml": {"top_features": []}},
        "news": [],
    }
    tok_confirm = sign_discord_action_token(999, "confirm")
    embed_payload = build_proposal_discord_payload(sample_prop, public_base_url=TUNNEL_BASE)
    embed_desc = embed_payload["embeds"][0]["description"]

    # Test Smart Position Manager math: +1.1R triggers Auto-BE; +1.6R triggers 50% Partial + Trailing SL
    mock_quote = {"bid": 3711.0, "ask": 3711.2, "point": 0.01, "digits": 2, "stops_level_price": 0.5, "volume_min": 0.01, "volume_step": 0.01}
    mock_pos_1r = {"ticket": 1, "symbol": "XAUUSD", "side": "BUY", "volume": 0.04, "price_open": 3700.0, "price_current": 3711.0, "sl": 3690.0, "tp": 3725.0}
    mock_state_0 = {"risk_distance": 10.0, "be_applied": 0, "partial_applied": 0, "trail_count": 0}
    plan_1r = evaluate_position_plan(mock_pos_1r, mock_state_0, mock_quote, pm_status["config"])

    mock_quote_16r = {**mock_quote, "bid": 3716.0, "ask": 3716.2}
    mock_pos_16r = {**mock_pos_1r, "price_current": 3716.0, "sl": 3700.05}
    mock_state_1 = {"risk_distance": 10.0, "be_applied": 1, "partial_applied": 0, "trail_count": 0}
    plan_16r = evaluate_position_plan(mock_pos_16r, mock_state_1, mock_quote_16r, pm_status["config"])

    g11_features_ok = (
        pm_status.get("running") is True
        and pm_cycle["cycle"].get("mt5_connected") is True
        and "webhook_url" in discord_cfg
        and unauth_blocked is True
        and false_tag == "NEUTRAL"
        and false_score == 0.0
        and len(false_matched) == 0
        and "daily_total_pnl_pct" in risk_st
        and "open_risk_pct" in risk_st
        and verify_discord_action_token(999, "confirm", tok_confirm) is True
        and verify_discord_action_token(999, "confirm", "invalid-token") is False
        and "action=confirm" in embed_desc
        and "action=reject" in embed_desc
        and plan_1r["be_applied"] is True
        and plan_1r["new_sl"] == 3700.05
        and plan_16r["partial_close_lots"] == 0.02
        and plan_16r["trail_count"] == 1
        and plan_16r["new_sl"] == 3708.0
        and "by_actor" in stats_res
        and {"AUTOPILOT", "AI_CONFIRMED", "MANUAL"}.issubset(set(stats_res["by_actor"].keys()))
    )
    record(
        "G11_DISCORD_POS_MGR_AUTOPILOT",
        g11_features_ok,
        (
            f"pm_running={pm_status.get('running')}, unauth_401={unauth_blocked}, "
            f"regex_clean={len(false_matched)==0}, daily_pnl={risk_st['daily_total_pnl_pct']}%, "
            f"open_risk={risk_st['open_risk_pct']}%, be_sl={plan_1r['new_sl']}, trail_sl={plan_16r['new_sl']}"
        ),
    )

    # Gate 12: Cleanup temporary synthetic Sheets config/ping log rows & verify zero new orders
    with get_connection(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM system_logs WHERE category = 'SHEETS' AND (message LIKE '%webhook%' OR message LIKE '%Google Sheets%')"
        )
    snap_after = http_json("GET", f"{BASE}/api/market/snapshot?symbol=XAUUSD")
    g12_ok = len(snap_after["positions"]) == len(snap["positions"])
    record("G12_CLEANUP_AND_SAFETY", g12_ok, f"open_positions_unchanged={len(snap_after['positions'])}")

    failed = [r for r in results if not r[1]]
    print(f"\n=== GAUNTLET SUMMARY: {len(results) - len(failed)}/{len(results)} PASSED ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
