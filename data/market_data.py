"""
Martin Capital Partners — Market Data Module
data/market_data.py

Reads price, dividend, and index data from Supabase (populated every 15 min
by prefetch_data.py running on the office machine via Task Scheduler).

Falls back to local JSON cache or direct yfinance if Supabase is unavailable.
"""

import json
import os
import requests
import streamlit as st
from datetime import datetime

# ── Supabase config ────────────────────────────────────────────────────────
# Must match the values in prefetch_data.py
SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
SUPABASE_KEY = "sb_secret_P1XNpklX_g_gcMamZb0qqw_udXSu8T7"   # paste your service role key here

_SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

# ── Local JSON cache (fallback) ────────────────────────────────────────────
_DATA_DIR    = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR   = os.path.join(_DATA_DIR, "cache")
_PRICE_CACHE = os.path.join(_CACHE_DIR, "prices.json")
_INDEX_CACHE = os.path.join(_CACHE_DIR, "indices.json")


def _sb_get(table, select="*", filters=None):
    """
    Fetch rows from a Supabase table via REST API.
    Returns list of dicts, or None on failure.
    """
    try:
        url    = f"{SUPABASE_URL}/rest/v1/{table}"
        params = {"select": select}
        if filters:
            params.update(filters)
        resp = requests.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _load_price_cache():
    """Load local JSON price cache as fallback."""
    if not os.path.exists(_PRICE_CACHE):
        return None, None
    try:
        with open(_PRICE_CACHE, "r") as f:
            raw = json.load(f)
        return raw.get("data", {}), raw.get("_meta", {})
    except Exception:
        return None, None


def _load_index_cache():
    """Load local JSON index cache as fallback."""
    if not os.path.exists(_INDEX_CACHE):
        return None, None
    try:
        with open(_INDEX_CACHE, "r") as f:
            raw = json.load(f)
        return raw.get("data", {}), raw.get("_meta", {})
    except Exception:
        return None, None


# ── Public API ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def fetch_batch_prices(tickers_tuple, _cache_v=2):
    """
    Fetch price data for a batch of tickers.
    Returns: { "TICK": { "price": 123.45, "change_1d_pct": 0.5, ... }, ... }

    Priority: Supabase -> local JSON cache -> live yfinance

    _cache_v: bump this number to force a cache miss after deploying fixes.
    """
    results = {}
    missing = list(tickers_tuple)

    # ── 1. Try Supabase ───────────────────────────────────────────────────
    if SUPABASE_KEY != "YOUR_SERVICE_ROLE_KEY":
        tickers_filter = f"in.({','.join(tickers_tuple)})"
        rows = _sb_get("prices", filters={"ticker": tickers_filter})
        if rows:
            for row in rows:
                t = row.get("ticker")
                if t:
                    results[t] = {
                        "price":          row.get("price", 0),
                        "previous_close": row.get("previous_close", 0),
                        "change_1d_pct":  row.get("change_1d_pct", 0),
                        "dividend_yield": row.get("dividend_yield", 0),
                        "sector":         row.get("sector", ""),
                        "industry":       row.get("industry", ""),
                        "pe_ratio":       row.get("pe_ratio", 0),
                        "forward_pe":     row.get("forward_pe", 0),
                        "market_cap":     row.get("market_cap", 0),
                        "52w_high":       row.get("week52_high", 0),
                        "52w_low":        row.get("week52_low", 0),
                        "beta":           row.get("beta", 0),
                        "name":           row.get("name", t),
                        "price_to_book":  row.get("price_to_book", 0),
                    }
            missing = [t for t in tickers_tuple if t not in results]

    # ── 2. Try local JSON cache for anything still missing ────────────────
    if missing:
        cache, _ = _load_price_cache()
        if cache:
            for t in list(missing):
                if t in cache:
                    results[t] = cache[t]
                    missing.remove(t)

    # ── 3. Live yfinance fallback for anything still missing ──────────────
    if missing:
        try:
            import yfinance as yf
            import time as _time

            for ticker in missing:
                try:
                    tk    = yf.Ticker(ticker)
                    hist5 = tk.history(period="5d", auto_adjust=True)
                    price, prev_close, chg_1d = 0.0, 0.0, 0.0

                    if hist5 is not None and len(hist5) >= 2:
                        price      = round(float(hist5["Close"].iloc[-1]), 2)
                        prev_close = round(float(hist5["Close"].iloc[-2]), 2)
                        if prev_close > 0:
                            chg_1d = round((price - prev_close) / prev_close * 100, 2)
                            if abs(chg_1d) > 25:
                                chg_1d = 0.0
                    elif hist5 is not None and len(hist5) == 1:
                        price = round(float(hist5["Close"].iloc[-1]), 2)

                    fi          = tk.fast_info
                    market_cap  = getattr(fi, "market_cap", 0) or 0
                    week52_high = round(float(getattr(fi, "year_high", 0) or 0), 2)
                    week52_low  = round(float(getattr(fi, "year_low",  0) or 0), 2)

                    info = {}
                    try:
                        info = tk.info or {}
                    except Exception:
                        pass

                    def g(key, default=0):
                        val = info.get(key, default)
                        return val if val is not None else default

                    div_yield = 0.0
                    div_rate  = g("dividendRate") or 0
                    if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                        div_yield = round((div_rate / price) * 100, 2)
                    else:
                        raw = g("dividendYield") or 0
                        if isinstance(raw, (int, float)) and raw > 0:
                            div_yield = round(raw * 100, 2) if raw < 1 else round(raw, 2)
                    if div_yield > 15:
                        div_yield = 0.0

                    results[ticker] = {
                        "price":          price,
                        "previous_close": prev_close,
                        "change_1d_pct":  chg_1d,
                        "dividend_yield": div_yield,
                        "sector":         g("sector", ""),
                        "industry":       g("industry", ""),
                        "pe_ratio":       round(float(g("trailingPE")  or 0), 2),
                        "forward_pe":     round(float(g("forwardPE")   or 0), 2),
                        "market_cap":     market_cap,
                        "52w_high":       week52_high,
                        "52w_low":        week52_low,
                        "beta":           round(float(g("beta")        or 0), 2),
                        "name":           g("longName", "") or g("shortName", ticker),
                        "price_to_book":  round(float(g("priceToBook") or 0), 2),
                    }
                    _time.sleep(0.3)

                except Exception:
                    results[ticker] = {
                        "price": 0, "change_1d_pct": 0, "dividend_yield": 0, "sector": "",
                    }

        except ImportError:
            for ticker in missing:
                results[ticker] = {
                    "price": 0, "change_1d_pct": 0, "dividend_yield": 0, "sector": "",
                }

    return results


