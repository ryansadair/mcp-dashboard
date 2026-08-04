"""
Martin Capital Partners — Quick Quote
data/quick_quote.py

"Any ticker, two seconds": type a symbol, get a live Finviz-powered
fundamentals strip plus a real price chart — without the Stock Detail
page's heavy yfinance load (five endpoints, .info throttling) and without
leaving the dashboard.

Data strategy (why this is reliable where Stock Detail wobbles):
  - Fundamentals come from the Finviz Elite export (data/finviz_export.py)
    — one authenticated call, self-throttled, works for any US-listed
    symbol, never rate-limited on Streamlit Cloud.
  - The chart is ONE lean yf.download price-series call — the exact call
    class the Markets tab charts make in production every day. What Yahoo
    throttles on shared cloud IPs is the .info metadata blob; bare series
    downloads are fine.
  - If the series call still fails, we fall back to Finviz's static daily
    chart image, so a chart always renders.

Chart styling, stats card, and period slicing are reused straight from
data/markets_tab.py so Quick Quote looks native to the house.

Sprint 26. Rendered at the top of the Watchlist tab.
"""

import streamlit as st

from utils.config import BRAND


# ──────────────────────────────────────────────────────────────────────────
# Fundamentals strip (Finviz row → compact HTML grid)
# ──────────────────────────────────────────────────────────────────────────
def _fmt(v, kind="num"):
    if v is None:
        return "—"
    try:
        if kind == "pct":
            return f"{v:.2f}%"
        if kind == "pct1":
            return f"{v:+.1f}%"
        if kind == "mcap":
            # Finviz market_cap arrives in $mm
            return f"${v/1000:,.1f}B" if v >= 1000 else f"${v:,.0f}M"
        if kind == "x":
            return f"{v:.1f}"
        if kind == "usd":
            return f"${v:,.2f}"
        return f"{v}"
    except (TypeError, ValueError):
        return "—"


def _fundamentals_html(fv):
    """
    Compact metric grid from the live Finviz row. Yield is shown on the
    TTM-regular basis (dividend_ttm / price), consistent with the firm's
    indicated-regular yield ruling — Finviz's own yield column is
    estimate-based and folds variable dividends in (CME reads 4.4% there
    vs the ~1.9% regular).
    """
    px = fv.get("price")
    ttm = fv.get("dividend_ttm")
    yld = (ttm / px * 100) if (ttm and px) else fv.get("dividend_yield")

    metrics = [
        ("Mkt Cap",   _fmt(fv.get("market_cap"), "mcap")),
        ("P/E",       _fmt(fv.get("pe"), "x")),
        ("Fwd P/E",   _fmt(fv.get("forward_pe"), "x")),
        ("Yield",     _fmt(yld, "pct")),
        ("Payout",    _fmt(fv.get("payout_ratio"), "pct")),
        ("ROE",       _fmt(fv.get("roe"), "pct")),
        ("DG 1Y",     _fmt(fv.get("div_growth_1y"), "pct1")),
        ("DG 3Y",     _fmt(fv.get("div_growth_3y"), "pct1")),
        ("DG 5Y",     _fmt(fv.get("div_growth_5y"), "pct1")),
        ("Beta",      _fmt(fv.get("beta"), "x")),
        ("Target",    _fmt(fv.get("target_price"), "usd")),
        ("Earnings",  fv.get("earnings_date") or "—"),
    ]
    cells = "".join(
        f'<div style="min-width:86px;">'
        f'<div style="font-size:9px;color:rgba(255,255,255,0.35);'
        f'text-transform:uppercase;letter-spacing:0.06em;">{label}</div>'
        f'<div style="font-size:13px;color:rgba(255,255,255,0.85);'
        f'font-weight:600;margin-top:2px;">{val}</div>'
        f'</div>'
        for label, val in metrics
    )
    sect = " · ".join(x for x in (fv.get("sector"), fv.get("industry")) if x)
    return (
        f'<div style="background:rgba(255,255,255,0.02);'
        f'border:1px solid rgba(255,255,255,0.05);border-radius:10px;'
        f'padding:14px 16px;margin-bottom:10px;">'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.4);'
        f'margin-bottom:10px;">{sect}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:14px 20px;">{cells}</div>'
        f'</div>'
    )


