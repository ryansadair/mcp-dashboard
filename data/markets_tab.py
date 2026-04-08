"""
Martin Capital Partners — Markets Tab
data/markets_tab.py

Single-page market overview inspired by Koyfin's layout.
All data from one batched yfinance call (~30 tickers), cached 15 min.

Sections:
  1. U.S. Indices (SPX, DJIA, NDX, RTY, VIX)
  2. S&P Sector ETFs (11 sectors)
  3. Fixed Income ETFs (Govt, IG, HY, Munis, TIPS, Convertibles)
  4. Global Markets (Developed + Emerging ETFs)
  5. Commodities (Gold, Oil, Nat Gas, Brent)
"""

import streamlit as st
import pandas as pd
from datetime import datetime

# ── Ticker Universe ────────────────────────────────────────────────────────

INDICES = [
    ("Nasdaq 100",         "^NDX"),
    ("Dow Jones 30",       "^DJI"),
    ("Russell 2000",       "^RUT"),
    ("Russell 1000 Value", "^RLV"),
    ("Russell 1000 Growth","^RLG"),
    ("US Agg Bond",        "AGG"),
]

DIVIDEND_BENCHMARKS = [
    ("S&P 500",                          "^GSPC"),
    ("S&P 500 High Div",                 "SPYD"),
    ("S&P Div Aristocrats (SDY)",        "SDY"),
    ("S&P MCap Div Aristocrats (REGL)",  "REGL"),
    ("S&P MidCap 400",                   "^SP400"),
    ("Russell 3000",                     "^RUA"),
    ("Intl Dividend (DWX)",              "DWX"),
    ("Dow Select Dividend (DVY)",        "DVY"),
]

SECTORS = [
    ("Technology",          "XLK"),
    ("Healthcare",          "XLV"),
    ("Financials",          "XLF"),
    ("Cons. Discretionary", "XLY"),
    ("Cons. Staples",       "XLP"),
    ("Industrials",         "XLI"),
    ("Energy",              "XLE"),
    ("Utilities",           "XLU"),
    ("Real Estate",         "XLRE"),
    ("Materials",           "XLB"),
    ("Communications",      "XLC"),
]

FIXED_INCOME = [
    ("10Y Treasury Yield", "^TNX"),
    ("U.S. Treasuries", "GOVT"),
    ("T.I.P.S.",        "TIP"),
    ("High Grade",      "LQD"),
    ("High Yield",      "HYG"),
    ("Municipals",      "MUB"),
    ("Convertibles",    "CWB"),
]

GLOBAL_DEVELOPED = [
    ("Developed (Broad)", "EFA"),
    ("Japan",             "EWJ"),
    ("United Kingdom",    "EWU"),
    ("Germany",           "EWG"),
    ("Australia",         "EWA"),
    ("France",            "EWQ"),
]

GLOBAL_EMERGING = [
    ("Emerging (Broad)", "EEM"),
    ("China",            "FXI"),
    ("India",            "EPI"),
    ("Brazil",           "EWZ"),
    ("Mexico",           "EWW"),
    ("South Korea",      "EWY"),
    ("South Africa",     "EZA"),
]

COMMODITIES = [
    ("Gold",        "GC=F"),
    ("Silver",      "SI=F"),
    ("Crude Oil",   "CL=F"),
    ("Brent Crude", "BZ=F"),
    ("Natural Gas", "NG=F"),
    ("Copper",      "HG=F"),
    ("Bitcoin",     "BTC-USD"),
]

# US Equity Factors — Morningstar-style 3x3 grid (iShares Russell ETFs)
# Rows: Large, Mid, Small  |  Columns: Value, Core, Growth
STYLE_BOX = [
    ("Large", [("Value", "IWD"), ("Core", "IWB"), ("Growth", "IWF")]),
    ("Mid",   [("Value", "IWS"), ("Core", "IWR"), ("Growth", "IWP")]),
    ("Small", [("Value", "IWN"), ("Core", "IWM"), ("Growth", "IWO")]),
]
_STYLE_BOX_TICKERS = [t for _, cols in STYLE_BOX for _, t in cols]

