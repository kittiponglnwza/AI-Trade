import { useEffect, useState } from "react";
import { Plus, Search, X } from "lucide-react";
import { searchSymbols, updateWatchlist } from "../services/api";
import type { SymbolSearchItem, WatchlistQuote } from "../types/trading";

interface WatchlistBarProps {
  activeSymbol: string;
  watchlistSymbols: string[];
  quotes: WatchlistQuote[];
  onSelectSymbol: (symbol: string) => void;
  onWatchlistChanged: (symbols: string[], quotes: WatchlistQuote[]) => void;
}

export function WatchlistBar({
  activeSymbol,
  watchlistSymbols,
  quotes,
  onSelectSymbol,
  onWatchlistChanged,
}: WatchlistBarProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [results, setResults] = useState<SymbolSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!modalOpen) return;
    let active = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      searchSymbols(query, category, 40)
        .then((res) => {
          if (active) setResults(res.symbols);
        })
        .catch(() => {
          if (active) setResults([]);
        })
        .finally(() => {
          if (active) setSearching(false);
        });
    }, 180);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [modalOpen, query, category]);

  const quoteMap = new Map(quotes.map((q) => [q.symbol.toUpperCase(), q]));

  const handleAdd = async (sym: string) => {
    if (watchlistSymbols.includes(sym.toUpperCase())) {
      onSelectSymbol(sym.toUpperCase());
      setModalOpen(false);
      return;
    }
    setBusy(true);
    try {
      const next = [...watchlistSymbols, sym.toUpperCase()];
      const res = await updateWatchlist(next);
      onWatchlistChanged(res.symbols, res.quotes);
      onSelectSymbol(sym.toUpperCase());
      setModalOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (sym: string) => {
    if (watchlistSymbols.length <= 1) return;
    setBusy(true);
    try {
      const next = watchlistSymbols.filter((s) => s !== sym);
      const res = await updateWatchlist(next);
      onWatchlistChanged(res.symbols, res.quotes);
      if (activeSymbol === sym && res.symbols.length > 0) {
        onSelectSymbol(res.symbols[0]);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="flex items-center gap-1.5 overflow-x-auto rounded-md border border-[#2b2b2b] bg-[#252526] px-2.5 py-1.5">
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-[#9d9d9d]">
          Watchlist
        </span>

        {watchlistSymbols.map((sym) => {
          const q = quoteMap.get(sym.toUpperCase());
          const isActive = activeSymbol.toUpperCase() === sym.toUpperCase();
          const chg = q?.change_pct ?? 0;

          return (
            <div
              key={sym}
              className={`group flex shrink-0 items-center gap-2 rounded border px-2.5 py-1 text-xs transition ${
                isActive
                  ? "border-[#007acc] bg-[#1e1e1e] text-white"
                  : "border-[#3c3c3c]/70 bg-[#1e1e1e]/70 text-[#cccccc] hover:bg-[#2a2d2e]"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectSymbol(sym)}
                className="flex items-center gap-2 text-left"
              >
                <span className="font-semibold">{sym}</span>
                {q && q.bid > 0 && (
                  <span className="font-mono-num text-[11px] text-[#9d9d9d]">
                    {q.bid.toFixed(Math.min(q.digits, 3))}
                  </span>
                )}
                {q && (
                  <span
                    className={`font-mono-num text-[10px] font-semibold ${
                      chg > 0 ? "text-[#3fb950]" : chg < 0 ? "text-[#f14c4c]" : "text-[#9d9d9d]"
                    }`}
                  >
                    {chg >= 0 ? "+" : ""}
                    {chg.toFixed(2)}%
                  </span>
                )}
                {q && !q.market_open && (
                  <span className="rounded bg-[#313131] px-1 text-[9px] text-[#9d9d9d]">
                    CLOSED
                  </span>
                )}
              </button>

              {watchlistSymbols.length > 1 && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleRemove(sym)}
                  className="rounded p-0.5 text-[#6e6e6e] opacity-70 hover:bg-[#3c3c3c] hover:text-white group-hover:opacity-100"
                  title={`Remove ${sym}`}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}

        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="flex shrink-0 items-center gap-1 rounded border border-[#3c3c3c] bg-[#313131] px-2.5 py-1 text-xs font-medium text-[#4fc1ff] hover:bg-[#3c3c3c]"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>Add Stock / Symbol</span>
        </button>
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-lg rounded-md border border-[#3c3c3c] bg-[#252526] p-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#2b2b2b] pb-2.5">
              <h3 className="text-sm font-semibold text-[#e1e1e1]">
                ค้นหาหุ้น / ทอง / Forex จาก MT5 (12,000+ Symbols)
              </h3>
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="rounded p-1 text-[#9d9d9d] hover:bg-[#313131] hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-[#6e6e6e]" />
                <input
                  type="text"
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="พิมพ์ Ticker เช่น NVDA, AAPL, TSLA, META, US500, EURUSD..."
                  className="w-full rounded border border-[#3c3c3c] bg-[#1e1e1e] py-1.5 pl-8 pr-3 text-xs text-[#e1e1e1] placeholder-[#6e6e6e] focus:border-[#007fd4] focus:outline-none"
                />
              </div>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2.5 py-1.5 text-xs text-[#cccccc]"
              >
                <option value="all">All Categories</option>
                <option value="Forex">Forex</option>
                <option value="Metals">Metals (Gold/Silver)</option>
                <option value="Nasdaq">Nasdaq (US Stocks)</option>
                <option value="NYSE">NYSE (US Stocks)</option>
                <option value="Index">Indices (US500/USTEC)</option>
                <option value="Crypto">Crypto</option>
                <option value="Energ">Energy / Oil</option>
              </select>
            </div>

            <div className="mt-3 max-h-72 space-y-1 overflow-y-auto rounded border border-[#2b2b2b] bg-[#1e1e1e] p-2">
              {searching ? (
                <div className="py-6 text-center text-xs text-[#9d9d9d]">Searching MT5...</div>
              ) : results.length === 0 ? (
                <div className="py-6 text-center text-xs text-[#6e6e6e]">ไม่พบ Symbol ที่ค้นหา</div>
              ) : (
                results.map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    disabled={busy}
                    onClick={() => handleAdd(item.name)}
                    className="flex w-full items-center justify-between rounded px-2.5 py-2 text-left text-xs hover:bg-[#2a2d2e]"
                  >
                    <div>
                      <span className="font-mono-num font-bold text-[#e1e1e1]">{item.name}</span>
                      <span className="ml-2 text-[#9d9d9d]">{item.description}</span>
                    </div>
                    <span className="rounded bg-[#313131] px-1.5 py-0.5 text-[10px] text-[#4fc1ff]">
                      {item.category}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
