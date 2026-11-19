"""Discord Webhook notification service with signed 1-Click Confirm / Reject links."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import html
import json
from typing import Any
import urllib.error
import urllib.request

from app.config import API_KEY
from app.database import add_system_log, get_discord_config


def _secret_key() -> str:
    return API_KEY or "mt5-local-dev-key"


def sign_discord_action_token(proposal_id: int, action: str) -> str:
    """Create an HMAC-SHA256 signature for 1-click proposal confirmation/rejection."""
    msg = f"{int(proposal_id)}:{action.strip().lower()}".encode("utf-8")
    return hmac.new(_secret_key().encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]


def verify_discord_action_token(proposal_id: int, action: str, token: str) -> bool:
    """Constant-time verification of a Discord action token."""
    expected = sign_discord_action_token(proposal_id, action)
    return hmac.compare_digest(expected, (token or "").strip())


def build_discord_action_urls(proposal_id: int, public_base_url: str | None = None) -> dict[str, str]:
    cfg = get_discord_config()
    base = (public_base_url or cfg.get("public_base_url") or "http://localhost:8000").strip().rstrip("/")
    c_tok = sign_discord_action_token(proposal_id, "confirm")
    r_tok = sign_discord_action_token(proposal_id, "reject")
    return {
        "confirm_url": f"{base}/api/discord/action?proposal_id={proposal_id}&action=confirm&token={c_tok}",
        "reject_url": f"{base}/api/discord/action?proposal_id={proposal_id}&action=reject&token={r_tok}",
    }


def send_discord_webhook(payload: dict[str, Any], webhook_url_override: str | None = None) -> dict[str, Any]:
    """Post a JSON payload to the configured Discord Webhook URL."""
    cfg = get_discord_config()
    url = (webhook_url_override or cfg.get("webhook_url") or "").strip()
    if not url:
        raise ValueError("ยังไม่ได้ใส่ Discord Webhook URL ในหน้า Settings")
    if not (url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")):
        raise ValueError("Discord Webhook URL ต้องขึ้นต้นด้วย https://discord.com/api/webhooks/...")

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MT5-AI-Trading-Desk/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            status = int(resp.status)
            return {"ok": 200 <= status < 300, "status": status}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Discord HTTP {exc.code}: {err_body}") from exc
    except Exception as exc:
        raise RuntimeError(f"ส่งเข้า Discord ไม่สำเร็จ: {exc}") from exc


def build_proposal_discord_payload(proposal: dict[str, Any], public_base_url: str | None = None) -> dict[str, Any]:
    """Build a Discord Rich Embed payload for a newly queued trade proposal with 1-click links."""
    pid = int(proposal["id"])
    side = str(proposal["side"])
    symbol = str(proposal["symbol"])
    lots = proposal.get("lots", 0.01)
    entry = proposal.get("entry_price")
    sl = proposal.get("sl")
    tp = proposal.get("tp")
    rr = proposal.get("rr_ratio")
    risk_usd = proposal.get("est_risk_usd", 0.0)
    tf = proposal.get("timeframe", "M15")

    gauntlet = proposal.get("gauntlet") or {}
    conf_pct = gauntlet.get("confidence_pct")
    passed = gauntlet.get("passed_count", 9)
    total = gauntlet.get("total_gates", 9)
    ml_info = gauntlet.get("ml") or {}
    top_features = ml_info.get("top_features") or []

    shap_txt = ", ".join(
        f"`{f.get('feature')}` ({'+' if f.get('shap_value', 0) >= 0 else ''}{f.get('shap_value', 0):.2f})"
        for f in top_features[:3]
    ) or "LightGBM Walk-Forward"

    news_list = proposal.get("news") or []
    if news_list:
        top_n = news_list[0]
        news_txt = f"[{top_n.get('title', 'News')[:80]}]({top_n.get('url', '')}) (`{top_n.get('sentiment_tag', 'NEUTRAL')}`)"
    else:
        news_txt = "No high-impact news conflict"

    urls = build_discord_action_urls(pid, public_base_url=public_base_url)
    is_buy = side.upper().startswith("BUY")
    color = 0x3FB950 if is_buy else 0xF14C4C

    conf_str = f"**{float(conf_pct):.1f}%** (Gauntlet {passed}/{total})" if conf_pct is not None else f"Gauntlet {passed}/{total}"

    embed = {
        "title": f"🎯 [AI รอยืนยัน #{pid}] {side} {lots} {symbol} @ {entry}",
        "description": (
            f"ผ่านด่าน **9-Gate ML + News Gauntlet** เรียบร้อย\n"
            f"⚡ **[✅ กดยืนยันยิงเข้า MT5 (1-Click Confirm)]({urls['confirm_url']})**   |   "
            f"**[❌ กดข้ามไม้นี้ (Reject)]({urls['reject_url']})**"
        ),
        "color": color,
        "fields": [
            {"name": "Symbol / TF", "value": f"`{symbol}` (`{tf}`)", "inline": True},
            {"name": "Side / Volume", "value": f"**{side}** · `{lots}` Lot", "inline": True},
            {"name": "ML + News Confidence", "value": conf_str, "inline": True},
            {
                "name": "Entry / SL / TP",
                "value": f"Entry: `{entry}` | SL: `{sl if sl is not None else '-'}` | TP: `{tp if tp is not None else '-'}`",
                "inline": False,
            },
            {
                "name": "Risk / R:R",
                "value": f"Risk: `${float(risk_usd):.2f}` · R:R `1:{rr if rr is not None else '-'}`",
                "inline": True,
            },
            {"name": "Top TreeSHAP Drivers", "value": shap_txt, "inline": False},
            {"name": "Live News Reference", "value": news_txt, "inline": False},
        ],
        "footer": {"text": f"MT5 AI Trading Desk · Proposal #{pid} · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"},
    }
    return {
        "username": "MT5 AI Trading Desk",
        "embeds": [embed],
    }


def notify_discord_proposal(proposal: dict[str, Any]) -> bool:
    """Send Discord alert for a new PENDING proposal if Discord notifications are enabled."""
    cfg = get_discord_config()
    if not cfg.get("enabled") or not cfg.get("notify_proposals", True) or not cfg.get("webhook_url"):
        return False
    try:
        payload = build_proposal_discord_payload(proposal)
        send_discord_webhook(payload)
        return True
    except Exception as exc:
        add_system_log("WARN", "DISCORD", f"Discord proposal notify warning: {exc}", symbol=str(proposal.get("symbol", "")))
        return False


def notify_discord_autopilot(proposal: dict[str, Any], exec_res: dict[str, Any]) -> bool:
    """Send Discord alert when Auto-Pilot automatically executes a high-conviction DEMO trade."""
    cfg = get_discord_config()
    if not cfg.get("enabled") or not cfg.get("notify_autopilot", True) or not cfg.get("webhook_url"):
        return False
    try:
        gauntlet = proposal.get("gauntlet") or {}
        conf_pct = gauntlet.get("confidence_pct")
        conf_str = f"{float(conf_pct):.1f}%" if conf_pct is not None else "≥80%"
        embed = {
            "title": f"🤖 [AUTO-PILOT DEMO ยิงออเดอร์แล้ว] {proposal['side']} {exec_res.get('exec_volume', proposal['lots'])} {proposal['symbol']}",
            "description": (
                f"โหมด **Auto-Pilot Demo** ยิงไม้เข้า MT5 อัตโนมัติเพราะความมั่นใจ **{conf_str}** ผ่านครบ 9 ด่าน\n"
                f"Ticket: `#{exec_res.get('order_ticket')}` · ราคาเข้าจริง: `{exec_res.get('exec_price')}`"
            ),
            "color": 0x007ACC,
            "fields": [
                {"name": "Symbol / TF", "value": f"`{proposal['symbol']}` (`{proposal.get('timeframe', 'M15')}`)", "inline": True},
                {"name": "SL / TP", "value": f"SL: `{proposal.get('sl')}` | TP: `{proposal.get('tp')}`", "inline": True},
                {"name": "ML + News Conf", "value": f"**{conf_str}**", "inline": True},
            ],
            "footer": {"text": f"MT5 AI Auto-Pilot (DEMO) · Proposal #{proposal['id']}"},
        }
        send_discord_webhook({"username": "MT5 AI Auto-Pilot", "embeds": [embed]})
        return True
    except Exception as exc:
        add_system_log("WARN", "DISCORD", f"Discord autopilot notify warning: {exc}", symbol=str(proposal.get("symbol", "")))
        return False


def notify_discord_position_action(
    ticket: int,
    symbol: str,
    side: str,
    action_title: str,
    detail: str,
) -> bool:
    """Send Discord alert when Smart Position Manager moves SL to BE, partial closes, or trails SL."""
    cfg = get_discord_config()
    if not cfg.get("enabled") or not cfg.get("notify_position_manager", True) or not cfg.get("webhook_url"):
        return False
    try:
        embed = {
            "title": f"🛡️ [Smart Position Manager] #{ticket} · {side} {symbol} — {action_title}",
            "description": detail,
            "color": 0x4EC9B0,
            "footer": {"text": f"MT5 Smart Position Manager · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"},
        }
        send_discord_webhook({"username": "MT5 Position Guard", "embeds": [embed]})
        return True
    except Exception as exc:
        add_system_log("WARN", "DISCORD", f"Discord position notify warning: {exc}", symbol=symbol)
        return False


def notify_discord_execution_result(proposal: dict[str, Any], action: str, detail: str) -> bool:
    """Send a follow-up Discord message when a proposal is confirmed or rejected via 1-Click link."""
    cfg = get_discord_config()
    if not cfg.get("enabled") or not cfg.get("webhook_url"):
        return False
    try:
        is_confirm = action == "confirm"
        embed = {
            "title": (
                f"✅ [ยืนยันยิงออเดอร์แล้ว] Proposal #{proposal['id']} ({proposal['side']} {proposal['symbol']})"
                if is_confirm
                else f"❌ [ปฏิเสธแผนเทรดแล้ว] Proposal #{proposal['id']} ({proposal['side']} {proposal['symbol']})"
            ),
            "description": detail,
            "color": 0x3FB950 if is_confirm else 0x858585,
        }
        send_discord_webhook({"username": "MT5 AI Trading Desk", "embeds": [embed]})
        return True
    except Exception:
        return False


def notify_discord_trade_closed(
    trade: dict[str, Any],
    current_balance: float | None = None,
    stats: dict[str, Any] | None = None,
) -> bool:
    """Send a Discord Rich Embed summary when a trade finishes/closes (TP, SL, or Manual Close)."""
    cfg = get_discord_config()
    if not cfg.get("enabled") or not cfg.get("webhook_url"):
        return False
    try:
        net = float(trade.get("net_profit") or 0.0)
        is_win = net >= 0
        symbol = str(trade.get("symbol") or "XAUUSD")
        side = str(trade.get("side") or "BUY")
        vol = float(trade.get("volume") or 0.01)
        entry = trade.get("entry_price")
        exit_p = trade.get("exit_price")
        pos_id = trade.get("mt5_position_id") or trade.get("mt5_deal_ticket") or trade.get("id")
        sign = "+" if net >= 0 else ""

        bal_txt = f"`${current_balance:,.2f}`" if current_balance is not None else "—"
        wr_txt = (
            f"`{stats['win_rate_pct']:.1f}%` ({stats['wins']}W/{stats['losses']}L · Net `{('+' if stats['net_profit']>=0 else '')}${stats['net_profit']:.2f}`)"
            if stats
            else "—"
        )

        embed = {
            "title": (
                f"🏆 [ปิดไม้กำไร WIN {sign}${net:.2f}] #{pos_id} · {side} {vol:.2f} {symbol}"
                if is_win
                else f"🛑 [ปิดไม้ขาดทุน LOSS {sign}${net:.2f}] #{pos_id} · {side} {vol:.2f} {symbol}"
            ),
            "description": f"ออเดอร์ `#{pos_id}` ({side} {vol:.2f} Lot `{symbol}`) จบไม้เรียบร้อยแล้ว",
            "color": 0x3FB950 if is_win else 0xF14C4C,
            "fields": [
                {"name": "Net P/L (กำไรสุทธิ)", "value": f"**{sign}${net:.2f}**", "inline": True},
                {"name": "Entry -> Exit", "value": f"`{entry}` -> `{exit_p}`", "inline": True},
                {"name": "ยอดพอร์ตล่าสุด (Balance)", "value": bal_txt, "inline": True},
                {"name": "สถิติรวมพอร์ต", "value": wr_txt, "inline": False},
            ],
            "footer": {
                "text": f"MT5 Trade Journal · Closed at {trade.get('close_time') or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            },
        }
        send_discord_webhook({"username": "MT5 Trade Journal", "embeds": [embed]})
        return True
    except Exception as exc:
        add_system_log("WARN", "DISCORD", f"Discord trade closed notify warning: {exc}", symbol=str(trade.get("symbol", "")))
        return False


def test_discord_connection(webhook_url: str | None = None, public_base_url: str | None = None) -> dict[str, Any]:
    """Send a test embed to verify the user's Discord Webhook URL."""
    cfg = get_discord_config()
    base = (public_base_url or cfg.get("public_base_url") or "http://localhost:8000").strip()
    embed = {
        "title": "⚡ เชื่อมต่อ MT5 AI Trading Desk เข้ากับ Discord สำเร็จ!",
        "description": (
            "ตั้งแต่นี้เมื่อ **24/7 Watchdog** เจอสัญญาณที่ผ่านครบ **9 ด่าน (ML + News ≥ 75%)**\n"
            "หรือ **Smart Position Manager** ขยับ SL บังทุน / แบ่งปิดกำไร ระบบจะเด้งแจ้งเตือนเข้าห้องนี้ทันที\n"
            f"🔗 Bridge URL สำหรับกดปุ่มยืนยัน: `{base}`"
        ),
        "color": 0x007ACC,
        "footer": {"text": f"MT5 AI Trading Desk · Test Ping · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"},
    }
    res = send_discord_webhook({"username": "MT5 AI Trading Desk", "embeds": [embed]}, webhook_url_override=webhook_url)
    return {"ok": res["ok"], "status": res["status"], "message": "ส่งข้อความทดสอบเข้าห้อง Discord สำเร็จ!"}