# Tickers for the normalized performance chart (actual indices, not ETF proxies)
PERF_CHART_TICKERS = {
    "^GSPC": ("S&P 500", "#6b8afc"),
    "^NDX":  ("Nasdaq 100", "#c084fc"),
    "^RUT":  ("Russell 2000", "#fbbf24"),
    "^DJI":  ("Dow Jones", "#f97066"),
}

PERF_PERIODS = {
    "1D":  {"period": "1d",  "interval": "5m"},
    "1M":  {"period": "1mo", "interval": "1h"},
    "3M":  {"period": "3mo", "interval": "1d"},
    "6M":  {"period": "6mo", "interval": "1d"},
    "YTD": {"period": "ytd", "interval": "1d"},
    "1Y":  {"period": "1y",  "interval": "1d"},
    "3Y":  {"period": "3y",  "interval": "1wk"},
    "5Y":  {"period": "5y",  "interval": "1wk"},
    "Max": {"period": "max", "interval": "1mo"},
}


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_perf_chart_data(period_key):
    """
    Fetch normalized performance data for the index comparison chart.
    For 1D: uses 5-min intraday bars, normalized from the same previous
            close that _fetch_market_quotes uses (ensures chart matches tables).
    For longer periods: uses daily/weekly bars, normalized from first close.
    Returns dict: {ticker: pd.Series of % change}
    """
    try:
        import yfinance as yf

        cfg = PERF_PERIODS.get(period_key, PERF_PERIODS["1D"])

        if period_key == "1D":
            # Get previous close from the same data the tables use
            quotes = _fetch_market_quotes()

            # Fetch intraday bars for the index tickers
            tickers_str = " ".join(PERF_CHART_TICKERS.keys())
            intraday = yf.download(
                tickers_str, period="1d", interval="5m",
                group_by="ticker", progress=False, threads=True,
            )

            result = {}
            for ticker in PERF_CHART_TICKERS:
                try:
                    i_df = intraday[ticker] if ticker in intraday.columns.get_level_values(0) else None
                    if i_df is None or i_df.empty:
                        continue

                    i_close = i_df["Close"].dropna()
                    if hasattr(i_close, "columns"):
                        i_close = i_close.iloc[:, 0]
                    if len(i_close) < 1:
                        continue

                    # Derive prev close from the same quote data the tables use
                    q = quotes.get(ticker, {})
                    price_now = q.get("price", 0)
                    chg_pct = q.get("change_pct", 0)

                    if price_now > 0 and chg_pct != 0:
                        prev_close = price_now / (1 + chg_pct / 100)
                    else:
                        prev_close = float(i_close.iloc[0])

                    if prev_close > 0:
                        pct = ((i_close / prev_close) - 1) * 100
                        # Convert UTC timestamps to Pacific for display
                        try:
                            from zoneinfo import ZoneInfo
                            pct.index = pct.index.tz_convert(ZoneInfo("America/Los_Angeles"))
                        except Exception:
                            pass
                        result[ticker] = pct
                except Exception:
                    continue
            return result

        else:
            # Longer periods: normalize from first close
            tickers_str = " ".join(PERF_CHART_TICKERS.keys())
            data = yf.download(
                tickers_str,
                period=cfg["period"],
                interval=cfg["interval"],
                group_by="ticker",
                progress=False,
                threads=True,
            )

            result = {}
            for ticker in PERF_CHART_TICKERS:
                try:
                    df = data[ticker] if ticker in data.columns.get_level_values(0) else None
                    if df is None or df.empty:
                        continue
                    close = df["Close"].dropna()
                    if hasattr(close, "columns"):
                        close = close.iloc[:, 0]
                    if len(close) < 2:
                        continue
                    base = float(close.iloc[0])
                    if base > 0:
                        pct = ((close / base) - 1) * 100
                        result[ticker] = pct
                except Exception:
                    continue
            return result
    except Exception:
        return {}


