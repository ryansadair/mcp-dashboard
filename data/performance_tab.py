"""
Martin Capital Partners — Performance Tab
Composite returns visualization: cumulative chart, period summary,
monthly heatmap, risk metrics, and annual returns.

Data source: Composite Returns (.xls or .xlsx) via data/composite_returns.py
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
from utils.config import BRAND, STRATEGIES
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
    "QDVD": BRAND["green"],
    "SMID": BRAND["gold"],
    "DAC": BRAND["blue"],
    "OR": BRAND["green"],
}

# Annual returns column name mapping (spreadsheet -> strategy key)
ANNUAL_COL_MAP = {
    "Quality Dividend Strategy": "QDVD",
    "Quality SMID Dividend Strategy": "SMID",
    "Quality All-Cap Dividend Strategy": "DAC",
    "Oregon Dividend Strategy": "OR",
}


def _data_unavailable_card(msg="Composite returns data unavailable", detail=None):
    """Show a styled unavailable message."""
    st.markdown(f"""
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
    </div>
    """, unsafe_allow_html=True)
    if detail:
        st.caption(detail)


@st.cache_data(ttl=3600)
def _load_cached_composite(_v=2):
    """Cache composite data for 1 hour. Bump _v to bust cache after format changes."""
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
            detail=data.get("error", "Composite Returns file not found on this machine (.xls or .xlsx).")
        )
        return

    if active_strategy not in data["composites"]:
        _data_unavailable_card(
            msg=f"No composite data for {active_strategy}",
            detail="This strategy is not in the Composite Returns file."
        )
        return

    comp_df = data["composites"][active_strategy]
    strat_color = STRATEGY_COLORS.get(active_strategy, BRAND["green"])
    strat_name = STRATEGY_NAMES.get(active_strategy, active_strategy)

    # As-of date
    as_of = data.get("as_of")
    if as_of:
        st.caption(f"Source: Composite Returns as of {as_of.strftime('%B %d, %Y')} · Gross of fees")

    _render_period_returns(data, active_strategy, strat_color)
    _render_cumulative_chart(comp_df, active_strategy, strat_color, strat_name)

    _render_risk_metrics(comp_df, active_strategy, strat_color)
    _render_monthly_heatmap(comp_df, active_strategy, strat_color)

    _render_annual_returns(data, active_strategy, strat_color)


# ── Period Returns Summary ──────────────────────────────────────────────────

def _render_period_returns(data, strategy, color):
    """Render period return KPI cards using st.columns (one card per column)."""
    pr = data["period_returns"].get(strategy, {})
    if not pr:
        return

    block = COMPOSITE_BLOCKS.get(strategy, {})
    bench_name = block.get("benchmarks", {}).get("primary", {}).get("name", "")
    bench_pr = data["period_returns"].get(bench_name, {})

    periods = ["QTD", "YTD", "1Y", "3Y", "5Y", "10Y", "Since Inception (Ann.)"]
    labels = ["QTD", "YTD", "1 Year", "3 Year", "5 Year", "10 Year", "Inception (Ann.)"]

    active_periods = [(p, l) for p, l in zip(periods, labels) if pr.get(p) is not None]
    if not active_periods:
        return

    cols = st.columns(len(active_periods))
    for i, (period, label) in enumerate(active_periods):
        val = pr[period]
        val_pct = val * 100
        val_color = BRAND["green"] if val >= 0 else BRAND["red"]

        alpha_html = ""
        bench_val = bench_pr.get(period)
        if bench_val is not None:
            alpha = (val - bench_val) * 100
            a_color = BRAND["green"] if alpha >= 0 else BRAND["red"]
            a_sign = "+" if alpha >= 0 else ""
            alpha_html = f'<div style="font-size:10px; color:{a_color}; margin-top:2px;">{a_sign}{alpha:.2f}% α</div>'

        with cols[i]:
            card_html = (
                f'<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);'
                f'border-radius:8px;padding:12px 14px;">'
                f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:4px;">{label}</div>'
                f'<div style="font-size:20px;font-weight:700;color:{val_color};">{val_pct:+.2f}%</div>'
                f'{alpha_html}'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)


# ── Cumulative Performance Chart ────────────────────────────────────────────

def _render_cumulative_chart(comp_df, strategy, color, name):
    """Cumulative growth of $100 chart with benchmark overlays."""
    strat_cum = get_cumulative_series(comp_df, "gross")
    bench1_name, bench1_cum = get_benchmark_cumulative(comp_df, "primary")
    bench2_name, bench2_cum = get_benchmark_cumulative(comp_df, "secondary")

    fig = go.Figure()
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

    fig.add_trace(go.Scatter(
        x=strat_cum.index, y=strat_cum.values,
        name=name, fill="tozeroy",
        fillcolor=f"rgba({r},{g},{b},0.06)",
        line=dict(color=color, width=2.5),
        hovertemplate="%{x|%b %Y}<br>" + name + ": $%{y:.0f}<extra></extra>",
    ))

    if len(bench1_cum) > 0 and bench1_name:
        fig.add_trace(go.Scatter(
            x=bench1_cum.index, y=bench1_cum.values,
            name=bench1_name,
            line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dot"),
            hovertemplate="%{x|%b %Y}<br>" + bench1_name + ": $%{y:.0f}<extra></extra>",
        ))

    if len(bench2_cum) > 0 and bench2_name:
        fig.add_trace(go.Scatter(
            x=bench2_cum.index, y=bench2_cum.values,
            name=bench2_name,
            line=dict(color="rgba(201,168,76,0.4)", width=1.5, dash="dash"),
            hovertemplate="%{x|%b %Y}<br>" + bench2_name + ": $%{y:.0f}<extra></extra>",
        ))

    fig.add_hline(y=100, line=dict(color="rgba(255,255,255,0.1)", width=1, dash="dash"))

    _layout = {**PLOTLY_DARK}
    _layout["margin"] = dict(l=50, r=20, t=16, b=40)
    fig.update_layout(
        **_layout,
        xaxis=_XAXIS,
        yaxis={**_YAXIS, "tickprefix": "$"},
        height=380,
        hovermode="x unified",
        showlegend=True,
    )
    st.markdown(
        f'<div style="font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:4px;">'
        f'Growth of $100 — {name} vs Benchmarks (Gross)</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


# ── Risk Metrics ────────────────────────────────────────────────────────────

def _render_risk_metrics(comp_df, strategy, color):
    """Render risk metrics as a compact flex grid — fits full page width."""
    risk = compute_risk_metrics(comp_df, return_type="gross")

    if risk is None:
        _data_unavailable_card("Insufficient data for risk metrics", "Need 12+ months")
        return

    metrics = [
        ("Ann. Return", f"{risk['annualized_return']:.1%}", BRAND["green"] if risk['annualized_return'] >= 0 else BRAND["red"]),
        ("Ann. Volatility", f"{risk['annualized_vol']:.1%}", "rgba(255,255,255,0.85)"),
        ("Sharpe Ratio", f"{risk['sharpe']:.2f}", "rgba(255,255,255,0.85)"),
        ("Sortino Ratio", f"{risk['sortino']:.2f}", "rgba(255,255,255,0.85)"),
        ("Beta", f"{risk['beta']:.2f}" if not np.isnan(risk['beta']) else "—", "rgba(255,255,255,0.85)"),
        ("Max Drawdown", f"{risk['max_drawdown']:.1%}", BRAND["red"]),
        ("Tracking Error", f"{risk['tracking_error']:.1%}" if not np.isnan(risk['tracking_error']) else "—", "rgba(255,255,255,0.85)"),
        ("Info Ratio", f"{risk['information_ratio']:.2f}" if not np.isnan(risk['information_ratio']) else "—", "rgba(255,255,255,0.85)"),
        ("Best Month", f"{risk['best_month']:.1%}", BRAND["green"]),
        ("Worst Month", f"{risk['worst_month']:.1%}", BRAND["red"]),
        ("% Positive", f"{risk['pct_positive_months']:.0%}", "rgba(255,255,255,0.85)"),
    ]

    st.markdown("""<div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px;">Risk Metrics</div>""", unsafe_allow_html=True)

    # Build cards in a flex grid — wraps naturally on all screen sizes
    cards_html = ""
    for label, val, val_color in metrics:
        cards_html += f"""<div style="
            flex:1 1 130px; min-width:100px;
            background:rgba(255,255,255,0.02);
            border:1px solid rgba(255,255,255,0.05);
            border-radius:8px; padding:10px 12px;
        ">
            <div style="font-size:10px; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:3px;">{label}</div>
            <div style="font-size:16px; font-weight:700; color:{val_color};">{val}</div>
        </div>"""

    st.markdown(f"""<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px;">{cards_html}</div>""", unsafe_allow_html=True)

    st.caption("Based on monthly gross returns · Risk-free rate: 4%")


