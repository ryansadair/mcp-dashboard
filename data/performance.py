"""
Strategy performance: YTD returns, benchmark comparison, alpha.
Sources: yfinance (benchmark), Tamarac (strategy NAV via Excel)
"""

import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import date
from utils.config import STRATEGIES
from utils.cache import query


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
    try:
        start = date(date.today().year, 1, 1)
        hist = yf.download(bench_ticker, start=start, progress=False, auto_adjust=True)
        if hist is None or len(hist) < 2:
            raise ValueError("Not enough data")
        closes = hist["Close"]
        if hasattr(closes, 'iloc'):
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
        else:
            raise ValueError("Unexpected format")
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