def _render_perf_chart(period_key="1D"):
    """Render the normalized performance Plotly chart."""
    import plotly.graph_objects as go

    chart_data = _fetch_perf_chart_data(period_key)
    if not chart_data:
        st.markdown(
            '<div style="padding:40px;text-align:center;color:rgba(255,255,255,0.3);'
            'font-size:13px;">Chart data unavailable</div>',
            unsafe_allow_html=True,
        )
        return

    fig = go.Figure()

    for ticker, pct_series in chart_data.items():
        name, color = PERF_CHART_TICKERS[ticker]
        final_pct = float(pct_series.iloc[-1])
        fig.add_trace(go.Scatter(
            x=pct_series.index,
            y=pct_series.values,
            name=f"{name}  {final_pct:+.2f}%",
            line=dict(color=color, width=2),
            hovertemplate=f"{name}<br>%{{x}}<br>%{{y:+.2f}}%<extra></extra>",
        ))

    # Zero line
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.15)", width=1, dash="dot"))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="rgba(255,255,255,0.5)", size=10),
        margin=dict(l=45, r=10, t=10, b=10),
        height=340,
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            showline=False,
            tickfont=dict(size=9),
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            showline=False,
            tickfont=dict(size=10),
            ticksuffix="%",
            zeroline=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        hovermode="x unified",
        showlegend=True,
    )

    st.plotly_chart(fig, use_container_width=True, config={
        "displayModeBar": False, "scrollZoom": False,
        "doubleClick": False, "showTips": False, "staticPlot": True,
    })


# ── Section Charts ─────────────────────────────────────────────────────────
# Color palette for section-level multi-line charts (up to ~12 lines)
_SECTION_COLORS = [
    "#6b8afc", "#c084fc", "#fbbf24", "#f97066", "#569542",
    "#34d399", "#f472b6", "#C9A84C", "#60a5fa", "#a78bfa",
    "#fb923c", "#07415A",
]

# Chart period options — same as the normalized perf chart at top of tab
SECTION_CHART_PERIODS = {
    "1D":  {"period": "1d",  "interval": "5m"},
    "1M":  {"period": "1mo", "interval": "1h"},
    "3M":  {"period": "3mo", "interval": "1d"},
    "6M":  {"period": "6mo", "interval": "1d"},
    "YTD": {"period": "ytd", "interval": "1d"},
    "1Y":  {"period": "1y",  "interval": "1d"},
    "3Y":  {"period": "3y",  "interval": "1wk"},
    "5Y":  {"period": "5y",  "interval": "1wk"},
    "Max": {"period": "max", "interval": "1mo"},
}


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_section_chart_data(tickers_tuple, period_key):
    """
    Fetch normalized % change data for a group of tickers.
    tickers_tuple: tuple of (name, ticker) pairs (must be hashable for caching).
    Returns dict: {ticker: pd.Series of % change}
    """
    try:
        import yfinance as yf

        cfg = SECTION_CHART_PERIODS.get(period_key, SECTION_CHART_PERIODS["1D"])
        ticker_list = [t for _, t in tickers_tuple]
        tickers_str = " ".join(ticker_list)

        if period_key == "1D":
            # Intraday: normalize from previous close via _fetch_market_quotes
            quotes = _fetch_market_quotes()
            intraday = yf.download(
                tickers_str, period="1d", interval="5m",
                group_by="ticker", progress=False, threads=True,
            )
            result = {}
            for _, ticker in tickers_tuple:
                try:
                    if len(ticker_list) == 1:
                        i_df = intraday
                    else:
                        i_df = intraday[ticker] if ticker in intraday.columns.get_level_values(0) else None
                    if i_df is None or i_df.empty:
                        continue
                    i_close = i_df["Close"].dropna()
                    if hasattr(i_close, "columns"):
                        i_close = i_close.iloc[:, 0]
                    if len(i_close) < 1:
                        continue
                    q = quotes.get(ticker, {})
                    price_now = q.get("price", 0)
                    chg_pct = q.get("change_pct", 0)
                    if price_now > 0 and chg_pct != 0:
                        prev_close = price_now / (1 + chg_pct / 100)
                    else:
                        prev_close = float(i_close.iloc[0])
                    if prev_close > 0:
                        pct = ((i_close / prev_close) - 1) * 100
                        try:
                            from zoneinfo import ZoneInfo
                            pct.index = pct.index.tz_convert(ZoneInfo("America/Los_Angeles"))
                        except Exception:
                            pass
                        result[ticker] = pct
                except Exception:
                    continue
            return result
        else:
            # Longer periods: normalize from first close
            data = yf.download(
                tickers_str,
                period=cfg["period"],
                interval=cfg["interval"],
                group_by="ticker",
                progress=False,
                threads=True,
            )
            result = {}
            for _, ticker in tickers_tuple:
                try:
                    if len(ticker_list) == 1:
                        df = data
                    else:
                        df = data[ticker] if ticker in data.columns.get_level_values(0) else None
                    if df is None or df.empty:
                        continue
                    close = df["Close"].dropna()
                    if hasattr(close, "columns"):
                        close = close.iloc[:, 0]
                    if len(close) < 2:
                        continue
                    base = float(close.iloc[0])
                    if base > 0:
                        pct = ((close / base) - 1) * 100
                        result[ticker] = pct
                except Exception:
                    continue
            return result
    except Exception:
        return {}


