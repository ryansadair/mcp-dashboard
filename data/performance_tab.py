"""
Martin Capital Partners — Performance Tab
Composite returns visualization: cumulative chart, period summary,
monthly heatmap, risk metrics, and annual returns.

Data source: Composite_Returns.xls via data/composite_returns.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

from data.composite_returns import (
    load_composite_data,
    get_cumulative_series,
    get_benchmark_cumulative,
    get_monthly_returns,
    compute_risk_metrics,
    build_monthly_heatmap_data,
    COMPOSITE_BLOCKS,
)
from utils.config import COLORS, STRATEGIES
from utils.mobile_css import inject_mobile_css

# ── Chart Theme ─────────────────────────────────────────────────────────────
PLOTLY_DARK = dict(
    paper_bgcolor="rgba(255,255,255,0.02)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    margin=dict(l=10, r=10, t=40, b=10),
)
_XAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))
_YAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))
PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False, "showTips": False, "staticPlot": True}

# Strategy display names and colors
STRATEGY_NAMES = {
    "QDVD": "Quality Dividend",
    "SMID": "Quality SMID Dividend",
    "DAC": "Quality All-Cap Dividend",
    "OR": "Oregon Dividend",
}
STRATEGY_COLORS = {
    "QDVD": COLORS["green"],
    "SMID": COLORS["gold"],
    "DAC": COLORS["blue"],
    "OR": COLORS["green"],
}

# Annual returns column name mapping (spreadsheet → strategy key)
ANNUAL_COL_MAP = {
    "Quality Dividend Strategy": "QDVD",
    "Quality SMID Dividend Strategy": "SMID",
    "Quality All-Cap Dividend Strategy": "DAC",
    "Oregon Dividend Strategy": "OR",
}


def _data_unavailable_card(msg="Composite returns data unavailable", detail=None):
    """Show a styled unavailable message."""
    html = f"""
    <div style="
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px;
        padding: 40px 24px;
        text-align: center;
        margin: 20px 0;
    ">
        <div style="font-size: 32px; margin-bottom: 12px; opacity: 0.3;">📊</div>
        <div style="font-size: 15px; color: rgba(255,255,255,0.6); font-weight: 600;">
            {msg}
        </div>
    """
    if detail:
        html += f"""
        <div style="font-size: 12px; color: rgba(255,255,255,0.3); margin-top: 8px;">
            {detail}
        </div>
        """
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def _load_cached_composite():
    """Cache composite data for 1 hour."""
    return load_composite_data()


def render_performance_tab(active_strategy):
    """
    Render the Performance tab for the given strategy.
    Called from 1_Dashboard.py when the Performance nav tab is active.
    """
    inject_mobile_css()
    data = _load_cached_composite()

    if not data["available"]:
        _data_unavailable_card(
            detail=data.get("error", "Composite_Returns.xls not found on this machine.")
        )
        return

    # Check if this strategy has composite data
    if active_strategy not in data["composites"]:
        _data_unavailable_card(
            msg=f"No composite data for {active_strategy}",
            detail="This strategy is not in Composite_Returns.xls."
        )
        return

    comp_df = data["composites"][active_strategy]
    strat_color = STRATEGY_COLORS.get(active_strategy, COLORS["green"])
    strat_name = STRATEGY_NAMES.get(active_strategy, active_strategy)

    # As-of date
    as_of = data.get("as_of")
    if as_of:
        st.caption(f"Source: Composite Returns as of {as_of.strftime('%B %d, %Y')} · Gross of fees")

    # ── Period Returns Summary ──────────────────────────────────────────
    _render_period_returns(data, active_strategy, strat_color)

    # ── Cumulative Performance Chart ────────────────────────────────────
    _render_cumulative_chart(comp_df, active_strategy, strat_color, strat_name)

    # ── Risk Metrics + Monthly Heatmap (side by side on desktop) ────────
    col_left, col_right = st.columns([1, 2])
    with col_left:
        _render_risk_metrics(comp_df, active_strategy, strat_color)
    with col_right:
        _render_monthly_heatmap(comp_df, active_strategy, strat_color)

    # ── Annual Returns Table ────────────────────────────────────────────
    _render_annual_returns(data, active_strategy, strat_color)


# ── Period Returns Summary ──────────────────────────────────────────────────

def _render_period_returns(data, strategy, color):
    """Render the QTD/YTD/1Y/3Y/5Y/10Y/Inception KPI row."""
    pr = data["period_returns"].get(strategy, {})
    if not pr:
        return

    # Get benchmark period returns for comparison
    bench_name = ""
    bench_block = None
    block = COMPOSITE_BLOCKS.get(strategy, {})
    if block:
        bench_name = block["benchmarks"].get("primary", {}).get("name", "")

    bench_pr = data["period_returns"].get(bench_name, {})

    # Build the cards
    periods = ["QTD", "YTD", "1Y", "3Y", "5Y", "10Y", "Since Inception (Ann.)"]
    labels = ["QTD", "YTD", "1 Year", "3 Year", "5 Year", "10 Year", "Inception (Ann.)"]

    cards_html = '<div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:20px;">'
    for period, label in zip(periods, labels):
        val = pr.get(period)
        if val is None:
            continue

        bench_val = bench_pr.get(period)
        val_pct = val * 100
        val_color = COLORS["green"] if val >= 0 else COLORS["red"]

        # Alpha line
        alpha_html = ""
        if bench_val is not None:
            alpha = (val - bench_val) * 100
            a_color = COLORS["green"] if alpha >= 0 else COLORS["red"]
            a_sign = "+" if alpha >= 0 else ""
            alpha_html = f'<div style="font-size:10px; color:{a_color}; margin-top:2px;">{a_sign}{alpha:.1f}% α</div>'

        cards_html += f"""
        <div style="
            flex: 1 1 110px;
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 8px;
            padding: 12px 14px;
            min-width: 100px;
        ">
            <div style="font-size:10px; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:4px;">{label}</div>
            <div style="font-size:20px; font-weight:700; color:{val_color};">{val_pct:+.1f}%</div>
            {alpha_html}
        </div>
        """
    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)


# ── Cumulative Performance Chart ────────────────────────────────────────────

def _render_cumulative_chart(comp_df, strategy, color, name):
    """Cumulative growth of $100 chart with benchmark overlays."""
    # Strategy cumulative
    strat_cum = get_cumulative_series(comp_df, "gross")

    # Primary benchmark
    bench1_name, bench1_cum = get_benchmark_cumulative(comp_df, "primary")

    # Secondary benchmark
    bench2_name, bench2_cum = get_benchmark_cumulative(comp_df, "secondary")

    fig = go.Figure()

    # Parse hex color for fill
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

    # Strategy line
    fig.add_trace(go.Scatter(
        x=strat_cum.index,
        y=strat_cum.values,
        name=name,
        fill="tozeroy",
        fillcolor=f"rgba({r},{g},{b},0.06)",
        line=dict(color=color, width=2.5),
        hovertemplate="%{x|%b %Y}<br>" + name + ": $%{y:.0f}<extra></extra>",
    ))

    # Primary benchmark
    if len(bench1_cum) > 0 and bench1_name:
        fig.add_trace(go.Scatter(
            x=bench1_cum.index,
            y=bench1_cum.values,
            name=bench1_name,
            line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dot"),
            hovertemplate="%{x|%b %Y}<br>" + bench1_name + ": $%{y:.0f}<extra></extra>",
        ))

    # Secondary benchmark
    if len(bench2_cum) > 0 and bench2_name:
        fig.add_trace(go.Scatter(
            x=bench2_cum.index,
            y=bench2_cum.values,
            name=bench2_name,
            line=dict(color="rgba(201,168,76,0.4)", width=1.5, dash="dash"),
            hovertemplate="%{x|%b %Y}<br>" + bench2_name + ": $%{y:.0f}<extra></extra>",
        ))

    # $100 baseline
    fig.add_hline(y=100, line=dict(color="rgba(255,255,255,0.1)", width=1, dash="dash"))

    _layout = {**PLOTLY_DARK}
    _layout["margin"] = dict(l=50, r=20, t=40, b=40)
    fig.update_layout(
        **_layout,
        title=f"Growth of $100 — {name} vs Benchmarks (Gross)",
        xaxis=_XAXIS,
        yaxis={**_YAXIS, "tickprefix": "$"},
        height=380,
        hovermode="x unified",
        showlegend=True,
    )

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


# ── Risk Metrics ────────────────────────────────────────────────────────────

def _render_risk_metrics(comp_df, strategy, color):
    """Render risk metrics card computed from monthly composite returns."""
    risk = compute_risk_metrics(comp_df, return_type="gross")

    if risk is None:
        _data_unavailable_card("Insufficient data for risk metrics", "Need 12+ months")
        return

    metrics = [
        ("Ann. Return", f"{risk['annualized_return']:.1%}"),
        ("Ann. Volatility", f"{risk['annualized_vol']:.1%}"),
        ("Sharpe Ratio", f"{risk['sharpe']:.2f}"),
        ("Sortino Ratio", f"{risk['sortino']:.2f}"),
        ("Beta", f"{risk['beta']:.2f}" if not np.isnan(risk['beta']) else "—"),
        ("Max Drawdown", f"{risk['max_drawdown']:.1%}"),
        ("Tracking Error", f"{risk['tracking_error']:.1%}" if not np.isnan(risk['tracking_error']) else "—"),
        ("Information Ratio", f"{risk['information_ratio']:.2f}" if not np.isnan(risk['information_ratio']) else "—"),
        ("Best Month", f"{risk['best_month']:.1%}"),
        ("Worst Month", f"{risk['worst_month']:.1%}"),
        ("% Positive Months", f"{risk['pct_positive_months']:.0%}"),
    ]

    rows_html = ""
    for label, val in metrics:
        # Color coding for certain metrics
        if label == "Ann. Return":
            val_color = COLORS["green"] if risk['annualized_return'] >= 0 else COLORS["red"]
        elif label == "Max Drawdown":
            val_color = COLORS["red"]
        elif label == "Best Month":
            val_color = COLORS["green"]
        elif label == "Worst Month":
            val_color = COLORS["red"]
        else:
            val_color = "rgba(255,255,255,0.85)"

        rows_html += f"""
        <div style="display:flex; justify-content:space-between; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
            <span style="font-size:12px; color:rgba(255,255,255,0.5);">{label}</span>
            <span style="font-size:12px; font-weight:600; color:{val_color};">{val}</span>
        </div>
        """

    html = f"""
    <div style="
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 16px 18px;
    ">
        <div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;">
            Risk Metrics
        </div>
        {rows_html}
        <div style="font-size:10px; color:rgba(255,255,255,0.2); margin-top:8px;">
            Based on monthly gross returns · Risk-free rate: 4%
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ── Monthly Returns Heatmap ─────────────────────────────────────────────────

