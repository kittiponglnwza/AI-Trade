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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Plug className="h-5 w-5 text-amber-400" />
            <h2 className="text-base font-semibold text-slate-100">
              MT5 Local Bridge Settings
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300">
              Bridge API URL (Local or Cloudflare/ngrok HTTPS Tunnel)
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:8000 or https://xxx.trycloudflare.com"
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Leave empty in local dev to use Vite proxy (<code className="text-slate-300">/api</code>).
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300">
              X-API-Key (Matches <code className="text-amber-300">MT5_API_KEY</code> in backend/.env)
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="mt5-local-dev-key"
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
            />
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-xs text-slate-300">
            <div className="font-semibold text-amber-300">
              Connecting from Vercel HTTPS?
            </div>
            <p className="mt-1 text-slate-400">
              Run this on your Windows PC alongside MT5 to expose a secure HTTPS/WSS tunnel:
            </p>
            <pre className="mt-2 overflow-x-auto rounded bg-slate-900 px-2.5 py-1.5 text-[11px] text-emerald-300">
              cloudflared tunnel --url http://localhost:8000
            </pre>
          </div>

          {testResult && (
            <div
              className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${
                testResult.ok
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : "border-rose-500/30 bg-rose-500/10 text-rose-300"
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

        <div className="mt-6 flex items-center justify-end gap-2 border-t border-slate-800 pt-4">
          <button
            type="button"
            onClick={handleTest}
            disabled={testing}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-medium text-slate-200 transition hover:bg-slate-700 disabled:opacity-50"
          >
            {testing ? "Testing..." : "Test Connection"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="rounded-lg bg-amber-500 px-4 py-2 text-xs font-semibold text-slate-950 transition hover:bg-amber-400"
          >
            Save & Reconnect
          </button>
        </div>
      </div>
    </div>
  );
}