def _render_section_chart(items, period_key, session_key):
    """
    Render a normalized % change Plotly chart for a section of tickers.
    items: list of (name, ticker) pairs.
    Matches exact styling of performance_tab charts:
      - PLOTLY_DARK theme, crosshair spikes, fixedrange, no zoom on mobile
    """
    import plotly.graph_objects as go

    chart_data = _fetch_section_chart_data(tuple(items), period_key)
    if not chart_data:
        st.markdown(
            '<div style="padding:40px;text-align:center;color:rgba(255,255,255,0.3);'
            'font-size:13px;">Chart data unavailable</div>',
            unsafe_allow_html=True,
        )
        return

    fig = go.Figure()
    name_map = {t: n for n, t in items}

    for idx, (ticker, pct_series) in enumerate(chart_data.items()):
        name = name_map.get(ticker, ticker)
        color = _SECTION_COLORS[idx % len(_SECTION_COLORS)]
        final_pct = float(pct_series.iloc[-1])
        fig.add_trace(go.Scatter(
            x=pct_series.index,
            y=pct_series.values,
            name=f"{name}  {final_pct:+.2f}%",
            line=dict(color=color, width=2),
            hovertemplate=f"{name}<br>%{{x}}<br>%{{y:+.2f}}%<extra></extra>",
        ))

    # Zero line
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.15)", width=1, dash="dot"))

    # Spike / crosshair axes — matches performance_tab pattern exactly
    _spike = dict(
        showspikes=True, spikecolor="rgba(255,255,255,0.15)",
        spikethickness=1, spikemode="across", spikedash="solid",
    )
    _xaxis = dict(gridcolor="rgba(255,255,255,0.04)", showline=False,
                  tickfont=dict(size=9), fixedrange=True, **_spike)
    _yaxis = dict(gridcolor="rgba(255,255,255,0.04)", showline=False,
                  tickfont=dict(size=10), ticksuffix="%", zeroline=False,
                  fixedrange=True, **_spike)

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="rgba(255,255,255,0.5)", size=10),
        margin=dict(l=45, r=10, t=10, b=10),
        height=340,
        xaxis=_xaxis,
        yaxis=_yaxis,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        hovermode="x unified",
        dragmode=False,
        showlegend=True,
    )

    st.plotly_chart(fig, use_container_width=True, config={
        "displayModeBar": False, "scrollZoom": False,
        "doubleClick": False, "showTips": False, "staticPlot": True,
    })


