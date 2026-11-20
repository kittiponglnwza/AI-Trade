"""Thread-safe MetaTrader 5 bridge service for real-time quotes, analytics, and gated execution."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from app.config import (
    ALLOW_REAL_TRADING,
    DEFAULT_SYMBOL,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    TERMINAL_PATH,
)
from app.indicators import MTF_ORDER, TIMEFRAME_MAP, classify_trend, compute_indicators, safe_float

TRADE_MODE_MAP = {
    mt5.ACCOUNT_TRADE_MODE_DEMO: "DEMO",
    mt5.ACCOUNT_TRADE_MODE_CONTEST: "CONTEST",
    mt5.ACCOUNT_TRADE_MODE_REAL: "REAL",
}

SIDE_ORDER_TYPE_MAP = {
    "BUY": mt5.ORDER_TYPE_BUY,
    "SELL": mt5.ORDER_TYPE_SELL,
    "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
}


def is_buy_side(side: str) -> bool:
    side_u = side.upper()
    if side_u not in SIDE_ORDER_TYPE_MAP:
        raise ValueError(f"Unsupported side '{side}'.")
    return side_u.startswith("BUY")


class MT5BridgeService:
    """Single-lock thread-safe wrapper around MetaTrader 5 IPC calls."""

    def __init__(self, terminal_path: str = TERMINAL_PATH) -> None:
        self.terminal_path = terminal_path
        self._lock = threading.RLock()
        self._connected = False
        self._active_login: int | None = None
        self._last_connect_fail_mono: float = 0.0
        self._resolved_symbols: dict[str, str] = {}

    def _sync_active_account(self, acc: Any) -> None:
        login = int(acc.login)
        if self._active_login != login:
            self._active_login = login
            self._resolved_symbols.clear()

    def _is_terminal_running(self) -> bool:
        """Check whether terminal64.exe is already running so we never secretly spawn a hidden MT5 window."""
        exe_name = Path(self.terminal_path).name or "terminal64.exe"
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
                creationflags=creationflags,
            )
            return exe_name.lower() in out.lower()
        except Exception:
            return True

    def connect(self, force: bool = False) -> bool:
        """Attempt to initialize MT5 connection and verify an active logged-in account."""
        with self._lock:
            now = time.monotonic()
            if not force and self._last_connect_fail_mono > 0 and (now - self._last_connect_fail_mono) < 5.0:
                return False

            if not self._is_terminal_running():
                self._connected = False
                self._last_connect_fail_mono = time.monotonic()
                return False

            init_kwargs: dict[str, Any] = {"path": self.terminal_path, "timeout": 8000}
            if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
                init_kwargs["login"] = MT5_LOGIN
                init_kwargs["password"] = MT5_PASSWORD
                init_kwargs["server"] = MT5_SERVER

            ok = mt5.initialize(**init_kwargs)
            if not ok and MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
                ok = mt5.initialize(path=self.terminal_path, timeout=5000)
                if ok and mt5.account_info() is None:
                    mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER, timeout=8000)

            acc = mt5.account_info() if ok else None
            if not ok or acc is None:
                self._connected = False
                self._last_connect_fail_mono = time.monotonic()
                return False
            self._connected = True
            self._last_connect_fail_mono = 0.0
            self._sync_active_account(acc)
            return True

    def disconnect(self) -> None:
        """Shutdown MT5 connection."""
        with self._lock:
            mt5.shutdown()
            self._connected = False
            self._active_login = None
            self._resolved_symbols.clear()

    def ensure_connected(self) -> None:
        """Ensure MT5 is connected, attempting automatic reconnect if needed."""
        with self._lock:
            if self._connected:
                acc = mt5.account_info()
                if acc is not None:
                    self._sync_active_account(acc)
                    return
            if not self.connect():
                raise RuntimeError(
                    f"MetaTrader 5 is not connected or no account is logged in: {mt5.last_error()}"
                )

    def _broker_link_ok(self) -> bool:
        """True only if the terminal is actually connected to the broker server (not just IPC-attached)."""
        term = mt5.terminal_info()
        if term is not None and bool(term.connected):
            return True
        now = time.monotonic()
        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER and (now - self._last_connect_fail_mono) >= 10.0:
            relogged = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER, timeout=8000)
            if not relogged:
                self._last_connect_fail_mono = time.monotonic()
            term = mt5.terminal_info()
            return term is not None and bool(term.connected)
        return False

    def is_connected(self) -> bool:
        """Non-throwing connection status check (IPC attached AND broker link alive)."""
        with self._lock:
            if not self._connected:
                if not self.connect():
                    return False
            acc = mt5.account_info()
            if acc is None:
                if not self.connect():
                    return False
                acc = mt5.account_info()
                if acc is None:
                    return False
            self._sync_active_account(acc)
            return self._broker_link_ok()

    def _wait_for_tick(self, symbol: str, timeout: float = 0.6) -> Any:
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.bid > 0 and tick.ask > 0 and tick.time > 0:
            return tick
        if info is not None and info.bid > 0 and info.ask > 0 and info.time > 0:
            return tick if tick is not None and tick.bid > 0 else info

        deadline = time.monotonic() + timeout
        while tick is None or tick.bid <= 0 or tick.ask <= 0 or tick.time <= 0:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.08)
            tick = mt5.symbol_info_tick(symbol)
        return tick

    def resolve_symbol(self, preferred: str = DEFAULT_SYMBOL) -> str:
        """Resolve a tradable broker symbol matching preferred (e.g., XAUUSD / XAUUSDm / GOLD)."""
        with self._lock:
            self.ensure_connected()
            pref_clean = preferred.strip() or DEFAULT_SYMBOL

            cached = self._resolved_symbols.get(pref_clean.upper())
            if cached:
                info = mt5.symbol_info(cached)
                if (
                    info is not None
                    and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL
                    and mt5.symbol_select(cached, True)
                ):
                    tick = mt5.symbol_info_tick(cached)
                    if tick is not None and tick.bid > 0 and tick.ask > 0:
                        return cached

            exact = mt5.symbol_info(pref_clean)
            if exact is not None and exact.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                if mt5.symbol_select(exact.name, True):
                    self._wait_for_tick(exact.name)
                    self._resolved_symbols[pref_clean.upper()] = exact.name
                    return exact.name

            symbols = mt5.symbols_get()
            if not symbols:
                raise RuntimeError(f"Failed to list symbols from MT5: {mt5.last_error()}")

            pref_upper = pref_clean.upper()
            patterns = [
                re.compile(rf"^{re.escape(pref_upper)}$"),
                re.compile(rf"^{re.escape(pref_upper)}[#M]$"),
                re.compile(rf"^{re.escape(pref_upper)}CASH[#M]?$"),
                re.compile(rf"^{re.escape(pref_upper)}.*"),
                re.compile(rf".*{re.escape(pref_upper)}.*"),
            ]
            alias_patterns: dict[str, list[str]] = {
                "XAUUSD": [r"^XAUUSD[#M]?$", r"^GOLD[#M]?$", r"^XAUUSD.*", r".*XAUUSD.*", r"^GOLD.*", r".*XAU.*USD.*"],
                "XAGUSD": [r"^XAGUSD[#M]?$", r"^SILVER[#M]?$", r"^SILVER.*"],
                "USTEC": [r"^US100CASH[#M]?$", r"^NAS100[#M]?$", r"^US100.*", r"^NDX.*"],
                "US500": [r"^US500CASH[#M]?$", r"^SPX500.*", r"^US500.*"],
                "US30": [r"^US30CASH[#M]?$", r"^WS30.*", r"^US30.*"],
                "NVDA": [r"^NVIDIA[#M]?$"],
                "AAPL": [r"^APPLE[#M]?$"],
                "TSLA": [r"^TESLA[#M]?$"],
                "MSFT": [r"^MICROSOFT[#M]?$"],
            }
            for pat_str in alias_patterns.get(pref_upper, []):
                patterns.append(re.compile(pat_str))

            desc_ticker_pat = re.compile(rf"\({re.escape(pref_upper)}(?:\.[A-Z]+)?\)")

            candidates: list[tuple[int, str, Any]] = []
            seen: set[str] = set()
            for sym in symbols:
                sym_upper = sym.name.upper()
                matched = False
                for rank, pat in enumerate(patterns):
                    if pat.match(sym_upper):
                        if sym.name not in seen:
                            seen.add(sym.name)
                            candidates.append((rank, sym.name, sym))
                        matched = True
                        break
                if not matched and desc_ticker_pat.search((sym.description or "").upper()):
                    if sym.name not in seen:
                        seen.add(sym.name)
                        candidates.append((len(patterns), sym.name, sym))

            if not candidates:
                raise ValueError(f"No symbol matching '{preferred}' found in MT5.")

            candidates.sort(
                key=lambda item: (
                    0 if item[2].trade_mode == mt5.SYMBOL_TRADE_MODE_FULL else 1,
                    item[0],
                    0 if item[2].visible else 1,
                    len(item[1]),
                    item[1],
                )
            )

            for _, name, sym in candidates:
                if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED and mt5.symbol_select(name, True):
                    self._wait_for_tick(name)
                    self._resolved_symbols[pref_clean.upper()] = name
                    return name

            raise RuntimeError(f"Could not select candidate symbol '{candidates[0][1]}' in Market Watch.")

    @staticmethod
    def detect_filling_mode(sym: Any) -> int:
        mask = int(sym.filling_mode)
        if mask & 2:
            return mt5.ORDER_FILLING_IOC
        if mask & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    @staticmethod
    def normalize_volume(volume: float, sym: Any) -> float:
        step = Decimal(str(sym.volume_step))
        vol_min = Decimal(str(sym.volume_min))
        vol_max = Decimal(str(sym.volume_max))
        vol_dec = Decimal(str(max(volume, 0.0)))

        if step > 0:
            steps = (vol_dec / step).to_integral_value(rounding=ROUND_DOWN)
            quantized = Decimal(steps) * step
        else:
            quantized = vol_dec

        if quantized < vol_min:
            quantized = vol_min
        elif quantized > vol_max:
            quantized = vol_max
        return float(quantized)

    def get_account_summary(self) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            acc = mt5.account_info()
            term = mt5.terminal_info()
            if acc is None or term is None:
                raise RuntimeError(f"Failed to read MT5 account/terminal info: {mt5.last_error()}")

            return {
                "login": int(acc.login),
                "server": str(acc.server),
                "name": str(acc.name),
                "company": str(acc.company),
                "currency": str(acc.currency),
                "leverage": int(acc.leverage),
                "balance": round(float(acc.balance), 2),
                "equity": round(float(acc.equity), 2),
                "margin": round(float(acc.margin), 2),
                "margin_free": round(float(acc.margin_free), 2),
                "margin_level": round(float(acc.margin_level), 2),
                "profit": round(float(acc.profit), 2),
                "trade_mode": TRADE_MODE_MAP.get(acc.trade_mode, f"UNKNOWN({acc.trade_mode})"),
                "account_trade_allowed": bool(acc.trade_allowed),
                "terminal_trade_allowed": bool(term.trade_allowed),
                "connected": bool(term.connected),
            }

    def get_quote(self, symbol: str = DEFAULT_SYMBOL) -> dict[str, Any]:
        with self._lock:
            resolved = self.resolve_symbol(symbol)
            sym = mt5.symbol_info(resolved)
            tick = self._wait_for_tick(resolved, timeout=0.6)
            if sym is None:
                raise RuntimeError(f"Failed to read quote for {resolved}: {mt5.last_error()}")

            bid = float(tick.bid) if tick is not None and tick.bid > 0 else float(sym.bid)
            ask = float(tick.ask) if tick is not None and tick.ask > 0 else float(sym.ask)
            tick_epoch = int(tick.time) if tick is not None and tick.time > 0 else int(sym.time)

            if bid <= 0:
                rates = mt5.copy_rates_from_pos(resolved, mt5.TIMEFRAME_D1, 0, 1)
                if rates is not None and len(rates) > 0:
                    bid = float(rates[-1]["close"])
                    ask = bid
                    tick_epoch = int(rates[-1]["time"])

            spread_price = max(0.0, float(ask - bid))
            spread_points = round(spread_price / sym.point) if sym.point > 0 else 0
            server_dt = (
                datetime.fromtimestamp(tick_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if tick_epoch > 0
                else ""
            )
            return {
                "symbol": resolved,
                "description": str(sym.description or resolved),
                "category": str(sym.path.split("\\")[0] if sym.path else "Market"),
                "bid": round(bid, int(sym.digits)),
                "ask": round(ask, int(sym.digits)),
                "spread_price": round(spread_price, int(sym.digits)),
                "spread_points": int(spread_points),
                "digits": int(sym.digits),
                "point": float(sym.point),
                "contract_size": float(sym.trade_contract_size),
                "volume_min": float(sym.volume_min),
                "volume_max": float(sym.volume_max),
                "volume_step": float(sym.volume_step),
                "stops_level_points": int(sym.trade_stops_level),
                "stops_level_price": round(float(sym.trade_stops_level * sym.point), int(sym.digits)),
                "tick_epoch": tick_epoch,
                "tick_time_server": server_dt,
            }

    def get_open_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.ensure_connected()
            raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
            if raw is None:
                return []
            out: list[dict[str, Any]] = []
            for p in raw:
                out.append(
                    {
                        "ticket": int(p.ticket),
                        "symbol": str(p.symbol),
                        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                        "volume": float(p.volume),
                        "price_open": float(p.price_open),
                        "price_current": float(p.price_current),
                        "sl": float(p.sl),
                        "tp": float(p.tp),
                        "profit": round(float(p.profit), 2),
                        "swap": round(float(p.swap), 2),
                        "magic": int(p.magic),
                        "comment": str(p.comment),
                        "open_time": datetime.fromtimestamp(int(p.time), tz=timezone.utc).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
            return out

    def get_pending_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.ensure_connected()
            raw = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
            if raw is None:
                return []
            rev = {v: k for k, v in SIDE_ORDER_TYPE_MAP.items()}
            out: list[dict[str, Any]] = []
            for o in raw:
                out.append(
                    {
                        "ticket": int(o.ticket),
                        "symbol": str(o.symbol),
                        "side": rev.get(o.type, f"TYPE_{o.type}"),
                        "volume": float(o.volume_current),
                        "price_open": float(o.price_open),
                        "price_current": float(o.price_current),
                        "sl": float(o.sl),
                        "tp": float(o.tp),
                        "magic": int(o.magic),
                        "comment": str(o.comment),
                        "time_setup": datetime.fromtimestamp(int(o.time_setup), tz=timezone.utc).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
            return out

    def get_candles(self, symbol: str = DEFAULT_SYMBOL, tf: str = "M15", bars: int = 250) -> dict[str, Any]:
        """Return OHLC bars + indicators with strictly ascending unique integer epoch timestamps."""
        tf_upper = tf.upper()
        if tf_upper not in TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe '{tf}'. Valid: {list(TIMEFRAME_MAP)}")

        with self._lock:
            resolved = self.resolve_symbol(symbol)
            sym = mt5.symbol_info(resolved)
            digits = int(sym.digits) if sym else 2
            fetch_count = max(bars + 220, 450)
            rates = mt5.copy_rates_from_pos(resolved, TIMEFRAME_MAP[tf_upper], 0, fetch_count)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"Failed to fetch candles for {resolved} {tf_upper}: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
        df = compute_indicators(df)
        sliced = df.tail(bars).reset_index(drop=True)

        candles: list[dict[str, Any]] = []
        for _, row in sliced.iterrows():
            candles.append(
                {
                    "time": int(row["time"]),
                    "open": safe_float(row["open"], digits),
                    "high": safe_float(row["high"], digits),
                    "low": safe_float(row["low"], digits),
                    "close": safe_float(row["close"], digits),
                    "volume": int(row["tick_volume"]),
                    "ema20": safe_float(row["ema20"], digits),
                    "ema50": safe_float(row["ema50"], digits),
                    "ema200": safe_float(row["ema200"], digits),
                    "rsi14": safe_float(row["rsi14"], 2),
                    "atr14": safe_float(row["atr14"], digits),
                }
            )

        last_row = sliced.iloc[-1]
        return {
            "symbol": resolved,
            "tf": tf_upper,
            "digits": digits,
            "count": len(candles),
            "trend": classify_trend(last_row),
            "candles": candles,
        }

    def get_last_bar_fast(self, symbol: str = DEFAULT_SYMBOL, tf: str = "M15") -> dict[str, Any] | None:
        """Fetch only the latest bar directly from MT5 in <1ms without 450-bar Pandas recomputation."""
        tf_upper = tf.upper()
        if tf_upper not in TIMEFRAME_MAP:
            return None
        with self._lock:
            resolved = self.resolve_symbol(symbol)
            sym = mt5.symbol_info(resolved)
            digits = int(sym.digits) if sym else 2
            rates = mt5.copy_rates_from_pos(resolved, TIMEFRAME_MAP[tf_upper], 0, 2)
            if rates is None or len(rates) == 0:
                return None
            r = rates[-1]
            return {
                "time": int(r["time"]),
                "open": round(float(r["open"]), digits),
                "high": round(float(r["high"]), digits),
                "low": round(float(r["low"]), digits),
                "close": round(float(r["close"]), digits),
                "volume": int(r["tick_volume"]),
                "ema20": None,
                "ema50": None,
                "ema200": None,
                "rsi14": None,
                "atr14": None,
            }

    def get_reference_server_epoch(self) -> int:
        """Resolve a live 24/5 FX/Metal reference server clock across broker suffixes."""
        with self._lock:
            self.ensure_connected()
            best = 0
            for candidate in ("XAUUSD", "EURUSD", "USDJPY", "GBPUSD"):
                try:
                    resolved = self.resolve_symbol(candidate)
                    t = mt5.symbol_info_tick(resolved)
                    if t is not None and int(t.time) > best:
                        best = int(t.time)
                except Exception:
                    continue
            return best

    def get_mtf_summary(self, symbol: str = DEFAULT_SYMBOL) -> list[dict[str, Any]]:
        """Summarize D1, H4, H1, M15, M5 trend, EMA alignment, RSI, and ATR."""
        with self._lock:
            resolved = self.resolve_symbol(symbol)
            sym = mt5.symbol_info(resolved)
            digits = int(sym.digits) if sym else 2
            summary: list[dict[str, Any]] = []
            for tf_name in MTF_ORDER:
                rates = mt5.copy_rates_from_pos(resolved, TIMEFRAME_MAP[tf_name], 0, 260)
                if rates is None or len(rates) == 0:
                    continue
                df = pd.DataFrame(rates).drop_duplicates(subset=["time"]).sort_values("time")
                ind = compute_indicators(df)
                last = ind.iloc[-1]
                w20 = ind.tail(20)
                summary.append(
                    {
                        "tf": tf_name,
                        "time": int(last["time"]),
                        "close": safe_float(last["close"], digits),
                        "ema20": safe_float(last["ema20"], digits),
                        "ema50": safe_float(last["ema50"], digits),
                        "ema200": safe_float(last["ema200"], digits),
                        "rsi14": safe_float(last["rsi14"], 1),
                        "macd_hist": safe_float(last["macd_hist"], 3),
                        "atr14": safe_float(last["atr14"], digits),
                        "high20": safe_float(w20["high"].max(), digits),
                        "low20": safe_float(w20["low"].min(), digits),
                        "trend": classify_trend(last),
                    }
                )
            return summary

    def get_market_snapshot(self, symbol: str = DEFAULT_SYMBOL) -> dict[str, Any]:
        """Return combined account, quote, positions, pending orders, and MTF summary."""
        with self._lock:
            resolved = self.resolve_symbol(symbol)
            return {
                "account": self.get_account_summary(),
                "quote": self.get_quote(resolved),
                "positions": self.get_open_positions(),
                "orders": self.get_pending_orders(),
                "mtf": self.get_mtf_summary(resolved),
            }

    def calculate_lot_size(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        sl_price: float,
        risk_pct: float,
    ) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            sym = mt5.symbol_info(symbol)
            acc = mt5.account_info()
            if sym is None or acc is None:
                raise RuntimeError(f"Cannot load symbol or account info for {symbol}.")

            if entry_price <= 0 or sl_price <= 0:
                raise ValueError("entry_price and sl_price must be positive.")
            sl_distance = abs(entry_price - sl_price)
            if sl_distance <= 0:
                raise ValueError("Stop loss distance must be greater than zero.")

            capital = float(acc.equity)
            order_type = mt5.ORDER_TYPE_BUY if is_buy_side(side) else mt5.ORDER_TYPE_SELL

            profit_1lot = mt5.order_calc_profit(order_type, symbol, 1.0, float(entry_price), float(sl_price))
            if profit_1lot is not None and profit_1lot != 0:
                loss_per_lot = abs(float(profit_1lot))
            else:
                tick_val = sym.trade_tick_value_loss or sym.trade_tick_value
                loss_per_lot = (sl_distance / sym.trade_tick_size) * tick_val

            target_risk = capital * (risk_pct / 100.0)
            raw_lots = target_risk / loss_per_lot

            calc_margin_1lot = mt5.order_calc_margin(order_type, symbol, 1.0, float(entry_price))
            chk_1lot = mt5.order_check(
                {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": 1.0,
                    "type": order_type,
                    "price": float(entry_price),
                    "deviation": 30,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": self.detect_filling_mode(sym),
                }
            )
            chk_margin_1lot = float(chk_1lot.margin) if chk_1lot is not None and chk_1lot.margin > 0 else 0.0
            margin_1lot = max(float(calc_margin_1lot or 0.0), chk_margin_1lot)

            margin_free = float(acc.margin_free)
            margin_capped = False
            if margin_1lot > 0 and margin_free > 0:
                max_lots = (margin_free * 0.85) / margin_1lot
                if raw_lots > max_lots:
                    raw_lots = max_lots
                    margin_capped = True

            lots = self.normalize_volume(raw_lots, sym)
            actual_profit = mt5.order_calc_profit(order_type, symbol, lots, float(entry_price), float(sl_price))
            actual_risk = abs(float(actual_profit)) if actual_profit is not None else lots * loss_per_lot
            actual_risk_pct = (actual_risk / capital * 100.0) if capital > 0 else 0.0
            req_margin = lots * margin_1lot if margin_1lot > 0 else mt5.order_calc_margin(order_type, symbol, lots, float(entry_price))

            return {
                "lots": lots,
                "capital": round(capital, 2),
                "target_risk_amount": round(target_risk, 2),
                "actual_risk_amount": round(actual_risk, 2),
                "actual_risk_pct": round(actual_risk_pct, 2),
                "required_margin": round(float(req_margin), 2) if req_margin is not None else 0.0,
                "margin_capped": margin_capped,
            }

    @staticmethod
    def _validate_sl_tp(
        side: str,
        entry_price: float,
        sl: float | None,
        tp: float | None,
        sym: Any,
        tick: Any,
    ) -> None:
        buy = is_buy_side(side)
        min_dist = float(sym.trade_stops_level * sym.point)

        if sl is not None:
            if buy and sl >= entry_price:
                raise ValueError(f"SL ({sl}) must be below entry ({entry_price}) for {side}.")
            if not buy and sl <= entry_price:
                raise ValueError(f"SL ({sl}) must be above entry ({entry_price}) for {side}.")
            if min_dist > 0 and abs(entry_price - sl) < min_dist:
                raise ValueError(f"SL distance smaller than broker stops_level ({min_dist}).")

        if tp is not None:
            if buy and tp <= entry_price:
                raise ValueError(f"TP ({tp}) must be above entry ({entry_price}) for {side}.")
            if not buy and tp >= entry_price:
                raise ValueError(f"TP ({tp}) must be below entry ({entry_price}) for {side}.")
            if min_dist > 0 and abs(tp - entry_price) < min_dist:
                raise ValueError(f"TP distance smaller than broker stops_level ({min_dist}).")

        if side == "BUY_LIMIT" and entry_price >= tick.ask:
            raise ValueError(f"BUY_LIMIT entry ({entry_price}) must be below Ask ({tick.ask}).")
        if side == "SELL_LIMIT" and entry_price <= tick.bid:
            raise ValueError(f"SELL_LIMIT entry ({entry_price}) must be above Bid ({tick.bid}).")
        if side == "BUY_STOP" and entry_price <= tick.ask:
            raise ValueError(f"BUY_STOP entry ({entry_price}) must be above Ask ({tick.ask}).")
        if side == "SELL_STOP" and entry_price >= tick.bid:
            raise ValueError(f"SELL_STOP entry ({entry_price}) must be below Bid ({tick.bid}).")

    def _build_order_request(
        self,
        symbol: str,
        side: str,
        lots: float | None,
        risk_pct: float | None,
        entry_price: float | None,
        sl: float | None,
        tp: float | None,
        deviation: int = 30,
        comment: str = "Web-Confirmed",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resolved = self.resolve_symbol(symbol)
        sym = mt5.symbol_info(resolved)
        tick = self._wait_for_tick(resolved, timeout=1.5)
        acc = mt5.account_info()
        if sym is None or tick is None or acc is None:
            raise RuntimeError(f"Failed to read MT5 state for {resolved}.")

        side_u = side.upper()
        is_pending = side_u in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP")
        if is_pending:
            if entry_price is None:
                raise ValueError(f"entry_price is required for {side_u}.")
            resolved_entry = round(float(entry_price), int(sym.digits))
            action = mt5.TRADE_ACTION_PENDING
        else:
            resolved_entry = round(float(tick.ask if is_buy_side(side_u) else tick.bid), int(sym.digits))
            action = mt5.TRADE_ACTION_DEAL

        sl_val = round(float(sl), int(sym.digits)) if sl is not None else None
        tp_val = round(float(tp), int(sym.digits)) if tp is not None else None
        self._validate_sl_tp(side_u, resolved_entry, sl_val, tp_val, sym, tick)

        margin_capped = False
        if risk_pct is not None:
            if sl_val is None:
                raise ValueError("SL is required to calculate lot size from risk_pct.")
            sizing = self.calculate_lot_size(resolved, side_u, resolved_entry, sl_val, float(risk_pct))
            resolved_lots = sizing["lots"]
            margin_capped = sizing["margin_capped"]
        elif lots is not None:
            resolved_lots = self.normalize_volume(float(lots), sym)
        else:
            raise ValueError("Provide either lots or risk_pct.")

        base_type = mt5.ORDER_TYPE_BUY if is_buy_side(side_u) else mt5.ORDER_TYPE_SELL
        est_risk_usd = 0.0
        est_risk_pct = 0.0
        if sl_val is not None:
            sl_prof = mt5.order_calc_profit(base_type, resolved, resolved_lots, resolved_entry, sl_val)
            if sl_prof is not None:
                est_risk_usd = round(abs(float(sl_prof)), 2)
                if acc.equity > 0:
                    est_risk_pct = round((est_risk_usd / float(acc.equity)) * 100.0, 2)

        est_reward_usd = 0.0
        rr_ratio = None
        if tp_val is not None:
            tp_prof = mt5.order_calc_profit(base_type, resolved, resolved_lots, resolved_entry, tp_val)
            if tp_prof is not None:
                est_reward_usd = round(abs(float(tp_prof)), 2)
                if est_risk_usd > 0:
                    rr_ratio = round(est_reward_usd / est_risk_usd, 2)

        request: dict[str, Any] = {
            "action": action,
            "symbol": resolved,
            "volume": float(resolved_lots),
            "type": SIDE_ORDER_TYPE_MAP[side_u],
            "price": float(resolved_entry),
            "deviation": int(deviation),
            "magic": 202611,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self.detect_filling_mode(sym),
        }
        if sl_val is not None:
            request["sl"] = float(sl_val)
        if tp_val is not None:
            request["tp"] = float(tp_val)

        meta = {
            "symbol": resolved,
            "side": side_u,
            "order_type": "PENDING" if is_pending else "MARKET",
            "entry_price": resolved_entry,
            "sl": sl_val,
            "tp": tp_val,
            "lots": resolved_lots,
            "est_risk_usd": est_risk_usd,
            "est_risk_pct": est_risk_pct,
            "est_reward_usd": est_reward_usd,
            "rr_ratio": rr_ratio,
            "margin_capped": margin_capped,
        }
        return request, meta

    def check_order(
        self,
        symbol: str,
        side: str,
        lots: float | None = None,
        risk_pct: float | None = None,
        entry_price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        """Run dry-run mt5.order_check and return sizing/margin breakdown without sending."""
        with self._lock:
            self.ensure_connected()
            request, meta = self._build_order_request(
                symbol=symbol,
                side=side,
                lots=lots,
                risk_pct=risk_pct,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
            )
            check = mt5.order_check(request)
            if check is None:
                raise RuntimeError(f"mt5.order_check returned None: {mt5.last_error()}")

            return {
                **meta,
                "required_margin": round(float(check.margin), 2),
                "margin_free_after": round(float(check.margin_free), 2),
                "retcode": int(check.retcode),
                "comment": str(check.comment),
                "valid": int(check.retcode) == 0,
            }

    def _guard_execution_allowed(self, allow_real: bool) -> dict[str, Any]:
        acc = self.get_account_summary()
        if acc["trade_mode"] != "DEMO" and not (ALLOW_REAL_TRADING and allow_real):
            raise PermissionError(
                f"Execution blocked on '{acc['trade_mode']}' account. Enable ALLOW_REAL_TRADING=true and pass allow_real=true."
            )
        if not acc["terminal_trade_allowed"]:
            raise RuntimeError(
                "MT5 Terminal Algo Trading is OFF. Click 'Algo Trading' in MT5 toolbar before confirming."
            )
        if not acc["account_trade_allowed"]:
            raise RuntimeError("Trading is disabled on this MT5 account.")
        return acc

    def send_order(
        self,
        symbol: str,
        side: str,
        lots: float | None = None,
        risk_pct: float | None = None,
        entry_price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        deviation: int = 30,
        comment: str = "Web-Confirmed",
        allow_real: bool = False,
    ) -> dict[str, Any]:
        """Validate via order_check and execute order_send in MT5."""
        with self._lock:
            self._guard_execution_allowed(allow_real)
            request, meta = self._build_order_request(
                symbol=symbol,
                side=side,
                lots=lots,
                risk_pct=risk_pct,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                deviation=deviation,
                comment=comment,
            )
            check = mt5.order_check(request)
            if check is None or check.retcode != 0:
                msg = check.comment if check is not None else str(mt5.last_error())
                code = int(check.retcode) if check is not None else -1
                raise RuntimeError(f"order_check failed ({code}: {msg}).")

            result = mt5.order_send(request)
            if result is None:
                raise RuntimeError(f"mt5.order_send returned None: {mt5.last_error()}")

            success = result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
            return {
                **meta,
                "success": bool(success),
                "retcode": int(result.retcode),
                "comment": str(result.comment),
                "order_ticket": int(result.order),
                "deal_ticket": int(result.deal),
                "exec_price": float(result.price) if result.price else meta["entry_price"],
                "exec_volume": float(result.volume) if result.volume else meta["lots"],
            }

    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
        price_open: float | None = None,
        allow_real: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._guard_execution_allowed(allow_real)
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                sym = mt5.symbol_info(pos.symbol)
                tick = self._wait_for_tick(pos.symbol, timeout=1.5)
                if sym is None or tick is None:
                    raise RuntimeError(f"Cannot load symbol/tick for {pos.symbol}.")

                new_sl = round(float(sl), int(sym.digits)) if sl is not None else float(pos.sl)
                new_tp = round(float(tp), int(sym.digits)) if tp is not None else float(pos.tp)
                side = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                cur_ref = float(tick.bid if side == "BUY" else tick.ask)
                self._validate_sl_tp(
                    side,
                    cur_ref,
                    new_sl if new_sl > 0 else None,
                    new_tp if new_tp > 0 else None,
                    sym,
                    tick,
                )

                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": pos.symbol,
                    "position": int(pos.ticket),
                    "sl": new_sl,
                    "tp": new_tp,
                }
                check = mt5.order_check(request)
                if check is None or check.retcode != 0:
                    msg = check.comment if check is not None else str(mt5.last_error())
                    raise RuntimeError(f"modify order_check failed: {msg}")

                result = mt5.order_send(request)
                if result is None:
                    raise RuntimeError(f"mt5.order_send returned None: {mt5.last_error()}")

                return {
                    "ticket": int(pos.ticket),
                    "symbol": str(pos.symbol),
                    "sl": new_sl,
                    "tp": new_tp,
                    "success": result.retcode == mt5.TRADE_RETCODE_DONE,
                    "retcode": int(result.retcode),
                    "comment": str(result.comment),
                }

            orders = mt5.orders_get(ticket=ticket)
            if orders:
                ord_item = orders[0]
                sym = mt5.symbol_info(ord_item.symbol)
                if sym is None:
                    raise RuntimeError(f"Cannot load symbol for {ord_item.symbol}.")
                new_price = round(float(price_open), int(sym.digits)) if price_open is not None and price_open > 0 else float(ord_item.price_open)
                new_sl = round(float(sl), int(sym.digits)) if sl is not None else float(ord_item.sl)
                new_tp = round(float(tp), int(sym.digits)) if tp is not None else float(ord_item.tp)
                request = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": int(ord_item.ticket),
                    "symbol": ord_item.symbol,
                    "price": new_price,
                    "sl": new_sl,
                    "tp": new_tp,
                    "type_time": int(ord_item.type_time),
                }
                result = mt5.order_send(request)
                if result is None:
                    raise RuntimeError(f"mt5.order_send returned None: {mt5.last_error()}")
                return {
                    "ticket": int(ord_item.ticket),
                    "symbol": str(ord_item.symbol),
                    "price_open": new_price,
                    "sl": new_sl,
                    "tp": new_tp,
                    "success": result.retcode == mt5.TRADE_RETCODE_DONE,
                    "retcode": int(result.retcode),
                    "comment": str(result.comment),
                }

            raise ValueError(f"Open position or pending order #{ticket} not found.")

    def panic_close_all(self, allow_real: bool = False) -> dict[str, Any]:
        """Emergency 1-Click Kill-Switch: close all open positions and cancel all pending orders."""
        with self._lock:
            self._guard_execution_allowed(allow_real)
            positions = mt5.positions_get() or []
            orders = mt5.orders_get() or []
            closed_positions: list[dict[str, Any]] = []
            cancelled_orders: list[dict[str, Any]] = []
            errors: list[str] = []

            for pos in positions:
                try:
                    res = self.close_position(int(pos.ticket), None, 50, allow_real=allow_real)
                    closed_positions.append(res)
                except Exception as exc:
                    errors.append(f"Pos #{pos.ticket}: {exc}")

            for ord_item in orders:
                try:
                    res = self.close_position(int(ord_item.ticket), None, 50, allow_real=allow_real)
                    cancelled_orders.append(res)
                except Exception as exc:
                    errors.append(f"Ord #{ord_item.ticket}: {exc}")

            return {
                "closed_positions_count": len(closed_positions),
                "cancelled_orders_count": len(cancelled_orders),
                "closed_positions": closed_positions,
                "cancelled_orders": cancelled_orders,
                "errors": errors,
            }

    def get_portfolio_risk_status(self) -> dict[str, Any]:
        """Compute today's realized + floating PnL % and total combined open risk % across positions."""
        with self._lock:
            self.ensure_connected()
            acc = mt5.account_info()
            if acc is None:
                raise RuntimeError("Failed to read MT5 account info.")
            equity = float(acc.equity) if acc.equity > 0 else float(acc.balance or 1.0)
            floating_pnl = float(acc.profit)

            # Calculate today's realized closed PnL
            now_utc = datetime.now(timezone.utc)
            start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            deals = mt5.history_deals_get(start_of_day, now_utc + timedelta(hours=6)) or []
            daily_realized = 0.0
            for d in deals:
                if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT):
                    daily_realized += float(d.profit) + float(d.commission) + float(d.swap)

            daily_total_pnl = round(daily_realized + floating_pnl, 2)
            daily_total_pnl_pct = round((daily_total_pnl / equity) * 100.0, 2) if equity > 0 else 0.0

            # Calculate total open risk across all open positions
            positions = mt5.positions_get() or []
            open_risk_usd = 0.0
            for pos in positions:
                is_buy = pos.type == mt5.POSITION_TYPE_BUY
                order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                if pos.sl and pos.sl > 0:
                    # If SL is already locked in profit (BE or trailing), open downside risk is 0
                    if (is_buy and pos.sl >= pos.price_open) or (not is_buy and pos.sl <= pos.price_open):
                        continue
                    prof = mt5.order_calc_profit(order_type, pos.symbol, float(pos.volume), float(pos.price_open), float(pos.sl))
                    if prof is not None and prof < 0:
                        open_risk_usd += abs(float(prof))
                else:
                    # Fallback 1% price move risk estimate if no SL is set
                    fallback_sl = float(pos.price_open) * (0.99 if is_buy else 1.01)
                    prof = mt5.order_calc_profit(order_type, pos.symbol, float(pos.volume), float(pos.price_open), fallback_sl)
                    if prof is not None:
                        open_risk_usd += abs(float(prof))

            open_risk_usd = round(open_risk_usd, 2)
            open_risk_pct = round((open_risk_usd / equity) * 100.0, 2) if equity > 0 else 0.0

            return {
                "equity": round(equity, 2),
                "daily_realized_pnl_usd": round(daily_realized, 2),
                "floating_pnl_usd": round(floating_pnl, 2),
                "daily_total_pnl_usd": daily_total_pnl,
                "daily_total_pnl_pct": daily_total_pnl_pct,
                "open_positions_count": len(positions),
                "open_risk_usd": open_risk_usd,
                "open_risk_pct": open_risk_pct,
            }

    def close_position(
        self,
        ticket: int,
        lots: float | None = None,
        deviation: int = 30,
        allow_real: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._guard_execution_allowed(allow_real)
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                sym = mt5.symbol_info(pos.symbol)
                tick = self._wait_for_tick(pos.symbol, timeout=1.5)
                if sym is None or tick is None:
                    raise RuntimeError(f"Cannot load symbol/tick for {pos.symbol}.")

                is_buy = pos.type == mt5.POSITION_TYPE_BUY
                close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                close_price = float(tick.bid if is_buy else tick.ask)
                close_vol = (
                    min(self.normalize_volume(float(lots), sym), float(pos.volume))
                    if lots is not None
                    else float(pos.volume)
                )

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": close_vol,
                    "type": close_type,
                    "position": int(pos.ticket),
                    "price": close_price,
                    "deviation": int(deviation),
                    "magic": int(pos.magic),
                    "comment": "Web-Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": self.detect_filling_mode(sym),
                }
                check = mt5.order_check(request)
                if check is None or check.retcode != 0:
                    msg = check.comment if check is not None else str(mt5.last_error())
                    raise RuntimeError(f"close order_check failed: {msg}")

                result = mt5.order_send(request)
                if result is None:
                    raise RuntimeError(f"mt5.order_send returned None: {mt5.last_error()}")

                return {
                    "ticket": int(pos.ticket),
                    "symbol": str(pos.symbol),
                    "closed_volume": close_vol,
                    "close_price": float(result.price) if result.price else close_price,
                    "success": result.retcode == mt5.TRADE_RETCODE_DONE,
                    "retcode": int(result.retcode),
                    "comment": str(result.comment),
                    "deal_ticket": int(result.deal),
                }

            orders = mt5.orders_get(ticket=ticket)
            if orders:
                ord_item = orders[0]
                request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ord_item.ticket)}
                result = mt5.order_send(request)
                if result is None:
                    raise RuntimeError(f"mt5.order_send returned None: {mt5.last_error()}")
                return {
                    "ticket": int(ord_item.ticket),
                    "symbol": str(ord_item.symbol),
                    "success": result.retcode == mt5.TRADE_RETCODE_DONE,
                    "retcode": int(result.retcode),
                    "comment": str(result.comment),
                }

            raise ValueError(f"Position or pending order #{ticket} not found.")

    def fetch_closed_deals(self, days: int = 90) -> list[dict[str, Any]]:
        """Reconstruct closed round-trip trades from MT5 deal history grouped by position_id."""
        with self._lock:
            self.ensure_connected()
            open_pos_ids = {int(p.ticket) for p in (mt5.positions_get() or [])}
            now_utc = datetime.now(timezone.utc)
            date_from = now_utc - timedelta(days=days)
            date_to = now_utc + timedelta(days=1)
            deals = mt5.history_deals_get(date_from, date_to)
            if deals is None or len(deals) == 0:
                return []

        by_position: dict[int, list[Any]] = defaultdict(list)
        for d in deals:
            if d.position_id and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                by_position[int(d.position_id)].append(d)

        closed: list[dict[str, Any]] = []
        for pos_id, pos_deals in by_position.items():
            # Skip positions that are still open (e.g. after a 50% Partial Close)
            if pos_id in open_pos_ids:
                continue
            pos_deals.sort(key=lambda item: (int(item.time), int(item.ticket)))
            in_deals = [d for d in pos_deals if d.entry == mt5.DEAL_ENTRY_IN]
            out_deals = [
                d
                for d in pos_deals
                if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT)
            ]
            if not out_deals:
                continue

            ref_in = in_deals[0] if in_deals else pos_deals[0]
            side = "BUY" if ref_in.type == mt5.DEAL_TYPE_BUY else "SELL"

            in_vol = sum(float(d.volume) for d in in_deals) if in_deals else 0.0
            entry_price = (
                sum(float(d.price) * float(d.volume) for d in in_deals) / in_vol
                if in_vol > 0
                else float(ref_in.price)
            )

            out_vol = sum(float(d.volume) for d in out_deals)
            exit_price = (
                sum(float(d.price) * float(d.volume) for d in out_deals) / out_vol
                if out_vol > 0
                else float(out_deals[-1].price)
            )

            gross_profit = sum(float(d.profit) for d in pos_deals)
            commission = sum(float(d.commission) for d in pos_deals)
            swap = sum(float(d.swap) for d in pos_deals)
            net_profit = gross_profit + commission + swap

            open_ts = int(ref_in.time)
            close_ts = int(out_deals[-1].time)
            in_comment = str(getattr(ref_in, "comment", "") or "")
            out_comment = str(out_deals[-1].comment or "")
            in_comment_u = in_comment.upper()
            if in_comment_u.startswith("AUTOPILOT"):
                deal_source = "AUTOPILOT"
            elif in_comment_u.startswith("WATCHDOG"):
                deal_source = "WATCHDOG"
            elif in_comment_u.startswith("GAUNTLET"):
                deal_source = "GAUNTLET"
            elif in_comment_u.startswith("WEB"):
                deal_source = "WEB"
            else:
                deal_source = "MT5_SYNC"

            closed.append(
                {
                    "mt5_deal_ticket": int(out_deals[-1].ticket),
                    "mt5_position_id": pos_id,
                    "symbol": str(out_deals[-1].symbol),
                    "side": side,
                    "volume": round(out_vol, 2),
                    "entry_price": round(entry_price, 5),
                    "exit_price": round(exit_price, 5),
                    "open_time": datetime.fromtimestamp(open_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "close_time": datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "gross_profit": round(gross_profit, 2),
                    "commission": round(commission, 2),
                    "swap": round(swap, 2),
                    "net_profit": round(net_profit, 2),
                    "notes": f"{in_comment} {out_comment}".strip(),
                    "source": deal_source,
                }
            )

        closed.sort(key=lambda item: item["close_time"], reverse=True)
        return closed

    def search_symbols(
        self,
        query: str = "",
        category: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Search tradable MT5 symbols by ticker name, description, or category."""
        with self._lock:
            self.ensure_connected()
            symbols = mt5.symbols_get()
            if not symbols:
                return []

            q = query.strip().upper()
            cat_filter = category.strip().lower() if category else None
            matches: list[tuple[int, int, str, dict[str, Any]]] = []

            for s in symbols:
                if s.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                    continue
                root_cat = s.path.split("\\")[0] if s.path else "Other"
                if cat_filter and cat_filter != "all" and cat_filter not in root_cat.lower():
                    continue

                name_u = s.name.upper()
                desc_u = (s.description or "").upper()
                if q:
                    if name_u == q:
                        rank = 0
                    elif name_u.startswith(q):
                        rank = 1
                    elif q in name_u:
                        rank = 2
                    elif q in desc_u:
                        rank = 3
                    else:
                        continue
                else:
                    rank = 0 if s.visible else 1

                matches.append(
                    (
                        rank,
                        len(s.name),
                        s.name,
                        {
                            "name": str(s.name),
                            "description": str(s.description or s.name),
                            "category": root_cat,
                            "digits": int(s.digits),
                        },
                    )
                )

            matches.sort(key=lambda item: (item[0], item[1], item[2]))
            return [m[3] for m in matches[:limit]]

    def get_watchlist_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch fast live quotes, D1 % change, and market-open status for a watchlist."""
        with self._lock:
            self.ensure_connected()
            ref_epoch = self.get_reference_server_epoch()
            is_weekend = datetime.now(timezone.utc).weekday() in (5, 6)

            out: list[dict[str, Any]] = []
            for raw_sym in symbols:
                try:
                    quote = self.get_quote(raw_sym)
                    resolved = quote["symbol"]
                    rates = mt5.copy_rates_from_pos(resolved, mt5.TIMEFRAME_D1, 0, 2)
                    change_pct = 0.0
                    if rates is not None and len(rates) > 0:
                        d1_open = float(rates[-1]["open"])
                        ref_close = quote["bid"] if quote["bid"] > 0 else float(rates[-1]["close"])
                        if d1_open > 0:
                            change_pct = round(((ref_close - d1_open) / d1_open) * 100.0, 2)

                    tick_age = abs(ref_epoch - quote["tick_epoch"]) if ref_epoch > 0 and quote["tick_epoch"] > 0 else 0
                    market_open = (not is_weekend) and quote["tick_epoch"] > 0 and (ref_epoch == 0 or tick_age < 900)

                    out.append(
                        {
                            "symbol": raw_sym.upper(),
                            "resolved_symbol": resolved,
                            "description": quote["description"],
                            "category": quote["category"],
                            "bid": quote["bid"],
                            "ask": quote["ask"],
                            "digits": quote["digits"],
                            "spread_points": quote["spread_points"],
                            "change_pct": change_pct,
                            "market_open": market_open,
                            "tick_time_server": quote["tick_time_server"],
                        }
                    )
                except Exception as exc:
                    out.append(
                        {
                            "symbol": raw_sym,
                            "description": raw_sym,
                            "category": "Unavailable",
                            "bid": 0.0,
                            "ask": 0.0,
                            "digits": 2,
                            "spread_points": 0,
                            "change_pct": 0.0,
                            "market_open": False,
                            "error": str(exc),
                        }
                    )
            return out


mt5_service = MT5BridgeService()
