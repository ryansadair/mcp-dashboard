"""
Martin Capital Partners — Intraday Performance Chart
data/intraday_chart.py

Builds today's intraday performance chart for the Overview tab: a single
strategy line plus two reference lines (^GSPC / SPYD), all normalized to
% change from previous close.

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

from datetime import datetime, timedelta, time as _dttime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


# ── Index/ETF tickers used on the chart ──────────────────────────────────
# Sprint 20: dropped ^NDX (Nasdaq 100) and ^DJI (Dow Jones) in favor of
# SPYD (SPDR Portfolio S&P 500 High Dividend ETF), which lines up with
# QDVD's secondary benchmark in COMPOSITE_BENCHMARKS. ^GSPC stays as the
# primary broad-market reference. Tuple shape preserved so downstream
# render code in pages/1_Dashboard.py keeps working unchanged.
CHART_INDICES = [
    ("^GSPC", "S&P 500"),
    ("SPYD",  "SPYD"),
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


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_intraday_supabase(tickers_tuple):
    """
    Read today's 5-minute bars from Supabase `intraday_bars` — written by
    the quick-mode prefetch every 15 minutes from GitHub Actions.

    Added 2026-08-06 when Yahoo began returning empty for all sub-daily
    requests from Streamlit Cloud's IPs (daily still served). Same return
    contract as the direct fetch: {ticker: DataFrame[Close]} indexed by
    tz-aware UTC datetimes, plus a "__diag__" entry. 60s cache so the
    chart picks up each prefetch cycle promptly.
    """
    diag = {"requested": list(tickers_tuple), "rows": 0, "shape": "supabase",
            "columns_sample": None, "error": None}
    out = {t: pd.DataFrame() for t in tickers_tuple}
    try:
        from data.market_data import _sb_get
        start_utc = datetime.now(_PT).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(ZoneInfo("UTC")).isoformat()
        rows = _sb_get(
            "intraday_bars",
            select="ticker,ts,close",
            filters={"ts": f"gte.{start_utc}",
                     "ticker": f"in.({','.join(tickers_tuple)})",
                     "order": "ts.asc",
                     "limit": "20000"},
        )
        if not rows:
            diag["error"] = ("no intraday_bars rows for today (prefetch "
                             "not run yet, or its intraday fetch is blocked)")
            return {**out, "__diag__": diag}
        diag["rows"] = len(rows)
        by_t = {}
        for r in rows:
            by_t.setdefault(r["ticker"], []).append(r)
        for t, rws in by_t.items():
            if t not in out:
                continue
            idx = pd.to_datetime([r["ts"] for r in rws], utc=True)
            out[t] = pd.DataFrame({"Close": [r["close"] for r in rws]},
                                  index=idx)
    except Exception as e:
        diag["error"] = f"supabase read failed: {e}"
    return {**out, "__diag__": diag}


def _fetch_intraday_bars(tickers_tuple):
    """
    Router: Supabase-first (the pipeline that works), direct Yahoo as a
    fallback for environments where it still responds (local dev). If
    both come back empty the chart shows its placeholder and the diag
    (?debug=1) explains which layer failed.
    """
    sb = _fetch_intraday_supabase(tickers_tuple)
    if any(len(sb.get(t, [])) for t in tickers_tuple):
        return sb
    yf_res = _fetch_intraday_5m(tickers_tuple)
    if any(len(yf_res.get(t, [])) for t in tickers_tuple):
        return yf_res
    # neither worked — return the Supabase result but carry both diags
    sb_diag = dict(sb.get("__diag__", {}))
    sb_diag["yf_fallback"] = yf_res.get("__diag__", {})
    return {**sb, "__diag__": sb_diag}


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_intraday_5m(tickers_tuple):
    """
    Batch-fetch today's 5-minute bars for a tuple of tickers via yfinance.
    Cached 15 min. Returns dict of {ticker: DataFrame[Close]} indexed by
    timezone-aware datetime in UTC. Empty DataFrames for tickers with no
    data (early morning, weekends, errors).

    Also returns a sentinel under key "__diag__" with details about what
    yfinance returned (shape, sample columns, exception). Useful for
    debugging when a batch silently produces no data.
    """
    diag = {"requested": list(tickers_tuple), "rows": 0, "shape": None,
            "columns_sample": None, "error": None}

    if not tickers_tuple:
        return {"__diag__": {**diag, "error": "empty input"}}

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
    except Exception as e:
        diag["error"] = f"yf.download raised: {type(e).__name__}: {e}"
        return {**{t: pd.DataFrame() for t in tickers_tuple}, "__diag__": diag}

    if data is None or (hasattr(data, "empty") and data.empty):
        diag["error"] = "yf.download returned empty"
        return {**{t: pd.DataFrame() for t in tickers_tuple}, "__diag__": diag}

    diag["shape"] = str(getattr(data, "shape", "?"))
    diag["rows"] = len(data) if hasattr(data, "__len__") else 0
    if hasattr(data, "columns"):
        try:
            if isinstance(data.columns, pd.MultiIndex):
                diag["columns_sample"] = list(data.columns.get_level_values(0).unique())[:8]
            else:
                diag["columns_sample"] = list(data.columns)[:8]
        except Exception:
            pass

    result = {}
    multi = len(tickers_tuple) > 1 and hasattr(data, "columns") and isinstance(data.columns, pd.MultiIndex)

    for ticker in tickers_tuple:
        try:
            if multi:
                # Try direct lookup first; fall back to checking the level-0 names
                level0 = data.columns.get_level_values(0)
                if ticker in level0:
                    df = data[ticker]
                else:
                    result[ticker] = pd.DataFrame()
                    continue
            else:
                df = data

            if df is None or df.empty or "Close" not in df.columns:
                result[ticker] = pd.DataFrame()
                continue

            close = df[["Close"]].dropna()
            result[ticker] = close
        except Exception as e:
            diag.setdefault("ticker_errors", []).append(f"{ticker}: {type(e).__name__}: {e}")
            result[ticker] = pd.DataFrame()

    result["__diag__"] = diag
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
    Derive previous close from a quote dict. Handles two shapes:

      1. _fetch_market_quotes() shape: {price, change_pct, ...}
         (used for indices — same source as ticker bar)
      2. fetch_batch_prices() shape: {price, previous_close, change_1d_pct, ...}
         (used for holdings — Supabase-backed, includes every Tamarac ticker)

    Returns 0 if no usable values are present.
    """
    if not quote:
        return 0

    # Shape 2: previous_close stored directly (Supabase prices table)
    pc = quote.get("previous_close", 0) or 0
    if pc and pc > 0:
        return float(pc)

    # Shape 1: derive from price + change percentage
    price = quote.get("price", 0) or 0
    if price <= 0:
        return 0

    chg_pct = quote.get("change_pct", quote.get("change_1d_pct", 0)) or 0
    if chg_pct == 0:
        return float(price)
    return float(price) / (1.0 + chg_pct / 100.0)