def _render_section_with_periods(title, items, session_prefix):
    """Render a section header + period selector + chart."""
    st.markdown(_section_header(title), unsafe_allow_html=True)

    period_cols = st.columns(len(SECTION_CHART_PERIODS))
    skey = f"mkt_chart_{session_prefix}"
    selected = st.session_state.get(skey, "1D")
    for i, pkey in enumerate(SECTION_CHART_PERIODS):
        with period_cols[i]:
            if st.button(pkey, key=f"{skey}_{pkey}", use_container_width=True,
                         type="primary" if pkey == selected else "secondary"):
                st.session_state[skey] = pkey
                selected = pkey

    _render_section_chart(items, selected, skey)

# Collect all tickers for batch fetch
_ALL_GROUPS = [INDICES, DIVIDEND_BENCHMARKS, SECTORS, FIXED_INCOME, GLOBAL_DEVELOPED, GLOBAL_EMERGING, COMMODITIES]
_ALL_TICKERS = []
for group in _ALL_GROUPS:
    for _, ticker in group:
        if ticker not in _ALL_TICKERS:
            _ALL_TICKERS.append(ticker)
for t in _STYLE_BOX_TICKERS:
    if t not in _ALL_TICKERS:
        _ALL_TICKERS.append(t)
for t in PERF_CHART_TICKERS:
    if t not in _ALL_TICKERS:
        _ALL_TICKERS.append(t)

# Extra tickers needed by the scrolling ticker bar (not in any table group)
_TICKER_BAR_EXTRAS = ["^IXIC", "DX-Y.NYB"]
for t in _TICKER_BAR_EXTRAS:
    if t not in _ALL_TICKERS:
        _ALL_TICKERS.append(t)


# ── Data Fetching ──────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_market_quotes():
    """
    Batch-fetch price and change data for all market tickers.
    Returns dict: {ticker: {price, change, change_pct}}
    """
    try:
        import yfinance as yf
        tickers_str = " ".join(_ALL_TICKERS)
        data = yf.download(
            tickers_str,
            period="1y",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )

        result = {}
        for ticker in _ALL_TICKERS:
            try:
                if len(_ALL_TICKERS) == 1:
                    df = data
                else:
                    df = data[ticker] if ticker in data.columns.get_level_values(0) else None

                if df is None or df.empty:
                    result[ticker] = {"price": 0, "change": 0, "change_pct": 0, "high_52w": 0, "pct_from_high": 0}
                    continue

                # Drop NaN rows
                df = df.dropna(subset=["Close"])
                if len(df) < 1:
                    result[ticker] = {"price": 0, "change": 0, "change_pct": 0, "high_52w": 0, "pct_from_high": 0}
                    continue

                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
                chg = close - prev
                chg_pct = (chg / prev * 100) if prev != 0 else 0

                # 52-week high from the full year of data
                high_52w = float(df["High"].max()) if "High" in df.columns else close
                pct_from_high = ((close - high_52w) / high_52w * 100) if high_52w > 0 else 0

                result[ticker] = {
                    "price": round(close, 2),
                    "change": round(chg, 2),
                    "change_pct": round(chg_pct, 2),
                    "high_52w": round(high_52w, 2),
                    "pct_from_high": round(pct_from_high, 1),
                }
            except Exception:
                result[ticker] = {"price": 0, "change": 0, "change_pct": 0, "high_52w": 0, "pct_from_high": 0}

        return result
    except Exception:
        return {t: {"price": 0, "change": 0, "change_pct": 0, "high_52w": 0, "pct_from_high": 0} for t in _ALL_TICKERS}


# ── Rendering Helpers ──────────────────────────────────────────────────────

