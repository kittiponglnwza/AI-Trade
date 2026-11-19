"""Confirmation-gated MT5 CLI with optional --propose bridge to SQLite/Web dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import create_execution_log, create_proposal, init_db, log_audit
from app.mt5_service import mt5_service


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Confirmation-gated MT5 trade CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show account status, open positions, and pending orders.")

    p_open = sub.add_parser("open", help="Dry-run check, queue proposal to Web UI, or confirm execution.")
    p_open.add_argument("--symbol", default="XAUUSD")
    p_open.add_argument("--side", required=True, choices=["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"])
    p_open.add_argument("--lots", type=float, default=None)
    p_open.add_argument("--risk-pct", type=float, default=None)
    p_open.add_argument("--price", type=float, default=None)
    p_open.add_argument("--sl", type=float, default=None)
    p_open.add_argument("--tp", type=float, default=None)
    p_open.add_argument("--timeframe", default="M15")
    p_open.add_argument("--rationale", default="")
    p_open.add_argument("--propose", action="store_true", help="Queue as PENDING proposal in SQLite for Web confirmation")
    p_open.add_argument("--confirm", action="store_true", help="Execute immediately in MT5")
    p_open.add_argument("--allow-real", action="store_true")

    p_close = sub.add_parser("close", help="Close open position or cancel pending order.")
    p_close.add_argument("--ticket", type=int, required=True)
    p_close.add_argument("--lots", type=float, default=None)
    p_close.add_argument("--confirm", action="store_true")
    p_close.add_argument("--allow-real", action="store_true")

    args = parser.parse_args()
    init_db()
    if not mt5_service.connect():
        raise RuntimeError("Failed to connect to MetaTrader 5 terminal.")

    try:
        if args.command == "status":
            acc = mt5_service.get_account_summary()
            print(f"Account: {acc['login']} ({acc['trade_mode']}) | Equity: {acc['equity']:,.2f} {acc['currency']}")
            print(f"Algo Trading: {'ON' if acc['terminal_trade_allowed'] else 'OFF'}")
            for p in mt5_service.get_open_positions():
                print(f"POS #{p['ticket']} {p['symbol']} {p['side']} {p['volume']} @ {p['price_open']} P/L={p['profit']:+.2f}")
            return 0

        if args.command == "open":
            checked = mt5_service.check_order(
                symbol=args.symbol,
                side=args.side,
                lots=args.lots,
                risk_pct=args.risk_pct,
                entry_price=args.price,
                sl=args.sl,
                tp=args.tp,
            )
            print("=== ORDER CHECK ===")
            print(checked)

            if args.propose:
                prop = create_proposal(
                    {
                        "source": "CLI",
                        "symbol": checked["symbol"],
                        "side": checked["side"],
                        "order_type": checked["order_type"],
                        "entry_price": checked["entry_price"],
                        "sl": checked["sl"],
                        "tp": checked["tp"],
                        "risk_pct": checked["est_risk_pct"] if args.risk_pct is None else args.risk_pct,
                        "lots": checked["lots"],
                        "est_risk_usd": checked["est_risk_usd"],
                        "est_reward_usd": checked["est_reward_usd"],
                        "rr_ratio": checked["rr_ratio"],
                        "rationale": args.rationale,
                        "timeframe": args.timeframe.upper(),
                    }
                )
                log_audit("PROPOSAL_CREATED", f"CLI queued Proposal #{prop['id']}", actor="CLI", payload=prop)
                print(f"Queued Proposal #{prop['id']} for Web confirmation.")
                return 0

            if not args.confirm:
                print("DRY RUN ONLY (--confirm not passed).")
                return 0

            res = mt5_service.send_order(
                symbol=args.symbol,
                side=args.side,
                lots=args.lots,
                risk_pct=args.risk_pct,
                entry_price=args.price,
                sl=args.sl,
                tp=args.tp,
                comment="CLI-Confirmed",
                allow_real=args.allow_real,
            )
            if res["success"]:
                create_execution_log(
                    {
                        "mt5_deal_ticket": res["deal_ticket"] or None,
                        "mt5_position_id": res["order_ticket"] or None,
                        "symbol": res["symbol"],
                        "side": res["side"],
                        "volume": res["exec_volume"],
                        "entry_price": res["exec_price"],
                        "sl": res["sl"],
                        "tp": res["tp"],
                        "status": "OPEN",
                        "strategy_tag": args.timeframe.upper(),
                        "notes": args.rationale,
                        "source": "CLI",
                    }
                )
            print("EXECUTION:", res)
            return 0 if res["success"] else 1

        if args.command == "close":
            if not args.confirm:
                print(f"DRY RUN: Would close ticket #{args.ticket}. Pass --confirm to execute.")
                return 0
            res = mt5_service.close_position(args.ticket, lots=args.lots, allow_real=args.allow_real)
            print("CLOSE RESULT:", res)
            return 0 if res["success"] else 1
    finally:
        mt5_service.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