@st.cache_data(ttl=900, show_spinner=False)
def fetch_price_history(ticker, period="ytd"):
    """
    Fetch historical OHLCV data for a single ticker.
    Always uses yfinance - historical data is not stored in Supabase.
    Returns DataFrame or None.
    """
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        hist = tk.history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def get_index_data():
    """
    Return market index data for the ticker bar.
    Always uses batch yf.download with 5-day history to compute change_pct.
    Supabase indices table is skipped — it was populated by fast_info which
    is unreliable for futures (GC=F, CL=F). This is only 9 tickers and
    cached for 15 min, so the direct yfinance call is fast and accurate.
    """
    INDEX_SYMBOLS = {
        "^GSPC":    "S&P 500",
        "^DJI":     "DJIA",
        "^IXIC":    "Nasdaq",
        "^TNX":     "10Y Treasury",
        "^VIX":     "VIX",
        "DX-Y.NYB": "US Dollar",
        "CL=F":     "Crude Oil",
        "GC=F":     "Gold",
        "BTC-USD":  "Bitcoin",
    }

    try:
        import yfinance as yf

        tickers_str = " ".join(INDEX_SYMBOLS.keys())
        data = yf.download(
            tickers_str,
            period="5d",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )

        results = {}
        for symbol, name in INDEX_SYMBOLS.items():
            try:
                if len(INDEX_SYMBOLS) == 1:
                    df = data
                else:
                    df = data[symbol] if symbol in data.columns.get_level_values(0) else None

                if df is None or df.empty:
                    results[symbol] = {"name": name, "price": 0, "change_pct": 0}
                    continue

                df = df.dropna(subset=["Close"])
                if len(df) < 1:
                    results[symbol] = {"name": name, "price": 0, "change_pct": 0}
                    continue

                price = round(float(df["Close"].iloc[-1]), 2)
                prev  = round(float(df["Close"].iloc[-2]), 2) if len(df) >= 2 else price
                chg   = round((price - prev) / prev * 100, 2) if prev > 0 else 0

                results[symbol] = {"name": name, "price": price, "change_pct": chg}
            except Exception:
                results[symbol] = {"name": name, "price": 0, "change_pct": 0}

        return results

    except Exception:
        # Last resort: try Supabase or local cache if yfinance completely fails
        if SUPABASE_KEY != "YOUR_SERVICE_ROLE_KEY":
            rows = _sb_get("indices")
            if rows:
                return {row["symbol"]: row for row in rows}
        cache, _ = _load_index_cache()
        if cache:
            return cache
        return {}


def get_cache_timestamp():
    """Return the timestamp of the last Supabase fetch, or local cache time."""
    if SUPABASE_KEY != "YOUR_SERVICE_ROLE_KEY":
        rows = _sb_get("prices", select="fetched_at", filters={
            "limit": "1",
            "order": "fetched_at.desc",
        })
        if rows and len(rows) > 0:
            return rows[0].get("fetched_at", "")
    _, meta = _load_price_cache()
    if meta:
        return meta.get("fetched_at", "")
    return ""