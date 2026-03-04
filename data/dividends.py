"""
Martin Capital Partners — Dividend Analysis Module
data/dividends.py

Computes dividend metrics: yield, growth rates, consecutive years,
ex-date calendars, payout ratios, and income projections.

Data source priority:
  1. Pre-fetched JSON cache (data/cache/dividends.json) — updated by prefetch_data.py
  2. yfinance live API (fallback for local development)

Known yfinance data quirks handled:
  - dividendYield field is unreliable (sometimes decimal, sometimes %, sometimes payout ratio)
  - payoutRatio can be > 1.0 or negative for some tickers
  - ETFs return inconsistent dividend history
  - Current partial year skews CAGR if included
  - Tickers with < 3 years of data produce noisy growth/consecutive metrics
"""

import json
import requests
import os
import streamlit as st
from datetime import datetime

# ── Supabase config (must match market_data.py) ────────────────────────────
SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
SUPABASE_KEY = "YOUR_SERVICE_ROLE_KEY"   # paste your service role key here

_SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def _sb_get_dividends(tickers):
    """Fetch dividend rows from Supabase for a list of tickers."""
    if SUPABASE_KEY == "YOUR_SERVICE_ROLE_KEY":
        return None
    try:
        url    = f"{SUPABASE_URL}/rest/v1/dividends"
        params = {"select": "*", "ticker": f"in.({','.join(tickers)})"}
        resp   = requests.get(url, headers=_SB_HEADERS, params=params, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            return {row["ticker"]: row for row in rows} if rows else None
        return None
    except Exception:
        return None

# ── Cache path ─────────────────────────────────────────────────────────────
_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_DATA_DIR, "cache")
_DIV_CACHE = os.path.join(_CACHE_DIR, "dividends.json")


def _load_div_cache():
    """Load pre-fetched dividend cache. Returns (data_dict, meta) or (None, None)."""
    if not os.path.exists(_DIV_CACHE):
        return None, None
    try:
        with open(_DIV_CACHE, "r") as f:
            raw = json.load(f)
        return raw.get("data", {}), raw.get("_meta", {})
    except Exception:
        return None, None


# ── Helpers for yfinance fallback ──────────────────────────────────────────

def _safe_dividend_yield(info, price=None):
    """Return dividend yield as a sensible percentage (e.g. 3.01 for 3.01%)."""
    rate = info.get("dividendRate") or 0
    px = price or info.get("currentPrice") or info.get("regularMarketPrice") or 0

    if isinstance(rate, (int, float)) and rate > 0 and px > 0:
        pct = round((rate / px) * 100, 2)
        if 0 < pct <= 15:
            return pct

    raw = info.get("dividendYield")
    if raw is not None and isinstance(raw, (int, float)) and raw > 0:
        if raw < 1:
            pct = round(raw * 100, 2)
        else:
            pct = round(raw, 2)
        if 0 < pct <= 15:
            return pct

    return 0.0


def _safe_payout_ratio(info):
    """Return payout ratio as a percentage (e.g. 45.0 for 45%)."""
    raw = info.get("payoutRatio")
    if raw is None or not isinstance(raw, (int, float)):
        return 0.0
    if raw < 0:
        return 0.0
    pct = raw * 100 if raw < 5 else raw
    if pct > 150:
        return 0.0
    return round(min(pct, 100), 1)


