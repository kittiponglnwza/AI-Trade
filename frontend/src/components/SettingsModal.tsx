import { useEffect, useState } from "react";
import { CheckCircle2, Copy, FileSpreadsheet, Plug, RefreshCw, X, XCircle } from "lucide-react";
import {
  fetchHealth,
  fetchSheetsConfig,
  getBridgeConfig,
  saveBridgeConfig,
  saveSheetsConfig,
  syncAllSheets,
  testSheetsConnection,
} from "../services/api";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

const APPS_SCRIPT_SNIPPET = `var HEADERS = {
  Trades: ["id","mt5_deal_ticket","mt5_position_id","symbol","side","volume","entry_price","exit_price","sl","tp","open_time","close_time","gross_profit","commission","swap","net_profit","status","strategy_tag","notes","source"],
  Proposals: ["id","created_at","source","symbol","side","entry_price","sl","tp","lots","risk_pct","est_risk_usd","rr_ratio","status","timeframe","rationale","exec_price","exec_comment"],
  WatchdogLogs: ["id","created_at","level","category","symbol","message"],
  Stats: ["updated_at","total_trades","wins","losses","win_rate_pct","net_profit","profit_factor","expectancy","max_drawdown_usd","max_drawdown_pct"]
};
function ensureSheetTab(ss, name) {
  var sheet = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sheet.getLastRow() === 0 && HEADERS[name]) {
    sheet.appendRow(HEADERS[name]);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, HEADERS[name].length).setFontWeight("bold");
  }
  return sheet;
}
function doPost(e) {
  try {
    var payload = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var action = payload.action || "append";
    if (action === "ping") {
      ["Trades","Proposals","WatchdogLogs","Stats"].forEach(function(t){ ensureSheetTab(ss, t); });
      return ContentService.createTextOutput(JSON.stringify({ ok: true, spreadsheet: ss.getName() })).setMimeType(ContentService.MimeType.JSON);
    }
    var sheet = ensureSheetTab(ss, payload.sheet || "WatchdogLogs");
    var rows = payload.rows || [];
    if (action === "replace" && sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
    if (rows.length > 0) sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    return ContentService.createTextOutput(JSON.stringify({ ok: true, written: rows.length })).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, error: String(err) })).setMimeType(ContentService.MimeType.JSON);
  }
}`;

