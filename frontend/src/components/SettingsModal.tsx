import { useState } from "react";
import { CheckCircle2, Plug, X, XCircle } from "lucide-react";
import { fetchHealth, getBridgeConfig, saveBridgeConfig } from "../services/api";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function SettingsModal({ open, onClose, onSaved }: SettingsModalProps) {
  const initial = getBridgeConfig();
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [apiKey, setApiKey] = useState(initial.apiKey);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  if (!open) return null;

  const handleTest = async () => {
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

  const handleSave = () => {
    saveBridgeConfig({ baseUrl, apiKey });
    onSaved();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
      <div className="w-full max-w-lg rounded-md border border-[#3c3c3c] bg-[#252526] p-5 shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-3">
          <div className="flex items-center gap-2">
            <Plug className="h-4 w-4 text-[#4fc1ff]" />
            <h2 className="text-sm font-semibold text-[#e1e1e1]">MT5 Local Bridge Settings</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#9d9d9d] hover:bg-[#313131] hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3.5">
          <div>
            <label className="block text-xs font-medium text-[#cccccc]">
              Bridge API URL (Local หรือ Cloudflare/ngrok Tunnel)
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
              X-API-Key (ตรงกับ <code className="text-[#dcdcaa]">MT5_API_KEY</code> ใน backend/.env)
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
            <p className="mt-1">รัน Tunnel บนเครื่อง Windows ที่เปิด MT5 อยู่:</p>
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
        </div>

        <div className="mt-5 flex items-center justify-end gap-2 border-t border-[#2b2b2b] pt-4">
          <button
            type="button"
            onClick={handleTest}
            disabled={testing}
            className="rounded border border-[#3c3c3c] bg-[#313131] px-3.5 py-1.5 text-xs font-medium text-[#cccccc] transition hover:bg-[#3c3c3c] disabled:opacity-50"
          >
            {testing ? "Testing..." : "Test Connection"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="rounded bg-[#007acc] px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-[#1f8ad2]"
          >
            Save & Reconnect
          </button>
        </div>
      </div>
    </div>
  );
}
