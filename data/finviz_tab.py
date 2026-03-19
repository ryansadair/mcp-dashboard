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
    recommendation_badge,
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

    # ── Analyst Consensus Summary ─────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        'Analyst Ratings &amp; MCP Price Targets</div>',
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

        rec_val = fv.get("recommendation")
        rec_label = fv.get("rec_label", "—")
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
            "rec_val": rec_val,
            "rec_label": rec_label,
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

    # ── Summary KPIs ──────────────────────────────────────────────────────
    valid_recs = [r for r in df["rec_val"].dropna()]
    valid_upsides = [r for r in df["upside"].dropna()]

    avg_rec = sum(valid_recs) / len(valid_recs) if valid_recs else None
    avg_upside = sum(valid_upsides) / len(valid_upsides) if valid_upsides else None
    buys = len([r for r in valid_recs if r <= 2.0])
    holds = len([r for r in valid_recs if 2.0 < r <= 3.0])
    sells = len([r for r in valid_recs if r > 3.0])

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        if avg_rec is not None:
            _, lbl = None, "—"
            if avg_rec <= 2.0:
                lbl = "Buy"
            elif avg_rec <= 3.0:
                lbl = "Hold"
            else:
                lbl = "Sell"
            st.metric("Avg Rating", f"{avg_rec:.1f} ({lbl})")
        else:
            st.metric("Avg Rating", "—")
    with k2:
        if avg_upside is not None:
            st.metric("Avg Upside to MCP Target", f"{avg_upside:+.1f}%")
        else:
            st.metric("Avg Upside to MCP Target", "—")
    with k3:
        st.metric("Buy / Hold / Sell", f"{buys} / {holds} / {sells}")
    with k4:
        above_200 = len([1 for _, r in df.iterrows() if r.get("sma200") and r["sma200"] > 0])
        st.metric("Above 200-SMA", f"{above_200} / {len(df)}")

    # ── Main Analyst Table ────────────────────────────────────────────────
    # Render as custom HTML for badge formatting
    header_style = (
        "padding:6px 8px;font-size:10px;font-weight:600;"
        "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
        "border-bottom:1px solid rgba(255,255,255,0.06)"
    )

    html = (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed">'
        '<colgroup>'
        '<col style="width:7%"><col style="width:18%"><col style="width:6%">'
        '<col style="width:8%"><col style="width:15%"><col style="width:8%">'
        '<col style="width:8%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:8%"><col style="width:8%">'
        '</colgroup>'
        f'<thead><tr>'
        f'<th style="text-align:left;{header_style}">Sym</th>'
        f'<th style="text-align:left;{header_style}">Company</th>'
        f'<th style="text-align:right;{header_style}">Wt%</th>'
        f'<th style="text-align:right;{header_style}">Price</th>'
        f'<th style="text-align:center;{header_style}">Analyst</th>'
        f'<th style="text-align:right;{header_style}">MCP Target</th>'
        f'<th style="text-align:right;{header_style}">Upside</th>'
        f'<th style="text-align:right;{header_style}">RSI</th>'
        f'<th style="text-align:right;{header_style}">SMA200</th>'
        f'<th style="text-align:right;{header_style}">Short%</th>'
        f'<th style="text-align:right;{header_style}">YTD</th>'
        f'</tr></thead><tbody>'
    )

    for _, r in df.iterrows():
        rec_html = recommendation_badge(r["rec_val"], r["rec_label"])
        up_html = upside_badge(r["upside"])
        rsi_html = rsi_indicator(r["rsi"])

        target_str = f"${r['target']:.0f}" if r["target"] else "—"
        sma200_str = f"{r['sma200']:+.1f}%" if r["sma200"] is not None else "—"
        sma200_color = GREEN if r.get("sma200") and r["sma200"] > 0 else RED if r.get("sma200") and r["sma200"] < 0 else "rgba(255,255,255,0.4)"
        short_str = f"{r['short_float']:.1f}%" if r["short_float"] is not None else "—"
        short_color = RED if r.get("short_float") and r["short_float"] > 5 else "rgba(255,255,255,0.6)"
        ytd_str = f"{r['perf_ytd']:+.1f}%" if r["perf_ytd"] is not None else "—"
        ytd_color = GREEN if r.get("perf_ytd") and r["perf_ytd"] >= 0 else RED

        # Highlight row if analyst says sell or big upside
        bg = ""
        if r.get("rec_val") and r["rec_val"] > 3.0:
            bg = "background:rgba(196,84,84,0.04);"
        elif r.get("upside") and r["upside"] >= 20:
            bg = "background:rgba(86,149,66,0.04);"

        html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03);{bg}">'
            f'<td style="text-align:left;padding:8px;font-size:12px;font-weight:600;color:#C9A84C;">{r["symbol"]}</td>'
            f'<td style="text-align:left;padding:8px;font-size:11px;color:rgba(255,255,255,0.5);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r["description"]}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.6);">{r["weight_pct"]:.1f}%</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.8);">${r["price"]:.2f}</td>'
            f'<td style="text-align:center;padding:8px;">{rec_html}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.7);">{target_str}</td>'
            f'<td style="text-align:right;padding:8px;">{up_html}</td>'
            f'<td style="text-align:right;padding:8px;">{rsi_html}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{sma200_color};">{sma200_str}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{short_color};">{short_str}</td>'
            f'<td style="text-align:right;padding:8px;font-size:12px;color:{ytd_color};">{ytd_str}</td>'
            f'</tr>'
        )

    html += '</tbody></table>'

    # Render row by row to avoid Streamlit HTML size limit
    # Split into chunks of ~5 rows each
    st.markdown(html, unsafe_allow_html=True)

    # ── Technical Signals Summary ─────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        'Technical Signals</div>',
        unsafe_allow_html=True,
    )

    col_rsi, col_sma = st.columns(2)

    with col_rsi:
        st.markdown("**RSI Extremes**")
        overbought = df[df["rsi"].apply(lambda x: x is not None and x >= 70)]
        oversold = df[df["rsi"].apply(lambda x: x is not None and x <= 30)]

        if not overbought.empty:
            for _, r in overbought.iterrows():
                st.markdown(
                    f'<div style="padding:6px 10px;margin-bottom:4px;border-radius:6px;'
                    f'background:rgba(196,84,84,0.08);border-left:3px solid {RED};">'
                    f'<span style="font-weight:600;color:rgba(255,255,255,0.8);">{r["symbol"]}</span>'
                    f' <span style="color:rgba(255,255,255,0.4);">RSI {r["rsi"]:.0f}</span>'
                    f' <span style="font-size:10px;color:{RED};">Overbought</span></div>',
                    unsafe_allow_html=True,
                )
        if not oversold.empty:
            for _, r in oversold.iterrows():
                st.markdown(
                    f'<div style="padding:6px 10px;margin-bottom:4px;border-radius:6px;'
                    f'background:rgba(86,149,66,0.08);border-left:3px solid {GREEN};">'
                    f'<span style="font-weight:600;color:rgba(255,255,255,0.8);">{r["symbol"]}</span>'
                    f' <span style="color:rgba(255,255,255,0.4);">RSI {r["rsi"]:.0f}</span>'
                    f' <span style="font-size:10px;color:{GREEN};">Oversold</span></div>',
                    unsafe_allow_html=True,
                )
        if overbought.empty and oversold.empty:
            st.caption("No holdings at RSI extremes (>70 or <30)")

    with col_sma:
        st.markdown("**Trend Position (200-SMA)**")
        for _, r in df.sort_values("sma200", ascending=True, na_position="last").iterrows():
            if r["sma200"] is None:
                continue
            dist = r["sma200"]
            if dist < -10:
                color = RED
                bar_color = "rgba(196,84,84,0.6)"
            elif dist < 0:
                color = GOLD
                bar_color = "rgba(201,168,76,0.5)"
            else:
                color = GREEN
                bar_color = "rgba(86,149,66,0.5)"

            # Normalize bar width: map -30% to +30% range onto 0-100%
            bar_pct = max(0, min(100, (dist + 30) / 60 * 100))

            st.markdown(
                f'<div style="display:flex;align-items:center;margin-bottom:4px;gap:8px;">'
                f'<span style="width:42px;font-size:11px;font-weight:600;color:#C9A84C;">{r["symbol"]}</span>'
                f'<div style="flex:1;height:10px;background:rgba(255,255,255,0.04);border-radius:3px;position:relative;">'
                f'<div style="position:absolute;left:50%;top:0;width:1px;height:10px;background:rgba(255,255,255,0.15);"></div>'
                f'<div style="width:{bar_pct:.0f}%;height:10px;border-radius:3px;background:{bar_color};"></div>'
                f'</div>'
                f'<span style="width:48px;font-size:11px;text-align:right;color:{color};">{dist:+.1f}%</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Short Interest Watchlist ──────────────────────────────────────────
    high_short = df[df["short_float"].apply(lambda x: x is not None and x >= 3.0)]
    if not high_short.empty:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
            'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
            'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
            'Elevated Short Interest (≥3%)</div>',
            unsafe_allow_html=True,
        )
        for _, r in high_short.sort_values("short_float", ascending=False).iterrows():
            color = RED if r["short_float"] >= 5 else GOLD
            st.markdown(
                f'<div style="padding:8px 12px;margin-bottom:6px;border-radius:6px;'
                f'background:rgba(201,168,76,0.05);border-left:3px solid {color};">'
                f'<span style="font-weight:600;color:rgba(255,255,255,0.8);">{r["symbol"]}</span>'
                f' — <span style="color:{color};font-weight:500;">{r["short_float"]:.1f}% short</span>'
                f' <span style="color:rgba(255,255,255,0.35);font-size:11px;">'
                f'· RSI {r["rsi"]:.0f}' if r["rsi"] else ''
                f'</span></div>',
                unsafe_allow_html=True,
            )

    st.caption(
        f"Source: Finviz (analyst ratings, technicals) · Notion (MCP targets) · Cached 1 hour · "
        f"{datetime.now().strftime('%I:%M %p')} · "
        f"Analyst ratings are consensus of Wall Street coverage"
    )