export function SettingsModal({ open, onClose, onSaved }: SettingsModalProps) {
  const initial = getBridgeConfig();
  const [tab, setTab] = useState<"bridge" | "sheets">("bridge");

  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [apiKey, setApiKey] = useState(initial.apiKey);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [sheetsEnabled, setSheetsEnabled] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [sheetsBusy, setSheetsBusy] = useState(false);
  const [sheetsMsg, setSheetsMsg] = useState<{ ok: boolean; message: string } | null>(null);
  const [copiedScript, setCopiedScript] = useState(false);

  useEffect(() => {
    if (!open) return;
    fetchSheetsConfig()
      .then((cfg) => {
        setSheetsEnabled(Boolean(cfg.enabled));
        setWebhookUrl(cfg.webhook_url || "");
      })
      .catch(() => {});
  }, [open]);

  if (!open) return null;

  const handleTestBridge = async () => {
    setTesting(true);
    setTestResult(null);
    saveBridgeConfig({ baseUrl, apiKey });
    try {
      const health = await fetchHealth();
      setTestResult({
        ok: true,
        message: health.mt5_connected
          ? `Connected to Bridge & MT5 (${health.trade_mode ?? "OK"})`
          : "Connected to Bridge, but MT5 Terminal is not attached yet.",
      });
    } catch (err) {
      setTestResult({
        ok: false,
        message: err instanceof Error ? err.message : "Failed to reach bridge",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveBridge = () => {
    saveBridgeConfig({ baseUrl, apiKey });
    onSaved();
    onClose();
  };

  const handleSaveAndTestSheets = async (runTest: boolean) => {
    setSheetsBusy(true);
    setSheetsMsg(null);
    try {
      await saveSheetsConfig({ enabled: sheetsEnabled, webhook_url: webhookUrl.trim() });
      if (runTest) {
        const res = await testSheetsConnection();
        setSheetsMsg({ ok: true, message: `เชื่อมต่อ Google Sheets สำเร็จ (${res.mode ?? "webhook"})` });
      } else {
        setSheetsMsg({ ok: true, message: "บันทึกการตั้งค่า Google Sheets แล้ว" });
      }
    } catch (err) {
      setSheetsMsg({
        ok: false,
        message: err instanceof Error ? err.message : "เชื่อมต่อ Google Sheets ไม่สำเร็จ",
      });
    } finally {
      setSheetsBusy(false);
    }
  };

  const handleSyncAllSheets = async () => {
    setSheetsBusy(true);
    setSheetsMsg(null);
    try {
      await saveSheetsConfig({ enabled: true, webhook_url: webhookUrl.trim() });
      setSheetsEnabled(true);
      const res = await syncAllSheets();
      setSheetsMsg({
        ok: true,
        message: `ซิงก์ข้อมูลทั้งหมดขึ้น Google Sheets แล้ว (${JSON.stringify(res.written)})`,
      });
    } catch (err) {
      setSheetsMsg({
        ok: false,
        message: err instanceof Error ? err.message : "ซิงก์ไม่สำเร็จ",
      });
    } finally {
      setSheetsBusy(false);
    }
  };

  const handleCopyScript = async () => {
    await navigator.clipboard.writeText(APPS_SCRIPT_SNIPPET);
    setCopiedScript(true);
    window.setTimeout(() => setCopiedScript(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
      <div className="w-full max-w-xl rounded-md border border-[#3c3c3c] bg-[#252526] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#2b2b2b] px-5 py-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setTab("bridge")}
              className={`flex items-center gap-1.5 border-b-2 pb-1 text-xs font-semibold ${
                tab === "bridge"
                  ? "border-[#007acc] text-white"
                  : "border-transparent text-[#9d9d9d] hover:text-[#e1e1e1]"
              }`}
            >
              <Plug className="h-3.5 w-3.5 text-[#4fc1ff]" />
              MT5 Local Bridge
            </button>
            <button
              type="button"
              onClick={() => setTab("sheets")}
              className={`flex items-center gap-1.5 border-b-2 pb-1 text-xs font-semibold ${
                tab === "sheets"
                  ? "border-[#007acc] text-white"
                  : "border-transparent text-[#9d9d9d] hover:text-[#e1e1e1]"
              }`}
            >
              <FileSpreadsheet className="h-3.5 w-3.5 text-[#3fb950]" />
              Google Sheets 24/7 Sync
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#9d9d9d] hover:bg-[#313131] hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {tab === "bridge" ? (
          <div className="p-5 space-y-3.5">
            <div>
              <label className="block text-xs font-medium text-[#cccccc]">
                Bridge API URL (Local หรือ Cloudflare Tunnel)
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:8000 หรือ https://xxx.trycloudflare.com"
                className="font-mono-num mt-1.5 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-2 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#cccccc]">
                X-API-Key (ตรงกับ <code className="text-[#dcdcaa]">MT5_API_KEY</code>)
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="mt5-local-dev-key"
                className="font-mono-num mt-1.5 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-2 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
              />
            </div>

            <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3 text-xs text-[#9d9d9d]">
              <div className="font-semibold text-[#4fc1ff]">เชื่อมต่อจาก Vercel HTTPS:</div>
              <pre className="font-mono-num mt-2 overflow-x-auto rounded border border-[#2b2b2b] bg-[#181818] px-2.5 py-1.5 text-[11px] text-[#4ec9b0]">
                cloudflared tunnel --url http://127.0.0.1:8000
              </pre>
            </div>

            {testResult && (
              <div
                className={`flex items-start gap-2 rounded border p-3 text-xs break-words ${
                  testResult.ok
                    ? "border-[#3fb950]/40 bg-[#1e3a29]/40 text-[#3fb950]"
                    : "border-[#f14c4c]/40 bg-[#5a1d1d]/40 text-[#f48771]"
                }`}
              >
                {testResult.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                )}
                <span>{testResult.message}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-[#2b2b2b] pt-4">
              <button
                type="button"
                onClick={handleTestBridge}
                disabled={testing}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3.5 py-1.5 text-xs font-medium text-[#cccccc] hover:bg-[#3c3c3c] disabled:opacity-50"
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
              <button
                type="button"
                onClick={handleSaveBridge}
                className="rounded bg-[#007acc] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2]"
              >
                Save & Reconnect
              </button>
            </div>
          </div>
        ) : (
          <div className="p-5 space-y-3.5">
            <label className="flex cursor-pointer items-center justify-between rounded border border-[#2b2b2b] bg-[#1e1e1e] px-3 py-2 text-xs">
              <span className="font-medium text-[#e1e1e1]">
                เปิดเขียนข้อมูลขึ้น Google Sheets อัตโนมัติ 24/7
              </span>
              <input
                type="checkbox"
                checked={sheetsEnabled}
                onChange={(e) => setSheetsEnabled(e.target.checked)}
                className="h-4 w-4 accent-[#007acc]"
              />
            </label>

            <div>
              <label className="block text-xs font-medium text-[#cccccc]">
                Google Apps Script Web App URL
              </label>
              <input
                type="text"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://script.google.com/macros/s/.../exec"
                className="font-mono-num mt-1.5 w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] px-3 py-2 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
              />
            </div>

            <div className="rounded border border-[#2b2b2b] bg-[#1e1e1e] p-3 text-[11px] text-[#9d9d9d] space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-[#3fb950]">ตั้งค่าใน 30 วินาที (ฟรี 100%):</span>
                <button
                  type="button"
                  onClick={handleCopyScript}
                  className="flex items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2 py-0.5 text-[10px] text-[#e1e1e1] hover:bg-[#3c3c3c]"
                >
                  <Copy className="h-3 w-3" />
                  {copiedScript ? "Copied!" : "Copy Apps Script (.gs)"}
                </button>
              </div>
              <ol className="list-decimal pl-4 space-y-0.5">
                <li>สร้าง Google Sheet ใหม่ → เมนู <strong>Extensions → Apps Script</strong></li>
                <li>กดปุ่ม <strong>Copy Apps Script (.gs)</strong> ด้านบนไปวางแทนโค้ดเดิมแล้ว Save</li>
                <li>กด <strong>Deploy → New deployment → Web app</strong> (Who has access: <strong>Anyone</strong>)</li>
                <li>คัดลอก URL มาวางด้านบน แล้วกด <strong>Test Ping</strong> (ระบบสร้างแท็บ Trades/Proposals/WatchdogLogs/Stats ให้เอง)</li>
              </ol>
            </div>

            {sheetsMsg && (
              <div
                className={`flex items-start gap-2 rounded border p-3 text-xs break-words ${
                  sheetsMsg.ok
                    ? "border-[#3fb950]/40 bg-[#1e3a29]/40 text-[#3fb950]"
                    : "border-[#f14c4c]/40 bg-[#5a1d1d]/40 text-[#f48771]"
                }`}
              >
                {sheetsMsg.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                )}
                <span>{sheetsMsg.message}</span>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[#2b2b2b] pt-4">
              <button
                type="button"
                disabled={sheetsBusy}
                onClick={() => handleSaveAndTestSheets(true)}
                className="rounded border border-[#3c3c3c] bg-[#313131] px-3 py-1.5 text-xs font-medium text-[#cccccc] hover:bg-[#3c3c3c] disabled:opacity-50"
              >
                Test Ping
              </button>
              <button
                type="button"
                disabled={sheetsBusy}
                onClick={handleSyncAllSheets}
                className="flex items-center gap-1 rounded bg-[#238636] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2ea043] disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${sheetsBusy ? "animate-spin" : ""}`} />
                Sync All Now
              </button>
              <button
                type="button"
                disabled={sheetsBusy}
                onClick={() => handleSaveAndTestSheets(false)}
                className="rounded bg-[#007acc] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#1f8ad2] disabled:opacity-50"
              >
                Save Settings
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
