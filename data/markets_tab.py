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

# ══════════════════════════════════════════════════════════════════════════
# FOCUS-CHART INFRASTRUCTURE (Option B)
# Per-section: ticker pills → stats card → period selector → single focus chart.
# Period keys match the Holdings tab price-chart selector exactly.
# ══════════════════════════════════════════════════════════════════════════

# Day counts per period for slicing a cached max-history batch — matches
# Holdings tab chart pattern (single download, client-side slice per period).
SECTION_CHART_PERIODS = {
    "1M":  21,
    "3M":  63,
    "6M":  126,
    "YTD": None,
    "1Y":  252,
    "2Y":  504,
    "3Y":  756,
    "5Y":  1260,
    "Max": 0,
}


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_section_history(tickers_tuple, _v=1):
    """
    Batch download full price history for a section, cached 15 min.
    Returns the raw yfinance multi-ticker DataFrame (group_by='ticker').
    We fetch once at max and slice client-side per period — same pattern
    as the Holdings chart sub-tab.
    """
    try:
        import yfinance as yf
        return yf.download(
            " ".join(tickers_tuple),
            period="max",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception:
        return None


def _slice_period(df, period_label):
    """Slice a single-ticker OHLC DataFrame to the selected period."""
    days = SECTION_CHART_PERIODS.get(period_label)
    if period_label == "YTD":
        year_start = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
        return df[df.index >= year_start]
    if period_label == "Max" or days == 0:
        return df
    return df.tail(days) if days else df


def _render_ticker_pills(items, quotes, selected_ticker, section_key):
    """
    Render a row of ticker pills showing TICKER +X.XX%. Clicking a pill
    sets it as the focus ticker and reruns.
    items: list of (name, ticker) pairs.
    """
    # Compute a responsive number of pills per row — 6 on desktop
    per_row = 6
    rows = [items[i:i + per_row] for i in range(0, len(items), per_row)]

    for row in rows:
        pill_cols = st.columns(per_row)
        for ci, (name, ticker) in enumerate(row):
            with pill_cols[ci]:
                q = quotes.get(ticker, {})
                pct = q.get("change_pct", 0)
                is_active = (ticker == selected_ticker)

                # Label format: Friendly Name · +X.XX%
                # The ticker is still shown in the stats card directly below
                # the pills, so dropping it from the pill itself is safe.
                label = f"{name}  {pct:+.2f}%"

                if st.button(
                    label,
                    key=f"{section_key}_pill_{ticker}",
                    width="stretch",
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state[f"{section_key}_focus"] = ticker
                    st.rerun()
        # Fill remaining cols in the last (possibly short) row with blanks
        if len(row) < per_row:
            for _ in range(per_row - len(row)):
                pass


def _render_stats_card(name, ticker, quotes, batch_data, period_label):
    """
    Render the LAST / 1D CHG / YTD / 52W RANGE stats card for the focus ticker.
    52W Range shown as both numeric ($low – $high) and a mini horizontal bar
    with a marker for the current price.
    """
    q = quotes.get(ticker, {})
    price = q.get("price", 0)
    chg_pct = q.get("change_pct", 0)
    high_52w = q.get("high_52w", 0)
    low_52w = q.get("low_52w", 0)
    ytd_pct = q.get("ytd_pct", 0)

    # Price formatting
    def _fmt_price(p):
        if p >= 10000:
            return f"${p:,.0f}"
        elif p >= 100:
            return f"${p:,.2f}"
        return f"${p:.2f}"

    chg_color = "#569542" if chg_pct >= 0 else "#c45454"
    ytd_color = "#569542" if ytd_pct >= 0 else "#c45454"

    # 52W range bar — marker position as a 0-100% offset from the low
    if high_52w > low_52w > 0:
        pos_pct = ((price - low_52w) / (high_52w - low_52w)) * 100
        pos_pct = max(0, min(100, pos_pct))
    else:
        pos_pct = 50

    range_bar_html = (
        f'<div style="position:relative;height:6px;background:rgba(255,255,255,0.06);'
        f'border-radius:3px;margin-top:6px;">'
        f'<div style="position:absolute;left:{pos_pct:.1f}%;top:-3px;'
        f'width:2px;height:12px;background:#C9A84C;border-radius:1px;'
        f'transform:translateX(-1px);"></div>'
        f'</div>'
    )

    # Build card HTML — single block, no multiline f-string pitfalls
    html = (
        '<div style="display:flex;gap:28px;align-items:flex-start;padding:14px 16px;'
        'background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);'
        'border-radius:8px;margin:8px 0 12px;flex-wrap:wrap;">'
    )

    # Ticker / Name
    html += (
        f'<div style="min-width:140px;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Focus</div>'
        f'<div style="font-size:16px;font-weight:700;color:#C9A84C;'
        f'font-family:monospace;letter-spacing:0.02em;">{ticker}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">{name}</div>'
        f'</div>'
    )

    # Last
    html += (
        f'<div><div style="font-size:10px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Last</div>'
        f'<div style="font-size:16px;font-weight:700;color:rgba(255,255,255,0.95);">'
        f'{_fmt_price(price)}</div></div>'
    )

    # 1D Chg
    html += (
        f'<div><div style="font-size:10px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">1D Chg</div>'
        f'<div style="font-size:16px;font-weight:700;color:{chg_color};">'
        f'{chg_pct:+.2f}%</div></div>'
    )

    # YTD
    html += (
        f'<div><div style="font-size:10px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">YTD</div>'
        f'<div style="font-size:16px;font-weight:700;color:{ytd_color};">'
        f'{ytd_pct:+.2f}%</div></div>'
    )

    # 52W Range (numeric + bar)
    html += (
        f'<div style="min-width:160px;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">52W Range</div>'
        f'<div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.85);">'
        f'{_fmt_price(low_52w)} – {_fmt_price(high_52w)}</div>'
        f'{range_bar_html}'
        f'</div>'
    )

    html += '</div>'

    st.markdown(html, unsafe_allow_html=True)


def _render_focus_chart(ticker, name, batch_data, period_label, section_key):
    """
    Render the single-ticker focus line chart with subtle area fill, crosshair
    on hover, and fixed zoom. Mirrors the Holdings chart sub-tab Plotly styling.
    """
    import plotly.graph_objects as go

    if batch_data is None:
        st.markdown(
            '<div style="padding:40px;text-align:center;color:rgba(255,255,255,0.3);'
            'font-size:13px;">Chart data unavailable</div>',
            unsafe_allow_html=True,
        )
        return

    # Extract this ticker's slice from the batched DataFrame
    try:
        if ticker in batch_data.columns.get_level_values(0):
            tk_full = batch_data[ticker]
        else:
            # Single-ticker download returns a flat DataFrame
            tk_full = batch_data
    except Exception:
        tk_full = None

    if tk_full is None or tk_full.empty or tk_full.dropna(subset=["Close"]).empty:
        st.markdown(
            f'<div style="padding:40px;text-align:center;color:rgba(255,255,255,0.3);'
            f'font-size:13px;">No data for {ticker}</div>',
            unsafe_allow_html=True,
        )
        return

    tk_full = tk_full.dropna(subset=["Close"]).copy()
    tk_df = _slice_period(tk_full, period_label)

    if tk_df.empty:
        st.markdown(
            f'<div style="padding:40px;text-align:center;color:rgba(255,255,255,0.3);'
            f'font-size:13px;">No data for {ticker} ({period_label})</div>',
            unsafe_allow_html=True,
        )
        return

    close = tk_df["Close"]
    first = float(close.iloc[0])
    last = float(close.iloc[-1])
    chg_pct = ((last - first) / first * 100) if first > 0 else 0
    chg_color = "#569542" if chg_pct >= 0 else "#c45454"
    fill_color = "rgba(86,149,66,0.08)" if chg_pct >= 0 else "rgba(196,84,84,0.08)"

    fig = go.Figure()

    # For Max period, fill from zero; otherwise fill from a slight floor below the min
    use_zero_base = (period_label == "Max")
    y_min_val = float(close.min())
    y_max_val = float(close.max())
    price_range = y_max_val - y_min_val if y_max_val > y_min_val else 1
    y_floor = 0 if use_zero_base else max(0, y_min_val - price_range * 0.05)

    # Invisible floor trace to serve as the anchor for tonexty fill
    fig.add_trace(go.Scatter(
        x=tk_df.index,
        y=[y_floor] * len(tk_df),
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Main price line + area fill
    fig.add_trace(go.Scatter(
        x=tk_df.index,
        y=close,
        mode="lines",
        name=ticker,
        line=dict(color=chg_color, width=2),
        fill="tonexty",
        fillcolor=fill_color,
        hovertemplate="%{x|%b %d, %Y}<br>$%{y:,.2f}<extra></extra>",
    ))

    # Crosshair / spikes — separate update calls (per PLOTLY_DARK learnings)
    spike = dict(
        showspikes=True, spikecolor="rgba(201,168,76,0.4)",
        spikethickness=1, spikemode="across", spikedash="solid",
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="rgba(255,255,255,0.5)", size=10),
        margin=dict(l=10, r=50, t=10, b=24),
        height=340,
        hovermode="x unified",
        dragmode=False,
        showlegend=False,
    )
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,0.04)",
        showline=False,
        tickfont=dict(size=10, color="rgba(255,255,255,0.35)"),
        fixedrange=True,
        tickformat=(
            "%b %d" if period_label in ("1M", "3M") else
            "%b '%y" if period_label in ("6M", "YTD", "1Y") else
            "%Y"
        ),
        **spike,
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.04)",
        showline=False,
        side="right",
        tickfont=dict(size=10, color="rgba(255,255,255,0.35)"),
        tickprefix="$",
        fixedrange=True,
        zeroline=False,
        **spike,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False, "scrollZoom": False,
            "doubleClick": False, "showTips": False, "staticPlot": False,
        },
        key=f"{section_key}_chart_{ticker}_{period_label}",
    )


