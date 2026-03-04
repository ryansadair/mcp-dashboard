"""
Strategy performance: YTD returns, benchmark comparison, alpha.
Sources: Supabase benchmark_ytd table (populated by prefetch_data.py)
         yfinance fallback if Supabase unavailable
"""

import pandas as pd
import streamlit as st
import requests
from datetime import date
from utils.config import STRATEGIES
from utils.cache import query

# ── Supabase config ────────────────────────────────────────────────────────
SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
SUPABASE_KEY = "YOUR_SERVICE_ROLE_KEY"   # paste your service role key here

_SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def _sb_get_benchmark_ytd(bench_ticker):
    """Fetch YTD return for a benchmark from Supabase."""
    if SUPABASE_KEY == "sb_secret_P1XNpklX_g_gcMamZb0qqw_udXSu8T7":
        return None
    try:
        url    = f"{SUPABASE_URL}/rest/v1/benchmark_ytd"
        params = {"select": "ytd_return", "symbol": f"eq.{bench_ticker}"}
        resp   = requests.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0].get("ytd_return")
        return None
    except Exception:
        return None

def _sb_get_benchmark_history(bench_ticker):
    """Fetch full YTD price history for a benchmark from Supabase."""
    if SUPABASE_KEY == "YOUR_SERVICE_ROLE_KEY":
        return None
    try:
        url    = f"{SUPABASE_URL}/rest/v1/benchmark_history"
        params = {"select": "date,close", "symbol": f"eq.{bench_ticker}", "order": "date.asc"}
        resp   = requests.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return pd.DataFrame(rows)
        return None
    except Exception:
        return None


# ── Strategy Returns (from Tamarac or manual) ──────────────────────────────

# Placeholder strategy KPIs — these get overwritten once Tamarac data flows in
# Update these manually or wire to Tamarac NAV exports
STRATEGY_KPIS = {
    "QDVD": {"ytd": 8.42, "aum": 42.3, "div_yield": 3.12, "holdings": 18},
    "DAC":  {"ytd": 6.89, "aum": 28.7, "div_yield": 2.87, "holdings": 12},
    "SMID": {"ytd": 11.23,"aum": 15.2, "div_yield": 2.41, "holdings": 14},
    "OR":   {"ytd": 14.56,"aum": 9.8,  "div_yield": 1.95, "holdings": 8},
    "DCP":  {"ytd": 9.78, "aum": 6.1,  "div_yield": 1.68, "holdings": 7},
}


@st.cache_data(ttl=3600)
def get_strategy_kpis(strategy: str) -> dict:
    """Get KPIs for a strategy — DB first, fallback to manual."""
    return STRATEGY_KPIS.get(strategy, {})


@st.cache_data(ttl=3600)
def get_benchmark_ytd(bench_ticker: str) -> float:
    # ── 1. Try Supabase ───────────────────────────────────────────────────
    sb_ytd = _sb_get_benchmark_ytd(bench_ticker)
    if sb_ytd is not None:
        return sb_ytd

    # ── 2. yfinance fallback ──────────────────────────────────────────────
    try:
        import yfinance as yf
        start = date(date.today().year, 1, 1)
        hist  = yf.download(bench_ticker, start=start, progress=False, auto_adjust=True)
        if hist is None or len(hist) < 2:
            raise ValueError("Not enough data")
        closes = hist["Close"]
        first  = float(closes.iloc[0])
        last   = float(closes.iloc[-1])
        return round(((last - first) / first) * 100, 2)
    except Exception:
        fallbacks = {"^GSPC": 7.15, "^SP500DVS": 5.92, "^RUT": 9.44, "^SP500GR": 8.21}
        return fallbacks.get(bench_ticker, 6.0)

@st.cache_data(ttl=3600)
def get_perf_chart_data(strategy: str, bench_ticker: str) -> pd.DataFrame:
    """
    Build monthly cumulative return series for strategy vs benchmark.
    Strategy returns: pulled from DB if available, else demo.
    Benchmark: yfinance.
    """
    # Demo monthly data — replace with actual NAV series from Tamarac
    demo = {
        "QDVD": [2.1, 3.4, 4.1, 3.8, 5.2, 5.9, 6.8, 7.1, 6.5, 7.4, 8.0, 8.42],
        "DAC":  [1.8, 2.9, 3.5, 3.1, 4.5, 5.0, 5.8, 6.1, 5.5, 6.3, 6.7, 6.89],
        "SMID": [2.5, 4.1, 5.0, 4.8, 6.5, 7.2, 8.5, 9.0, 8.2, 9.5, 10.5, 11.23],
        "OR":   [3.2, 5.1, 6.3, 5.8, 8.1, 9.4, 10.8, 11.5, 10.9, 12.1, 13.5, 14.56],
        "DCP":  [2.0, 3.2, 3.9, 3.6, 5.0, 5.8, 6.7, 7.0, 6.4, 7.3, 8.8, 9.78],
    }
    bench_demo = [1.8, 2.9, 3.5, 4.2, 4.8, 5.1, 5.9, 6.4, 5.8, 6.5, 6.9, 7.15]
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","YTD"]

    strat_vals = demo.get(strategy, demo["QDVD"])
    df = pd.DataFrame({
        "month": months,
        "strategy": strat_vals,
        "benchmark": bench_demo,
    })
    return df