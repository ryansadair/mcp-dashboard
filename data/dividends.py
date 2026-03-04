"""
Martin Capital Partners — Dividend Analysis Module
data/dividends.py

Computes dividend metrics: yield, growth rates, consecutive years,
ex-date calendars, payout ratios, and income projections.

Known yfinance data quirks handled:
  - dividendYield field is unreliable (sometimes decimal, sometimes %, sometimes payout ratio)
  - payoutRatio can be > 1.0 or negative for some tickers
  - ETFs return inconsistent dividend history
  - Current partial year skews CAGR if included
  - Tickers with < 3 years of data produce noisy growth/consecutive metrics
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st


def _safe_dividend_yield(info, price=None):
    """
    Return dividend yield as a sensible percentage (e.g. 3.01 for 3.01%).
    Primary method: dividendRate / price (most reliable).
    Fallback: dividendYield field with sanity checks.
    Hard cap at 15% — no legitimate equity yield is higher.
    """
    rate = info.get("dividendRate") or 0
    px = price or info.get("currentPrice") or info.get("regularMarketPrice") or 0

    # Primary: calculate from rate and price
    if isinstance(rate, (int, float)) and rate > 0 and px > 0:
        pct = round((rate / px) * 100, 2)
        if 0 < pct <= 15:
            return pct

    # Fallback: use dividendYield field
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
    """
    Return payout ratio as a percentage (e.g. 45.0 for 45%).
    yfinance returns this as a decimal (0.45) but sometimes returns
    garbage values > 2.0 or negatives. Cap at 100%, floor at 0%.
    """
    raw = info.get("payoutRatio")
    if raw is None or not isinstance(raw, (int, float)):
        return 0.0
    if raw < 0:
        return 0.0
    pct = raw * 100 if raw < 5 else raw  # handle both decimal and already-percentage
    if pct > 150:  # anything above 150% is likely garbage
        return 0.0
    return round(min(pct, 100), 1)


@st.cache_data(ttl=3600, show_spinner=False)
def get_dividend_details(ticker, _cache_v=2):
    """
    Get comprehensive dividend data for a single ticker.
    Returns dict with yield, rate, growth, consecutive years, etc.
    _cache_v: bump this to bust Streamlit's in-memory cache after logic changes.
    """
    try:
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

        # ── Dividend growth (1Y, 3Y, 5Y CAGR) ────────────────────────────
        if not divs.empty and len(divs) >= 4:
            divs_df = divs.reset_index()
            divs_df.columns = ["date", "amount"]
            divs_df["year"] = pd.to_datetime(divs_df["date"]).dt.year

            # Exclude current partial year — it skews CAGR downward
            current_year = datetime.now().year
            annual = divs_df[divs_df["year"] < current_year].groupby("year")["amount"].sum()

            def _calc_cagr(annual_series, years_back):
                """Calculate CAGR for a given lookback period. Returns None if not enough data."""
                if len(annual_series) < years_back + 1:
                    return None
                recent = annual_series.iloc[-1]
                older = annual_series.iloc[-(years_back + 1)]
                if older > 0 and recent > 0:
                    cagr = ((recent / older) ** (1 / years_back) - 1) * 100
                    if -50 < cagr < 100:  # sanity cap
                        return round(cagr, 1)
                return None

            # 1-year growth (simple YoY)
            g1 = _calc_cagr(annual, 1) if len(annual) >= 2 else None
            result["div_growth_1y"] = g1 if g1 is not None else 0.0

            # 3-year CAGR
            g3 = _calc_cagr(annual, 3) if len(annual) >= 4 else None
            result["div_growth_3y"] = g3 if g3 is not None else 0.0

            # 5-year CAGR
            g5 = _calc_cagr(annual, 5) if len(annual) >= 6 else None
            result["div_growth_5y"] = g5 if g5 is not None else 0.0

            # Track how many years of data we actually have
            result["div_growth_years"] = len(annual)

            # ── Consecutive years of dividend increases ───────────────────
            # Recalculate annual including current year for this metric
            annual_all = divs_df.groupby("year")["amount"].sum()
            if len(annual_all) >= 3:
                consec = 0
                for i in range(len(annual_all) - 1, 0, -1):
                    # Strictly greater — flat dividends don't count as growth
                    if annual_all.iloc[i] > annual_all.iloc[i - 1] * 0.99:
                        # 0.99 multiplier: allow tiny rounding differences (< 1%)
                        consec += 1
                    else:
                        break
                result["consecutive_years"] = consec
            else:
                # Not enough history to be meaningful
                result["consecutive_years"] = 0
        else:
            result["div_growth_1y"] = 0.0
            result["div_growth_3y"] = 0.0
            result["div_growth_5y"] = 0.0
            result["div_growth_years"] = 0
            result["consecutive_years"] = 0

        return result

    except Exception as e:
        return {
            "symbol": ticker,
            "dividend_yield": 0, "dividend_rate": 0, "payout_ratio": 0,
            "ex_dividend_date": "", "five_year_avg_yield": 0,
            "div_growth_1y": 0, "div_growth_3y": 0, "div_growth_5y": 0,
            "div_growth_years": 0, "consecutive_years": 0,
        }


@st.cache_data(ttl=3600, show_spinner=False)
def get_batch_dividend_details(tickers_tuple, _cache_v=2):
    """Fetch dividend details for a batch of tickers."""
    results = {}
    for t in tickers_tuple:
        results[t] = get_dividend_details(t)
    return results


def compute_strategy_income(holdings_df, price_data, div_data):
    """
    Compute estimated annual dividend income for a strategy.
    holdings_df: DataFrame with symbol, quantity columns
    price_data: dict from fetch_batch_prices
    div_data: dict from get_batch_dividend_details
    """
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
            if 0 < yld <= 15:  # extra safety — skip any yield that snuck past
                weighted_yield += weight * yld
                total_weight += weight
    if total_weight > 0:
        return round(weighted_yield / total_weight, 2)
    return 0.0