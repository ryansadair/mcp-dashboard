"""
Martin Capital Partners — Watchlist Tab
data/watchlist_tab.py

Reads from data/Watchlists.xlsx (5 sheets, ticker-only).
Dropdown selector switches between watchlists.
yfinance enriches with live price, valuation, and dividend data.

Sprint 25-2: converted from custom HTML table to st.dataframe with row
selection. Drill-through to the Stock Detail page now matches the
Holdings tab pattern. Sortable columns come for free. The custom red /
gold / green tier coloring on "% From 52W Hi" is gone — Streamlit's
NumberColumn doesn't support value-based color tiers. Sortability +
drill-through is the better trade.

Sprint 25-3: fixed vibration bug on short watchlists. Root cause was the
dataframe height sitting on the scrollbar-threshold boundary, causing
a layout reflow loop. Added a 250px minimum height floor. Also removed
a redundant st.rerun() after the selectbox (selectbox triggers its own
rerun on change) and gave the dataframe a per-watchlist key so selection
state can't leak between lists.

Sprint 25-8: added back the value-based color tiers via pandas Styler.
Same pattern as the MCP Targets table on the Holdings tab — sortable
dataframe + per-cell colors driven by Styler.map callbacks. Tiers are
tuned for a dividend-focused research watchlist: yields >7% flagged gold
(possible trap), P/E <=15 green (cheap), beta <=1 green (defensive),
% From 52W Hi <-25% red (deep weakness).
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from utils.config import normalize_sector

# Brand colors — used by the yield comparison chart at the bottom
GREEN = "#569542"
BLUE = "#07415A"
GOLD = "#C9A84C"
RED  = "#c45454"


def render_watchlist_tab():
    """
    Full watchlist tab. Call inside `with tab_watchlist:` in 1_Dashboard.py.
    """
    from data.watchlist import (
        parse_watchlist_excel, get_watchlist_names, enrich_batch,
    )

    st.markdown(
        '<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);'
        'text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">'
        'Research Watchlists</div>',
        unsafe_allow_html=True,
    )

    # ── Parse the Excel file ───────────────────────────────────────────────
    @st.cache_data(ttl=300)
    def _load_watchlists():
        return parse_watchlist_excel()

    parsed = _load_watchlists()

    if not parsed:
        st.warning(
            "**Watchlists.xlsx not found** — place it in the `data/` folder.\n\n"
            "Expected: one sheet per watchlist, column A = ticker symbols.\n\n"
            "Sheets: QDVD Watchlist A, QDVD Watchlist B, SMID Watchlist A, SMID Watchlist B, C Watch"
        )
        return

    # ── Dropdown selector ──────────────────────────────────────────────────
    list_names = get_watchlist_names(parsed)

    if "wl_active_list" not in st.session_state:
        st.session_state["wl_active_list"] = list_names[0]

    if st.session_state["wl_active_list"] not in list_names:
        st.session_state["wl_active_list"] = list_names[0]

    sel_col, info_col = st.columns([2, 3])
    with sel_col:
        selected = st.selectbox(
            "Watchlist",
            options=list_names,
            format_func=lambda x: f"{x}  ({len(parsed.get(x, []))})",
            index=list_names.index(st.session_state["wl_active_list"]),
            key="wl_list_selector",
            label_visibility="collapsed",
        )
        st.session_state["wl_active_list"] = selected

    with info_col:
        st.caption(
            f"Reading from `data/Watchlists.xlsx` · Sheet: **{st.session_state['wl_active_list']}** · "
            f"Updated: {datetime.now().strftime('%I:%M %p')}"
        )

    active_list = st.session_state["wl_active_list"]
    tickers = parsed.get(active_list, [])

    if not tickers:
        st.info(f"No tickers found in '{active_list}'.")
        return

    # ── Fetch live data ────────────────────────────────────────────────────
    @st.cache_data(ttl=900)
    def _enrich_tickers(ticker_tuple, _v=2):
        """Batch fetch — _v param busts cache when logic changes."""
        return enrich_batch(list(ticker_tuple))

    with st.spinner(f"Fetching data for {len(tickers)} tickers..."):
        live_data = _enrich_tickers(tuple(tickers))

    # ── Build display rows ─────────────────────────────────────────────────
    # All values stay numeric so st.dataframe can sort them properly. The
    # NumberColumn formatters below handle the $ / % / decimals display.
    rows = []
    for tk in tickers:
        live = live_data.get(tk, {})
        price = live.get("current_price", 0) or 0
        hi = live.get("52w_high", 0) or 0
        lo = live.get("52w_low", 0) or 0

        # % From 52W Hi — Holdings-tab convention. Negative = below the high.
        # None when we lack price/hi data so the formatter can render it
        # as em-dash (st.column_config drops NaN to "—" by default).
        if hi > 0 and price > 0:
            from_hi = round((price - hi) / hi * 100, 2)
        else:
            from_hi = None

        rows.append({
            "Ticker": tk,
            "Company": live.get("company_name", "") or "",
            "Sector": normalize_sector(live.get("sector", "")),
            "Price": price if price > 0 else None,
            # Cap insane-looking yields at 15% (data quality guard)
            "Div Yield": min(live.get("dividend_yield", 0) or 0, 15) or None,
            "P/E": live.get("pe_ratio", 0) or None,
            "Fwd P/E": live.get("forward_pe", 0) or None,
            "Beta": live.get("beta", 0) or None,
            "Mkt Cap": live.get("market_cap", "") or "",
            "% From 52W Hi": from_hi,
        })

    display_df = pd.DataFrame(rows)

    # ── Cell color functions (Sprint 25-8: Styler-based color tiers) ──────
    # Match the MCP Targets table pattern on the Holdings tab. Each function
    # returns a CSS declaration string; Styler.map applies it per cell.

    def _color_ticker(v):
        return f"color: {GOLD}; font-weight: 600"

    def _color_yield(v):
        # Dividend-focused watchlist: higher yield = more interesting, but
        # very high yields (>7%) often signal yield traps, so they get gold
        # instead of green to flag "investigate before buying."
        try:
            v = float(v)
            if v >= 7:    return f"color: {GOLD}; font-weight: 600"  # possible trap
            if v >= 4:    return f"color: {GREEN}; font-weight: 600"  # attractive
            if v >= 2:    return f"color: {GOLD}"                      # moderate
            return "color: rgba(255,255,255,0.6)"                      # low
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_pe(v):
        # Lower P/E = cheaper. Negative P/E means earnings are negative.
        try:
            v = float(v)
            if v <= 0:    return f"color: {RED}"                       # losing money
            if v <= 15:   return f"color: {GREEN}; font-weight: 600"   # cheap
            if v <= 25:   return "color: rgba(255,255,255,0.7)"        # neutral
            if v <= 35:   return f"color: {GOLD}"                      # rich
            return f"color: {RED}; font-weight: 600"                   # very expensive
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_beta(v):
        # Beta interpretation for a dividend boutique: <1 is less volatile
        # (good), 1-1.5 is moderate, >1.5 is high-volatility (caution).
        try:
            v = float(v)
            if v <= 1.0:  return f"color: {GREEN}"                     # defensive
            if v <= 1.5:  return f"color: {GOLD}"                      # moderate
            return f"color: {RED}; font-weight: 600"                   # volatile
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_from_hi(v):
        # % From 52W High is always negative or near zero.
        # Near highs = neutral, modest pullback = gold (opportunity-watching),
        # deep pullback = red (broken or value, requires investigation).
        try:
            v = float(v)
            if v >= -10:  return "color: rgba(255,255,255,0.6)"        # near highs
            if v >= -25:  return f"color: {GOLD}"                      # pullback zone
            return f"color: {RED}; font-weight: 600"                   # deep weakness
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    styled = (
        display_df.style
        .map(_color_ticker,  subset=["Ticker"])
        .map(_color_yield,   subset=["Div Yield"])
        .map(_color_pe,      subset=["P/E"])
        .map(_color_pe,      subset=["Fwd P/E"])
        .map(_color_beta,    subset=["Beta"])
        .map(_color_from_hi, subset=["% From 52W Hi"])
    )

    # ── KPI Cards ──────────────────────────────────────────────────────────
    avg_yield = display_df["Div Yield"].dropna().mean() if not display_df.empty else 0
    pe_valid = display_df["P/E"].dropna()
    avg_pe = pe_valid.mean() if len(pe_valid) > 0 else 0
    fwd_valid = display_df["Fwd P/E"].dropna()
    avg_fwd_pe = fwd_valid.mean() if len(fwd_valid) > 0 else 0

    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.metric("Tickers", len(display_df))
    kc2.metric("Avg Div Yield", f"{avg_yield:.2f}%" if pd.notna(avg_yield) else "—")
    kc3.metric("Avg P/E", f"{avg_pe:.1f}" if pd.notna(avg_pe) and avg_pe > 0 else "—")
    kc4.metric("Avg Fwd P/E", f"{avg_fwd_pe:.1f}" if pd.notna(avg_fwd_pe) and avg_fwd_pe > 0 else "—")

    # ── Main Table — st.dataframe with single-row selection ────────────────
    # Height floor of 250px prevents short watchlists (QDVD A/B, SMID A/B) from
    # oscillating on the scrollbar threshold. Without the floor, lists of 3-5
    # tickers produced a height where Streamlit's layout engine flipped between
    # "needs scrollbar" and "doesn't need scrollbar" on every render pass,
    # causing the visible left-right vibration.
    _df_height = max(250, min(80 + len(display_df) * 40, 2000))

    event = st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        height=_df_height,
        selection_mode="single-row",
        on_select="rerun",
        key=f"watchlist_table_{active_list}",
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Company": st.column_config.TextColumn("Company", width="medium"),
            "Sector": st.column_config.TextColumn("Sector", width="small"),
            "Price": st.column_config.NumberColumn("Price", format="$%.2f", width="small"),
            "Div Yield": st.column_config.NumberColumn("Div Yield", format="%.2f%%", width="small"),
            "P/E": st.column_config.NumberColumn("P/E", format="%.2f", width="small"),
            "Fwd P/E": st.column_config.NumberColumn("Fwd P/E", format="%.2f", width="small"),
            "Beta": st.column_config.NumberColumn("Beta", format="%.2f", width="small"),
            "Mkt Cap": st.column_config.TextColumn("Mkt Cap", width="small"),
            "% From 52W Hi": st.column_config.NumberColumn("% From Hi", format="%+.2f%%", width="small"),
        },
    )

    # ── Drill-through to Stock Detail when a row is selected ───────────────
    # Same pattern as Holdings tab and Dividends Detail sub-tab.
    if event and event.selection and event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_ticker = display_df.iloc[selected_idx]["Ticker"]
        st.session_state["detail_ticker"] = selected_ticker
        st.query_params["ticker"] = selected_ticker
        st.switch_page("pages/2_Stock_Detail.py")

    # ── Yield Chart ────────────────────────────────────────────────────────
    yield_df = display_df[display_df["Div Yield"].notna() & (display_df["Div Yield"] > 0)][
        ["Ticker", "Div Yield"]
    ].sort_values("Div Yield", ascending=True)
    if not yield_df.empty and len(yield_df) > 1:
        st.markdown("---")
        st.markdown("**Dividend Yield Comparison**")
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=yield_df["Div Yield"],
            y=yield_df["Ticker"],
            orientation="h",
            marker=dict(
                color=yield_df["Div Yield"],
                colorscale=[[0, BLUE], [0.5, GOLD], [1, GREEN]],
            ),
            text=[f"{y:.2f}%" for y in yield_df["Div Yield"]],
            textposition="outside",
            textfont=dict(size=11, color="rgba(255,255,255,0.6)"),
        ))
        fig.update_layout(
            paper_bgcolor="rgba(255,255,255,0.02)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10), title="Yield %"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=11)),
            margin=dict(l=10, r=40, t=10, b=10),
            height=max(250, len(yield_df) * 30 + 60),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch", config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False,
            "showTips": False,
            "staticPlot": True,
        })

    st.caption(f"Data via yfinance · Click any row to view full Stock Detail · {datetime.now().strftime('%I:%M %p PT')}")