def _render_focus_section(title, items, session_prefix, quotes):
    """
    Render one Option B focus-chart section:
      header → ticker pills → stats card → period selector → focus chart.
    Uses a single cached batch download for all tickers in the section.
    """
    section_key = f"mkt_focus_{session_prefix}"

    # ── Section header ──────────────────────────────────────────────────────
    st.markdown(_section_header(title), unsafe_allow_html=True)

    # ── Focus ticker selection (default = first item) ──────────────────────
    focus_key = f"{section_key}_focus"
    default_ticker = items[0][1]
    selected_ticker = st.session_state.get(focus_key, default_ticker)
    # Guard: if a prior session left a ticker no longer in this section
    if selected_ticker not in [t for _, t in items]:
        selected_ticker = default_ticker
        st.session_state[focus_key] = selected_ticker

    # ── Ticker pills row ───────────────────────────────────────────────────
    _render_ticker_pills(items, quotes, selected_ticker, section_key)

    # ── Period selection (default = 1Y, matches Holdings) ─────────────────
    period_key = f"{section_key}_period"
    if period_key not in st.session_state:
        st.session_state[period_key] = "1Y"
    selected_period = st.session_state[period_key]

    # ── Batch fetch history for this section ──────────────────────────────
    ticker_tuple = tuple(t for _, t in items)
    name_map = {t: n for n, t in items}
    batch_data = _fetch_section_history(ticker_tuple)

    # ── Stats card (LAST / 1D / YTD / 52W range) ──────────────────────────
    _render_stats_card(
        name=name_map.get(selected_ticker, selected_ticker),
        ticker=selected_ticker,
        quotes=quotes,
        batch_data=batch_data,
        period_label=selected_period,
    )

    # ── Period selector buttons (matches Holdings tab exactly) ────────────
    period_cols = st.columns(len(SECTION_CHART_PERIODS))
    for i, pkey in enumerate(SECTION_CHART_PERIODS):
        with period_cols[i]:
            if st.button(
                pkey,
                key=f"{section_key}_period_{pkey}",
                width="stretch",
                type="primary" if pkey == selected_period else "secondary",
            ):
                st.session_state[period_key] = pkey
                st.rerun()

    # ── Focus chart ───────────────────────────────────────────────────────
    _render_focus_chart(
        ticker=selected_ticker,
        name=name_map.get(selected_ticker, selected_ticker),
        batch_data=batch_data,
        period_label=selected_period,
        section_key=section_key,
    )

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
    Returns dict: {ticker: {price, change, change_pct, high_52w, low_52w,
                            pct_from_high, ytd_pct}}
    """
    _empty = {
        "price": 0, "change": 0, "change_pct": 0,
        "high_52w": 0, "low_52w": 0, "pct_from_high": 0, "ytd_pct": 0,
    }
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

        # Compute YTD start date (Jan 1 of current year)
        year_start_str = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")

        result = {}
        for ticker in _ALL_TICKERS:
            try:
                if len(_ALL_TICKERS) == 1:
                    df = data
                else:
                    df = data[ticker] if ticker in data.columns.get_level_values(0) else None

                if df is None or df.empty:
                    result[ticker] = dict(_empty)
                    continue

                # Drop NaN rows
                df = df.dropna(subset=["Close"])
                if len(df) < 1:
                    result[ticker] = dict(_empty)
                    continue

                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
                chg = close - prev
                chg_pct = (chg / prev * 100) if prev != 0 else 0

                # 52-week high/low from the full year of data
                high_52w = float(df["High"].max()) if "High" in df.columns else close
                low_52w = float(df["Low"].min()) if "Low" in df.columns else close
                pct_from_high = ((close - high_52w) / high_52w * 100) if high_52w > 0 else 0

                # YTD % — first close on/after Jan 1 of current year
                ytd_df = df[df.index >= year_start_str]
                if not ytd_df.empty:
                    ytd_base = float(ytd_df["Close"].iloc[0])
                    ytd_pct = ((close - ytd_base) / ytd_base * 100) if ytd_base > 0 else 0
                else:
                    ytd_pct = 0

                result[ticker] = {
                    "price": round(close, 2),
                    "change": round(chg, 2),
                    "change_pct": round(chg_pct, 2),
                    "high_52w": round(high_52w, 2),
                    "low_52w": round(low_52w, 2),
                    "pct_from_high": round(pct_from_high, 1),
                    "ytd_pct": round(ytd_pct, 2),
                }
            except Exception:
                result[ticker] = dict(_empty)

        return result
    except Exception:
        return {t: dict(_empty) for t in _ALL_TICKERS}


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
    # CHARTS SUB-TAB — Option B: focus chart with ticker pills per section
    # Lazy-loaded: charts don't render until user clicks "Load charts",
    # same pattern as the Holdings tab price-chart sub-tab. This keeps the
    # rest of the dashboard fast since loading all 7 sections runs 40+
    # yfinance ticker fetches + 7 Plotly renders per rerun.
    # ══════════════════════════════════════════════════════════════════════
    with tab_charts:
        _loaded_key = "mkt_charts_loaded"
        _charts_loaded = st.session_state.get(_loaded_key, False)

        if not _charts_loaded:
            # ── Lazy-load gate ───────────────────────────────────────────────
            st.markdown(
                "<div style='padding:40px 20px;text-align:center;"
                "background:rgba(255,255,255,0.02);border-radius:10px;"
                "border:1px solid rgba(255,255,255,0.05);margin:12px 0;'>"
                "<div style='font-size:14px;color:rgba(255,255,255,0.7);"
                "margin-bottom:8px;font-weight:600;'>"
                "Market charts · 7 sections, focus view</div>"
                "<div style='font-size:12px;color:rgba(255,255,255,0.4);"
                "margin-bottom:18px;'>"
                "Loading charts takes ~15-25 seconds on first view. "
                "Click any ticker pill to focus that chart."
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            _bcol1, _bcol2, _bcol3 = st.columns([1, 1, 1])
            with _bcol2:
                if st.button(
                    "Load charts",
                    key="mkt_charts_load",
                    type="primary",
                    width="stretch",
                ):
                    st.session_state[_loaded_key] = True
                    st.rerun()
        else:
            # ── Charts loaded — render all focus sections ────────────────────
            # [3, 1] gives the Hide button ~25% of desktop width (keeps it
            # right-aligned and compact). Dropping width="stretch" lets the
            # button size to its text content so "Hide charts" stays on a
            # single line on narrow mobile columns.
            _hdr_left, _hdr_right = st.columns([3, 1])
            with _hdr_right:
                if st.button(
                    "Hide charts",
                    key="mkt_charts_hide",
                    type="secondary",
                ):
                    st.session_state.pop(_loaded_key, None)
                    st.rerun()

            st.markdown(
                '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:16px">'
                'Click a ticker pill to focus · Period selector matches Holdings tab · Hover for values'
                '</div>',
                unsafe_allow_html=True,
            )

            # Section quotes (cached 15 min)
            with st.spinner("Loading market data..."):
                _quotes = _fetch_market_quotes()

            # One focus section per market group
            _render_focus_section("Indices", INDICES, "idx", _quotes)
            _render_focus_section("Dividend Benchmarks", DIVIDEND_BENCHMARKS, "divbench", _quotes)
            _render_focus_section("S&P Sector ETFs", SECTORS, "sectors", _quotes)
            _render_focus_section("Commodities", COMMODITIES, "commod", _quotes)
            _render_focus_section("Fixed Income ETFs", FIXED_INCOME, "fi", _quotes)
            _render_focus_section("Global Markets — Developed", GLOBAL_DEVELOPED, "gldev", _quotes)
            _render_focus_section("Global Markets — Emerging", GLOBAL_EMERGING, "glem", _quotes)

    # ── Footer ────────────────────────────────────────────────────────────
    st.caption(f"Data: yfinance (ETF proxies) · Cached 15 min · {datetime.now().strftime('%I:%M %p')}")