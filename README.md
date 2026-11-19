# XAUUSD AI Trading Desk — Real-Time MT5 Web Terminal

Full-stack real-time trading dashboard connecting **MetaTrader 5** (Windows) to a **React + TypeScript + Tailwind CSS** web interface with human-in-the-loop order confirmation, persistent SQLite trade journaling, and performance analytics.

## Architecture

```text
+-----------------------------------+       HTTPS / WSS Tunnel       +------------------------------------+
|  Frontend (Vercel / Local Vite)   |  <==========================>  |  Local Windows MT5 Bridge          |
|  React 19 + Tailwind v4           |   (cloudflared / localhost)    |  FastAPI + WebSocket + SQLite      |
|  TradingView Lightweight Charts   |   X-API-Key Protected          |  Thread-safe MetaTrader5 IPC Lock  |
+-----------------------------------+                                +------------------------------------+
                                                                                      ^
                                                                                      | IPC
                                                                                      v
                                                                     +------------------------------------+
                                                                     |  MetaTrader 5 Terminal (DEMO/LIVE) |
                                                                     +------------------------------------+
```

- **Why a local bridge?** MetaTrader 5's native Python API operates exclusively on Windows via local terminal IPC. Deploying the React frontend to **Vercel** lets you monitor charts, queue/confirm proposals, and review trade stats from anywhere while keeping MT5 execution secure on your Windows PC.

---

## Project Structure

```text
Trade/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI REST endpoints & /ws/live WebSocket stream
│   │   ├── mt5_service.py    # Thread-safe MT5 wrapper (quotes, candles, order_check, order_send, deals)
│   │   ├── database.py       # SQLite persistence (proposals, trade_logs, equity_snapshots, audit_events)
│   │   ├── analytics.py      # Win rate, profit factor, drawdown, expectancy, streaks, equity curve
│   │   ├── indicators.py     # EMA 20/50/200, Wilder RSI(14), MACD, ATR(14)
│   │   ├── schemas.py        # Pydantic v2 validation schemas
│   │   └── config.py         # .env configuration
│   ├── scripts/
│   │   ├── mt5_analyze.py    # CLI MTF analyzer + dark PNG chart renderer
│   │   └── mt5_trade.py      # CLI dry-run & --propose bridge to Web UI
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/       # HeaderBar, AccountKpiStrip, LiveChartPanel, OrderTicketPanel,
│   │   │                     # ProposalsQueue, PositionsTable, StatsDashboard, TradeLogTable, SettingsModal
│   │   ├── services/api.ts   # Typed REST & WebSocket client with auto-reconnect
│   │   └── types/trading.ts
│   ├── package.json
│   └── vercel.json
├── start_dev.ps1             # One-click local backend + frontend launcher
└── vercel.json               # Root Vercel monorepo build configuration
```

---

## Quickstart (Local Development)

1. Open **MetaTrader 5** on Windows and log in to your **DEMO** account (enable **Algo Trading** when ready to confirm orders).
2. Configure environment variables:
   ```powershell
   copy backend\.env.example backend\.env
   ```
   Edit `backend/.env` to set a strong `MT5_API_KEY`.
3. Install Python dependencies (if not already installed) and Node dependencies:
   ```powershell
   pip install -r backend\requirements.txt
   cd frontend && npm install
   ```
4. Launch both Backend (`:8000`) and Frontend (`:5173`):
   ```powershell
   .\start_dev.ps1
   ```

---

## Deploying Frontend to Vercel & Connecting Live MT5

1. **Push to GitHub**:
   ```bash
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
2. **Import into Vercel**:
   - Select the GitHub repository in Vercel (root `vercel.json` is pre-configured to build `frontend/` automatically).
   - Deploy!
3. **Expose your local MT5 Bridge securely over HTTPS/WSS** (from your Windows PC):
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```
   Copy the generated `https://*.trycloudflare.com` URL.
4. **Link Vercel UI to your PC**:
   - Open your Vercel URL → click the **Settings** gear icon in the top-right header.
   - Paste the `https://*.trycloudflare.com` URL and your `MT5_API_KEY`.
   - Click **Test Connection** → **Save & Reconnect**.

---

## Key Features

- **Real-Time Live Stream (`500ms`)**: Live Bid/Ask/Spread, live candle updates, floating P/L, and positions over WebSocket (`/ws/live`).
- **Human-in-the-Loop Safety**: Orders are dry-run validated via `mt5.order_check()` and queued as `PENDING` proposals. Nothing executes in MT5 until you explicitly click **Confirm & Execute** (and DEMO-only guard blocks real accounts unless explicitly overridden).
- **Persistent Trade Journal & Stats**: Syncs closed MT5 deals into SQLite (`trade_journal.db`), stores custom strategy tags & notes, logs every proposal/confirm/reject in an audit trail, computes win rate, profit factor, max drawdown, equity curve, and exports to CSV.
