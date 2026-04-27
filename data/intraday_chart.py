"""
Martin Capital Partners — Intraday Performance Chart
data/intraday_chart.py

Builds today's intraday performance chart for the Overview tab: a single
strategy line plus three index reference lines (^NDX / ^GSPC / ^DJI),
all normalized to % change from previous close.

Data path:
  - Index intraday paths: yf.download(period="1d", interval="5m") for the
    three indices, cached 15 min. Endpoints are anchored to the same prev-
    close used by _fetch_market_quotes() in markets_tab.py, which is what
    the ticker bar displays — so the chart's last point matches the ticker
    bar by construction.
  - Strategy line: weighted average of holdings' intraday paths, computed
    from the same 5-minute yfinance batch. Weights come from Tamarac. The
    cash weight is included in the denominator so the endpoint matches
    the "Daily Return" KPI card formula exactly.

Numbers are computed live; nothing here writes to Supabase. The 15-min
@st.cache_data TTL keeps cold-path cost low (~1-2s per strategy switch
per cache window).
"""

from datetime import datetime, time as _dttime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


# ── Index tickers used on the chart (matches ticker bar labels) ──────────
# Ticker → display label. ^NDX is "Nasdaq 100" everywhere on the dashboard.
CHART_INDICES = [
    ("^GSPC", "S&P 500"),
    ("^NDX",  "Nasdaq 100"),
    ("^DJI",  "Dow Jones"),
]

# Trading session bounds in US/Eastern, displayed in US/Pacific
_ET = ZoneInfo("America/New_York")
_PT = ZoneInfo("America/Los_Angeles")
_SESSION_OPEN_ET  = _dttime(9, 30)   # 9:30 AM ET = 6:30 AM PT
_SESSION_CLOSE_ET = _dttime(16, 30)  # 4:30 PM ET = 1:30 PM PT (30-min margin past close)