def _chg_color(val):
    """Return green/red/neutral color based on value."""
    if val > 0:
        return "#569542"
    elif val < 0:
        return "#c45454"
    return "rgba(255,255,255,0.4)"


def _render_market_table(items, quotes, show_pct=True, section_label=None):
    """
    Render a compact HTML table for a list of (name, ticker) items.
    Includes a '% From High' column showing distance from 52-week high.
    """
    # Header
    header_cols = (
        '<col style="width:34%"><col style="width:12%">'
        '<col style="width:18%"><col style="width:20%"><col style="width:16%">'
    )
    th_style = (
        "padding:6px 8px;font-size:10px;font-weight:600;"
        "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
        "border-bottom:1px solid rgba(255,255,255,0.06)"
    )

    html = f'<table style="width:100%;border-collapse:collapse;table-layout:fixed"><colgroup>{header_cols}</colgroup>'
    html += f'<thead><tr>'
    html += f'<th style="text-align:left;{th_style}">{section_label or "Name"}</th>'
    html += f'<th style="text-align:right;{th_style}">Ticker</th>'
    html += f'<th style="text-align:right;{th_style}">Price</th>'
    html += f'<th style="text-align:right;{th_style}">Chg / %</th>'
    html += f'<th style="text-align:right;{th_style}">% From High</th>'
    html += '</tr></thead><tbody>'

    for name, ticker in items:
        q = quotes.get(ticker, {})
        price = q.get("price", 0)
        chg = q.get("change", 0)
        pct = q.get("change_pct", 0)
        pct_from_high = q.get("pct_from_high", 0)
        color = _chg_color(pct)

        # Format price
        if price >= 10000:
            price_str = f"{price:,.0f}"
        elif price >= 100:
            price_str = f"{price:,.2f}"
        else:
            price_str = f"{price:.2f}"

        # Format change
        chg_str = f"{chg:+.2f}"
        pct_str = f"{pct:+.2f}%"

        # Format % from high — always negative or zero
        if pct_from_high == 0 and price > 0:
            from_high_str = "AT HIGH"
            from_high_color = "#569542"
        elif pct_from_high != 0:
            from_high_str = f"{pct_from_high:.2f}%"
            from_high_color = "#c45454"
        else:
            from_high_str = "—"
            from_high_color = "rgba(255,255,255,0.3)"

        # Highlight background for big movers (>2%)
        bg = ""
        if abs(pct) >= 2:
            bg_color = "rgba(86,149,66,0.08)" if pct > 0 else "rgba(196,84,84,0.08)"
            bg = f"background:{bg_color};"

        html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03);{bg}">'
            f'<td style="text-align:left;padding:8px 8px;font-size:13px;font-weight:500;'
            f'color:rgba(255,255,255,0.75)">{name}</td>'
            f'<td style="text-align:right;padding:8px 8px;font-size:12px;'
            f'color:rgba(255,255,255,0.35);font-family:monospace">{ticker}</td>'
            f'<td style="text-align:right;padding:8px 8px;font-size:13px;font-weight:600;'
            f'color:rgba(255,255,255,0.9)">{price_str}</td>'
            f'<td style="text-align:right;padding:8px 8px;font-size:12px;font-weight:500;'
            f'color:{color}">{chg_str}&nbsp;&nbsp;{pct_str}</td>'
            f'<td style="text-align:right;padding:8px 8px;font-size:12px;font-weight:500;'
            f'color:{from_high_color}">{from_high_str}</td>'
            f'</tr>'
        )

    html += '</tbody></table>'
    return html


def _section_header(title):
    return (
        f'<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        f'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        f'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:4px">'
        f'{title}</div>'
    )


