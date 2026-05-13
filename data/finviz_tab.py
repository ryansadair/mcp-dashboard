"""
Martin Capital Partners — Finviz Enrichment Rendering
data/finviz_tab.py

Renders Finviz-sourced data (analyst ratings, price targets, RSI, insider
activity) as an enrichment panel within the Holdings tab.

Called from 1_Dashboard.py after the main holdings table, providing
a research overlay without cluttering the core holdings view.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from utils.config import BRAND
from data.finviz_data import fetch_finviz_batch

GREEN = BRAND["green"]
GOLD  = BRAND["gold"]
RED   = BRAND["red"]
BLUE  = BRAND["blue"]


def render_finviz_panel(tam_df, price_data, notion_data=None):
    """
    Render the Finviz enrichment panel below the main holdings table.

    Args:
        tam_df: DataFrame from get_holdings_for_strategy()
        price_data: dict from fetch_batch_prices()
        notion_data: dict from fetch_notion_metrics() (optional; provides MCP Target)
    """
    if tam_df.empty:
        return

    if notion_data is None:
        notion_data = {}

    tickers = tuple(tam_df["symbol"].tolist())

    with st.spinner("Loading Finviz analyst data..."):
        fv_data = fetch_finviz_batch(tickers)

    # Check if we got any meaningful data
    has_data = any(bool(fv_data.get(t, {})) for t in tickers)
    if not has_data:
        st.caption("Finviz data unavailable — check network or try again later.")
        return

    # ── MCP Targets & Technicals ──────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        'MCP Targets &amp; Technicals</div>',
        unsafe_allow_html=True,
    )

    # Build the analyst summary table
    rows = []
    for _, h in tam_df.iterrows():
        sym = h["symbol"]
        fv = fv_data.get(sym, {})
        mkt = price_data.get(sym, {})

        if not fv:
            continue

        rsi = fv.get("rsi_14")
        price = mkt.get("price", 0) or fv.get("price", 0)

        # MCP Target from Notion (replaces Finviz consensus target)
        nm = notion_data.get(sym.upper(), {})
        mcp_target = nm.get("mcp_target")
        if mcp_target and price and price > 0:
            upside = round((mcp_target - price) / price * 100, 1)
        else:
            upside = None

        rows.append({
            "symbol": sym,
            "description": h["description"],
            "weight_pct": h["weight_pct"],
            "price": price,
            "target": mcp_target,
            "upside": upside,
            "rsi": rsi,
            "sma20": fv.get("sma20_dist"),
            "sma50": fv.get("sma50_dist"),
            "sma200": fv.get("sma200_dist"),
            "short_float": fv.get("short_float"),
            "insider_own": fv.get("insider_own"),
            "insider_trans": fv.get("insider_trans"),
            "perf_ytd": fv.get("perf_ytd"),
            "beta": fv.get("beta"),
        })

    if not rows:
        st.caption("No Finviz data available for current holdings.")
        return

    df = pd.DataFrame(rows).sort_values("weight_pct", ascending=False)

    # ── Main Table (Sprint 25-7: sortable st.dataframe with color coding) ──
    # Convert to a Styler so we can color cells based on their numeric value,
    # then pass to st.dataframe for sortable column headers + row selection.
    # The Holdings table above uses the same pattern.

    # Build the display frame with friendly column names. The Symbol column
    # stays in the frame so we can recover the ticker on row-click for
    # drill-through to Stock Detail.
    display_df = pd.DataFrame({
        "Symbol":      df["symbol"],
        "Company":     df["description"],
        "Wt %":        df["weight_pct"],
        "Price":       df["price"],
        "MCP Target":  df["target"],
        "Upside %":    df["upside"],
        "RSI":         df["rsi"],
        "SMA200 %":    df["sma200"],
        "Short %":     df["short_float"],
        "Insider %":   df["insider_trans"],
        "YTD %":       df["perf_ytd"],
    }).reset_index(drop=True)

    # ── Cell color functions (return CSS strings for Styler.map) ──────────
    # Each function takes a single cell value and returns a CSS declaration.
    # Tier thresholds match the original badge logic in finviz_data.py.

    def _color_upside(v):
        try:
            v = float(v)
            if v >= 10:   return f"color: {GREEN}; font-weight: 600"
            if v >= 0:    return "color: rgba(255,255,255,0.7)"
            if v >= -10:  return f"color: {GOLD}"
            return f"color: {RED}; font-weight: 600"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_rsi(v):
        try:
            v = float(v)
            if v >= 70: return f"color: {RED}; font-weight: 600"
            if v >= 60: return f"color: {GOLD}"
            if v >= 40: return "color: rgba(255,255,255,0.7)"
            if v >= 30: return f"color: {GOLD}"
            return f"color: {GREEN}; font-weight: 600"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_sma200(v):
        try:
            v = float(v)
            if v > 0:  return f"color: {GREEN}"
            if v < 0:  return f"color: {RED}"
            return "color: rgba(255,255,255,0.6)"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_short(v):
        try:
            v = float(v)
            if v >= 5: return f"color: {RED}; font-weight: 600"
            if v >= 3: return f"color: {GOLD}"
            return "color: rgba(255,255,255,0.6)"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_insider(v):
        try:
            v = float(v)
            if v >= 0.5:   return f"color: {GREEN}; font-weight: 600"
            if v <= -0.5:  return f"color: {RED}; font-weight: 600"
            return "color: rgba(255,255,255,0.5)"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_ytd(v):
        try:
            v = float(v)
            return f"color: {GREEN}" if v >= 0 else f"color: {RED}"
        except (ValueError, TypeError):
            return "color: rgba(255,255,255,0.3)"

    def _color_symbol(v):
        return f"color: {GOLD}; font-weight: 600"

    styled = (
        display_df.style
        .map(_color_symbol,  subset=["Symbol"])
        .map(_color_upside,  subset=["Upside %"])
        .map(_color_rsi,     subset=["RSI"])
        .map(_color_sma200,  subset=["SMA200 %"])
        .map(_color_short,   subset=["Short %"])
        .map(_color_insider, subset=["Insider %"])
        .map(_color_ytd,     subset=["YTD %"])
    )

    # Generous height to prevent internal scrollbar on mobile (matches
    # Holdings tab pattern: 80px header + 40px per row, with a floor of
    # 250 to avoid the scrollbar-threshold oscillation we hit earlier).
    _df_height = max(250, min(80 + len(display_df) * 40, 2000))

    event = st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        height=_df_height,
        selection_mode="single-row",
        on_select="rerun",
        key="finviz_mcp_targets_table",
        column_config={
            "Symbol":      st.column_config.TextColumn("Sym", width="small"),
            "Company":     st.column_config.TextColumn("Company", width="medium"),
            "Wt %":        st.column_config.NumberColumn("Wt %", format="%.1f%%", width="small"),
            "Price":       st.column_config.NumberColumn("Price", format="$%.2f", width="small"),
            "MCP Target":  st.column_config.NumberColumn(
                "MCP Target", format="$%.0f", width="small",
                help="Martin Capital's internal price target (from Notion)",
            ),
            "Upside %":    st.column_config.NumberColumn(
                "Upside", format="%+.1f%%", width="small",
                help="% upside to MCP Target from current price",
            ),
            "RSI":         st.column_config.NumberColumn(
                "RSI", format="%.0f", width="small",
                help="14-day Relative Strength Index. >70 overbought, <30 oversold.",
            ),
            "SMA200 %":    st.column_config.NumberColumn(
                "SMA200", format="%+.1f%%", width="small",
                help="Distance from the 200-day simple moving average",
            ),
            "Short %":     st.column_config.NumberColumn(
                "Short %", format="%.1f%%", width="small",
                help="Short float — % of shares sold short",
            ),
            "Insider %":   st.column_config.NumberColumn(
                "Insider", format="%+.1f%%", width="small",
                help="Net insider transactions over last 6 months. Green = net buying, red = net selling.",
            ),
            "YTD %":       st.column_config.NumberColumn("YTD", format="%+.1f%%", width="small"),
        },
    )

    # Navigate to Stock Detail on row selection (matches Holdings tab pattern)
    if event and event.selection and event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_ticker = display_df.iloc[selected_idx]["Symbol"]
        st.session_state["detail_ticker"] = selected_ticker
        st.query_params["ticker"] = selected_ticker
        st.switch_page("pages/2_Stock_Detail.py")

    # Sprint 25-6b: removed the three Technical Signals summary widgets that
    # used to live below the main table (RSI Extremes, Trend Position 200-SMA
    # bars, Elevated Short Interest). The same data already appears in the
    # main MCP Targets & Technicals table above (RSI, SMA200, Short% columns
    # with their own color coding), so the bottom widgets were redundant.

    st.caption(
        f"Source: Finviz (technicals) · Notion (MCP targets) · Cached 1 hour · "
        f"{datetime.now().strftime('%I:%M %p')}"
    )