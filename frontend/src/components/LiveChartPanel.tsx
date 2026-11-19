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
        background: { color: "#1e1e1e" },
        textColor: "#9d9d9d",
      },
      grid: {
        vertLines: { color: "#282828" },
        horzLines: { color: "#282828" },
      },
      crosshair: {
        vertLine: { color: "#555555", style: LineStyle.Dashed },
        horzLine: { color: "#555555", style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "#2b2b2b",
      },
      timeScale: {
        borderColor: "#2b2b2b",
        timeVisible: true,
        secondsVisible: false,
      },
      width: el.clientWidth,
      height: 430,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#3fb950",
      downColor: "#f14c4c",
      borderUpColor: "#3fb950",
      borderDownColor: "#f14c4c",
      wickUpColor: "#3fb950",
      wickDownColor: "#f14c4c",
    });

    const ema20Series = chart.addLineSeries({
      color: "#dcdcaa",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50Series = chart.addLineSeries({
      color: "#4fc1ff",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema200Series = chart.addLineSeries({
      color: "#c586c0",
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
          color: "#4fc1ff",
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
            color: "#f14c4c",
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
            color: "#3fb950",
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
            color: "#007acc",
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
            color: "#f14c4c",
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
            color: "#3fb950",
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
    <div className="rounded-md border border-[#2b2b2b] bg-[#252526] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2b2b2b] pb-2.5">
        <div className="flex flex-wrap items-center gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onTimeframeChange(tf)}
              className={`rounded px-2.5 py-1 text-xs font-semibold transition ${
                timeframe === tf
                  ? "bg-[#007acc] text-white"
                  : "border border-[#3c3c3c] bg-[#1e1e1e] text-[#9d9d9d] hover:bg-[#2a2d2e] hover:text-[#e1e1e1]"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex cursor-pointer items-center gap-1.5 text-[#dcdcaa]">
            <input
              type="checkbox"
              checked={showEma20}
              onChange={(e) => setShowEma20(e.target.checked)}
              className="accent-[#007acc]"
            />
            EMA20
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-[#4fc1ff]">
            <input
              type="checkbox"
              checked={showEma50}
              onChange={(e) => setShowEma50(e.target.checked)}
              className="accent-[#007acc]"
            />
            EMA50
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-[#c586c0]">
            <input
              type="checkbox"
              checked={showEma200}
              onChange={(e) => setShowEma200(e.target.checked)}
              className="accent-[#007acc]"
            />
            EMA200
          </label>
          {latestCandle?.rsi14 != null && (
            <span className="font-mono-num rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-0.5 text-[#9d9d9d]">
              RSI14: <strong className="text-[#4fc1ff]">{latestCandle.rsi14.toFixed(1)}</strong>
            </span>
          )}
          {latestCandle?.atr14 != null && (
            <span className="font-mono-num rounded border border-[#3c3c3c] bg-[#1e1e1e] px-2 py-0.5 text-[#9d9d9d]">
              ATR14: <strong className="text-[#dcdcaa]">${latestCandle.atr14.toFixed(2)}</strong>
            </span>
          )}
        </div>
      </div>

      <div ref={containerRef} className="mt-2.5 w-full overflow-hidden rounded border border-[#2b2b2b]" />

      {mtf.length > 0 && (
        <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {mtf.map((row) => {
            const isBull = row.trend.includes("BULL");
            const isBear = row.trend.includes("BEAR");
            return (
              <div
                key={row.tf}
                className="rounded border border-[#2b2b2b] bg-[#1e1e1e] px-2.5 py-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-[#e1e1e1]">{row.tf}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      isBull
                        ? "bg-[#3fb950]/15 text-[#3fb950]"
                        : isBear
                        ? "bg-[#f14c4c]/15 text-[#f14c4c]"
                        : "bg-[#313131] text-[#cccccc]"
                    }`}
                  >
                    {row.trend.replace(" (ABOVE EMA200)", "").replace(" (BELOW EMA200)", "")}
                  </span>
                </div>
                <div className="font-mono-num mt-1 flex items-center justify-between text-[11px] text-[#9d9d9d]">
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
