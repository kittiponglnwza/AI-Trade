"""Live verifiable financial RSS news fetcher and sentiment analyzer."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import threading
import time
from typing import Any
from urllib.parse import quote_plus
import urllib.request

import feedparser

_CACHE_LOCK = threading.RLock()
_NEWS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SEC = 180.0

HIGH_IMPACT_PATTERNS = [
    ("FOMC", re.compile(r"\bFOMC\b", re.I)),
    ("Fed", re.compile(r"\b(?:Fed|Federal Reserve|Powell|Waller|Cook)\b", re.I)),
    ("CPI", re.compile(r"\bCPI\b|inflation", re.I)),
    ("NFP", re.compile(r"\bNFP\b|payrolls|jobless claims", re.I)),
    ("GDP", re.compile(r"\bGDP\b", re.I)),
    ("PCE", re.compile(r"\bPCE\b", re.I)),
    ("Rate Decision", re.compile(r"rate\s+(?:hike|cut|decision)", re.I)),
    ("Earnings", re.compile(r"\bearnings\b|\bguidance\b|\bquarterly results\b", re.I)),
]

BULLISH_TERMS = (
    "surge",
    "rally",
    "soar",
    "jump",
    "gain",
    "bullish",
    "beat",
    "upgrade",
    "breakout",
    "rebound",
    "higher",
    "boost",
    "safe-haven",
    "safe haven",
    "rate cut",
    "dovish",
    "record high",
)

BEARISH_TERMS = (
    "drop",
    "fall",
    "plunge",
    "sell-off",
    "selloff",
    "decline",
    "bearish",
    "miss",
    "downgrade",
    "slump",
    "tumble",
    "lower",
    "weakest",
    "pressure",
    "hawkish",
    "rate hike",
    "stronger dollar",
    "crisis",
    "downside",
    "losses",
)

BULLISH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (term, re.compile(rf"\b{re.escape(term)}(?:s|es|ed|ing)?\b", re.I))
    for term in BULLISH_TERMS
]

BEARISH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (term, re.compile(rf"\b{re.escape(term)}(?:s|es|ed|ing)?\b", re.I))
    for term in BEARISH_TERMS
]

INDEX_TICKER_MAP = {
    "US500": ("^GSPC", "S&P 500 stock market"),
    "SP500": ("^GSPC", "S&P 500 stock market"),
    "USTEC": ("^IXIC", "Nasdaq 100 stock market"),
    "NAS100": ("^IXIC", "Nasdaq 100 stock market"),
    "US30": ("^DJI", "Dow Jones stock market"),
}


def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _feeds_for_symbol(symbol: str) -> list[tuple[str, str]]:
    sym = symbol.upper().split(".")[0]
    if sym.startswith(("XAU", "XAG", "GOLD", "SILVER")):
        return [
            (
                "Google News (Gold)",
                "https://news.google.com/rss/search?q=XAUUSD+OR+%22gold+price%22+when:1d&hl=en-US&gl=US&ceid=US:en",
            ),
            ("FXStreet", "https://www.fxstreet.com/rss/news"),
            ("Investing.com Commodities", "https://www.investing.com/rss/news_11.rss"),
            (
                "Google News (Fed/Macro)",
                "https://news.google.com/rss/search?q=Federal+Reserve+OR+USD+OR+inflation+when:1d&hl=en-US&gl=US&ceid=US:en",
            ),
        ]

    if sym in INDEX_TICKER_MAP:
        yahoo_sym, query_str = INDEX_TICKER_MAP[sym]
        return [
            (
                f"Yahoo Finance ({sym})",
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(yahoo_sym)}&region=US&lang=en-US",
            ),
            (
                f"Google News ({sym})",
                f"https://news.google.com/rss/search?q={quote_plus(query_str)}+when:1d&hl=en-US&gl=US&ceid=US:en",
            ),
        ]

    if len(sym) == 6 and sym.isalpha() and any(
        c in sym for c in ("USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD")
    ):
        pair = f"{sym[:3]}/{sym[3:]}"
        return [
            ("FXStreet", "https://www.fxstreet.com/rss/news"),
            (
                f"Google News ({pair})",
                f"https://news.google.com/rss/search?q={quote_plus(sym)}+OR+{quote_plus(pair)}+forex+when:1d&hl=en-US&gl=US&ceid=US:en",
            ),
        ]

    return [
        (
            f"Yahoo Finance ({sym})",
            f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(sym)}&region=US&lang=en-US",
        ),
        (
            f"Google News ({sym})",
            f"https://news.google.com/rss/search?q={quote_plus(sym + ' stock news')}+when:2d&hl=en-US&gl=US&ceid=US:en",
        ),
    ]


def _score_article(title: str, summary: str) -> tuple[str, float, list[str], list[str]]:
    text = f"{title} {summary}"
    bull_hits = [term for term, pat in BULLISH_PATTERNS if pat.search(text)]
    bear_hits = [term for term, pat in BEARISH_PATTERNS if pat.search(text)]
    score = float(len(bull_hits) - len(bear_hits))
    if score > 0:
        tag = "BULLISH"
    elif score < 0:
        tag = "BEARISH"
    else:
        tag = "NEUTRAL"

    impact_hits = [label for label, pat in HIGH_IMPACT_PATTERNS if pat.search(text)]
    matched = list(dict.fromkeys(bull_hits + bear_hits + impact_hits))
    return tag, score, matched, impact_hits


def _fetch_single_feed(source_name: str, url: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        raw = resp.read()
    parsed = feedparser.parse(raw)
    items: list[dict[str, Any]] = []
    for entry in parsed.entries[:12]:
        title = _clean_html(getattr(entry, "title", "") or "")
        link = str(getattr(entry, "link", "") or "").strip()
        if not title or not link:
            continue
        summary = _clean_html(getattr(entry, "summary", "") or "")
        published = str(getattr(entry, "published", "") or getattr(entry, "updated", "") or "")
        entry_source = source_name
        src_obj = getattr(entry, "source", None)
        if isinstance(src_obj, dict) and src_obj.get("title"):
            entry_source = str(src_obj["title"])
        tag, score, matched, impact_hits = _score_article(title, summary)
        items.append(
            {
                "title": title,
                "source": entry_source,
                "feed": source_name,
                "url": link,
                "published": published,
                "sentiment_tag": tag,
                "raw_score": score,
                "matched_terms": matched[:6],
                "impact_hits": impact_hits,
            }
        )
    return items


def fetch_symbol_news(symbol: str = "XAUUSD", force_refresh: bool = False) -> dict[str, Any]:
    """Fetch live RSS news headlines & clickable source URLs with sentiment scoring."""
    key = symbol.strip().upper() or "XAUUSD"
    now = time.monotonic()

    if not force_refresh:
        with _CACHE_LOCK:
            cached = _NEWS_CACHE.get(key)
            if cached and (now - cached[0]) < CACHE_TTL_SEC:
                return cached[1]

    feeds = _feeds_for_symbol(key)
    all_articles: list[dict[str, Any]] = []
    sources_used: list[str] = []

    for source_name, url in feeds:
        try:
            entries = _fetch_single_feed(source_name, url)
            if entries:
                sources_used.append(source_name)
                all_articles.extend(entries)
        except Exception:
            continue

    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for art in all_articles:
        norm = re.sub(r"\W+", "", art["title"].lower())[:60]
        if norm and norm not in seen_titles:
            seen_titles.add(norm)
            deduped.append(art)

    top_articles = deduped[:12]
    total_raw = sum(a["raw_score"] for a in top_articles)
    norm_score = round(max(-1.0, min(1.0, total_raw / max(len(top_articles) * 2.0, 1.0))), 2)

    if norm_score >= 0.15:
        sentiment = "BULLISH"
    elif norm_score <= -0.15:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    impact_keywords: list[str] = []
    for a in top_articles:
        for k in a["impact_hits"]:
            if k not in impact_keywords:
                impact_keywords.append(k)

    clean_articles = [
        {
            "title": a["title"],
            "source": a["source"],
            "url": a["url"],
            "published": a["published"],
            "sentiment_tag": a["sentiment_tag"],
            "matched_terms": a["matched_terms"],
        }
        for a in top_articles
    ]

    result = {
        "symbol": key,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "sentiment": sentiment,
        "sentiment_score": norm_score,
        "high_impact_event": len(impact_keywords) > 0,
        "high_impact_keywords": impact_keywords,
        "sources_used": sources_used,
        "articles": clean_articles,
    }

    with _CACHE_LOCK:
        _NEWS_CACHE[key] = (now, result)
    return result