# ── Public API ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_dividend_details(ticker, _cache_v=3):
    """
    Get comprehensive dividend data for a single ticker.
    Priority: Supabase -> JSON cache -> yfinance live.
    """
    # ── 1. Try Supabase ───────────────────────────────────────────────────
    sb_data = _sb_get_dividends([ticker])
    if sb_data and ticker in sb_data:
        row = sb_data[ticker]
        return {
            "symbol":              ticker,
            "dividend_yield":      row.get("dividend_yield", 0),
            "dividend_rate":       row.get("dividend_rate", 0),
            "payout_ratio":        row.get("payout_ratio", 0),
            "ex_dividend_date":    row.get("ex_dividend_date", ""),
            "five_year_avg_yield": row.get("five_year_avg_yield", 0),
            "div_growth_1y":       row.get("div_growth_1y", 0),
            "div_growth_3y":       row.get("div_growth_3y", 0),
            "div_growth_5y":       row.get("div_growth_5y", 0),
            "div_growth_years":    row.get("div_growth_years", 0),
            "consecutive_years":   row.get("consecutive_years", 0),
        }

    # ── 2. Try local JSON cache ───────────────────────────────────────────
    cache, _ = _load_div_cache()
    if cache and ticker in cache:
        return cache[ticker]

    # Fallback: yfinance live
    try:
        import yfinance as yf
        import pandas as pd

        tk = yf.Ticker(ticker)
        info = tk.info or {}
        divs = tk.dividends

        result = {
            "symbol": ticker,
            "dividend_yield": _safe_dividend_yield(info),
            "dividend_rate": round(info.get("dividendRate", 0) or 0, 4),
            "payout_ratio": _safe_payout_ratio(info),
            "ex_dividend_date": "",
            "five_year_avg_yield": round((info.get("fiveYearAvgDividendYield", 0) or 0), 2),
            "div_growth_1y": 0,
            "div_growth_3y": 0,
            "div_growth_5y": 0,
            "div_growth_years": 0,
            "consecutive_years": 0,
        }

        # Ex-dividend date
        ex_div = info.get("exDividendDate")
        if ex_div:
            try:
                if isinstance(ex_div, (int, float)):
                    result["ex_dividend_date"] = datetime.fromtimestamp(ex_div).strftime("%Y-%m-%d")
                else:
                    result["ex_dividend_date"] = str(ex_div)
            except Exception:
                pass

        # Dividend growth
        if divs is not None and not divs.empty and len(divs) >= 4:
            divs_df = divs.reset_index()
            divs_df.columns = ["date", "amount"]
            divs_df["year"] = pd.to_datetime(divs_df["date"]).dt.year

            current_year = datetime.now().year
            annual = divs_df[divs_df["year"] < current_year].groupby("year")["amount"].sum()

            if len(annual) >= 2:
                recent = annual.iloc[-1]

                for label, years_back in [("div_growth_1y", 1), ("div_growth_3y", 3), ("div_growth_5y", 5)]:
                    yb = min(years_back, len(annual) - 1)
                    if yb >= 1:
                        older = annual.iloc[-(yb + 1)]
                        if older > 0 and recent > 0:
                            cagr = ((recent / older) ** (1 / yb) - 1) * 100
                            if -50 < cagr < 100:
                                result[label] = round(cagr, 1)
                                if label == "div_growth_5y":
                                    result["div_growth_years"] = yb

            # Consecutive years
            annual_all = divs_df.groupby("year")["amount"].sum()
            if len(annual_all) >= 3:
                consec = 0
                for j in range(len(annual_all) - 1, 0, -1):
                    if annual_all.iloc[j] > annual_all.iloc[j - 1] * 0.99:
                        consec += 1
                    else:
                        break
                result["consecutive_years"] = consec

        return result

    except Exception:
        return {
            "symbol": ticker,
            "dividend_yield": 0, "dividend_rate": 0, "payout_ratio": 0,
            "ex_dividend_date": "", "five_year_avg_yield": 0,
            "div_growth_1y": 0, "div_growth_3y": 0, "div_growth_5y": 0,
            "div_growth_years": 0, "consecutive_years": 0,
        }


@st.cache_data(ttl=3600, show_spinner=False)
def get_batch_dividend_details(tickers_tuple, _cache_v=3):
    """Fetch dividend details for a batch of tickers.
    Priority: Supabase -> local JSON cache -> yfinance per-ticker fallback.
    """
    results = {}
    missing = list(tickers_tuple)

    # ── 1. Try Supabase ───────────────────────────────────────────────────
    sb_data = _sb_get_dividends(list(tickers_tuple))
    if sb_data:
        for t, row in sb_data.items():
            results[t] = {
                "symbol":              t,
                "dividend_yield":      row.get("dividend_yield", 0),
                "dividend_rate":       row.get("dividend_rate", 0),
                "payout_ratio":        row.get("payout_ratio", 0),
                "ex_dividend_date":    row.get("ex_dividend_date", ""),
                "five_year_avg_yield": row.get("five_year_avg_yield", 0),
                "div_growth_1y":       row.get("div_growth_1y", 0),
                "div_growth_3y":       row.get("div_growth_3y", 0),
                "div_growth_5y":       row.get("div_growth_5y", 0),
                "div_growth_years":    row.get("div_growth_years", 0),
                "consecutive_years":   row.get("consecutive_years", 0),
            }
        missing = [t for t in tickers_tuple if t not in results]

    # ── 2. Try local JSON cache for anything still missing ────────────────
    if missing:
        cache, _ = _load_div_cache()
        if cache:
            for t in list(missing):
                if t in cache:
                    results[t] = cache[t]
                    missing.remove(t)

    # ── 3. yfinance fallback for anything still missing ───────────────────
    if missing:
        for t in missing:
            results[t] = get_dividend_details(t)

    return results


def compute_strategy_income(holdings_df, price_data, div_data):
    """Compute estimated annual dividend income for a strategy."""
    total_income = 0.0
    for _, row in holdings_df.iterrows():
        symbol = row["symbol"]
        qty = row.get("quantity", 0)
        if symbol in div_data:
            rate = div_data[symbol].get("dividend_rate", 0) or 0
            total_income += qty * rate
    return total_income


def compute_weighted_yield(holdings_df, div_data):
    """Compute weighted average dividend yield for a strategy."""
    total_weight = 0.0
    weighted_yield = 0.0
    for _, row in holdings_df.iterrows():
        symbol = row["symbol"]
        weight = row.get("weight", 0)
        if symbol in div_data:
            yld = div_data[symbol].get("dividend_yield", 0) or 0
            if 0 < yld <= 15:
                weighted_yield += weight * yld
                total_weight += weight
    if total_weight > 0:
        return round(weighted_yield / total_weight, 2)
    return 0.0