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
from data.finviz_data import (
    fetch_finviz_batch,
    upside_badge,
    rsi_indicator,
)

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

    # ── Main Table ────────────────────────────────────────────────────────
    # Render as custom HTML for badge formatting
    header_style = (
        "padding:6px 8px;font-size:10px;font-weight:600;"
        "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
        "border-bottom:1px solid rgba(255,255,255,0.06)"
    )

    html = (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed">'
        '<colgroup>'
        '<col style="width:6%"><col style="width:20%"><col style="width:6%">'
        '<col style="width:8%"><col style="width:11%"><col style="width:9%">'
        '<col style="width:8%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:8%"><col style="width:8%">'
        '</colgroup>'
        f'<thead><tr>'
        f'<th style="text-align:left;{header_style}">Sym</th>'
        f'<th style="text-align:left;{header_style}">Company</th>'
        f'<th style="text-align:right;{header_style}">Wt%</th>'
        f'<th style="text-align:right;{header_style}">Price</th>'
        f'<th style="text-align:right;{header_style}">MCP Target</th>'
        f'<th style="text-align:right;{header_style}">Upside</th>'
        f'<th style="text-align:right;{header_style}">RSI</th>'
        f'<th style="text-align:right;{header_style}">SMA200</th>'
        f'<th style="text-align:right;{header_style}">Short%</th>'
        f'<th style="text-align:right;{header_style}" title="Net insider transactions over the last 6 months. Green = net buying, red = net selling.">Insider</th>'
        f'<th style="text-align:right;{header_style}">YTD</th>'
        f'</tr></thead><tbody>'
    )

    for _, r in df.iterrows():
        up_html = upside_badge(r["upside"])
        rsi_html = rsi_indicator(r["rsi"])

        target_str = f"${r['target']:.0f}" if r["target"] else "—"
        sma200_str = f"{r['sma200']:+.1f}%" if r["sma200"] is not None else "—"
        sma200_color = GREEN if r.get("sma200") and r["sma200"] > 0 else RED if r.get("sma200") and r["sma200"] < 0 else "rgba(255,255,255,0.4)"
        short_str = f"{r['short_float']:.1f}%" if r["short_float"] is not None else "—"
        short_color = RED if r.get("short_float") and r["short_float"] > 5 else "rgba(255,255,255,0.6)"
        ytd_str = f"{r['perf_ytd']:+.1f}%" if r["perf_ytd"] is not None else "—"
        ytd_color = GREEN if r.get("perf_ytd") and r["perf_ytd"] >= 0 else RED

        # Insider transactions — net % change in insider holdings over last 6 months.
        # Positive = net buying (bullish), negative = net selling (bearish).
        # Thresholds: |x| < 0.5% treated as noise/flat.
        it = r.get("insider_trans")
        if it is None:
            insider_html = '<span style="color:rgba(255,255,255,0.25);">—</span>'
        elif abs(it) < 0.5:
            insider_html = (
                f'<span style="font-size:11px;color:rgba(255,255,255,0.4);">'
                f'{it:+.1f}%</span>'
            )
        elif it > 0:
            # Net buying — green badge with up arrow
            insider_html = (
                f'<span style="font-size:11px;font-weight:600;color:{GREEN};'
                f'background:rgba(86,149,66,0.10);padding:2px 6px;border-radius:3px;'
                f'white-space:nowrap;">▲ {it:+.1f}%</span>'
            )
        else:
            # Net selling — red badge with down arrow
            insider_html = (
                f'<span style="font-size:11px;font-weight:600;color:{RED};'
                f'background:rgba(196,84,84,0.10);padding:2px 6px;border-radius:3px;'
                f'white-space:nowrap;">▼ {it:+.1f}%</span>'
            )

        # Highlight row when MCP target shows big upside (analyst-driven highlight removed
        # along with the Analyst column).
        bg = ""
        if r.get("upside") and r["upside"] >= 20:
            bg = "background:rgba(86,149,66,0.04);"

        html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03);{bg}">'
            f'<td style="text-align:left;padding:8px;font-size:12px;font-weight:600;color:#C9A84C;">{r["symbol"]}</td>'
            f'<td style="text-align:left;padding:8px;font-size:11px;color:rgba(255,255,255,0.5);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r["description"]}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.6);">{r["weight_pct"]:.1f}%</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.8);">${r["price"]:.2f}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.7);">{target_str}</td>'
            f'<td style="text-align:right;padding:8px;">{up_html}</td>'
            f'<td style="text-align:right;padding:8px;">{rsi_html}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{sma200_color};">{sma200_str}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{short_color};">{short_str}</td>'
            f'<td style="text-align:right;padding:8px;">{insider_html}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{ytd_color};">{ytd_str}</td>'
            f'</tr>'
        )

    html += '</tbody></table>'

    # Render row by row to avoid Streamlit HTML size limit
    # Split into chunks of ~5 rows each
    st.markdown(html, unsafe_allow_html=True)

    # Sprint 25-6b: removed the three Technical Signals summary widgets that
    # used to live below the main table (RSI Extremes, Trend Position 200-SMA
    # bars, Elevated Short Interest). The same data already appears in the
    # main MCP Targets & Technicals table above (RSI, SMA200, Short% columns
    # with their own color coding), so the bottom widgets were redundant.

    st.caption(
        f"Source: Finviz (technicals) · Notion (MCP targets) · Cached 1 hour · "
        f"{datetime.now().strftime('%I:%M %p')}"
    )