def _append_live_point(x, y, live_chg, open_pt, close_pt):
    """
    Append the current live quote as the final point of an intraday series,
    so the line's endpoint always equals the value shown in the legend and
    the Daily Return KPI (both quote-driven and ~1-min fresh via Finviz),
    instead of lagging on the last cached 5-minute bar (up to 15 min old).

    Rules: only during/after today's session (never before the open), never
    plotted past the close, only appended when it's newer than the last bar,
    and only onto a line that already has bars (a lone point doesn't render).
    Mutates and returns (x, y).
    """
    if live_chg is None or not x:
        return x, y
    now_pt = datetime.now(_PT)
    if now_pt < open_pt:
        return x, y
    ts = min(now_pt, close_pt)
    last = x[-1]
    try:
        if ts <= last:
            return x, y
    except TypeError:
        return x, y
    x.append(ts)
    y.append(round(float(live_chg), 3))
    return x, y


def fetch_intraday_chart_data(active_strategy, tamarac_parsed, _retry=True):
    """
    Build the three series for the Overview intraday chart:
        - Active strategy (weighted average of holdings' intraday paths,
          cash-included denominator to match the Daily Return KPI)
        - ^GSPC (S&P 500) and SPYD (SPDR S&P 500 High Dividend ETF)

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
    from data.market_data import fetch_batch_prices
    from data.tamarac_parser import get_holdings_for_strategy, get_cash_weight

    open_pt, close_pt = _today_session_bounds_pt()

    # ── Index/ETF lines ─────────────────────────────────────────────────
    # _fetch_market_quotes() carries Markets-tab tickers (^GSPC plus the
    # other Markets-tab indices). If a ticker isn't there — e.g. SPYD,
    # added in Sprint 20 — we fall back to fetch_batch_prices() from
    # Supabase, which carries any ticker the prefetch pipeline has touched.
    # If neither has it, _intraday_pct_series returns empty and the trace
    # is skipped cleanly.
    quotes = _fetch_market_quotes() or {}
    idx_tickers = tuple(t for t, _ in CHART_INDICES)
    idx_intraday = _fetch_intraday_bars(idx_tickers)

    # Pull Supabase prices once for any ticker not in the Markets quote dict.
    _missing = tuple(t for t in idx_tickers if t not in quotes)
    idx_supabase_quotes = fetch_batch_prices(_missing) if _missing else {}

    index_series = []
    for ticker, label in CHART_INDICES:
        quote = quotes.get(ticker) or idx_supabase_quotes.get(ticker, {})
        prev = _prev_close_from_quote(quote)
        x, y = _intraday_pct_series(idx_intraday.get(ticker), prev)
        # Live endpoint from the same quote that supplied prev close —
        # SPYD rides the Finviz live layer; ^GSPC uses the freshest
        # index quote available (same source as the ticker bar).
        live_chg = quote.get("change_pct", quote.get("change_1d_pct", None))
        x, y = _append_live_point(x, y, live_chg, open_pt, close_pt)
        index_series.append({"ticker": ticker, "label": label, "x": x, "y": y})

    # ── Strategy line ───────────────────────────────────────────────────
    strategy_x, strategy_y = [], []
    holdings_intraday = {}  # always defined so the diag block below is safe

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
            holdings_intraday = _fetch_intraday_bars(tickers)
            # Holdings are not in _fetch_market_quotes (Markets-tab tickers only).
            # Pull from Supabase via fetch_batch_prices, which already has
            # previous_close stored for every Tamarac holding via the prefetch
            # pipeline. Same source as the Daily Return KPI.
            holdings_quotes = fetch_batch_prices(tickers)

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

                # Live endpoint: the current quote-weighted daily return —
                # by construction the SAME number as the Daily Return KPI
                # (same weights, same cash-included denominator, same
                # fetch_batch_prices quotes), so legend and KPI now agree.
                live_wsum = 0.0
                for _, row in holdings.iterrows():
                    q = holdings_quotes.get(row["symbol"], {})
                    live_wsum += float(row["weight"]) * float(q.get("change_1d_pct", 0) or 0)
                strategy_x, strategy_y = _append_live_point(
                    strategy_x, strategy_y, live_wsum / denom, open_pt, close_pt
                )

    result = {
        "strategy": {"name": active_strategy, "x": strategy_x, "y": strategy_y},
        "indices":  index_series,
        "session":  (open_pt, close_pt),
        "diag": {
            "indices_5m":  idx_intraday.get("__diag__", {}) if isinstance(idx_intraday, dict) else {},
            "holdings_5m": holdings_intraday.get("__diag__", {}) if isinstance(holdings_intraday, dict) else {},
        },
    }

    # ── Early-session cache-poisoning guard (2026-08-06) ───────────────────
    # The first render after the open can ask Yahoo before ANY 5-min bar
    # for today exists; that empty answer then sits in the 15-minute cache
    # and the chart stays blank until expiry even though bars appear within
    # minutes (observed: blank at 6:44 AM while Yahoo already had 4 bars).
    # If every line is empty during the first 45 minutes of the session,
    # drop the cached fetch and retry ONCE immediately — if Yahoo has bars
    # by now the chart appears this run instead of at cache expiry.
    _all_empty = (not result["strategy"]["x"]
                  and not any(s["x"] for s in result["indices"]))
    if _all_empty and _retry:
        _now_pt = datetime.now(_PT)
        if open_pt <= _now_pt <= open_pt + timedelta(minutes=45):
            try:
                _fetch_intraday_supabase.clear()
                _fetch_intraday_5m.clear()
            except Exception:
                pass
            return fetch_intraday_chart_data(active_strategy, tamarac_parsed,
                                             _retry=False)

    return result