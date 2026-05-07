"""
Martin Capital Partners — Warbook Metrics Module
data/warbook_metrics.py

Computes yfinance-derived metrics that the warbook tabs need but which aren't
provided by market_data.py or dividends.py. Single batched entry point with
two-tier caching (memory via @st.cache_data + disk via @disk_cached) so the
expensive cold path runs at most once per day.

Sprint 23A — produces the data layer for warbook tabs 1–4:
  Tab 1 (Strategy Overview)        — uses TR windows + 3yr upside helpers
  Tab 2 (QDG Characteristics)      — ROE, payout, FCF yield, debt metrics
  Tab 3 (Risk Correlation)         — sub-industry, country, debt coverage,
                                     net-debt-to-capital, beta, super sector
  Tab 4 (Attribution & Quality)    — TR over 5 windows + vs SPX, ROE 5yr avg,
                                     EPS / CF / FCF dividend coverage,
                                     cash-flow / EV yield

Note: dividend metadata (paid_since, raised_since, frequency, last bump) is
NOT computed here — Sprint 23A direction was to use Fish CCC exclusively for
that data via data/dividend_streaks.py. This module covers everything else.

Caching architecture:
  Memory   (@st.cache_data, ttl=3600)  — fastest, per-session
  Disk     (@disk_cached,  ttl=86400)  — fast, survives session eviction
  Compute  (yfinance + financial stmts)

Cold path is ~2-3 minutes for ~50 tickers due to per-ticker financial-
statement queries. Disk cache makes that a once-per-day cost. Subsequent
calls within 24h read from disk (~10ms per ticker).

The single public entry point is fetch_warbook_metrics_batch().
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta
from typing import Optional

import streamlit as st

from utils.disk_cache import disk_cached


# ── Module constants ──────────────────────────────────────────────────────

# SPY proxy for "vs SPX" total return comparisons. Using SPY because it
# includes dividends in its price action when fetched with auto_adjust=True
# — gives a clean total-return reference series.
_SPX_PROXY_TICKER = "SPY"

# Inter-ticker delay during the cold path. Without this yfinance throttles
# silently and returns empty frames for some tickers. 0.4s × 50 tickers
# = ~20s overhead, but that's only paid once per day per the disk cache.
_THROTTLE_SECONDS = 0.4

# yfinance's super sector mapping. yfinance returns sector strings like
# "Technology" / "Healthcare" / "Energy"; Morningstar groups these into
# Cyclical / Sensitive / Defensive at the super sector level. This map
# is the standard Morningstar grouping.
_SUPER_SECTOR_MAP = {
    # Cyclical
    "Basic Materials":         "Cyclical",
    "Materials":               "Cyclical",
    "Consumer Cyclical":       "Cyclical",
    "Consumer Discretionary":  "Cyclical",
    "Financial Services":      "Cyclical",
    "Financials":              "Cyclical",
    "Real Estate":             "Cyclical",
    # Sensitive
    "Communication Services":  "Sensitive",
    "Energy":                  "Sensitive",
    "Industrials":             "Sensitive",
    "Technology":              "Sensitive",
    # Defensive
    "Consumer Defensive":      "Defensive",
    "Consumer Staples":        "Defensive",
    "Healthcare":              "Defensive",
    "Utilities":               "Defensive",
}

# Sentinel for "couldn't compute" — distinct from 0.0 so callers can render
# em dashes vs zeros correctly.
MISSING = None


# ── Helpers ───────────────────────────────────────────────────────────────

def _safe_float(v, default=None):
    """Coerce to float, returning default on any failure or NaN."""
    if v is None:
        return default
    try:
        f = float(v)
        # NaN check via self-comparison
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


def _period_start_end(period_label: str):
    """
    Return (start_date, end_date) for total-return windows. end_date is
    today; start_date depends on period.
        MTD — first day of current month
        QTD — first day of current quarter
        YTD — first day of current year
        3M  — 90 calendar days ago
        1Y  — 365 calendar days ago
    """
    today = date.today()
    if period_label == "MTD":
        return today.replace(day=1), today
    if period_label == "QTD":
        # Quarter starts: Jan 1, Apr 1, Jul 1, Oct 1
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_start_month, day=1), today
    if period_label == "YTD":
        return today.replace(month=1, day=1), today
    if period_label == "3M":
        return today - timedelta(days=90), today
    if period_label == "1Y":
        return today - timedelta(days=365), today
    raise ValueError(f"Unknown period: {period_label}")


def _total_return_from_history(hist, start_date):
    """
    Compute total return % from a yfinance OHLCV DataFrame between
    start_date and the end of the series.

    Method: simple sum-of-dividends-paid-during-window approach.
    TR = (end_close + sum_divs_during_window) / start_close - 1

    Uses auto_adjust=True at fetch time so the close prices already reflect
    splits. Dividends are added back explicitly because auto_adjust folds
    them into prior prices (which would understate actual TR for the holder).

    Returns float (percent) or None if data insufficient.

    Edge cases handled:
      - start_date falls on a market-closed day: use first available bar at-or-after
      - hist has NaN closes: dropna first
      - len < 2 after filtering: return None
    """
    if hist is None or len(hist) == 0:
        return None

    try:
        df = hist.dropna(subset=["Close"]).copy()
        if df.empty:
            return None

        # Filter to bars on or after start_date. yfinance index is
        # tz-aware datetime; convert to date for comparison.
        idx_dates = df.index.map(lambda x: x.date() if hasattr(x, "date") else x)
        mask = [d >= start_date for d in idx_dates]
        window = df[mask]

        if len(window) < 2:
            return None

        start_close = float(window["Close"].iloc[0])
        end_close = float(window["Close"].iloc[-1])

        if start_close <= 0:
            return None

        # Add back dividends paid during the window. auto_adjust=True folds
        # them back into prior prices, which gives a price-only return; we
        # want total return so the dividend stream is added explicitly.
        div_sum = 0.0
        if "Dividends" in window.columns:
            div_sum = float(window["Dividends"].fillna(0).sum())

        tr_pct = ((end_close + div_sum) / start_close - 1) * 100
        return round(tr_pct, 2)
    except Exception:
        return None


def _compute_balance_sheet_metrics(tk):
    """
    Read latest balance sheet to compute leverage/coverage ratios.

    Returns dict with:
      lt_debt_to_capital    — long-term debt / (LT debt + total equity)  [%]
      net_debt_to_capital   — (LT debt - cash) / (LT debt + total equity) [%]
      debt_coverage_ratio   — operating income / interest expense  [×]

    Each field is None if the underlying data isn't available. yfinance's
    balance sheet has inconsistent row labels across tickers — we try
    several common variants for each metric.

    Note: balance sheet rows are columns in yfinance's frame. The most
    recent reporting period is the leftmost column.
    """
    out = {
        "lt_debt_to_capital": None,
        "net_debt_to_capital": None,
        "debt_coverage_ratio": None,
    }

    try:
        bs = tk.balance_sheet
        if bs is None or bs.empty:
            return out

        # Latest period is column 0
        col = bs.columns[0]

        def _bs_get(*keys):
            """Try several row labels for the same metric."""
            for k in keys:
                if k in bs.index:
                    v = _safe_float(bs.loc[k, col])
                    if v is not None:
                        return v
            return None

        lt_debt = _bs_get(
            "Long Term Debt",
            "Long-Term Debt",
            "LongTermDebt",
        )
        equity = _bs_get(
            "Stockholders Equity",
            "Common Stock Equity",
            "Total Stockholder Equity",
            "Total Equity Gross Minority Interest",
        )
        cash = _bs_get(
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments",
            "Cash",
        )

        # LT Debt / Capital
        if lt_debt is not None and equity is not None:
            denom = lt_debt + equity
            if denom > 0:
                out["lt_debt_to_capital"] = round((lt_debt / denom) * 100, 1)

        # Net Debt / Capital
        if lt_debt is not None and equity is not None and cash is not None:
            net_debt = lt_debt - cash
            denom = lt_debt + equity
            if denom > 0:
                out["net_debt_to_capital"] = round((net_debt / denom) * 100, 1)
    except Exception:
        pass

    # Interest coverage from income statement
    try:
        is_ = tk.income_stmt
        if is_ is not None and not is_.empty:
            col = is_.columns[0]

            def _is_get(*keys):
                for k in keys:
                    if k in is_.index:
                        v = _safe_float(is_.loc[k, col])
                        if v is not None:
                            return v
                return None

            op_income = _is_get(
                "Operating Income",
                "Total Operating Income As Reported",
                "Operating Revenue",
            )
            interest_exp = _is_get(
                "Interest Expense",
                "Interest Expense Non Operating",
            )

            if op_income is not None and interest_exp is not None:
                # Interest expense is usually reported as a positive number
                # representing an expense. Take absolute value defensively.
                ie_abs = abs(interest_exp)
                if ie_abs > 0:
                    out["debt_coverage_ratio"] = round(op_income / ie_abs, 1)
    except Exception:
        pass

    return out


def _compute_cash_flow_metrics(tk, info):
    """
    Compute cash-flow-driven coverage metrics:
      fcf_yield               — TTM FCF / market cap × 100
      fcf_div_coverage        — TTM FCF / annual dividends paid (×)
      cf_div_coverage         — TTM operating CF / annual dividends paid (×)
      eps_div_coverage        — TTM EPS / annual dividend per share (×)
      cash_flow_ev_yield      — operating CF / enterprise value × 100

    Uses yfinance's `info` dict for the simple fields and falls back to
    cash_flow / income_stmt for anything missing.
    """
    out = {
        "fcf_yield": None,
        "fcf_div_coverage": None,
        "cf_div_coverage": None,
        "eps_div_coverage": None,
        "cash_flow_ev_yield": None,
    }

    fcf = _safe_float(info.get("freeCashflow"))
    op_cf = _safe_float(info.get("operatingCashflow"))
    market_cap = _safe_float(info.get("marketCap"))
    enterprise_value = _safe_float(info.get("enterpriseValue"))
    eps = _safe_float(info.get("trailingEps"))
    div_rate = _safe_float(info.get("dividendRate"))
    shares_out = _safe_float(info.get("sharesOutstanding"))

    # FCF yield
    if fcf is not None and market_cap is not None and market_cap > 0:
        out["fcf_yield"] = round((fcf / market_cap) * 100, 2)

    # CF / EV yield
    if op_cf is not None and enterprise_value is not None and enterprise_value > 0:
        out["cash_flow_ev_yield"] = round((op_cf / enterprise_value) * 100, 2)

    # Coverage ratios — we need TOTAL annual dividends ($), which is
    # div_rate × shares_outstanding. div_rate is per-share.
    if div_rate is not None and div_rate > 0 and shares_out is not None and shares_out > 0:
        annual_divs_total = div_rate * shares_out

        if fcf is not None and annual_divs_total > 0:
            out["fcf_div_coverage"] = round(fcf / annual_divs_total, 1)
        if op_cf is not None and annual_divs_total > 0:
            out["cf_div_coverage"] = round(op_cf / annual_divs_total, 1)

    # EPS coverage — per-share quantities, simpler
    if eps is not None and div_rate is not None and div_rate > 0:
        out["eps_div_coverage"] = round(eps / div_rate, 1)

    return out


def _compute_5yr_roe_avg(tk):
    """
    Compute 5-year average ROE from historical income statement and
    balance sheet. yfinance returns 4 fiscal years by default in
    `income_stmt` and `balance_sheet`; we use whatever's available
    up to 5 and average. Returns None if fewer than 2 years available.

    ROE per year = Net Income / Stockholders Equity (period-end)
    """
    try:
        is_ = tk.income_stmt
        bs = tk.balance_sheet
        if is_ is None or bs is None or is_.empty or bs.empty:
            return None

        roes = []
        # Iterate up to 5 periods or whatever the shorter frame provides
        max_periods = min(5, len(is_.columns), len(bs.columns))

        for i in range(max_periods):
            try:
                is_col = is_.columns[i]
                bs_col = bs.columns[i] if i < len(bs.columns) else None
                if bs_col is None:
                    continue

                # Net income — try several label variants
                ni = None
                for k in ("Net Income", "Net Income Common Stockholders",
                         "Net Income Continuous Operations"):
                    if k in is_.index:
                        ni = _safe_float(is_.loc[k, is_col])
                        if ni is not None:
                            break

                # Equity — try several label variants
                eq = None
                for k in ("Stockholders Equity", "Common Stock Equity",
                         "Total Stockholder Equity"):
                    if k in bs.index:
                        eq = _safe_float(bs.loc[k, bs_col])
                        if eq is not None:
                            break

                if ni is not None and eq is not None and eq > 0:
                    roes.append((ni / eq) * 100)
            except Exception:
                continue

        if len(roes) < 2:
            return None

        return round(sum(roes) / len(roes), 1)
    except Exception:
        return None


# ── Per-ticker compute ────────────────────────────────────────────────────

def _compute_ticker(ticker, spx_hist):
    """
    Compute the full warbook metric set for a single ticker. spx_hist is
    the pre-fetched SPX/SPY daily history used for vs-SPX comparisons.

    Returns dict with all fields populated (None for missing values).
    """
    out = {
        # TR windows
        "tr_mtd": None, "tr_qtd": None, "tr_ytd": None,
        "tr_3m": None, "tr_1y": None,
        "tr_qtd_vs_spx": None, "tr_ytd_vs_spx": None,
        # Quality
        "roe_ttm": None, "roe_5y_avg": None,
        # Balance sheet
        "lt_debt_to_capital": None, "net_debt_to_capital": None,
        "debt_coverage_ratio": None,
        # Cash flow
        "fcf_yield": None, "fcf_div_coverage": None,
        "cf_div_coverage": None, "eps_div_coverage": None,
        "cash_flow_ev_yield": None,
        # Industry / geo
        "super_sector": None, "sub_industry": None, "country": None,
        "forward_pe": None,
    }

    try:
        import yfinance as yf
    except ImportError:
        return out

    try:
        tk = yf.Ticker(ticker)

        # Pull info once — used by multiple sub-computations
        try:
            info = tk.info or {}
        except Exception:
            info = {}

        # Fetch up to 1Y history with dividends. auto_adjust=True gives us
        # split-adjusted closes; dividends column is preserved separately
        # and we add them back for total return.
        try:
            hist = tk.history(period="1y", auto_adjust=True, actions=True)
        except Exception:
            hist = None

        # Total return windows
        for label in ("MTD", "QTD", "YTD", "3M", "1Y"):
            start, _ = _period_start_end(label)
            tr = _total_return_from_history(hist, start)
            out[f"tr_{label.lower()}"] = tr

        # vs-SPX windows: stock TR minus SPY TR for the same window
        for label in ("QTD", "YTD"):
            start, _ = _period_start_end(label)
            stock_tr = out[f"tr_{label.lower()}"]
            spx_tr = _total_return_from_history(spx_hist, start) if spx_hist is not None else None
            if stock_tr is not None and spx_tr is not None:
                out[f"tr_{label.lower()}_vs_spx"] = round(stock_tr - spx_tr, 2)

        # ROE TTM (already a percent in some yfinance versions, decimal in others)
        roe = _safe_float(info.get("returnOnEquity"))
        if roe is not None:
            # Heuristic: if |roe| < 5 it's almost certainly a decimal fraction
            out["roe_ttm"] = round(roe * 100, 1) if abs(roe) < 5 else round(roe, 1)

        # ROE 5-year average (slow path — separate financial statement query)
        out["roe_5y_avg"] = _compute_5yr_roe_avg(tk)

        # Balance sheet metrics
        bs_metrics = _compute_balance_sheet_metrics(tk)
        out.update(bs_metrics)

        # Cash flow metrics
        cf_metrics = _compute_cash_flow_metrics(tk, info)
        out.update(cf_metrics)

        # Sector / sub-industry / country / forward P/E
        sector_raw = info.get("sector", "") or ""
        out["super_sector"] = _SUPER_SECTOR_MAP.get(sector_raw)
        out["sub_industry"] = info.get("industry", "") or None
        out["country"] = info.get("country", "") or None

        fwd_pe = _safe_float(info.get("forwardPE"))
        if fwd_pe is not None:
            out["forward_pe"] = round(fwd_pe, 1)

    except Exception:
        # Soft-fail: leave the output dict with whatever we managed to fill
        pass

    return out


# ── Public API ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
@disk_cached(namespace="warbook", ttl=86400, version=1)
def fetch_warbook_metrics_batch(tickers_tuple):
    """
    Fetch warbook-specific metrics for a batch of tickers.

    Returns:
        { "TICK": {
              "tr_mtd": ..., "tr_qtd": ..., "tr_ytd": ...,
              "tr_3m": ..., "tr_1y": ...,
              "tr_qtd_vs_spx": ..., "tr_ytd_vs_spx": ...,
              "roe_ttm": ..., "roe_5y_avg": ...,
              "lt_debt_to_capital": ..., "net_debt_to_capital": ...,
              "debt_coverage_ratio": ...,
              "fcf_yield": ..., "fcf_div_coverage": ...,
              "cf_div_coverage": ..., "eps_div_coverage": ...,
              "cash_flow_ev_yield": ...,
              "super_sector": ..., "sub_industry": ..., "country": ...,
              "forward_pe": ...,
          },
          ...
        }

    Cold path is ~2-3 minutes for ~50 tickers (per-ticker income/balance
    sheet queries are slow). Disk cache makes that a once-per-day cost;
    subsequent calls within 24h read from disk in milliseconds.

    Errors during compute leave the affected fields as None — the caller
    is expected to render em dashes for missing data.
    """
    results = {}
    if not tickers_tuple:
        return results

    # Fetch SPX/SPY history once for vs-SPX comparisons. This avoids
    # re-fetching it for every ticker.
    try:
        import yfinance as yf
        spx_hist = yf.Ticker(_SPX_PROXY_TICKER).history(
            period="1y", auto_adjust=True, actions=True
        )
        if spx_hist is None or spx_hist.empty:
            spx_hist = None
    except Exception:
        spx_hist = None

    # Per-ticker compute with throttle
    for ticker in tickers_tuple:
        try:
            results[ticker] = _compute_ticker(ticker, spx_hist)
        except Exception:
            # Per-ticker failure shouldn't kill the whole batch
            results[ticker] = {}
        _time.sleep(_THROTTLE_SECONDS)

    return results


def get_warbook_metrics_for_ticker(ticker):
    """
    Convenience: get warbook metrics for a single ticker.
    Goes through the batch path so the disk cache is shared.
    """
    data = fetch_warbook_metrics_batch((ticker,))
    return data.get(ticker, {})