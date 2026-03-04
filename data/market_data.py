"""
Martin Capital Partners — Market Data Module
data/market_data.py

Fetches stock prices, daily changes, and fundamentals.

Data source priority:
  1. Pre-fetched JSON cache (data/cache/prices.json) — updated by prefetch_data.py
  2. yfinance live API (fallback for local development)

The cache approach eliminates yfinance rate-limiting issues on Streamlit Cloud.
"""

import json
import os
import streamlit as st
from datetime import datetime

# ── Cache path ─────────────────────────────────────────────────────────────
_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_DATA_DIR, "cache")
_PRICE_CACHE = os.path.join(_CACHE_DIR, "prices.json")
_INDEX_CACHE = os.path.join(_CACHE_DIR, "indices.json")


def _load_price_cache():
    """Load pre-fetched price cache. Returns (data_dict, meta) or (None, None)."""
    if not os.path.exists(_PRICE_CACHE):
        return None, None
    try:
        with open(_PRICE_CACHE, "r") as f:
            raw = json.load(f)
        return raw.get("data", {}), raw.get("_meta", {})
    except Exception:
        return None, None


def _load_index_cache():
    """Load pre-fetched index cache. Returns (data_dict, meta) or (None, None)."""
    if not os.path.exists(_INDEX_CACHE):
        return None, None
    try:
        with open(_INDEX_CACHE, "r") as f:
            raw = json.load(f)
        return raw.get("data", {}), raw.get("_meta", {})
    except Exception:
        return None, None


# ── Public API (same signatures as before) ─────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def fetch_batch_prices(tickers_tuple):
    """
    Fetch price data for a batch of tickers.
    Returns: { "TICK": { "price": 123.45, "change_1d_pct": 0.5, ... }, ... }

    Tries JSON cache first (populated by prefetch_data.py on office machine).
    Falls back to yfinance for any tickers not in cache.
    """
    cache, meta = _load_price_cache()

    results = {}
    missing = []

    if cache:
        for t in tickers_tuple:
            if t in cache:
                results[t] = cache[t]
            else:
                missing.append(t)
    else:
        missing = list(tickers_tuple)

    # Fallback: fetch missing tickers from yfinance directly
    if missing:
        try:
            import yfinance as yf
            import time as _time

            for ticker in missing:
                try:
                    tk = yf.Ticker(ticker)
                    info = tk.info or {}

                    def g(key, default=0):
                        val = info.get(key, default)
                        return val if val is not None else default

                    price = g("currentPrice") or g("regularMarketPrice") or 0
                    prev_close = g("previousClose") or g("regularMarketPreviousClose") or 0

                    if price and prev_close and prev_close > 0:
                        chg_1d = round((price - prev_close) / prev_close * 100, 2)
                    else:
                        chg_1d = 0

                    # Safe dividend yield
                    div_rate = g("dividendRate") or 0
                    if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                        div_yield = round((div_rate / price) * 100, 2)
                        if div_yield > 15:
                            div_yield = 0
                    else:
                        raw = g("dividendYield") or 0
                        if isinstance(raw, (int, float)) and raw > 0:
                            div_yield = round(raw * 100, 2) if raw < 1 else round(raw, 2)
                            if div_yield > 15:
                                div_yield = 0
                        else:
                            div_yield = 0

                    results[ticker] = {
                        "price": round(float(price), 2) if price else 0,
                        "previous_close": round(float(prev_close), 2) if prev_close else 0,
                        "change_1d_pct": chg_1d,
                        "dividend_yield": div_yield,
                        "sector": g("sector", ""),
                        "industry": g("industry", ""),
                        "pe_ratio": round(float(g("trailingPE") or 0), 2),
                        "forward_pe": round(float(g("forwardPE") or 0), 2),
                        "market_cap": g("marketCap", 0),
                        "52w_high": round(float(g("fiftyTwoWeekHigh") or 0), 2),
                        "52w_low": round(float(g("fiftyTwoWeekLow") or 0), 2),
                        "beta": round(float(g("beta") or 0), 2),
                        "name": g("longName", "") or g("shortName", ticker),
                        "price_to_book": round(float(g("priceToBook") or 0), 2),
                    }
                    _time.sleep(0.2)

                except Exception:
                    results[ticker] = {
                        "price": 0, "change_1d_pct": 0, "dividend_yield": 0, "sector": "",
                    }

        except ImportError:
            # yfinance not available (shouldn't happen but be safe)
            for ticker in missing:
                results[ticker] = {
                    "price": 0, "change_1d_pct": 0, "dividend_yield": 0, "sector": "",
                }

    return results


@st.cache_data(ttl=900, show_spinner=False)
def fetch_price_history(ticker, period="ytd"):
    """
    Fetch historical OHLCV data for a single ticker.
    This always uses yfinance (historical data is not rate-limited as heavily).
    Returns: DataFrame with Date, Open, High, Low, Close, Volume columns.
    """
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


def get_cache_timestamp():
    """Return the timestamp of the last cache update, or None."""
    _, meta = _load_price_cache()
    if meta:
        return meta.get("fetched_at", "")
    return ""


def get_index_data():
    """
    Return market index data for the ticker bar.
    Tries JSON cache first, then falls back to yfinance.
    """
    cache, _ = _load_index_cache()
    if cache:
        return cache

    # Fallback: live fetch
    try:
        import yfinance as yf
        import time as _time

        indices = {
            "^GSPC": "S&P 500",
            "^DJI": "DJIA",
            "^IXIC": "Nasdaq",
            "^TNX": "10Y Treasury",
            "^VIX": "VIX",
            "DX-Y.NYB": "US Dollar",
            "CL=F": "Crude Oil",
        }

        results = {}
        for symbol, name in indices.items():
            try:
                t = yf.Ticker(symbol)
                info = t.info or {}
                price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
                prev = info.get("regularMarketPreviousClose") or info.get("previousClose") or 0
                chg = round((price - prev) / prev * 100, 2) if prev else 0
                results[symbol] = {"name": name, "price": round(float(price), 2), "change_pct": chg}
                _time.sleep(0.2)
            except Exception:
                results[symbol] = {"name": name, "price": 0, "change_pct": 0}
        return results

    except ImportError:
        return {}