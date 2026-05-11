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
from utils.disk_cache import disk_cached

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
# Sprint 24-4 followup: cumulative chart wants hover tooltips (so values are
# legible without enabling pan/zoom). Setting staticPlot=False re-enables
# hover; the layout-level dragmode=False + axis fixedrange=True keep
# pan/zoom interactions disabled.
PLOTLY_CHART_CONFIG = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False, "showTips": False, "staticPlot": False}

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


@st.cache_data(ttl=86400, show_spinner=False)
@disk_cached(namespace="perf_composite_raw", ttl=86400, version=2)
def _load_cached_composite(_v=2):
    """Cache composite data for 24 hours (Sprint 24-2: was 1 hour).

    Three-tier cache: memory (per session) → disk (survives session eviction)
    → Excel parse. On return-from-idle, disk layer avoids the multi-second
    openpyxl/xlrd parse that was blocking every tab after Performance.

    Bump the outer version (decorator) to force disk cache busts after Excel
    format changes; bump _v for behavioral changes to the parser.
    """
    return load_composite_data()


# Per-strategy computation cache (Sprint 24-2: bundled)
# Previously three separate @disk_cached functions (_cached_cumulative,
# _cached_risk_metrics, _cached_heatmap). Each re-read _load_cached_composite()
# and wrote its own payload to disk. On Streamlit Cloud ephemeral disk
# that is three round-trips per strategy view.
# Now collapsed to one bundled function: one parse, one serialize, one write.

@st.cache_data(ttl=86400, show_spinner=False)
@disk_cached(namespace="perf_per_strategy", ttl=86400, version=3)
def _cached_per_strategy(strategy: str, as_of_iso: str, _v=3):
    """Compute every per-strategy artifact in one shot.

    Returns:
        {
          "cumulative": { strat_cum, bench1_name, bench1_cum,
                          bench2_name, bench2_cum },
          "risk":       dict from compute_risk_metrics(),
          "heatmap":    pd.DataFrame from build_monthly_heatmap_data(),
        }
    """
    data = _load_cached_composite()
    comp_df = data["composites"][strategy]
    strat_cum = get_cumulative_series(comp_df, "gross")
    bench1_name, bench1_cum = get_benchmark_cumulative(comp_df, "primary")
    bench2_name, bench2_cum = get_benchmark_cumulative(comp_df, "secondary")
    return {
        "cumulative": {
            "strat_cum":   strat_cum,
            "bench1_name": bench1_name,
            "bench1_cum":  bench1_cum,
            "bench2_name": bench2_name,
            "bench2_cum":  bench2_cum,
        },
        "risk":    compute_risk_metrics(comp_df, return_type="gross"),
        "heatmap": build_monthly_heatmap_data(comp_df, return_type="gross"),
    }




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

    # As-of date — used as a cache key so computations auto-invalidate
    # when the quarterly Composite Returns file updates.
    as_of = data.get("as_of")
    as_of_iso = as_of.isoformat() if as_of else "none"
    if as_of:
        st.caption(f"Source: Composite Returns as of {as_of.strftime('%B %d, %Y')} · Gross of fees")

    _render_period_returns(data, active_strategy, strat_color)
    _render_cumulative_chart(comp_df, active_strategy, strat_color, strat_name, as_of_iso)

    _render_risk_metrics(comp_df, active_strategy, strat_color, as_of_iso)
    _render_monthly_heatmap(comp_df, active_strategy, strat_color, as_of_iso)

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