# ──────────────────────────────────────────────────────────────────────────
# Quote shape for the shared stats card
# ──────────────────────────────────────────────────────────────────────────
def _quote_shape(ticker, fv, batch_data):
    """
    Build the quotes-dict entry _render_stats_card expects, preferring the
    live Finviz row and computing YTD / 52W context from the history batch.
    """
    q = {}
    hist = None
    try:
        if batch_data is not None:
            hist = (batch_data[ticker]
                    if ticker in getattr(batch_data.columns, "levels", [[]])[0]
                    else batch_data)
            hist = hist.dropna(subset=["Close"])
    except Exception:
        hist = None

    price = (fv or {}).get("price")
    if not price and hist is not None and len(hist):
        price = float(hist["Close"].iloc[-1])
    q["price"] = price or 0

    chg_pct = (fv or {}).get("change_pct")
    if chg_pct is None and hist is not None and len(hist) >= 2:
        chg_pct = (hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100
    q["change_pct"] = chg_pct or 0
    prev = (fv or {}).get("prev_close")
    q["change"] = (price - prev) if (price and prev) else 0

    hi = (fv or {}).get("week52_high")
    lo = (fv or {}).get("week52_low")
    if hist is not None and len(hist):
        yr = hist.tail(252)
        hi = hi or float(yr["Close"].max())
        lo = lo or float(yr["Close"].min())
        try:
            ytd = yr[yr.index.year == yr.index[-1].year]
            q["ytd_pct"] = (float(ytd["Close"].iloc[-1])
                            / float(ytd["Close"].iloc[0]) - 1) * 100
        except Exception:
            q["ytd_pct"] = 0
    q["high_52w"] = hi or 0
    q["low_52w"] = lo or 0
    q["pct_from_high"] = ((price / hi - 1) * 100) if (price and hi) else 0
    q.setdefault("ytd_pct", 0)
    return q


# ──────────────────────────────────────────────────────────────────────────
# Main render
# ──────────────────────────────────────────────────────────────────────────
def render_quick_quote():
    """
    Quick Quote block: ticker input → Finviz fundamentals strip + stats
    card + period-selectable chart. Call at the top of the Watchlist tab.
    Makes zero network calls until a ticker is entered.
    """
    from data.markets_tab import (
        _fetch_section_history, _render_stats_card, _render_focus_chart,
        SECTION_CHART_PERIODS,
    )

    st.markdown(
        f'<div style="font-size:13px;font-weight:700;color:{BRAND["gold"]};'
        f'text-transform:uppercase;letter-spacing:0.08em;margin:2px 0 6px;">'
        f'Quick Quote</div>',
        unsafe_allow_html=True,
    )

    c_in, c_hint = st.columns([1, 3])
    with c_in:
        raw = st.text_input(
            "Ticker", key="qq_ticker", placeholder="Any ticker — e.g. NVDA",
            label_visibility="collapsed",
        )
    with c_hint:
        st.markdown(
            '<div style="font-size:11px;color:rgba(255,255,255,0.3);'
            'padding-top:9px;">Live Finviz fundamentals + chart for any '
            'US-listed symbol — research names, competitors, whatever\'s '
            'in the news.</div>',
            unsafe_allow_html=True,
        )

    ticker = (raw or "").strip().upper()
    if not ticker:
        return
    if not ticker.replace(".", "").replace("-", "").isalnum() or len(ticker) > 6:
        st.warning(f"'{ticker}' doesn't look like a ticker symbol.")
        return

    # ── Live Finviz row (any US-listed symbol; None for indices/some OTC) ──
    fv = None
    try:
        from data.finviz_export import get_snapshot
        fv = get_snapshot((ticker,)).get(ticker)
    except Exception:
        fv = None

    # ── One lean series download (the Markets-tab call class) ─────────────
    batch_data = None
    try:
        batch_data = _fetch_section_history((ticker,))
    except Exception:
        batch_data = None
    have_series = False
    try:
        probe = (batch_data[ticker]
                 if batch_data is not None
                 and ticker in getattr(batch_data.columns, "levels", [[]])[0]
                 else batch_data)
        have_series = probe is not None and not probe.dropna(subset=["Close"]).empty
    except Exception:
        have_series = False

    if fv is None and not have_series:
        st.warning(f"No data found for '{ticker}' — check the symbol "
                   f"(indices and some OTC names aren't covered).")
        return

    display_name = (fv or {}).get("name") or ticker

    if fv:
        st.markdown(_fundamentals_html(fv), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="font-size:11px;color:rgba(255,255,255,0.3);'
            'margin-bottom:8px;">Fundamentals unavailable for this symbol '
            '(not in Finviz coverage) — showing chart only.</div>',
            unsafe_allow_html=True,
        )

    # ── Stats card + period selector + chart (shared house components) ────
    section_key = "qq_focus"
    quotes = {ticker: _quote_shape(ticker, fv, batch_data)}

    if have_series:
        period_key = f"{section_key}_period"
        if period_key not in st.session_state:
            st.session_state[period_key] = "1Y"
        selected_period = st.session_state[period_key]

        _render_stats_card(
            name=display_name, ticker=ticker, quotes=quotes,
            batch_data=batch_data, period_label=selected_period,
        )

        period_cols = st.columns(len(SECTION_CHART_PERIODS))
        for i, pkey in enumerate(SECTION_CHART_PERIODS):
            with period_cols[i]:
                if st.button(
                    pkey, key=f"{section_key}_period_{pkey}",
                    width="stretch",
                    type="primary" if pkey == selected_period else "secondary",
                ):
                    st.session_state[period_key] = pkey
                    st.rerun()

        _render_focus_chart(
            ticker=ticker, name=display_name, batch_data=batch_data,
            period_label=selected_period, section_key=section_key,
        )
    else:
        # Yahoo series unavailable — Finviz static daily chart so a chart
        # still renders. (Elite intraday params need auth cookies; the
        # daily image is public.)
        st.markdown(
            '<div style="font-size:11px;color:rgba(255,255,255,0.35);'
            'margin:4px 0;">Interactive chart unavailable (Yahoo series '
            'failed) — Finviz daily chart:</div>',
            unsafe_allow_html=True,
        )
        st.image(f"https://charts2.finviz.com/chart.ashx?t={ticker}"
                 f"&ty=c&ta=1&p=d&s=l")

    st.markdown(
        '<div style="border-bottom:1px solid rgba(255,255,255,0.05);'
        'margin:14px 0 10px;"></div>',
        unsafe_allow_html=True,
    )