import { useState } from "react";
import { Activity, Eye, EyeOff, Lock, Mail, ShieldCheck } from "lucide-react";
import { getBridgeConfig, saveBridgeConfig } from "../services/api";
import {
  discoverBridgeStateFromSupabase,
  signInWithSupabase,
  type SupabaseSession,
} from "../services/supabase";

interface LoginGateProps {
  onAuthenticated: (session: SupabaseSession) => void;
}

export function LoginGate({ onAuthenticated }: LoginGateProps) {
  const [email, setEmail] = useState("kitipongzaza566@gmail.com");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const session = await signInWithSupabase(email, password);
      const bridgeState = await discoverBridgeStateFromSupabase();
      if (bridgeState?.public_url) {
        const isLocalhost =
          window.location.hostname === "localhost" ||
          window.location.hostname === "127.0.0.1";
        const current = getBridgeConfig();
        saveBridgeConfig({
          baseUrl: isLocalhost && !current.baseUrl ? "" : bridgeState.public_url,
          apiKey: bridgeState.api_key || current.apiKey,
        });
      }
      onAuthenticated(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "เข้าสู่ระบบไม่สำเร็จ");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#141414] px-4 text-[#cccccc]">
      <div className="w-full max-w-md rounded-lg border border-[#2b2b2b] bg-[#1e1e1e] p-6 shadow-2xl">
        <div className="mb-5 flex items-center gap-3 border-b border-[#2b2b2b] pb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-md border border-[#3c3c3c] bg-[#252526] text-[#4fc1ff]">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-white">AI Multi-Market Desk</h1>
              <span className="rounded border border-[#3fb950]/40 bg-[#3fb950]/10 px-1.5 py-0.5 text-[10px] font-bold text-[#3fb950]">
                SUPABASE AUTH
              </span>
            </div>
            <p className="text-xs text-[#9d9d9d]">
              Single-Owner Protected Terminal & Auto-Bridge Discovery
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[#cccccc]">
              Owner Email
            </label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[#6e6e6e]" />
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="kitipongzaza566@gmail.com"
                className="w-full rounded border border-[#3c3c3c] bg-[#141414] py-2 pl-9 pr-3 text-xs text-white placeholder-[#6e6e6e] focus:border-[#007acc] focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-[#cccccc]">
              Password
            </label>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[#6e6e6e]" />
              <input
                type={showPassword ? "text" : "password"}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded border border-[#3c3c3c] bg-[#141414] py-2 pl-9 pr-9 text-xs text-white placeholder-[#6e6e6e] focus:border-[#007acc] focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-2.5 top-2 text-[#8e8e8e] hover:text-white"
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded border border-[#f14c4c]/40 bg-[#5a1d1d]/40 px-3 py-2 text-xs text-[#f48771]">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded bg-[#007acc] px-4 py-2.5 text-xs font-bold text-white transition hover:bg-[#1f8ad2] disabled:opacity-50"
          >
            <ShieldCheck className="h-4 w-4" />
            {loading ? "กำลังตรวจสอบสิทธิ์ & ดึงลิงก์ MT5 Bridge..." : "Login & Auto-Connect MT5"}
          </button>
        </form>

        <div className="mt-4 rounded border border-[#2b2b2b] bg-[#141414] p-3 text-[11px] text-[#9d9d9d] space-y-1">
          <div className="font-semibold text-[#4fc1ff]">
            ✨ ระบบเชื่อมต่ออัตโนมัติ (Zero Copy-Paste)
          </div>
          <p>
            เมื่อ Login สำเร็จ หน้าเว็บจะดึงลิงก์ Cloudflare Tunnel ล่าสุดของคอมคุณจาก{" "}
            <strong className="text-[#e1e1e1]">Supabase PostgreSQL (RLS Locked)</strong>{" "}
            มาเชื่อม MT5 ให้อัตโนมัติ และดูประวัติเทรด/สถิติย้อนหลังได้ 24 ชม. แม้ปิดคอม
          </p>
        </div>
      </div>
    </div>
  );
}