def _render_monthly_heatmap(comp_df, strategy, color):
    """Render a year × month returns heatmap."""
    hm = build_monthly_heatmap_data(comp_df, return_type="gross")

    if hm.empty:
        _data_unavailable_card("No heatmap data available")
        return

    # Build the heatmap as an HTML table for pixel-perfect control
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Annual"]

    # Header row
    header_cells = '<th style="padding:4px 6px; font-size:10px; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.04em; text-align:center; border-bottom:1px solid rgba(255,255,255,0.06);">Year</th>'
    for m in months:
        weight = "font-weight:700;" if m == "Annual" else ""
        header_cells += f'<th style="padding:4px 6px; font-size:10px; color:rgba(255,255,255,0.3); text-align:center; border-bottom:1px solid rgba(255,255,255,0.06); {weight}">{m}</th>'

    # Data rows
    data_rows = ""
    for year in hm.index:
        row_cells = f'<td style="padding:5px 6px; font-size:12px; font-weight:600; color:rgba(255,255,255,0.7); white-space:nowrap;">{int(year)}</td>'
        for m in months:
            val = hm.loc[year, m] if m in hm.columns else np.nan
            if pd.isna(val):
                row_cells += '<td style="padding:5px 6px; text-align:center; font-size:11px; color:rgba(255,255,255,0.15);">—</td>'
            else:
                pct = val * 100
                # Color intensity based on magnitude
                if pct > 0:
                    intensity = min(pct / 8, 1)  # cap at 8% for full green
                    bg = f"rgba(86,149,66,{0.08 + intensity * 0.25})"
                    txt_color = COLORS["green"]
                elif pct < 0:
                    intensity = min(abs(pct) / 8, 1)
                    bg = f"rgba(196,84,84,{0.08 + intensity * 0.25})"
                    txt_color = COLORS["red"]
                else:
                    bg = "transparent"
                    txt_color = "rgba(255,255,255,0.5)"

                is_annual = m == "Annual"
                fw = "font-weight:700;" if is_annual else ""
                border = "border-left:2px solid rgba(255,255,255,0.06);" if is_annual else ""

                row_cells += f'<td style="padding:5px 6px; text-align:center; font-size:11px; color:{txt_color}; background:{bg}; {fw} {border}">{pct:+.1f}%</td>'

        data_rows += f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03);">{row_cells}</tr>'

    html = f"""
    <div style="
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 16px 18px;
        overflow-x: auto;
    ">
        <div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;">
            Monthly Returns Heatmap
        </div>
        <div style="overflow-x:auto; -webkit-overflow-scrolling:touch;">
            <table style="width:100%; border-collapse:collapse; min-width:680px; table-layout:fixed;">
                <colgroup>
                    <col style="width:52px;">
                    {''.join('<col style="width:48px;">' for _ in range(12))}
                    <col style="width:56px;">
                </colgroup>
                <thead><tr>{header_cells}</tr></thead>
                <tbody>{data_rows}</tbody>
            </table>
        </div>
        <div style="font-size:10px; color:rgba(255,255,255,0.2); margin-top:8px;">
            Monthly gross returns · Annual = geometric compounding
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ── Annual Returns Table ────────────────────────────────────────────────────

def _render_annual_returns(data, strategy, color):
    """Render calendar year returns table for this strategy vs benchmarks."""
    ar = data.get("annual_returns")
    if ar is None or ar.empty:
        return

    # Map column names to get strategy and benchmark columns
    block = COMPOSITE_BLOCKS.get(strategy, {})
    benchmarks = block.get("benchmarks", {})

    # Find strategy column
    strat_col = None
    for col_name, key in ANNUAL_COL_MAP.items():
        if key == strategy and col_name in ar.columns:
            strat_col = col_name
            break

    if strat_col is None:
        return

    # Benchmark columns
    bench_cols = []
    for btype in ["primary", "secondary"]:
        bname = benchmarks.get(btype, {}).get("name", "")
        if bname:
            # Find matching column in annual returns
            for col in ar.columns:
                if bname.lower().replace(" ", "") in col.lower().replace(" ", ""):
                    bench_cols.append((bname, col))
                    break
            else:
                # Try partial match
                if bname == "S&P Mid Cap 400":
                    for col in ar.columns:
                        if "S&P 400" in col or "Mid Cap" in col:
                            bench_cols.append((bname, col))
                            break
                elif bname == "S&P 400 Aristocrats":
                    for col in ar.columns:
                        if "Aristocrats" in col and "400" in col:
                            bench_cols.append((bname, col))
                            break

    # Build HTML table
    strat_name = STRATEGY_NAMES.get(strategy, strategy)

    # Header
    header = f"""
    <th style="padding:8px 10px; font-size:10px; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.04em; text-align:center; border-bottom:1px solid rgba(255,255,255,0.06);">Year</th>
    <th style="padding:8px 10px; font-size:10px; color:{color}; text-transform:uppercase; letter-spacing:0.04em; text-align:center; border-bottom:1px solid rgba(255,255,255,0.06); font-weight:700;">{strategy}</th>
    """
    for bname, _ in bench_cols:
        header += f'<th style="padding:8px 10px; font-size:10px; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.04em; text-align:center; border-bottom:1px solid rgba(255,255,255,0.06);">{bname}</th>'
    header += f'<th style="padding:8px 10px; font-size:10px; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.04em; text-align:center; border-bottom:1px solid rgba(255,255,255,0.06);">Alpha vs Primary</th>'

    # Data rows
    rows_html = ""
    for _, row in ar.iterrows():
        year = int(row["Year"])
        strat_val = row.get(strat_col)

        # Strategy cell
        if pd.notna(strat_val):
            pct = strat_val * 100
            val_color = COLORS["green"] if strat_val >= 0 else COLORS["red"]
            strat_cell = f'<td style="padding:8px 10px; text-align:center; font-size:12px; font-weight:600; color:{val_color};">{pct:+.1f}%</td>'
        else:
            strat_cell = '<td style="padding:8px 10px; text-align:center; font-size:12px; color:rgba(255,255,255,0.15);">—</td>'

        # Benchmark cells
        bench_cells = ""
        primary_bench_val = None
        for i, (bname, bcol) in enumerate(bench_cols):
            bval = row.get(bcol)
            if i == 0:
                primary_bench_val = bval
            if pd.notna(bval):
                bpct = bval * 100
                bcolor = "rgba(255,255,255,0.6)" if bval >= 0 else COLORS["red"]
                bench_cells += f'<td style="padding:8px 10px; text-align:center; font-size:12px; color:{bcolor};">{bpct:+.1f}%</td>'
            else:
                bench_cells += '<td style="padding:8px 10px; text-align:center; font-size:12px; color:rgba(255,255,255,0.15);">—</td>'

        # Alpha cell
        if pd.notna(strat_val) and pd.notna(primary_bench_val):
            alpha = (strat_val - primary_bench_val) * 100
            a_color = COLORS["green"] if alpha >= 0 else COLORS["red"]
            a_sign = "+" if alpha >= 0 else ""
            alpha_cell = f'<td style="padding:8px 10px; text-align:center; font-size:12px; font-weight:600; color:{a_color};">{a_sign}{alpha:.1f}%</td>'
        else:
            alpha_cell = '<td style="padding:8px 10px; text-align:center; font-size:12px; color:rgba(255,255,255,0.15);">—</td>'

        rows_html += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
            <td style="padding:8px 10px; text-align:center; font-size:12px; font-weight:600; color:rgba(255,255,255,0.7);">{year}</td>
            {strat_cell}
            {bench_cells}
            {alpha_cell}
        </tr>
        """

    html = f"""
    <div style="
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 16px 18px;
        margin-top: 16px;
        overflow-x: auto;
    ">
        <div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;">
            Calendar Year Returns (Gross)
        </div>
        <div style="overflow-x:auto; -webkit-overflow-scrolling:touch;">
            <table style="width:100%; border-collapse:collapse; min-width:480px;">
                <thead><tr>{header}</tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)