def render_discord_action_html(
    proposal: dict[str, Any] | None,
    action: str,
    token: str,
    executed: bool = False,
    result_ok: bool = False,
    result_message: str = "",
) -> str:
    """Render a mobile-first VS Code Dark HTML page for 1-click Discord Confirm/Reject."""
    if proposal is None:
        return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>MT5 AI Trading Desk</title></head>
        <body style="background:#181818;color:#e1e1e1;font-family:system-ui,sans-serif;padding:24px;text-align:center;">
        <div style="max-width:440px;margin:40px auto;background:#252526;border:1px solid #3c3c3c;border-radius:8px;padding:24px;">
        <h2 style="color:#f14c4c;margin-top:0;">ไม่พบแผนเทรดนี้</h2>
        <p style="color:#9d9d9d;font-size:14px;">Proposal อาจถูกลบหรือดำเนินการไปแล้ว</p>
        </div></body></html>"""

    pid = int(proposal["id"])
    sym = html.escape(str(proposal["symbol"]))
    side = html.escape(str(proposal["side"]))
    lots = html.escape(str(proposal["lots"]))
    entry = html.escape(str(proposal["entry_price"]))
    sl = html.escape(str(proposal.get("sl") or "-"))
    tp = html.escape(str(proposal.get("tp") or "-"))
    status = html.escape(str(proposal.get("status") or "PENDING"))
    gauntlet = proposal.get("gauntlet") or {}
    conf = gauntlet.get("confidence_pct")
    conf_str = f"{float(conf):.1f}%" if conf is not None else "N/A"
    is_confirm = action == "confirm"

    if executed or status != "PENDING":
        badge_color = "#3fb950" if (result_ok or status == "EXECUTED") else "#f14c4c"
        headline = result_message or f"Proposal #{pid} สถานะปัจจุบัน: {status}"
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Proposal #{pid} · MT5 AI Trading Desk</title></head>
        <body style="background:#181818;color:#e1e1e1;font-family:system-ui,-apple-system,sans-serif;padding:18px;margin:0;">
        <div style="max-width:460px;margin:28px auto;background:#252526;border:1px solid #3c3c3c;border-radius:8px;padding:22px;box-shadow:0 12px 32px rgba(0,0,0,0.45);">
          <div style="font-size:11px;color:#4fc1ff;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">MT5 AI Trading Desk · Discord Action</div>
          <h2 style="margin:8px 0 12px;font-size:18px;color:{badge_color};">{html.escape(headline)}</h2>
          <div style="background:#1e1e1e;border:1px solid #2b2b2b;border-radius:6px;padding:14px;font-family:Consolas,monospace;font-size:13px;line-height:1.7;">
            <div><strong>Proposal:</strong> #{pid} ({status})</div>
            <div><strong>Order:</strong> {side} {lots} Lot {sym} @ {entry}</div>
            <div><strong>SL / TP:</strong> {sl} / {tp}</div>
            <div><strong>ML + News Confidence:</strong> {conf_str}</div>
          </div>
        </div></body></html>"""

    btn_bg = "#238636" if is_confirm else "#c72e2e"
    btn_label = f"🚀 ยืนยันยิงออเดอร์ {side} {lots} {sym} เข้า MT5" if is_confirm else f"❌ ยืนยันปฏิเสธแผนเทรด #{pid}"
    alt_action = "reject" if is_confirm else "confirm"
    alt_token = sign_discord_action_token(pid, alt_action)
    alt_label = "หรือกดปฏิเสธไม้นี้แทน" if is_confirm else "หรือสลับไปกดยืนยันยิงออเดอร์"

    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Confirm Proposal #{pid} · MT5 AI Trading Desk</title></head>
    <body style="background:#181818;color:#e1e1e1;font-family:system-ui,-apple-system,sans-serif;padding:18px;margin:0;">
    <div style="max-width:460px;margin:24px auto;background:#252526;border:1px solid #3c3c3c;border-radius:8px;padding:22px;box-shadow:0 12px 32px rgba(0,0,0,0.45);">
      <div style="font-size:11px;color:#4fc1ff;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">MT5 AI Trading Desk · 1-Click Discord Control</div>
      <h2 style="margin:8px 0 14px;font-size:19px;color:#ffffff;">Proposal #{pid}: {side} {lots} {sym}</h2>
      <div style="background:#1e1e1e;border:1px solid #2b2b2b;border-radius:6px;padding:14px;font-family:Consolas,monospace;font-size:13px;line-height:1.75;margin-bottom:18px;">
        <div><strong>Entry Reference:</strong> {entry}</div>
        <div><strong>Stop Loss (SL):</strong> <span style="color:#f14c4c;">{sl}</span></div>
        <div><strong>Take Profit (TP):</strong> <span style="color:#3fb950;">{tp}</span></div>
        <div><strong>ML + News Confidence:</strong> <span style="color:#c586c0;font-weight:700;">{conf_str}</span></div>
      </div>
      <form method="POST" action="/api/discord/action" style="margin:0;">
        <input type="hidden" name="proposal_id" value="{pid}" />
        <input type="hidden" name="action" value="{html.escape(action)}" />
        <input type="hidden" name="token" value="{html.escape(token)}" />
        <button type="submit" style="width:100%;background:{btn_bg};color:#ffffff;border:none;border-radius:6px;padding:14px 16px;font-size:15px;font-weight:700;cursor:pointer;">
          {btn_label}
        </button>
      </form>
      <div style="margin-top:14px;text-align:center;">
        <a href="/api/discord/action?proposal_id={pid}&action={alt_action}&token={alt_token}" style="color:#9d9d9d;font-size:12px;text-decoration:underline;">
          {alt_label}
        </a>
      </div>
    </div></body></html>"""
