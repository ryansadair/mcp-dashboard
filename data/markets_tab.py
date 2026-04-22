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
    ("S&P 500",       "^GSPC"),
    ("Dow Jones",     "^DJI"),
    ("Nasdaq 100",    "^NDX"),
    ("Russell 2000",  "^RUT"),
    ("VIX",           "^VIX"),
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
    ("Gold",        "GLD"),
    ("Crude Oil",   "USO"),
    ("Brent Crude", "BNO"),
    ("Natural Gas", "UNG"),
    ("Silver",      "SLV"),
    ("Copper",      "CPER"),
]

# Collect all tickers for batch fetch
_ALL_GROUPS = [INDICES, SECTORS, FIXED_INCOME, GLOBAL_DEVELOPED, GLOBAL_EMERGING, COMMODITIES]
_ALL_TICKERS = []
for group in _ALL_GROUPS:
    for _, ticker in group:
        if ticker not in _ALL_TICKERS:
            _ALL_TICKERS.append(ticker)


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
            period="5d",
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
                    result[ticker] = {"price": 0, "change": 0, "change_pct": 0}
                    continue

                # Drop NaN rows
                df = df.dropna(subset=["Close"])
                if len(df) < 1:
                    result[ticker] = {"price": 0, "change": 0, "change_pct": 0}
                    continue

                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
                chg = close - prev
                chg_pct = (chg / prev * 100) if prev != 0 else 0

                result[ticker] = {
                    "price": round(close, 2),
                    "change": round(chg, 2),
                    "change_pct": round(chg_pct, 2),
                }
            except Exception:
                result[ticker] = {"price": 0, "change": 0, "change_pct": 0}

        return result
    except Exception:
        return {t: {"price": 0, "change": 0, "change_pct": 0} for t in _ALL_TICKERS}


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
    """
    # Header
    header_cols = (
        '<col style="width:40%"><col style="width:15%">'
        '<col style="width:22%"><col style="width:23%">'
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
    html += '</tr></thead><tbody>'

    for name, ticker in items:
        q = quotes.get(ticker, {})
        price = q.get("price", 0)
        chg = q.get("change", 0)
        pct = q.get("change_pct", 0)
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
        pct_str = f"{pct:+.1f}%"

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
            f'</tr>'
        )

    html += '</tbody></table>'
    return html


def _section_header(emoji, title):
    return (
        f'<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        f'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        f'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:4px">'
        f'{emoji} {title}</div>'
    )


# ══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════

def render_markets_tab():
    """Render the full Markets tab."""

    st.markdown(
        '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px">'
        'Broad market snapshot · ETF proxies · 15-min cache'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Fetching market data..."):
        quotes = _fetch_market_quotes()

    # ── U.S. Indices ──────────────────────────────────────────────────────
    st.markdown(_section_header("🇺🇸", "U.S. Equity Indices"), unsafe_allow_html=True)
    st.markdown(_render_market_table(INDICES, quotes, section_label="Index"), unsafe_allow_html=True)

    # ── Sector ETFs ───────────────────────────────────────────────────────
    st.markdown(_section_header("📊", "S&P Sector ETFs"), unsafe_allow_html=True)

    # Sort by change_pct descending (best performers at top)
    sorted_sectors = sorted(SECTORS, key=lambda x: quotes.get(x[1], {}).get("change_pct", 0), reverse=True)
    st.markdown(_render_market_table(sorted_sectors, quotes, section_label="Sector"), unsafe_allow_html=True)

    # ── Fixed Income ──────────────────────────────────────────────────────
    st.markdown(_section_header("🏦", "Fixed Income ETFs"), unsafe_allow_html=True)
    st.markdown(_render_market_table(FIXED_INCOME, quotes, section_label="Category"), unsafe_allow_html=True)

    # ── Global Markets ────────────────────────────────────────────────────
    st.markdown(_section_header("🌍", "Global Markets"), unsafe_allow_html=True)

    col_dev, col_em = st.columns(2)
    with col_dev:
        st.markdown(
            '<div style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.4);'
            'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Developed</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_render_market_table(GLOBAL_DEVELOPED, quotes, section_label="Market"), unsafe_allow_html=True)
    with col_em:
        st.markdown(
            '<div style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.4);'
            'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Emerging</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_render_market_table(GLOBAL_EMERGING, quotes, section_label="Market"), unsafe_allow_html=True)

    # ── Commodities ───────────────────────────────────────────────────────
    st.markdown(_section_header("🛢️", "Commodities"), unsafe_allow_html=True)
    st.markdown(_render_market_table(COMMODITIES, quotes, section_label="Commodity"), unsafe_allow_html=True)

    # ── Footer ────────────────────────────────────────────────────────────
    st.caption(f"Data: yfinance (ETF proxies) · Cached 15 min · {datetime.now().strftime('%I:%M %p')}")