def _render_style_box(quotes):
    """
    Render a Koyfin-inspired 3x3 US Equity Factors heatmap.
    Color intensity scales with magnitude of daily change.
    """
    col_labels = ["Value", "Core", "Growth"]

    # Find max absolute change for color scaling
    all_pcts = []
    for _, cols in STYLE_BOX:
        for _, ticker in cols:
            pct = quotes.get(ticker, {}).get("change_pct", 0)
            all_pcts.append(abs(pct))
    max_abs = max(all_pcts) if all_pcts and max(all_pcts) > 0 else 1

    def _cell_bg(pct):
        """Return background color with intensity based on magnitude."""
        intensity = min(abs(pct) / max(max_abs, 0.5), 1.0)
        if pct > 0:
            # Green scale
            r, g, b = 86, 149, 66
            alpha = 0.15 + intensity * 0.55
        elif pct < 0:
            # Red scale
            r, g, b = 196, 84, 84
            alpha = 0.15 + intensity * 0.55
        else:
            return "rgba(255,255,255,0.04)"
        return f"rgba({r},{g},{b},{alpha:.2f})"

    # Build HTML grid
    html = '<div style="margin-top:8px;">'

    # Column headers
    html += '<div style="display:flex;gap:4px;margin-bottom:4px;margin-left:52px;">'
    for cl in col_labels:
        html += (
            f'<div style="flex:1;text-align:center;font-size:10px;font-weight:600;'
            f'color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.06em;">'
            f'{cl}</div>'
        )
    html += '</div>'

    # Rows
    for row_label, cols in STYLE_BOX:
        html += '<div style="display:flex;gap:4px;margin-bottom:4px;align-items:stretch;">'

        # Row label
        html += (
            f'<div style="width:48px;display:flex;align-items:center;font-size:10px;font-weight:600;'
            f'color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.04em;">'
            f'{row_label}</div>'
        )

        # Cells
        for _, ticker in cols:
            pct = quotes.get(ticker, {}).get("change_pct", 0)
            bg = _cell_bg(pct)
            text_color = "rgba(255,255,255,0.9)" if abs(pct) > 0.3 else "rgba(255,255,255,0.6)"

            html += (
                f'<div style="flex:1;background:{bg};border-radius:6px;padding:24px 8px;'
                f'text-align:center;min-height:72px;display:flex;align-items:center;justify-content:center;">'
                f'<span style="font-size:16px;font-weight:700;color:{text_color};'
                f'font-family:\'DM Serif Display\',serif;">{pct:+.2f}%</span>'
                f'</div>'
            )

        html += '</div>'

    # Subtitle
    html += (
        '<div style="font-size:10px;color:rgba(255,255,255,0.25);margin-top:6px;text-align:center;">'
        '1-Day Performance · iShares Russell ETFs</div>'
    )
    html += '</div>'

    return html


# ══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════