def _today_session_bounds_pt():
    """
    Return (open_dt_pt, close_dt_pt) for today's regular trading session,
    in Pacific time. Used to anchor the chart's x-axis range so it shows
    the full day from market open even when only part of the session has
    elapsed.
    """
    now_et = datetime.now(_ET)
    # Anchor on TODAY's calendar date in ET (handles weekends/after-hours
    # gracefully — the chart still draws the full session window)
    open_et  = datetime.combine(now_et.date(), _SESSION_OPEN_ET,  tzinfo=_ET)
    close_et = datetime.combine(now_et.date(), _SESSION_CLOSE_ET, tzinfo=_ET)
    return open_et.astimezone(_PT), close_et.astimezone(_PT)


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_intraday_5m(tickers_tuple):
    """
    Batch-fetch today's 5-minute bars for a tuple of tickers via yfinance.
    Cached 15 min. Returns dict of {ticker: DataFrame[Close]} indexed by
    timezone-aware datetime in UTC. Empty DataFrames for tickers with no
    data (early morning, weekends, errors).
    """
    if not tickers_tuple:
        return {}

    try:
        import yfinance as yf
        data = yf.download(
            tickers=" ".join(tickers_tuple),
            period="1d",
            interval="5m",
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
    except Exception:
        return {t: pd.DataFrame() for t in tickers_tuple}

    result = {}
    multi = len(tickers_tuple) > 1 and hasattr(data, "columns") and isinstance(data.columns, pd.MultiIndex)

    for ticker in tickers_tuple:
        try:
            if multi and ticker in data.columns.get_level_values(0):
                df = data[ticker]
            elif not multi:
                df = data
            else:
                result[ticker] = pd.DataFrame()
                continue

            if df is None or df.empty or "Close" not in df.columns:
                result[ticker] = pd.DataFrame()
                continue

            # Keep just Close, drop NaN. Index is already tz-aware (yfinance)
            close = df[["Close"]].dropna()
            result[ticker] = close
        except Exception:
            result[ticker] = pd.DataFrame()

    return result


def _intraday_pct_series(close_df, prev_close):
    """
    Convert a Close-price DataFrame into a % change vs prev_close series.
    Returns (datetime_index_pt, pct_values) lists, ready for Plotly.
    Returns ([], []) if data is missing or prev_close is invalid.
    """
    if close_df is None or close_df.empty or not prev_close or prev_close <= 0:
        return [], []

    # Compute % vs prev close
    pct = (close_df["Close"] / prev_close - 1.0) * 100.0

    # Convert index to PT for display (yfinance returns tz-aware UTC or ET)
    idx = close_df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx_pt = idx.tz_convert(_PT)

    return list(idx_pt), [round(v, 3) for v in pct.values]


def _prev_close_from_quote(quote):
    """
    Derive previous close from a _fetch_market_quotes()-style quote dict.
    Quote has {price, change_pct}; prev_close = price / (1 + change_pct/100).
    Returns 0 if either value is missing.
    """
    if not quote:
        return 0
    price = quote.get("price", 0) or 0
    chg_pct = quote.get("change_pct", 0) or 0
    if price <= 0:
        return 0
    if chg_pct == 0:
        # No change today — prev close == current price (still fine to use)
        return price
    return price / (1.0 + chg_pct / 100.0)


def fetch_intraday_chart_data(active_strategy, tamarac_parsed):
    """
    Build the four series for the Overview intraday chart:
        - Active strategy (weighted average of holdings' intraday paths,
          cash-included denominator to match the Daily Return KPI)
        - ^NDX / ^GSPC / ^DJI

    Returns a dict:
        {
          "strategy":  {"name": "QDVD", "x": [...], "y": [...]},
          "indices":   [
              {"ticker": "^GSPC", "label": "S&P 500", "x": [...], "y": [...]},
              ...
          ],
          "session":   (open_dt_pt, close_dt_pt),
        }

    Empty x/y lists indicate data wasn't available for that line. The chart
    render code handles this gracefully by skipping the trace.

    Performance: ~1-2s on cold cache (one batched yf.download for indices +
    one for the strategy's holdings). Within the 15-min cache window all
    calls are instant.
    """
    # Lazy-import to keep this module light on import (matches Markets tab)
    from data.markets_tab import _fetch_market_quotes
    from data.tamarac_parser import get_holdings_for_strategy, get_cash_weight

    open_pt, close_pt = _today_session_bounds_pt()

    # ── Index lines ─────────────────────────────────────────────────────
    quotes = _fetch_market_quotes() or {}
    idx_tickers = tuple(t for t, _ in CHART_INDICES)
    idx_intraday = _fetch_intraday_5m(idx_tickers)

    index_series = []
    for ticker, label in CHART_INDICES:
        prev = _prev_close_from_quote(quotes.get(ticker, {}))
        x, y = _intraday_pct_series(idx_intraday.get(ticker), prev)
        index_series.append({"ticker": ticker, "label": label, "x": x, "y": y})

    # ── Strategy line ───────────────────────────────────────────────────
    strategy_x, strategy_y = [], []

    if tamarac_parsed and active_strategy in tamarac_parsed:
        holdings = get_holdings_for_strategy(tamarac_parsed, active_strategy)
        cash_pct = get_cash_weight(tamarac_parsed, active_strategy)  # 0-100

        if not holdings.empty:
            # Tamarac weights are decimals (e.g. 0.024 = 2.4%). cash_pct is a
            # percentage (e.g. 9.68 = 9.68%). To compute the same weighted
            # daily return as the KPI card:
            #   weighted_chg = Σ(weight_decimal × change_pct)
            #   daily_return = weighted_chg / total_portfolio_weight
            # where total_portfolio_weight = Σ(equity weights) + cash_decimal.
            # That cash term in the denominator dampens the return — same as
            # _render_strategy_header in 1_Dashboard.py.
            equity_weight = float(holdings["weight"].sum())
            cash_decimal  = cash_pct / 100.0
            denom = equity_weight + cash_decimal

            tickers = tuple(holdings["symbol"].tolist())
            holdings_intraday = _fetch_intraday_5m(tickers)
            holdings_quotes = quotes  # already fetched above; same dict

            # Build per-ticker pct series, aligned to a common time index.
            # We pick the first non-empty series as the master timeline so
            # holdings with sparse data (e.g. low-volume bars) don't break
            # the alignment.
            per_ticker_pct = {}
            master_idx = None
            for _, row in holdings.iterrows():
                sym = row["symbol"]
                prev = _prev_close_from_quote(holdings_quotes.get(sym, {}))
                close_df = holdings_intraday.get(sym)
                if close_df is None or close_df.empty or prev <= 0:
                    continue
                idx_pt, pct_vals = _intraday_pct_series(close_df, prev)
                if not idx_pt:
                    continue
                s = pd.Series(pct_vals, index=pd.DatetimeIndex(idx_pt))
                per_ticker_pct[sym] = s
                if master_idx is None or len(s) > len(master_idx):
                    master_idx = s.index

            if per_ticker_pct and master_idx is not None and denom > 0:
                # Reindex every series to the master timeline; forward-fill
                # short gaps so a missing bar doesn't drop the holding from
                # that timestamp's weighted average.
                weighted = pd.Series(0.0, index=master_idx)
                for _, row in holdings.iterrows():
                    sym = row["symbol"]
                    if sym not in per_ticker_pct:
                        continue
                    wt_decimal = float(row["weight"])
                    s = per_ticker_pct[sym].reindex(master_idx).ffill()
                    weighted = weighted.add(s * wt_decimal, fill_value=0.0)

                # Divide by total portfolio weight (cash-included)
                weighted = weighted / denom

                strategy_x = list(weighted.index)
                strategy_y = [round(v, 3) for v in weighted.values]

    return {
        "strategy": {"name": active_strategy, "x": strategy_x, "y": strategy_y},
        "indices":  index_series,
        "session":  (open_pt, close_pt),
    }
