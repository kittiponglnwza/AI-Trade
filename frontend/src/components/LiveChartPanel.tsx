import { useEffect, useRef, useState } from "react";
import {
  createChart,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type {
  CandlePoint,
  ChartPreviewLevels,
  MtfSummaryRow,
  OpenPosition,
  Timeframe,
} from "../types/trading";

interface LiveChartPanelProps {
  symbol: string;
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  candles: CandlePoint[];
  lastBar: CandlePoint | null;
  mtf: MtfSummaryRow[];
  positions: OpenPosition[];
  previewLevels: ChartPreviewLevels | null;
}

const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export function LiveChartPanel({
  symbol,
  timeframe,
  onTimeframeChange,
  candles,
  lastBar,
  mtf,
  positions,
  previewLevels,
}: LiveChartPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema200SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const lastCandleTimeRef = useRef<number>(0);

  const [showEma20, setShowEma20] = useState(true);
  const [showEma50, setShowEma50] = useState(true);
  const [showEma200, setShowEma200] = useState(true);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      layout: {
        background: { color: "#0b1120" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      crosshair: {
        vertLine: { color: "#475569", style: LineStyle.Dashed },
        horzLine: { color: "#475569", style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "#1e293b",
      },
      timeScale: {
        borderColor: "#1e293b",
        timeVisible: true,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height: 430,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderUpColor: "#10b981",
      borderDownColor: "#f43f5e",
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });

    const ema20Series = chart.addLineSeries({
      color: "#fbbf24",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50Series = chart.addLineSeries({
      color: "#22d3ee",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema200Series = chart.addLineSeries({
      color: "#c084fc",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    ema20SeriesRef.current = ema20Series;
    ema50SeriesRef.current = ema50Series;
    ema200SeriesRef.current = ema200Series;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      }
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema20SeriesRef.current = null;
      ema50SeriesRef.current = null;
      ema200SeriesRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    const ohlc = candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeriesRef.current.setData(ohlc);
    lastCandleTimeRef.current = candles[candles.length - 1].time;

    if (ema20SeriesRef.current) {
      ema20SeriesRef.current.setData(
        candles
          .filter((c) => c.ema20 !== null)
          .map((c) => ({ time: c.time as UTCTimestamp, value: c.ema20 as number }))
      );
    }
    if (ema50SeriesRef.current) {
      ema50SeriesRef.current.setData(
        candles
          .filter((c) => c.ema50 !== null)
          .map((c) => ({ time: c.time as UTCTimestamp, value: c.ema50 as number }))
      );
    }
    if (ema200SeriesRef.current) {
      ema200SeriesRef.current.setData(
        candles
          .filter((c) => c.ema200 !== null)
          .map((c) => ({ time: c.time as UTCTimestamp, value: c.ema200 as number }))
      );
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    ema20SeriesRef.current?.applyOptions({ visible: showEma20 });
    ema50SeriesRef.current?.applyOptions({ visible: showEma50 });
    ema200SeriesRef.current?.applyOptions({ visible: showEma200 });
  }, [showEma20, showEma50, showEma200]);

  useEffect(() => {
    if (!lastBar || !candleSeriesRef.current) return;
    if (lastBar.time < lastCandleTimeRef.current) return;
    lastCandleTimeRef.current = lastBar.time;

    candleSeriesRef.current.update({
      time: lastBar.time as UTCTimestamp,
      open: lastBar.open,
      high: lastBar.high,
      low: lastBar.low,
      close: lastBar.close,
    });
    if (lastBar.ema20 !== null) {
      ema20SeriesRef.current?.update({ time: lastBar.time as UTCTimestamp, value: lastBar.ema20 });
    }
    if (lastBar.ema50 !== null) {
      ema50SeriesRef.current?.update({ time: lastBar.time as UTCTimestamp, value: lastBar.ema50 });
    }
    if (lastBar.ema200 !== null) {
      ema200SeriesRef.current?.update({ time: lastBar.time as UTCTimestamp, value: lastBar.ema200 });
    }
  }, [lastBar]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;

    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    for (const pos of positions) {
      if (pos.symbol !== symbol) continue;
      priceLinesRef.current.push(
        series.createPriceLine({
          price: pos.price_open,
          color: "#38bdf8",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${pos.side} #${pos.ticket}`,
        })
      );
      if (pos.sl > 0) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: pos.sl,
            color: "#fb7185",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `SL #${pos.ticket}`,
          })
        );
      }
      if (pos.tp > 0) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: pos.tp,
            color: "#34d399",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: `TP #${pos.ticket}`,
          })
        );
      }
    }

    if (previewLevels) {
      if (previewLevels.entry) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: previewLevels.entry,
            color: "#f59e0b",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `PLAN ${previewLevels.side}`,
          })
        );
      }
      if (previewLevels.sl) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: previewLevels.sl,
            color: "#f43f5e",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "PLAN SL",
          })
        );
      }
      if (previewLevels.tp) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: previewLevels.tp,
            color: "#10b981",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "PLAN TP",
          })
        );
      }
    }
  }, [positions, previewLevels, symbol, candles]);

  const latestCandle = lastBar ?? candles[candles.length - 1] ?? null;

  return (
    <div className="rounded-2xl border border-slate-800/90 bg-slate-900/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onTimeframeChange(tf)}
              className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                timeframe === tf
                  ? "bg-amber-500 text-slate-950"
                  : "border border-slate-800 bg-slate-950 text-slate-300 hover:bg-slate-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex cursor-pointer items-center gap-1.5 text-amber-300">
            <input
              type="checkbox"
              checked={showEma20}
              onChange={(e) => setShowEma20(e.target.checked)}
              className="accent-amber-400"
            />
            EMA20
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-cyan-300">
            <input
              type="checkbox"
              checked={showEma50}
              onChange={(e) => setShowEma50(e.target.checked)}
              className="accent-cyan-400"
            />
            EMA50
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-purple-300">
            <input
              type="checkbox"
              checked={showEma200}
              onChange={(e) => setShowEma200(e.target.checked)}
              className="accent-purple-400"
            />
            EMA200
          </label>
          {latestCandle?.rsi14 != null && (
            <span className="rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-300 tabular-nums">
              RSI14: <strong className="text-sky-300">{latestCandle.rsi14.toFixed(1)}</strong>
            </span>
          )}
          {latestCandle?.atr14 != null && (
            <span className="rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-slate-300 tabular-nums">
              ATR14: <strong className="text-amber-300">${latestCandle.atr14.toFixed(2)}</strong>
            </span>
          )}
        </div>
      </div>

      <div ref={containerRef} className="mt-3 w-full overflow-hidden rounded-xl border border-slate-800/70" />

      {mtf.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {mtf.map((row) => {
            const isBull = row.trend.includes("BULL");
            const isBear = row.trend.includes("BEAR");
            return (
              <div
                key={row.tf}
                className="rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-200">{row.tf}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      isBull
                        ? "bg-emerald-500/15 text-emerald-300"
                        : isBear
                        ? "bg-rose-500/15 text-rose-300"
                        : "bg-slate-700/40 text-slate-300"
                    }`}
                  >
                    {row.trend.replace(" (ABOVE EMA200)", "").replace(" (BELOW EMA200)", "")}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400 tabular-nums">
                  <span>RSI {row.rsi14.toFixed(1)}</span>
                  <span>ATR ${row.atr14.toFixed(2)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
