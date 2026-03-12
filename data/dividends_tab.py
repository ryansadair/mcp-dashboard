"""
Martin Capital Partners — Dividend Intelligence Tab
data/dividends_tab.py

Comprehensive dividend analytics rendered as sub-tabs within the main Dividends tab.
Sub-tabs:
  1. Announcements — existing dividend_calendar_tab.py (render_dividend_calendar)
  2. Income Dashboard — income KPIs, monthly income chart, yield comparison, streaks
  3. Dividend Detail — full sortable table with growth rates, payout, safety, history
  4. Safety & Growth — growth tiers, safety scores, payout trends, risk monitor

Data sources:
  - Tamarac Holdings Excel (yield_at_cost, current_yield, annual_income, cost_basis, value, quantity)
  - Supabase dividends table (div_growth_1y/3y/5y, consecutive_years, payout_ratio, ex_dividend_date)
  - yfinance via market_data.py (current price, dividend_yield, sector)
  - dividend_calendar_tab.py (existing announcement calendar)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from utils.config import BRAND, STRATEGIES
from data.dividends import (
    get_batch_dividend_details,
    compute_strategy_income,
    compute_weighted_yield,
)
from data.market_data import fetch_batch_prices
from data.tamarac_parser import (
    get_holdings_for_strategy,
    get_cash_weight,
    get_all_unique_tickers,
    STRATEGY_NAMES,
)

# Attempt to import the existing announcement calendar
try:
    from data.dividend_calendar_tab import render_dividend_calendar
    _CALENDAR_AVAILABLE = True
except ImportError:
    _CALENDAR_AVAILABLE = False

# Authoritative CCC data (Fish/IREIT spreadsheet)
try:
    from data.dividend_streaks import get_streak, get_fish_metrics, get_dividend_history
    _STREAKS_AVAILABLE = True
except ImportError:
    _STREAKS_AVAILABLE = False

# ── Plotly theme (matches 1_Dashboard.py) ──────────────────────────────────
PLOTLY_DARK = dict(
    paper_bgcolor="rgba(255,255,255,0.02)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    margin=dict(l=10, r=10, t=40, b=10),
)
PLOTLY_CONFIG = {
    "displayModeBar": False, "scrollZoom": False,
    "doubleClick": False, "showTips": False, "staticPlot": True,
}
PLOTLY_CONFIG_HOVER = {
    "displayModeBar": False, "scrollZoom": False,
    "doubleClick": False, "showTips": False, "staticPlot": False,
}
_XAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))
_YAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))

# ── Colors ─────────────────────────────────────────────────────────────────
GREEN = BRAND["green"]
BLUE  = BRAND["blue"]
GOLD  = BRAND["gold"]
RED   = BRAND["red"]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: build the enriched holdings dataframe used across all sub-tabs
# ═══════════════════════════════════════════════════════════════════════════

def _build_enriched_df(tam_df, price_data, div_data):
    """
    Merge Tamarac holdings with live price + dividend data into a single DF.
    Returns a DataFrame with one row per holding, sorted by weight descending.
    """
    rows = []
    for _, h in tam_df.iterrows():
        sym = h["symbol"]
        mkt = price_data.get(sym, {})
        dd  = div_data.get(sym, {})

        # Yield on Cost from Tamarac (decimal → percentage)
        yoc_raw = h.get("yield_at_cost", 0) or 0
        yoc_pct = float(yoc_raw) * 100 if 0 < float(yoc_raw) < 1 else float(yoc_raw)

        # Current yield from Tamarac (decimal → percentage)
        cy_raw = h.get("current_yield", 0) or 0
        cy_pct = float(cy_raw) * 100 if 0 < float(cy_raw) < 1 else float(cy_raw)

        # Annual income from Tamarac
        annual_inc = float(h.get("annual_income", 0) or 0)

        # Value (market value) from Tamarac
        value = float(h.get("value", 0) or 0)

        # Cost basis from Tamarac
        cost_basis = float(h.get("cost_basis", 0) or 0)

        # Quantity from Tamarac
        qty = float(h.get("quantity", 0) or 0)

        # Dividend data: prefer Fish CCC spreadsheet, fallback to Supabase/yfinance
        div_yield    = dd.get("dividend_yield", 0) or 0
        ex_date      = dd.get("ex_dividend_date", "")

        # Fish CCC data (authoritative for growth rates, payout, streaks)
        fish = {}
        div_hist = {}
        if _STREAKS_AVAILABLE:
            fish = get_fish_metrics(sym)
            div_hist = get_dividend_history(sym)

        # Annualized dividend amount: Fish first (col 12), yfinance fallback
        div_rate = fish.get("div_amount", 0) or (dd.get("dividend_rate", 0) or 0)

        # Growth rates: Fish first, yfinance fallback
        # Track source so risk monitor can avoid false cut alerts on ADRs/specials.
        # Key insight: ADRs like KOF, TTE can appear in Fish CCC data, but their
        # growth rates are USD-converted totals that fluctuate with FX rates.
        # If Fish shows negative growth AND the ticker has no meaningful streak
        # (< 5 years), treat the growth data as unreliable.
        fish_dgr_1y = fish.get("dgr_1y", 0) or 0
        fish_dgr_5y = fish.get("dgr_5y", 0) or 0
        fish_has_any = bool(fish_dgr_1y or fish_dgr_5y)

        growth_1y  = fish_dgr_1y or (dd.get("div_growth_1y", 0) or 0)
        growth_3y  = (fish.get("dgr_3y", 0) or 0) or (dd.get("div_growth_3y", 0) or 0)
        growth_5y  = fish_dgr_5y or (dd.get("div_growth_5y", 0) or 0)
        growth_10y = fish.get("dgr_10y", 0)

        # Fish data is "reliable" only if:
        #   1) Fish has growth data AND growth is positive (clearly not an ADR issue), OR
        #   2) Fish has growth data AND the ticker has a 5+ year streak (real dividend grower)
        # Otherwise, negative Fish growth is likely FX/special noise.
        _fish_has_growth = False
        if fish_has_any:
            if growth_5y >= 0 or growth_1y >= 0:
                _fish_has_growth = True  # positive growth — trust it
            elif consec_years >= 5:
                _fish_has_growth = True  # long streak — real grower with a down year
            # else: negative growth + short/no streak → likely ADR/special, don't trust

        # Payout ratio: Fish first, yfinance fallback
        payout_ratio = fish.get("payout_ratio", 0) or (dd.get("payout_ratio", 0) or 0)

        # Consecutive years: Fish first, yfinance fallback
        if _STREAKS_AVAILABLE:
            ccc_years, _ = get_streak(sym)
            consec_years = ccc_years if ccc_years > 0 else (dd.get("consecutive_years", 0) or 0)
        else:
            consec_years = dd.get("consecutive_years", 0) or 0

        # New Fish-only fields
        chowder        = fish.get("chowder", 0)
        streak_began   = fish.get("streak_began", None)
        recessions     = fish.get("recessions", 0)

        # Market data
        price  = mkt.get("price", 0) or 0
        sector = mkt.get("sector", "") or ""
        chg_1d = mkt.get("change_1d_pct", 0) or 0

        rows.append({
            "symbol":        sym,
            "description":   h.get("description", sym),
            "weight":        h.get("weight", 0),
            "weight_pct":    h.get("weight_pct", 0),
            "quantity":      qty,
            "price":         price,
            "value":         value,
            "cost_basis":    cost_basis,
            "sector":        sector,
            "chg_1d":        chg_1d,
            # Dividend metrics (Fish CCC preferred, yfinance fallback)
            "yield_on_cost": round(yoc_pct, 2),
            "current_yield": round(cy_pct, 2),
            "div_yield":     round(div_yield, 2),
            "div_rate":      round(div_rate, 4),
            "annual_income": round(annual_inc, 2),
            "payout_ratio":  round(payout_ratio, 1),
            "consec_years":  int(consec_years),
            "growth_1y":     round(growth_1y, 1),
            "growth_3y":     round(growth_3y, 1),
            "growth_5y":     round(growth_5y, 1),
            "growth_10y":    round(growth_10y, 1),
            "ex_date":       ex_date,
            # Fish-only fields
            "chowder":       round(chowder, 1),
            "streak_began":  streak_began,
            "recessions":    int(recessions),
            "div_history":   div_hist,
            "fish_sourced":  _fish_has_growth,
        })

    return pd.DataFrame(rows).sort_values("weight", ascending=False).reset_index(drop=True)


def _safety_grade(payout, growth_5y, consec, fish_sourced=False):
    """
    Compute a simple dividend safety grade based on available data.
    For non-Fish tickers (ADRs, special div payers), treat moderate negative
    growth as neutral since yfinance lumps FX effects and specials into totals.
    Returns letter grade string.
    """
    score = 0
    # Payout ratio component (lower is safer)
    if payout <= 0:
        score += 2  # no data — neutral
    elif payout < 40:
        score += 5
    elif payout < 55:
        score += 4
    elif payout < 70:
        score += 3
    elif payout < 85:
        score += 2
    else:
        score += 1

    # Growth component — trust Fish data; be lenient with yfinance fallback
    if fish_sourced:
        if growth_5y >= 10:
            score += 5
        elif growth_5y >= 5:
            score += 4
        elif growth_5y >= 2:
            score += 3
        elif growth_5y >= 0:
            score += 2
        else:
            score += 0
    else:
        # Non-Fish: only penalize severe declines (>15%), treat moderate
        # negatives as neutral (likely ADR FX noise or special div drops)
        if growth_5y >= 10:
            score += 5
        elif growth_5y >= 5:
            score += 4
        elif growth_5y >= 2:
            score += 3
        elif growth_5y >= -15:
            score += 2  # neutral — could be FX/special noise
        else:
            score += 0  # severe enough to likely be real

    # Streak component (0 = no data available, treat as neutral)
    if consec == 0:
        score += 3  # neutral — no CCC data (ADR/ETF/non-US)
    elif consec >= 25:
        score += 5
    elif consec >= 15:
        score += 4
    elif consec >= 10:
        score += 3
    elif consec >= 5:
        score += 2
    else:
        score += 1

    # Map to letter grade
    if score >= 14:
        return "A+"
    elif score >= 12:
        return "A"
    elif score >= 10:
        return "A-"
    elif score >= 8:
        return "B+"
    elif score >= 6:
        return "B"
    elif score >= 4:
        return "B-"
    else:
        return "C"


def _growth_tier(growth_5y, fish_sourced=False):
    """Classify a holding into dividend growth tiers.
    For non-Fish tickers, moderate negative growth is labeled as uncertain."""
    if growth_5y >= 10:
        return "Elite (10%+)"
    elif growth_5y >= 5:
        return "Strong (5–10%)"
    elif growth_5y >= 2:
        return "Steady (2–5%)"
    elif growth_5y >= 0:
        return "Slow (<2%)"
    elif not fish_sourced and growth_5y > -15:
        return "Uncertain (non-CCC)"
    else:
        return "Cut / Frozen"


def _payout_color(val):
    """Return hex color based on payout ratio."""
    if val <= 0:
        return "rgba(255,255,255,0.3)"
    if val < 50:
        return GREEN
    if val < 70:
        return GOLD
    if val < 85:
        return "#e8a838"
    return RED


def _streak_tier(years):
    """Classify consecutive-increase streak."""
    if years >= 50:
        return ("King", GREEN)
    elif years >= 25:
        return ("Aristocrat", "#6aad56")
    elif years >= 10:
        return ("Contender", GOLD)
    elif years >= 5:
        return ("Challenger", "#e8a838")
    else:
        return ("—", "rgba(255,255,255,0.3)")


# ── Shared style helpers (used by both detail and safety sub-tabs) ─────────

def _color_safety(val):
    """Styler function for safety grade cells."""
    if "A" in str(val):
        return f"color: {GREEN}; font-weight: 700"
    elif "B" in str(val):
        return f"color: {GOLD}; font-weight: 700"
    return f"color: {RED}; font-weight: 700"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER FUNCTION — called from 1_Dashboard.py inside tab_divs
# ═══════════════════════════════════════════════════════════════════════════

def render_dividends_tab(tamarac_parsed, active_strategy, strat_config, kpis):
    """
    Render the full dividend intelligence section with sub-tabs.

    Args:
        tamarac_parsed: dict from parse_tamarac_excel()
        active_strategy: str, e.g. "QDVD"
        strat_config: dict from STRATEGIES[active]
        kpis: dict with current KPI values
    """
    strat_color = strat_config["color"]

    # ── Load data ──────────────────────────────────────────────────────────
    tam_df = get_holdings_for_strategy(tamarac_parsed, active_strategy)
    if tam_df.empty:
        st.info("No holdings for this strategy in Tamarac file.")
        return

    tickers = tuple(tam_df["symbol"].tolist())

    with st.spinner("Loading dividend intelligence..."):
        price_data = fetch_batch_prices(tickers)
        div_data   = get_batch_dividend_details(tickers)

    edf = _build_enriched_df(tam_df, price_data, div_data)

    # Add computed columns
    edf["safety"]      = edf.apply(lambda r: _safety_grade(r["payout_ratio"], r["growth_5y"], r["consec_years"], r.get("fish_sourced", False)), axis=1)
    edf["growth_tier"] = edf.apply(lambda r: _growth_tier(r["growth_5y"], r.get("fish_sourced", False)), axis=1)

    # ── Sub-tabs ───────────────────────────────────────────────────────────
    sub_announce, sub_income, sub_detail, sub_safety = st.tabs([
        "📅 Announcements", "💵 Income Dashboard", "📊 Dividend Detail", "🛡️ Safety & Growth"
    ])

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 1: ANNOUNCEMENTS (existing calendar)
    # ═══════════════════════════════════════════════════════════════════════
    with sub_announce:
        st.markdown("**Estimated Dividend Increase Announcements**")

        if _CALENDAR_AVAILABLE:
            render_dividend_calendar()
        else:
            st.info(
                "Dividend calendar not yet available. "
                "Run `dividend_calendar.py` to generate `data/dividend_calendar.xlsx`."
            )

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 2: INCOME DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════
    with sub_income:
        _render_income_dashboard(edf, tam_df, div_data, active_strategy, strat_color)

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 3: DIVIDEND DETAIL TABLE
    # ═══════════════════════════════════════════════════════════════════════
    with sub_detail:
        _render_dividend_detail(edf, active_strategy, strat_color)

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 4: SAFETY & GROWTH
    # ═══════════════════════════════════════════════════════════════════════
    with sub_safety:
        _render_safety_growth(edf, active_strategy, strat_color)

    st.caption(f"Dividend data via Tamarac + yfinance/Supabase • {datetime.now().strftime('%I:%M %p')}")


# ═══════════════════════════════════════════════════════════════════════════
# SUB-TAB 2: INCOME DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

def _render_income_dashboard(edf, tam_df, div_data, active_strategy, strat_color):
    """Income KPIs, yield comparison, and streak leaderboard."""

    # ── KPI row ────────────────────────────────────────────────────────────
    total_income   = edf["annual_income"].sum()
    total_value    = edf["value"].sum()
    total_cost     = edf["cost_basis"].sum()

    # Weighted average yield on cost (weight by portfolio weight)
    wtd_yoc = 0
    total_wt = edf["weight"].sum()
    if total_wt > 0:
        wtd_yoc = (edf["yield_on_cost"] * edf["weight"]).sum() / total_wt

    # Weighted current yield
    wtd_cy = 0
    if total_wt > 0:
        wtd_cy = (edf["current_yield"] * edf["weight"]).sum() / total_wt

    # Weighted 5Y growth
    valid_growth = edf[edf["growth_5y"].between(-50, 100) & (edf["growth_5y"] != 0)]
    if not valid_growth.empty and valid_growth["weight"].sum() > 0:
        wtd_growth_5y = (valid_growth["growth_5y"] * valid_growth["weight"]).sum() / valid_growth["weight"].sum()
    else:
        wtd_growth_5y = 0

    # Grower count
    growers = len(edf[edf["growth_5y"] > 0])
    cutters = len(edf[edf["growth_5y"] < 0])

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1: st.metric("Annual Income", f"${total_income:,.0f}")
    with k2: st.metric("Wtd Avg Yield", f"{wtd_cy:.2f}%")
    with k3: st.metric("Wtd Yield on Cost", f"{wtd_yoc:.2f}%")
    with k4: st.metric("Wtd 5Y Div CAGR", f"{wtd_growth_5y:+.1f}%")
    with k5: st.metric("Div Growers", f"{growers} / {len(edf)}")
    with k6: st.metric("Div Cutters", f"{cutters}")

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Yield on Cost vs Current Yield comparison ──────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Current Yield vs Yield on Cost**")
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            "YoC reflects dividend growth since purchase — the real compounding story"
            "</div>",
            unsafe_allow_html=True,
        )

        # Build comparison data
        yoc_df = edf[["symbol", "current_yield", "yield_on_cost", "weight_pct"]].copy()
        yoc_df = yoc_df.sort_values("yield_on_cost", ascending=True)

        fig_yoc = go.Figure()
        fig_yoc.add_trace(go.Bar(
            y=yoc_df["symbol"], x=yoc_df["current_yield"], orientation="h",
            name="Current Yield",
            marker=dict(color=BLUE, opacity=0.7),
            text=[f"{v:.2f}%" for v in yoc_df["current_yield"]],
            textposition="outside",
            textfont=dict(size=9, color="rgba(255,255,255,0.5)"),
        ))
        fig_yoc.add_trace(go.Bar(
            y=yoc_df["symbol"], x=yoc_df["yield_on_cost"], orientation="h",
            name="Yield on Cost",
            marker=dict(color=GREEN, opacity=0.7),
            text=[f"{v:.2f}%" for v in yoc_df["yield_on_cost"]],
            textposition="outside",
            textfont=dict(size=9, color="rgba(255,255,255,0.5)"),
        ))
        _yoc_layout = {**PLOTLY_DARK}
        _yoc_layout["margin"] = dict(l=10, r=60, t=30, b=10)
        _yoc_layout["legend"] = dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=10, color="rgba(255,255,255,0.5)"),
            bgcolor="rgba(0,0,0,0)",
        )
        fig_yoc.update_layout(
            **_yoc_layout,
            barmode="group",
            height=max(300, len(yoc_df) * 28 + 80),
            xaxis={**_XAXIS, "ticksuffix": "%"},
            yaxis={**_YAXIS, "tickfont": dict(size=10)},
            showlegend=True,
        )
        st.plotly_chart(fig_yoc, use_container_width=True, config=PLOTLY_CONFIG)

    with col_right:
        st.markdown("**Consecutive Dividend Increase Streaks**")
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            "King (50+) · Aristocrat (25+) · Contender (10+) · Challenger (5+)"
            "</div>",
            unsafe_allow_html=True,
        )

        # Build streak data sorted descending
        streak_df = edf[edf["consec_years"] > 0][["symbol", "consec_years"]].copy()
        streak_df = streak_df.sort_values("consec_years", ascending=True)

        if not streak_df.empty:
            colors = []
            tier_labels = []
            for _, row in streak_df.iterrows():
                tier_name, tier_color = _streak_tier(row["consec_years"])
                colors.append(tier_color)
                tier_labels.append(f'{row["consec_years"]}y — {tier_name}')

            fig_streak = go.Figure()
            fig_streak.add_trace(go.Bar(
                y=streak_df["symbol"], x=streak_df["consec_years"], orientation="h",
                marker=dict(color=colors, opacity=0.8),
                text=tier_labels,
                textposition="outside",
                textfont=dict(size=10, color="rgba(255,255,255,0.6)"),
            ))
            _streak_layout = {**PLOTLY_DARK}
            _streak_layout["margin"] = dict(l=10, r=80, t=30, b=10)
            fig_streak.update_layout(
                **_streak_layout,
                height=max(300, len(streak_df) * 24 + 80),
                xaxis={**_XAXIS, "title": "Years"},
                yaxis=_YAXIS,
                showlegend=False,
            )
            st.plotly_chart(fig_streak, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("No consecutive-year data available for this strategy.")

    # ── Income by Holding bar chart ────────────────────────────────────────
    st.divider()
    st.markdown("**Annual Dividend Income by Holding**")

    income_df = edf[edf["annual_income"] > 0][["symbol", "annual_income", "weight_pct"]].copy()
    income_df = income_df.sort_values("annual_income", ascending=True)

    if not income_df.empty:
        fig_inc = go.Figure()
        fig_inc.add_trace(go.Bar(
            y=income_df["symbol"], x=income_df["annual_income"], orientation="h",
            marker=dict(
                color=income_df["annual_income"],
                colorscale=[[0, BLUE], [0.5, GOLD], [1, GREEN]],
            ),
            text=[f"${v:,.0f}" for v in income_df["annual_income"]],
            textposition="outside",
            textfont=dict(size=10, color="rgba(255,255,255,0.6)"),
        ))
        _inc_layout = {**PLOTLY_DARK}
        _inc_layout["margin"] = dict(l=10, r=60, t=30, b=10)
        fig_inc.update_layout(
            **_inc_layout,
            height=max(300, len(income_df) * 24 + 80),
            xaxis={**_XAXIS, "tickprefix": "$", "tickformat": ","},
            yaxis=_YAXIS,
            showlegend=False,
        )
        st.plotly_chart(fig_inc, use_container_width=True, config=PLOTLY_CONFIG)


# ═══════════════════════════════════════════════════════════════════════════
# SUB-TAB 3: DIVIDEND DETAIL TABLE
# ═══════════════════════════════════════════════════════════════════════════

def _render_dividend_detail(edf, active_strategy, strat_color):
    """Full sortable dividend metrics table with all the details."""

    # ── KPI summary row ────────────────────────────────────────────────────
    # Weighted avg yield (by portfolio weight, excluding zeros)
    valid_yield = edf[edf["current_yield"] > 0]
    wtd_yield = round((valid_yield["current_yield"] * valid_yield["weight"]).sum() / valid_yield["weight"].sum(), 2) if not valid_yield.empty and valid_yield["weight"].sum() > 0 else 0

    # Avg growth rates (exclude zeros and outliers)
    def _avg_col(col, lo=-50, hi=100):
        vals = edf[(edf[col] != 0) & (edf[col] > lo) & (edf[col] < hi)][col]
        return round(vals.mean(), 1) if not vals.empty else 0

    avg_1y = _avg_col("growth_1y")
    avg_3y = _avg_col("growth_3y")
    avg_5y = _avg_col("growth_5y")

    consec = edf[edf["consec_years"] > 0]["consec_years"].tolist()
    avg_consec = round(sum(consec) / len(consec), 0) if consec else 0

    d1, d2, d3, d4, d5 = st.columns(5)
    with d1: st.metric("Wtd Avg Yield", f"{wtd_yield}%")
    with d2: st.metric("Avg 1Y Div Growth", f"{avg_1y:+.1f}%")
    with d3: st.metric("Avg 3Y Div Growth", f"{avg_3y:+.1f}%")
    with d4: st.metric("Avg 5Y Div Growth", f"{avg_5y:+.1f}%")
    with d5: st.metric("Avg Consec. Years", f"{int(avg_consec)}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown(f"**Dividend Metrics — {STRATEGY_NAMES.get(active_strategy, active_strategy)}** · {len(edf)} holdings")

    # Build display columns
    detail_rows = []
    for _, r in edf.iterrows():
        began = r.get("streak_began", None)
        try:
            began_str = str(int(float(str(began)))) if began and str(began).strip() not in ("", "0", "None", "nan") else "N/A"
        except (ValueError, TypeError):
            began_str = "N/A"
        detail_rows.append({
            "Symbol":         r["symbol"],
            "Company":        r["description"],
            "Wt%":            r["weight_pct"],
            "Curr Yield":     r["current_yield"],
            "Yield on Cost":  r["yield_on_cost"],
            "Div Amount":     r["div_rate"],
            "1Y Growth":      r["growth_1y"],
            "3Y Growth":      r["growth_3y"],
            "5Y Growth":      r["growth_5y"],
            "10Y Growth":     r["growth_10y"],
            "Streak":         r["consec_years"] if r["consec_years"] > 0 else "N/A",
            "Began":          began_str,
            "Recessions":     r["recessions"] if r["consec_years"] > 0 else "N/A",
            "Payout %":       r["payout_ratio"],
            "Safety":         r["safety"],
            "Src":            "CCC" if r.get("fish_sourced", False) else "yF",
            "Sector":         r["sector"],
        })
    detail_df = pd.DataFrame(detail_rows)

    # Color formatting
    def _color_growth(val):
        try:
            v = float(val)
            if v > 0: return f"color: {GREEN}; font-weight: 500"
            if v < 0: return f"color: {RED}; font-weight: 500"
        except (ValueError, TypeError):
            pass
        return ""

    def _color_payout(val):
        try:
            v = float(val)
            color = _payout_color(v)
            return f"color: {color}; font-weight: 500"
        except (ValueError, TypeError):
            return ""

    def _color_yield(val):
        try:
            v = float(val)
            if v > 0: return f"color: {GOLD}; font-weight: 600"
        except (ValueError, TypeError):
            pass
        return ""

    def _color_src(val):
        if val == "CCC":
            return f"color: {GREEN}; font-weight: 600; font-size: 10px"
        return f"color: rgba(255,255,255,0.3); font-size: 10px"

    styled = (
        detail_df.style
        .map(_color_growth, subset=["1Y Growth", "3Y Growth", "5Y Growth", "10Y Growth"])
        .map(_color_payout, subset=["Payout %"])
        .map(_color_yield, subset=["Curr Yield", "Yield on Cost"])
        .map(_color_safety, subset=["Safety"])
        .map(_color_src, subset=["Src"])
        .format({
            "Wt%":            "{:.2f}%",
            "Curr Yield":     "{:.2f}%",
            "Yield on Cost":  "{:.2f}%",
            "Div Amount":     "${:.2f}",
            "1Y Growth":      "{:+.1f}%",
            "3Y Growth":      "{:+.1f}%",
            "5Y Growth":      "{:+.1f}%",
            "10Y Growth":     lambda v: f"{v:+.1f}%" if isinstance(v, (int, float)) and v != 0 else "N/A",
            "Streak":         lambda v: f"{v:.0f}y" if isinstance(v, (int, float)) else str(v),
            "Recessions":     lambda v: str(v) if isinstance(v, (int, float)) else str(v),
            "Payout %":       "{:.0f}%",
        })
    )

    st.dataframe(
        styled, use_container_width=True, hide_index=True,
        height=(42 + len(detail_df) * 36),
        column_config={
            "Symbol":        st.column_config.TextColumn("Symbol", width="small"),
            "Company":       st.column_config.TextColumn("Company", width="medium"),
            "Wt%":           st.column_config.NumberColumn("Wt%", format="%.2f%%"),
            "Curr Yield":    st.column_config.NumberColumn("Yield", format="%.2f%%"),
            "Yield on Cost": st.column_config.NumberColumn("YoC", format="%.2f%%"),
            "Div Amount":    st.column_config.NumberColumn("Div Amt", format="$%.2f"),
            "1Y Growth":     st.column_config.NumberColumn("1Y Gr", format="%+.1f%%"),
            "3Y Growth":     st.column_config.NumberColumn("3Y Gr", format="%+.1f%%"),
            "5Y Growth":     st.column_config.NumberColumn("5Y Gr", format="%+.1f%%"),
            "10Y Growth":    st.column_config.TextColumn("10Y Gr", width="small"),
            "Streak":        st.column_config.TextColumn("Streak", width="small"),
            "Began":         st.column_config.TextColumn("Began", width="small"),
            "Recessions":    st.column_config.TextColumn("Recess.", width="small"),
            "Payout %":      st.column_config.NumberColumn("Payout", format="%.0f%%"),
            "Safety":        st.column_config.TextColumn("Safety", width="small"),
            "Src":           st.column_config.TextColumn("Src", width="small"),
            "Sector":        st.column_config.TextColumn("Sector", width="medium"),
        },
    )

    # ── Yield chart ────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Dividend Yield by Holding**")
    yield_df = edf[edf["div_yield"] > 0][["symbol", "div_yield"]].sort_values("div_yield", ascending=True)
    if not yield_df.empty:
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            x=yield_df["div_yield"], y=yield_df["symbol"], orientation="h",
            marker=dict(
                color=yield_df["div_yield"],
                colorscale=[[0, BLUE], [0.5, GOLD], [1, GREEN]],
            ),
            text=[f"{y:.2f}%" for y in yield_df["div_yield"]],
            textposition="outside",
            textfont=dict(size=11, color="rgba(255,255,255,0.6)"),
        ))
        fig3.update_layout(
            **PLOTLY_DARK,
            xaxis={**_XAXIS, "title": "Yield %"},
            yaxis=_YAXIS,
            height=max(300, len(yield_df) * 28 + 80),
            showlegend=False,
        )
        st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG)

    # ── 5Y Growth chart ────────────────────────────────────────────────────
    st.divider()
    st.markdown("**5-Year Dividend Growth Rate**")
    growth_df = edf[edf["growth_5y"] != 0][["symbol", "growth_5y"]].sort_values("growth_5y", ascending=True)
    if not growth_df.empty:
        colors = [GREEN if g >= 0 else RED for g in growth_df["growth_5y"]]
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(
            x=growth_df["growth_5y"], y=growth_df["symbol"], orientation="h",
            marker=dict(color=colors),
            text=[f"{g:+.1f}%" for g in growth_df["growth_5y"]],
            textposition="outside",
            textfont=dict(size=11, color="rgba(255,255,255,0.6)"),
        ))
        fig4.update_layout(
            **PLOTLY_DARK,
            xaxis=_XAXIS,
            yaxis=_YAXIS,
            height=max(300, len(growth_df) * 28 + 80),
            showlegend=False,
        )
        st.plotly_chart(fig4, use_container_width=True, config=PLOTLY_CONFIG)

    # ── Dividend History (from Fish Historical sheet) ──────────────────────
    st.divider()
    st.markdown("**Dividend Per Share History** (from CCC Historical Data)")

    # Individual holding selector for detailed history
    hist_tickers = edf[edf["div_history"].apply(lambda d: len(d) > 0)]["symbol"].tolist()
    if hist_tickers:
        selected_hist = st.selectbox(
            "View individual dividend history",
            options=["Select a ticker..."] + hist_tickers,
            key="div_hist_select",
        )
        if selected_hist and selected_hist != "Select a ticker...":
            row_data = edf[edf["symbol"] == selected_hist].iloc[0]
            hist = row_data["div_history"]
            if hist:
                years_sorted = sorted(hist.keys())
                amounts = [hist[y] for y in years_sorted]

                # Bar chart
                fig_single = go.Figure()
                bar_colors = [GREEN if (i == 0 or amounts[i] >= amounts[i-1]) else RED
                              for i in range(len(amounts))]
                fig_single.add_trace(go.Bar(
                    x=years_sorted, y=amounts,
                    marker=dict(color=bar_colors, opacity=0.8),
                    text=[f"${a:.2f}" for a in amounts],
                    textposition="outside",
                    textfont=dict(size=9, color="rgba(255,255,255,0.6)"),
                ))
                _single_layout = {**PLOTLY_DARK}
                _single_layout["margin"] = dict(l=10, r=10, t=40, b=10)
                fig_single.update_layout(
                    **_single_layout,
                    title=f"{selected_hist} - Annual Dividend Per Share",
                    height=300,
                    xaxis={**_XAXIS, "dtick": 1},
                    yaxis={**_YAXIS, "tickprefix": "$"},
                    showlegend=False,
                )
                st.plotly_chart(fig_single, use_container_width=True, config=PLOTLY_CONFIG)

                # YoY growth table — newest to oldest, full height
                if len(amounts) >= 2:
                    st.markdown(f"**Year-over-Year Dividend Growth for {selected_hist}**")
                    growth_data = []
                    for i in range(len(amounts) - 1, 0, -1):
                        if amounts[i-1] > 0:
                            pct = ((amounts[i] - amounts[i-1]) / amounts[i-1]) * 100
                        else:
                            pct = 0
                        growth_data.append({
                            "Year": f"{years_sorted[i-1]}-{years_sorted[i]}",
                            "From": f"${amounts[i-1]:.2f}",
                            "To": f"${amounts[i]:.2f}",
                            "Growth": f"{pct:+.1f}%",
                        })
                    st.dataframe(
                        pd.DataFrame(growth_data),
                        use_container_width=True, hide_index=True,
                        height=(42 + len(growth_data) * 36),
                    )
    else:
        st.info("No dividend history data available. Ensure the Fish/IREIT CCC spreadsheet is in the data folder.")


# ═══════════════════════════════════════════════════════════════════════════
# SUB-TAB 4: SAFETY & GROWTH ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════

def _render_safety_growth(edf, active_strategy, strat_color):
    """Growth tier distribution, safety scores, payout trends, risk monitor."""

    col_left, col_right = st.columns(2)

    # ── Growth Tier Distribution ───────────────────────────────────────────
    with col_left:
        st.markdown("**Dividend Growth Tier Distribution**")
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            "Based on 5-year CAGR of dividend per share"
            "</div>",
            unsafe_allow_html=True,
        )

        tier_order = ["Elite (10%+)", "Strong (5–10%)", "Steady (2–5%)", "Slow (<2%)", "Uncertain (non-CCC)", "Cut / Frozen"]
        tier_colors = {
            "Elite (10%+)":       GREEN,
            "Strong (5–10%)":     "#6aad56",
            "Steady (2–5%)":      GOLD,
            "Slow (<2%)":         "#e8a838",
            "Uncertain (non-CCC)": "rgba(255,255,255,0.35)",
            "Cut / Frozen":       RED,
        }

        # Only include holdings with non-zero growth data
        has_growth = edf[edf["growth_5y"] != 0].copy()
        no_data = edf[edf["growth_5y"] == 0]

        for tier in tier_order:
            tier_holdings = has_growth[has_growth["growth_tier"] == tier]
            count = len(tier_holdings)
            if count == 0:
                continue
            pct = round(count / len(edf) * 100, 0)
            tickers = ", ".join(tier_holdings["symbol"].tolist()[:8])
            color = tier_colors.get(tier, "rgba(255,255,255,0.3)")

            st.markdown(
                f"<div style='margin-bottom:12px;'>"
                f"<div style='display:flex;justify-content:space-between;margin-bottom:4px;'>"
                f"<span style='font-size:12px;color:{color};font-weight:600;'>{tier}</span>"
                f"<span style='font-size:12px;color:rgba(255,255,255,0.6);'>{count} holdings ({pct:.0f}%)</span>"
                f"</div>"
                f"<div style='height:16px;border-radius:4px;background:rgba(255,255,255,0.03);overflow:hidden;'>"
                f"<div style='width:{pct}%;height:100%;border-radius:4px;"
                f"background:linear-gradient(90deg,{color}66,{color}cc);'></div>"
                f"</div>"
                f"<div style='font-size:10px;color:rgba(255,255,255,0.3);margin-top:3px;'>{tickers}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if len(no_data) > 0:
            st.markdown(
                f"<div style='font-size:11px;color:rgba(255,255,255,0.25);margin-top:4px;'>"
                f"{len(no_data)} holdings with no 5Y growth data available</div>",
                unsafe_allow_html=True,
            )

    # ── Safety Score Distribution ──────────────────────────────────────────
    with col_right:
        st.markdown("**Dividend Safety Scores**")
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            "Composite of payout ratio, 5Y growth rate, and consecutive-year streak"
            "</div>",
            unsafe_allow_html=True,
        )

        grade_order = ["A+", "A", "A-", "B+", "B", "B-", "C"]
        grade_colors = {
            "A+": GREEN, "A": "#6aad56", "A-": "#8cc47a",
            "B+": GOLD, "B": "#e8a838", "B-": RED, "C": "#8a3030",
        }

        for grade in grade_order:
            grade_holdings = edf[edf["safety"] == grade]
            count = len(grade_holdings)
            if count == 0:
                continue
            pct = round(count / len(edf) * 100, 0)
            color = grade_colors.get(grade, "rgba(255,255,255,0.3)")
            tickers = ", ".join(grade_holdings["symbol"].tolist()[:6])

            st.markdown(
                f"<div style='margin-bottom:10px;'>"
                f"<div style='display:flex;justify-content:space-between;margin-bottom:3px;'>"
                f"<span style='font-size:12px;font-weight:700;color:{color};'>{grade}</span>"
                f"<span style='font-size:12px;color:rgba(255,255,255,0.6);'>{count} ({pct:.0f}%)</span>"
                f"</div>"
                f"<div style='height:14px;border-radius:4px;background:rgba(255,255,255,0.03);overflow:hidden;'>"
                f"<div style='width:{pct}%;height:100%;border-radius:4px;"
                f"background:linear-gradient(180deg,{color}cc,{color}55);'></div>"
                f"</div>"
                f"<div style='font-size:10px;color:rgba(255,255,255,0.3);margin-top:2px;'>{tickers}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # Portfolio weighted safety
        a_plus_count = len(edf[edf["safety"].str.startswith("A")])
        a_pct = round(a_plus_count / len(edf) * 100, 0)
        st.markdown(
            f"<div style='padding:14px;background:rgba(86,149,66,0.04);border-radius:8px;"
            f"border:1px solid rgba(86,149,66,0.1);margin-top:12px;'>"
            f"<div style='display:flex;justify-content:space-between;'>"
            f"<span style='font-size:12px;font-weight:600;color:rgba(255,255,255,0.6);'>A-rated or better</span>"
            f"<span style='font-size:16px;font-weight:700;color:{GREEN};'>{a_pct:.0f}%</span>"
            f"</div>"
            f"<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-top:4px;'>"
            f"{a_plus_count} of {len(edf)} holdings rated A- or better</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Payout Ratio Heatmap ──────────────────────────────────────────────
    st.divider()
    st.markdown("**Payout Ratio — Traffic Light System**")
    st.markdown(
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
        "Green (&lt;50%) · Gold (50–70%) · Amber (70–85%) · Red (&gt;85%)"
        "</div>",
        unsafe_allow_html=True,
    )

    payout_df = edf[edf["payout_ratio"] > 0][["symbol", "payout_ratio", "safety", "consec_years", "sector"]].copy()
    payout_df = payout_df.sort_values("payout_ratio", ascending=True)

    if not payout_df.empty:
        colors = [_payout_color(v) for v in payout_df["payout_ratio"]]
        fig_pay = go.Figure()
        fig_pay.add_trace(go.Bar(
            y=payout_df["symbol"], x=payout_df["payout_ratio"], orientation="h",
            marker=dict(color=colors, opacity=0.8),
            text=[f"{v:.0f}%" for v in payout_df["payout_ratio"]],
            textposition="outside",
            textfont=dict(size=10, color="rgba(255,255,255,0.6)"),
        ))
        # Add reference lines
        fig_pay.add_vline(x=50, line_dash="dot", line_color="rgba(201,168,76,0.3)", annotation_text="50%", annotation_position="top")
        fig_pay.add_vline(x=70, line_dash="dot", line_color="rgba(232,168,56,0.3)", annotation_text="70%", annotation_position="top")

        _pay_layout = {**PLOTLY_DARK}
        _pay_layout["margin"] = dict(l=10, r=50, t=30, b=10)
        fig_pay.update_layout(
            **_pay_layout,
            height=max(280, len(payout_df) * 24 + 80),
            xaxis={**_XAXIS, "title": "Payout Ratio %", "ticksuffix": "%"},
            yaxis=_YAXIS,
            showlegend=False,
        )
        st.plotly_chart(fig_pay, use_container_width=True, config=PLOTLY_CONFIG)

    # ── Risk Monitor ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("**⚠️ Dividend Risk Monitor**")
    st.markdown(
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
        "Holdings with elevated payout ratios, declining growth, or broken streaks"
        "</div>",
        unsafe_allow_html=True,
    )

    # Flag holdings that meet any risk criteria
    # Note: for holdings without Fish CCC data (ADRs, foreign stocks), yfinance
    # growth rates can be misleading (FX effects, special dividends counted then
    # dropped). We use stricter thresholds for non-Fish tickers to avoid false alarms.
    risk_rows = []
    for _, r in edf.iterrows():
        concerns = []
        is_fish = r.get("fish_sourced", False)

        if r["payout_ratio"] >= 75:
            concerns.append(f"Elevated payout ratio ({r['payout_ratio']:.0f}%)")

        if is_fish:
            # Fish data is reliable — flag any negative growth
            if r["growth_5y"] < 0:
                concerns.append(f"Negative 5Y dividend growth ({r['growth_5y']:+.1f}%)")
            if r["growth_1y"] < -10:
                concerns.append(f"Significant 1Y decline ({r['growth_1y']:+.1f}%)")
        else:
            # yfinance fallback — use stricter thresholds to filter ADR/special noise
            if r["growth_5y"] < -10:
                concerns.append(f"Possible 5Y decline ({r['growth_5y']:+.1f}%) — verify (non-CCC)")
            if r["growth_1y"] < -20:
                concerns.append(f"Possible 1Y decline ({r['growth_1y']:+.1f}%) — verify (non-CCC)")

        if 0 < r["consec_years"] < 5:
            concerns.append(f"Short streak ({r['consec_years']}y) — possible reset")

        if concerns:
            risk_rows.append({
                "Symbol":    r["symbol"],
                "Company":   r["description"],
                "Safety":    r["safety"],
                "Payout":    r["payout_ratio"],
                "5Y Growth": r["growth_5y"],
                "Streak":    r["consec_years"] if r["consec_years"] > 0 else "N/A",
                "Concern":   " · ".join(concerns),
            })

    if risk_rows:
        risk_df = pd.DataFrame(risk_rows)

        def _risk_color(val):
            return f"color: #e8a838; font-style: italic"

        styled_risk = (
            risk_df.style
            .map(_color_safety, subset=["Safety"])
            .map(_risk_color, subset=["Concern"])
            .format({
                "Payout": "{:.0f}%",
                "5Y Growth": "{:+.1f}%",
                "Streak": lambda v: f"{v:.0f}y" if isinstance(v, (int, float)) else str(v),
            })
        )
        st.dataframe(
            styled_risk, use_container_width=True, hide_index=True,
            height=(42 + len(risk_df) * 36),
            column_config={
                "Symbol":    st.column_config.TextColumn("Symbol", width="small"),
                "Company":   st.column_config.TextColumn("Company", width="medium"),
                "Safety":    st.column_config.TextColumn("Safety", width="small"),
                "Payout":    st.column_config.NumberColumn("Payout", format="%.0f%%"),
                "5Y Growth": st.column_config.NumberColumn("5Y Gr", format="%+.1f%%"),
                "Streak":    st.column_config.TextColumn("Streak", width="small"),
                "Concern":   st.column_config.TextColumn("Concern", width="large"),
            },
        )
    else:
        st.success("✅ No holdings currently flagged for dividend risk.")