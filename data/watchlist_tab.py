"""
Martin Capital Partners — Watchlist Tab
data/watchlist_tab.py

Reads from data/Watchlists.xlsx (5 sheets, ticker-only).
Dropdown selector switches between watchlists.
yfinance enriches with live price, valuation, and dividend data.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

# Brand colors
GREEN = "#569542"
BLUE = "#07415A"
GOLD = "#C9A84C"


def render_watchlist_tab():
    """
    Full watchlist tab. Call inside `with tab_watchlist:` in 1_Dashboard.py.
    """
    from data.watchlist import (
        parse_watchlist_excel, get_watchlist_names, enrich_batch,
    )

    st.markdown("#### 🔍 Research Watchlists")

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
        if selected != st.session_state["wl_active_list"]:
            st.session_state["wl_active_list"] = selected
            st.rerun()

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
    rows = []
    for tk in tickers:
        live = live_data.get(tk, {})
        price = live.get("current_price", 0)
        hi = live.get("52w_high", 0)
        lo = live.get("52w_low", 0)

        # 52-week range position
        if hi > lo > 0 and price > 0:
            range_pct = ((price - lo) / (hi - lo)) * 100
            range_str = f"{range_pct:.0f}%"
        else:
            range_str = "—"

        rows.append({
            "Ticker": tk,
            "Company": live.get("company_name", ""),
            "Sector": live.get("sector", ""),
            "Price": price,
            "Div Yield": min(live.get("dividend_yield", 0), 15),  # cap at 15% — no legit equity yield is higher
            "P/E": live.get("pe_ratio", 0),
            "Fwd P/E": live.get("forward_pe", 0),
            "P/B": live.get("price_to_book", 0),
            "Beta": live.get("beta", 0),
            "Mkt Cap": live.get("market_cap", ""),
            "52W Range": range_str,
            "52W High": hi,
            "52W Low": lo,
            "Payout %": live.get("payout_ratio", 0),
        })

    display_df = pd.DataFrame(rows)

    # ── KPI Cards ──────────────────────────────────────────────────────────
    avg_yield = display_df["Div Yield"].mean() if not display_df.empty else 0
    pe_valid = display_df[display_df["P/E"] > 0]
    avg_pe = pe_valid["P/E"].mean() if len(pe_valid) > 0 else 0
    fwd_valid = display_df[display_df["Fwd P/E"] > 0]
    avg_fwd_pe = fwd_valid["Fwd P/E"].mean() if len(fwd_valid) > 0 else 0
    avg_payout = display_df[display_df["Payout %"] > 0]["Payout %"].mean() if len(display_df[display_df["Payout %"] > 0]) > 0 else 0

    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    kc1.metric("Tickers", len(display_df))
    kc2.metric("Avg Div Yield", f"{avg_yield:.2f}%")
    kc3.metric("Avg P/E", f"{avg_pe:.1f}")
    kc4.metric("Avg Fwd P/E", f"{avg_fwd_pe:.1f}")
    kc5.metric("Avg Payout", f"{avg_payout:.0f}%")

    # ── Main Table ─────────────────────────────────────────────────────────
    table_cols = ["Ticker", "Company", "Sector", "Price", "Div Yield",
                  "P/E", "Fwd P/E", "P/B", "Beta", "Mkt Cap", "52W Range", "Payout %"]
    table_df = display_df[table_cols].copy()

    # Format for display
    table_df["Price"] = table_df["Price"].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
    table_df["Div Yield"] = table_df["Div Yield"].apply(lambda x: f"{x:.2f}%" if x > 0 else "—")
    table_df["P/E"] = table_df["P/E"].apply(lambda x: f"{x:.1f}" if x > 0 else "—")
    table_df["Fwd P/E"] = table_df["Fwd P/E"].apply(lambda x: f"{x:.1f}" if x > 0 else "—")
    table_df["P/B"] = table_df["P/B"].apply(lambda x: f"{x:.2f}" if x > 0 else "—")
    table_df["Beta"] = table_df["Beta"].apply(lambda x: f"{x:.2f}" if x > 0 else "—")
    table_df["Payout %"] = table_df["Payout %"].apply(lambda x: f"{x:.0f}%" if x > 0 else "—")

    html = _build_watchlist_html(table_df)
    st.markdown(html, unsafe_allow_html=True)

    # ── Yield Chart ────────────────────────────────────────────────────────
    yield_df = display_df[display_df["Div Yield"] > 0][["Ticker", "Div Yield"]].sort_values("Div Yield", ascending=True)
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
        st.plotly_chart(fig, use_container_width=True)

    st.caption(f"Data via yfinance · {datetime.now().strftime('%I:%M %p PT')}")


def _build_watchlist_html(df):
    """Dark-themed HTML table matching Martin Capital styling."""
    header_style = (
        "padding:8px 10px; font-size:10px; font-weight:600; "
        "color:rgba(255,255,255,0.35); text-transform:uppercase; "
        "letter-spacing:0.06em; border-bottom:1px solid rgba(255,255,255,0.08); "
        "text-align:right; white-space:nowrap;"
    )
    cell_style = (
        "padding:10px 10px; font-size:13px; color:rgba(255,255,255,0.65); "
        "border-bottom:1px solid rgba(255,255,255,0.03); text-align:right; white-space:nowrap;"
    )
    left_align = "text-align:left;"

    html = '<div style="overflow-x:auto;">'
    html += '<table style="width:100%; border-collapse:collapse; font-family:DM Sans, sans-serif;">'

    # Header
    html += "<thead><tr>"
    for col in df.columns:
        align = left_align if col in ("Ticker", "Company", "Sector") else ""
        html += f'<th style="{header_style}{align}">{col}</th>'
    html += "</tr></thead>"

    # Rows
    html += "<tbody>"
    for _, row in df.iterrows():
        html += "<tr>"
        for col in df.columns:
            val = row[col]
            align = left_align if col in ("Ticker", "Company", "Sector") else ""

            if col == "Ticker":
                style = f'{cell_style}{align}font-weight:600; color:{GOLD}; letter-spacing:0.03em;'
            elif col == "Company":
                style = f'{cell_style}{align}color:rgba(255,255,255,0.7);'
            elif col == "Div Yield" and val != "—":
                style = f'{cell_style}{align}color:{GOLD};'
            elif col == "Sector":
                style = f'{cell_style}{align}color:rgba(255,255,255,0.45); font-size:12px;'
            else:
                style = f'{cell_style}{align}'

            html += f'<td style="{style}">{val}</td>'
        html += "</tr>"
    html += "</tbody></table></div>"
    return html