def _render_cumulative_chart(comp_df, strategy, color, name, as_of_iso):
    """Cumulative growth of $100 chart with benchmark overlays.

    Sprint 24-4: adds date-range controls so the user can zoom into any
    window. Six preset buttons (YTD/1Y/3Y/5Y/10Y/All) plus two
    st.date_input widgets for arbitrary ranges. The series are filtered
    and re-rebased to $100 at the new start date, so a "2020-2023" view
    starts at $100 on Jan 2020 — making side-by-side comparison with
    benchmarks meaningful for any sub-period.
    """
    cached = _cached_per_strategy(strategy, as_of_iso)["cumulative"]
    strat_cum = cached["strat_cum"]
    bench1_name = cached["bench1_name"]
    bench1_cum = cached["bench1_cum"]
    bench2_name = cached["bench2_name"]
    bench2_cum = cached["bench2_cum"]

    if strat_cum is None or len(strat_cum) == 0:
        _data_unavailable_card("No cumulative return data")
        return

    # ── Range bounds from the actual data ───────────────────────────────
    series_start = strat_cum.index.min().date()
    series_end = strat_cum.index.max().date()

    # Session state keys are namespaced per strategy so QDVD/DCP/etc.
    # don't share a single range (their inceptions differ). These are
    # ALSO the date_input widget keys — Streamlit lets you set widget
    # state directly via session_state before the widget is constructed,
    # which is how preset buttons update the date pickers.
    sk_start = f"perf_range_start_{strategy}"
    sk_end = f"perf_range_end_{strategy}"

    # Initialize on first render. If a stale value exists from another
    # strategy (or out-of-range), clamp it to the current strategy bounds.
    def _clamp(d):
        if d < series_start:
            return series_start
        if d > series_end:
            return series_end
        return d

    if sk_start not in st.session_state:
        st.session_state[sk_start] = series_start
    else:
        st.session_state[sk_start] = _clamp(st.session_state[sk_start])
    if sk_end not in st.session_state:
        st.session_state[sk_end] = series_end
    else:
        st.session_state[sk_end] = _clamp(st.session_state[sk_end])

    # ── Preset helpers ──────────────────────────────────────────────────
    import datetime as _dt
    today = series_end  # use latest data point as anchor for preset math

    def _apply_preset(years=None, ytd=False, inception=False):
        if inception:
            new_start = series_start
        elif ytd:
            new_start = _dt.date(today.year, 1, 1)
        elif years is not None:
            try:
                new_start = today.replace(year=today.year - years)
            except ValueError:
                new_start = today.replace(year=today.year - years, day=28)
        else:
            return
        # Write directly to widget keys so date_input picks up the change.
        st.session_state[sk_start] = max(new_start, series_start)
        st.session_state[sk_end] = series_end

    # Layout: six narrow preset buttons, then two date pickers
    # Small vertical spacer so the controls don't crowd the period-return cards above.
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    preset_cols = st.columns([1, 1, 1, 1, 1, 1, 2, 2])
    if preset_cols[0].button("YTD", key=f"preset_ytd_{strategy}", use_container_width=True):
        _apply_preset(ytd=True)
        st.rerun()
    if preset_cols[1].button("1Y", key=f"preset_1y_{strategy}", use_container_width=True):
        _apply_preset(years=1)
        st.rerun()
    if preset_cols[2].button("3Y", key=f"preset_3y_{strategy}", use_container_width=True):
        _apply_preset(years=3)
        st.rerun()
    if preset_cols[3].button("5Y", key=f"preset_5y_{strategy}", use_container_width=True):
        _apply_preset(years=5)
        st.rerun()
    if preset_cols[4].button("10Y", key=f"preset_10y_{strategy}", use_container_width=True):
        _apply_preset(years=10)
        st.rerun()
    if preset_cols[5].button("All", key=f"preset_all_{strategy}", use_container_width=True):
        _apply_preset(inception=True)
        st.rerun()

    # date_input widgets — NO `value=` parameter when key is already in
    # session_state; Streamlit reads the value from session_state directly.
    # This is what lets the preset buttons drive the date pickers.
    with preset_cols[6]:
        st.date_input(
            "From",
            min_value=series_start,
            max_value=series_end,
            key=sk_start,
            format="MM/DD/YYYY",
        )
    with preset_cols[7]:
        st.date_input(
            "To",
            min_value=series_start,
            max_value=series_end,
            key=sk_end,
            format="MM/DD/YYYY",
        )

    # Read the current values from session state (post-widget interaction)
    range_start = st.session_state[sk_start]
    range_end = st.session_state[sk_end]

    # date_input can occasionally return tuples for ranged mode; we used
    # scalar mode but normalize defensively.
    if isinstance(range_start, (list, tuple)):
        range_start = range_start[0]
    if isinstance(range_end, (list, tuple)):
        range_end = range_end[0]

    invalid_msg = None
    if range_start > range_end:
        invalid_msg = "Start date is after end date — showing full range instead."
        range_start, range_end = series_start, series_end

    # ── Filter and rebase ───────────────────────────────────────────────
    range_start_ts = pd.Timestamp(range_start)
    range_end_ts = pd.Timestamp(range_end)

    def _slice_and_rebase(series):
        """Slice to [start, end] and rebase to 100 at the new start."""
        if series is None or len(series) == 0:
            return series
        mask = (series.index >= range_start_ts) & (series.index <= range_end_ts)
        sliced = series[mask]
        if len(sliced) == 0:
            return sliced
        return sliced / sliced.iloc[0] * 100.0

    strat_plot = _slice_and_rebase(strat_cum)
    bench1_plot = _slice_and_rebase(bench1_cum) if bench1_cum is not None and len(bench1_cum) > 0 else bench1_cum
    bench2_plot = _slice_and_rebase(bench2_cum) if bench2_cum is not None and len(bench2_cum) > 0 else bench2_cum

    if strat_plot is None or len(strat_plot) < 2:
        st.caption("Selected range has too few data points — try a wider window.")
        return

    # ── Plot ────────────────────────────────────────────────────────────
    # Series are rebased to 100 at the window start, so percent-from-start
    # at any point is just (value - 100). Pass this as customdata so the
    # hovertemplate can display "+38.35%" instead of "$138". Total return
    # over the window goes into the legend label so a user can read each
    # line's headline performance without hovering.
    fig = go.Figure()
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

    def _pct_arr(s):
        # Plotly wraps 1D customdata as 2D internally, and format specs
        # only apply to indexed elements. Pass an explicit column vector
        # so %{customdata[0]:+.2f} works as expected in the hovertemplate.
        return (s - 100).values.reshape(-1, 1)

    def _final_pct(s):
        return float(s.iloc[-1]) - 100.0

    # Note: hovertemplate omits the date prefix because hovermode="x unified"
    # already shows the date in the tooltip header. Including it again here
    # would render "Jan 31, 2026" + "Jan 2026" stacked.
    strat_label = f"{name}  {_final_pct(strat_plot):+.2f}%"
    fig.add_trace(go.Scatter(
        x=strat_plot.index, y=strat_plot.values,
        customdata=_pct_arr(strat_plot),
        name=strat_label, fill="tozeroy",
        fillcolor=f"rgba({r},{g},{b},0.06)",
        line=dict(color=color, width=2.5),
        hovertemplate=name + ": %{customdata[0]:+.2f}%<extra></extra>",
    ))

    if bench1_plot is not None and len(bench1_plot) > 0 and bench1_name:
        bench1_label = f"{bench1_name}  {_final_pct(bench1_plot):+.2f}%"
        fig.add_trace(go.Scatter(
            x=bench1_plot.index, y=bench1_plot.values,
            customdata=_pct_arr(bench1_plot),
            name=bench1_label,
            line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dot"),
            hovertemplate=bench1_name + ": %{customdata[0]:+.2f}%<extra></extra>",
        ))

    if bench2_plot is not None and len(bench2_plot) > 0 and bench2_name:
        bench2_label = f"{bench2_name}  {_final_pct(bench2_plot):+.2f}%"
        fig.add_trace(go.Scatter(
            x=bench2_plot.index, y=bench2_plot.values,
            customdata=_pct_arr(bench2_plot),
            name=bench2_label,
            line=dict(color="rgba(201,168,76,0.4)", width=1.5, dash="dash"),
            hovertemplate=bench2_name + ": %{customdata[0]:+.2f}%<extra></extra>",
        ))

    fig.add_hline(y=100, line=dict(color="rgba(255,255,255,0.1)", width=1, dash="dash"))

    _layout = {**PLOTLY_DARK}
    _layout["margin"] = dict(l=50, r=20, t=16, b=40)
    # Pan/zoom disabled at the layout level (fixedrange axes + dragmode=False)
    # so re-enabling hover via PLOTLY_CHART_CONFIG doesn't bring back drag-to-zoom.
    fig.update_layout(
        **_layout,
        xaxis={**_XAXIS, "fixedrange": True},
        yaxis={**_YAXIS, "tickprefix": "$", "fixedrange": True},
        height=380,
        hovermode="x unified",
        showlegend=True,
        dragmode=False,
    )

    # Title line includes the actual rendered range (snaps to data points)
    actual_start = strat_plot.index.min().strftime("%b %Y")
    actual_end = strat_plot.index.max().strftime("%b %Y")
    st.markdown(
        f'<div style="font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:4px;">'
        f'Growth of $100 — {name} vs Benchmarks (Gross) '
        f'<span style="font-weight:400;color:rgba(255,255,255,0.4);font-size:12px;">'
        f'· {actual_start} – {actual_end}</span></div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CHART_CONFIG)

    if invalid_msg:
        st.caption(invalid_msg)


# ── Risk Metrics ────────────────────────────────────────────────────────────

def _render_risk_metrics(comp_df, strategy, color, as_of_iso):
    """Render risk metrics as two card rows.

    Sprint 24-3: split the original 11-card grid into two visually distinct
    rows. Row 1 keeps the original Risk Metrics (Sharpe, Sortino, Beta, ...).
    Row 2 adds Capture & Drawdown stats lifted from Cameron's quarterly
    Characteristics & Risk Metrics spreadsheet.
    """
    risk = _cached_per_strategy(strategy, as_of_iso)["risk"]

    if risk is None:
        _data_unavailable_card("Insufficient data for risk metrics", "Need 12+ months")
        return

    def _fmt_pct(v, decimals=1, signed=False):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "\u2014"
        sign = "+" if signed and v >= 0 else ""
        return f"{sign}{v * 100:.{decimals}f}%"

    def _fmt_num(v, decimals=2):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "\u2014"
        return f"{v:.{decimals}f}"

    def _fmt_int(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "\u2014"
        return str(int(v))

    def _is_neg(v):
        if v is None:
            return False
        if isinstance(v, float) and np.isnan(v):
            return False
        return v < 0

    NEUTRAL = "rgba(255,255,255,0.85)"

    row1 = [
        ("Ann. Return", _fmt_pct(risk["annualized_return"]),
            BRAND["green"] if risk["annualized_return"] >= 0 else BRAND["red"]),
        ("Ann. Volatility", _fmt_pct(risk["annualized_vol"]), NEUTRAL),
        ("Sharpe Ratio", _fmt_num(risk["sharpe"]), NEUTRAL),
        ("Sortino Ratio", _fmt_num(risk["sortino"]), NEUTRAL),
        ("Beta", _fmt_num(risk["beta"]), NEUTRAL),
        ("Max Drawdown", _fmt_pct(risk["max_drawdown"]), BRAND["red"]),
        ("Tracking Error", _fmt_pct(risk["tracking_error"]), NEUTRAL),
        ("Info Ratio", _fmt_num(risk["information_ratio"]), NEUTRAL),
        ("Best Month", _fmt_pct(risk["best_month"]), BRAND["green"]),
        ("Worst Month", _fmt_pct(risk["worst_month"]), BRAND["red"]),
        ("% Positive", _fmt_pct(risk["pct_positive_months"], decimals=0), NEUTRAL),
    ]

    row2 = [
        ("Rolling 12M Std Dev", _fmt_pct(risk.get("rolling_12m_std", float("nan"))), NEUTRAL),
        ("Worst Quarter", _fmt_pct(risk.get("worst_quarter", float("nan")), decimals=2), BRAND["red"]),
        ("CALMAR Ratio", _fmt_num(risk.get("calmar", float("nan"))), NEUTRAL),
        ("CALMAR Drawdown", _fmt_pct(risk.get("calmar_drawdown", float("nan"))), BRAND["red"]),
        ("MAR Ratio", _fmt_num(risk.get("mar", float("nan"))), NEUTRAL),
        ("Up Capture (Mo)", _fmt_pct(risk.get("up_capture_monthly", float("nan"))), NEUTRAL),
        ("Down Capture (Mo)", _fmt_pct(risk.get("down_capture_monthly", float("nan"))), NEUTRAL),
        ("Up Capture (Qtr)", _fmt_pct(risk.get("up_capture_quarterly", float("nan"))), NEUTRAL),
        ("Down Capture (Qtr)", _fmt_pct(risk.get("down_capture_quarterly", float("nan"))), NEUTRAL),
        ("Ann. Return when SPX Neg.", _fmt_pct(risk.get("ann_return_when_bench_neg", float("nan")), decimals=2),
            BRAND["red"] if _is_neg(risk.get("ann_return_when_bench_neg", float("nan"))) else BRAND["green"]),
        ("Rolling 6M Loss Count", _fmt_int(risk.get("rolling_6m_loss_count", float("nan"))), NEUTRAL),
        ("Rolling Qtr Loss Count", _fmt_int(risk.get("rolling_qtr_loss_count", float("nan"))), NEUTRAL),
        ("R Sq. vs Primary", _fmt_pct(risk.get("r_squared_primary", float("nan"))), NEUTRAL),
        ("R Sq. vs Secondary", _fmt_pct(risk.get("r_squared_secondary", float("nan"))), NEUTRAL),
    ]

    def _emit_row(title, metrics, suffix=""):
        # suffix is appended inline next to the title in a muted style.
        # Used to clarify that these metrics are computed from the full
        # composite series and don't change with the chart's date range.
        suffix_html = (
            f'<span style="font-weight:400;color:rgba(255,255,255,0.4);'
            f'font-size:11px;text-transform:none;letter-spacing:0;'
            f'margin-left:8px;">{suffix}</span>' if suffix else ""
        )
        st.markdown(
            f"""<div style="font-size:13px; font-weight:700; color:rgba(255,255,255,0.7); """
            f"""text-transform:uppercase; letter-spacing:0.04em; margin-top:10px; """
            f"""margin-bottom:8px;">{title}{suffix_html}</div>""",
            unsafe_allow_html=True,
        )
        cards_html = ""
        for label, val, val_color in metrics:
            cards_html += f"""<div style="
                flex:1 1 110px; min-width:90px;
                background:rgba(255,255,255,0.02);
                border:1px solid rgba(255,255,255,0.05);
                border-radius:8px; padding:10px 12px;
            ">
                <div style="font-size:10px; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:3px;">{label}</div>
                <div style="font-size:16px; font-weight:700; color:{val_color};">{val}</div>
            </div>"""
        st.markdown(
            f"""<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px;">{cards_html}</div>""",
            unsafe_allow_html=True,
        )

    # Build a human-readable as-of suffix to clarify these metrics use the
    # full composite series, not the chart's selected date range.
    try:
        as_of_dt = datetime.fromisoformat(as_of_iso)
        as_of_suffix = f"as of {as_of_dt.strftime('%b %d, %Y')} · full series"
    except (ValueError, TypeError):
        as_of_suffix = "full series"

    _emit_row("Risk Metrics", row1, suffix=as_of_suffix)
    _emit_row("Capture & Drawdown", row2, suffix=as_of_suffix)

    st.caption("Based on monthly gross returns. Risk-free rate: 4%. CALMAR uses trailing 36 months. MAR uses since inception.")


# ── Monthly Returns Heatmap ─────────────────────────────────────────────────

def _render_monthly_heatmap(comp_df, strategy, color, as_of_iso):
    """Render heatmap using Plotly (avoids HTML size limit).
    Uses a minimum width of 760px so the 13-column grid never gets
    squeezed — on narrow screens the chart container scrolls horizontally.
    """
    hm = _cached_per_strategy(strategy, as_of_iso)["heatmap"]

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
        # Sprint 24-1: drop autorange="reversed" so the largest numeric y
        # (newest year) renders at the top of the heatmap. The upstream
        # build_monthly_heatmap_data already sorts descending; combined
        # with Plotly default behavior, this puts 2026 at top.
        yaxis=dict(fixedrange=True, dtick=1, tickfont=dict(size=10)),
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