# ── Monthly Returns Heatmap ─────────────────────────────────────────────────

def _render_monthly_heatmap(comp_df, strategy, color):
    """Render heatmap using Plotly (avoids HTML size limit).
    Uses a minimum width of 760px so the 13-column grid never gets
    squeezed — on narrow screens the chart container scrolls horizontally.
    """
    hm = build_monthly_heatmap_data(comp_df, return_type="gross")

    if hm.empty:
        _data_unavailable_card("No heatmap data available")
        return

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Annual"]
    available_months = [m for m in months if m in hm.columns]
    z_data = hm[available_months].values
    years = hm.index.astype(int).tolist()

    text = []
    for row in z_data:
        text.append([f"{v*100:+.2f}%" if not pd.isna(v) else "" for v in row])

    # Minimum width ensures cells stay readable; container scrolls on mobile
    min_width = max(760, len(available_months) * 62)
    chart_height = max(280, len(years) * 30 + 100)

    fig = go.Figure(go.Heatmap(
        z=z_data * 100,
        x=available_months,
        y=years,
        colorscale=[
            [0, "#c45454"], [0.35, "#8a3a3a"],
            [0.5, "rgba(40,40,50,1)"],
            [0.65, "#3a6a30"], [1, "#569542"],
        ],
        zmid=0,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=11),
        showscale=False,
        hovertemplate="Year: %{y}<br>%{x}: %{z:.2f}%<extra></extra>",
    ))

    _hm_layout = {**PLOTLY_DARK}
    _hm_layout["margin"] = dict(l=40, r=10, t=30, b=10)
    fig.update_layout(
        **_hm_layout,
        height=chart_height,
        xaxis=dict(side="top", fixedrange=True, tickfont=dict(size=10)),
        yaxis=dict(autorange="reversed", fixedrange=True, dtick=1, tickfont=dict(size=10)),
    )

    # Title outside chart so it never overlaps month labels
    st.markdown("""<div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); text-transform:uppercase; letter-spacing:0.04em; margin-top:16px; margin-bottom:4px;">Monthly Returns Heatmap (Gross)</div>""", unsafe_allow_html=True)

    # Wrap in a scrollable container so mobile doesn't squish columns
    st.markdown(
        '<div class="heatmap-scroll-wrapper" style="overflow-x:auto; -webkit-overflow-scrolling:touch;">',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    st.markdown('</div>', unsafe_allow_html=True)


# ── Annual Returns Table ────────────────────────────────────────────────────

def _render_annual_returns(data, strategy, color):
    """Render annual returns using st.dataframe (avoids HTML size limit)."""
    ar = data.get("annual_returns")
    if ar is None or ar.empty:
        return

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
            for col in ar.columns:
                if bname.lower().replace(" ", "") in col.lower().replace(" ", ""):
                    bench_cols.append((bname, col))
                    break
            else:
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

    # Build a clean display DataFrame
    display_data = {"Year": ar["Year"].astype(int)}
    display_data[strategy] = ar[strat_col].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "—")

    primary_bench_col = None
    for i, (bname, bcol) in enumerate(bench_cols):
        if i == 0:
            primary_bench_col = bcol
        display_data[bname] = ar[bcol].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "—")

    # Alpha column
    if primary_bench_col and strat_col:
        def calc_alpha(row):
            s = row[strat_col]
            b = row[primary_bench_col]
            if pd.notna(s) and pd.notna(b):
                a = (s - b) * 100
                return f"{a:+.2f}%"
            return "—"
        display_data["Alpha"] = ar.apply(calc_alpha, axis=1)

    display_df = pd.DataFrame(display_data)

    st.markdown("""<div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); text-transform:uppercase; letter-spacing:0.04em; margin-top:16px; margin-bottom:8px;">Calendar Year Returns (Gross)</div>""", unsafe_allow_html=True)
    st.dataframe(display_df, hide_index=True, use_container_width=True)