def render_markets_tab():
    """Render the full Markets tab with inner Tables / Charts sub-tabs."""

    # Row hover highlight (matches holdings/dividends tab behavior)
    st.markdown(
        '<style>'
        '[data-testid="stMarkdownContainer"] table tbody tr:hover {'
        '  background: rgba(255,255,255,0.04) !important;'
        '}'
        '</style>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px">'
        'Broad market snapshot · ETF proxies · 15-min cache'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_tables, tab_charts = st.tabs(["Tables", "Charts"])

    # ══════════════════════════════════════════════════════════════════════
    # TABLES SUB-TAB (existing layout)
    # ══════════════════════════════════════════════════════════════════════
    with tab_tables:
        with st.spinner("Fetching market data..."):
            quotes = _fetch_market_quotes()

        def _sort_by_change(items):
            """Sort items by change_pct descending (best performers on top)."""
            return sorted(items, key=lambda x: quotes.get(x[1], {}).get("change_pct", 0), reverse=True)

        # ── Indices & Dividend Benchmarks (side by side) ─────────────────
        col_idx, col_div = st.columns(2)
        with col_idx:
            st.markdown(_section_header("Indices"), unsafe_allow_html=True)
            st.markdown(_render_market_table(_sort_by_change(INDICES), quotes, section_label="Index"), unsafe_allow_html=True)
        with col_div:
            st.markdown(_section_header("Dividend Benchmarks"), unsafe_allow_html=True)
            st.markdown(_render_market_table(_sort_by_change(DIVIDEND_BENCHMARKS), quotes, section_label="Benchmark"), unsafe_allow_html=True)

        # ── Sector ETFs & US Equity Factors (side by side) ───────────────
        col_sectors, col_factors = st.columns([3, 2])
        with col_sectors:
            st.markdown(_section_header("S&P Sector ETFs"), unsafe_allow_html=True)
            st.markdown(_render_market_table(_sort_by_change(SECTORS), quotes, section_label="Sector"), unsafe_allow_html=True)
        with col_factors:
            st.markdown(_section_header("US Equity Factors"), unsafe_allow_html=True)
            st.markdown(_render_style_box(quotes), unsafe_allow_html=True)

        # ── Commodities ──────────────────────────────────────────────────
        st.markdown(_section_header("Commodities"), unsafe_allow_html=True)
        st.markdown(_render_market_table(_sort_by_change(COMMODITIES), quotes, section_label="Commodity"), unsafe_allow_html=True)

        # ── Fixed Income ─────────────────────────────────────────────────
        st.markdown(_section_header("Fixed Income ETFs"), unsafe_allow_html=True)
        st.markdown(_render_market_table(_sort_by_change(FIXED_INCOME), quotes, section_label="Category"), unsafe_allow_html=True)

        # ── Global Markets ───────────────────────────────────────────────
        st.markdown(_section_header("Global Markets"), unsafe_allow_html=True)
        col_dev, col_em = st.columns(2)
        with col_dev:
            st.markdown(
                '<div style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.4);'
                'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Developed</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_render_market_table(_sort_by_change(GLOBAL_DEVELOPED), quotes, section_label="Market"), unsafe_allow_html=True)
        with col_em:
            st.markdown(
                '<div style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.4);'
                'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Emerging</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_render_market_table(_sort_by_change(GLOBAL_EMERGING), quotes, section_label="Market"), unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    # CHARTS SUB-TAB (normalized % change for each section)
    # ══════════════════════════════════════════════════════════════════════
    with tab_charts:
        st.markdown(
            '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:16px">'
            'Normalized % change · Same period options as performance tab · Hover for values'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── Normalized Performance Chart (lead chart) ────────────────────
        st.markdown(_section_header("Normalized Performance"), unsafe_allow_html=True)
        period_cols = st.columns(len(PERF_PERIODS))
        selected_period = st.session_state.get("mkt_perf_period", "1D")
        for i, pkey in enumerate(PERF_PERIODS):
            with period_cols[i]:
                if st.button(pkey, key=f"mkt_perf_{pkey}", use_container_width=True,
                             type="primary" if pkey == selected_period else "secondary"):
                    st.session_state["mkt_perf_period"] = pkey
                    selected_period = pkey
        _render_perf_chart(selected_period)

        # Indices
        _render_section_with_periods("Indices", INDICES, "idx")

        # Dividend Benchmarks
        _render_section_with_periods("Dividend Benchmarks", DIVIDEND_BENCHMARKS, "divbench")

        # S&P Sector ETFs
        _render_section_with_periods("S&P Sector ETFs", SECTORS, "sectors")

        # Commodities
        _render_section_with_periods("Commodities", COMMODITIES, "commod")

        # Fixed Income ETFs
        _render_section_with_periods("Fixed Income ETFs", FIXED_INCOME, "fi")

        # Global Developed
        _render_section_with_periods("Global Markets — Developed", GLOBAL_DEVELOPED, "gldev")

        # Global Emerging
        _render_section_with_periods("Global Markets — Emerging", GLOBAL_EMERGING, "glem")

    # ── Footer ────────────────────────────────────────────────────────────
    st.caption(f"Data: yfinance (ETF proxies) · Cached 15 min · {datetime.now().strftime('%I:%M %p')}")