"""
Martin Capital Partners — Dividend Intelligence Tab
data/dividends_tab.py

Comprehensive dividend analytics rendered as sub-tabs within the main Dividends tab.
Sub-tabs:
  1. Announcements — existing dividend_calendar_tab.py (render_dividend_calendar)
  2. Dividend Detail — full sortable table with growth rates, payout, safety, history,
     plus Yield vs YoC chart and Consecutive Increases chart; clickable rows navigate
     to Stock Detail page
  3. Safety & Growth — growth tiers, safety scores, payout trends, risk monitor

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
from utils.disk_cache import disk_cached
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
# HELPER: yfinance dividend history fallback (for tickers not in Fish CCC)
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_yf_annual_dividends(ticker):
    """
    Fetch annual dividend totals from yfinance as a fallback when Fish CCC
    Historical data is unavailable (ADRs, newer holdings, non-US stocks).
    Returns dict: {year: annual_total} or empty dict on failure.
    """
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        divs = tk.dividends
        if divs is None or divs.empty:
            return {}

        df = divs.reset_index()
        df.columns = ["date", "amount"]
        df["year"] = pd.to_datetime(df["date"]).dt.year
        current_year = datetime.now().year

        # Sum by year, exclude current (incomplete) year
        annual = df[df["year"] < current_year].groupby("year")["amount"].sum()
        return {int(yr): round(float(amt), 4) for yr, amt in annual.items() if amt > 0}
    except Exception:
        return {}


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

        # Yield on Cost from Tamarac (decimal → percentage).
        # Tamarac API template 41 no longer returns yield_at_cost — it's 0 until
        # we move to a richer template. None signals "unavailable" so the UI
        # can render em-dash instead of a misleading 0.00%.
        yoc_raw = h.get("yield_at_cost", 0) or 0
        yoc_pct = (float(yoc_raw) * 100 if 0 < float(yoc_raw) < 1
                   else float(yoc_raw)) if yoc_raw else None

        # Current yield: Tamarac first, then Supabase `dividends` table, then
        # Supabase `prices` table. Different fields update at different rates
        # and one can have zero while the other is populated.
        # All three sources store dividend_yield as a percentage (e.g. 3.01).
        cy_raw = h.get("current_yield", 0) or 0
        if cy_raw:
            cy_pct = float(cy_raw) * 100 if 0 < float(cy_raw) < 1 else float(cy_raw)
        else:
            _dd_yield = float(dd.get("dividend_yield", 0) or 0)
            _mkt_yield = float(mkt.get("dividend_yield", 0) or 0)
            # Pick whichever source has a non-zero value; prefer dividends table
            cy_pct = _dd_yield if _dd_yield > 0 else _mkt_yield

        # Quantity from Tamarac (pulled early because annual_income derives from it)
        qty = float(h.get("quantity", 0) or 0)

        # Annual income: Tamarac first, else compute from dividend_rate × quantity.
        # dividend_rate is the annual per-share payment; × shares = annual income.
        tam_annual = h.get("annual_income", 0) or 0
        if tam_annual:
            annual_inc = float(tam_annual)
        else:
            _rate = dd.get("dividend_rate", 0) or 0
            annual_inc = float(_rate) * qty

        # Value (market value) from Tamarac
        value = float(h.get("value", 0) or 0)

        # Cost basis from Tamarac (template 41 returns 0; UI should render em-dash)
        cost_basis = float(h.get("cost_basis", 0) or 0)

        # Dividend data: prefer Fish CCC spreadsheet, fallback to Supabase/yfinance
        div_yield    = dd.get("dividend_yield", 0) or 0
        ex_date      = dd.get("ex_dividend_date", "")

        # Fish CCC data (authoritative for growth rates, payout, streaks)
        fish = {}
        div_hist = {}
        if _STREAKS_AVAILABLE:
            fish = get_fish_metrics(sym)
            div_hist = get_dividend_history(sym)

        # Consecutive years: Fish first, yfinance fallback
        # (computed early because _fish_has_growth below references consec_years)
        if _STREAKS_AVAILABLE:
            ccc_years, _ = get_streak(sym)
            consec_years = ccc_years if ccc_years > 0 else (dd.get("consecutive_years", 0) or 0)
        else:
            consec_years = dd.get("consecutive_years", 0) or 0

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
            "yield_on_cost": round(yoc_pct, 2) if yoc_pct is not None else None,
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


# ── Cached strategy-level enrichment ─────────────────────────────────────
# Wraps _build_enriched_df + the two .apply() calls so everything that
# depends only on (strategy, ticker tuple) is memoized. First visit to a
# strategy pays the full cost; every subsequent render — including strategy
# switches, autorefreshes, and sub-tab clicks — is a cache hit.
#
# The cache key is (strategy, ticker_tuple). The underscore prefix on
# `_tamarac_parsed` tells Streamlit to skip hashing that (large, unhashable)
# argument. The ticker tuple acts as the data identity: it changes when the
# Tamarac file is updated, so the cache invalidates on its own.

@st.cache_data(ttl=1800, show_spinner=False, max_entries=32)
@disk_cached(namespace="div_enriched", ttl=1800, version=1)
def _enriched_df_for_strategy(strategy, ticker_tuple, _tamarac_parsed, _v=1):
    """Cached enrichment keyed on (strategy, ticker_tuple).

    Fetches price + dividend data from already-cached helpers, runs
    _build_enriched_df, and appends the safety/growth_tier computed columns.
    The _tamarac_parsed arg is passed through so we can reconstruct tam_df
    on cache misses; leading underscore tells Streamlit not to hash it.
    """
    tam_df = get_holdings_for_strategy(_tamarac_parsed, strategy)
    price_data = fetch_batch_prices(ticker_tuple)
    div_data = get_batch_dividend_details(ticker_tuple)

    edf = _build_enriched_df(tam_df, price_data, div_data)
    edf["safety"] = edf.apply(
        lambda r: _safety_grade(
            r["payout_ratio"], r["growth_5y"], r["consec_years"],
            r.get("fish_sourced", False)
        ),
        axis=1,
    )
    edf["growth_tier"] = edf.apply(
        lambda r: _growth_tier(r["growth_5y"], r.get("fish_sourced", False)),
        axis=1,
    )
    return edf


def _enrich_for_strategy(tamarac_parsed, active_strategy):
    """Fetch + enrich dividend data for a strategy, with per-strategy caching.

    Returns (edf, tam_df, price_data, div_data) or (None, None, None, None)
    if the strategy has no holdings.
    """
    tam_df = get_holdings_for_strategy(tamarac_parsed, active_strategy)
    if tam_df.empty:
        return None, None, None, None

    ticker_tuple = tuple(tam_df["symbol"].tolist())

    # The cached helper does the expensive work on cache misses. On hits,
    # this returns instantly.
    edf = _enriched_df_for_strategy(active_strategy, ticker_tuple, tamarac_parsed)

    # We still return price_data and div_data for callers that need them
    # (income dashboard uses them directly). These are cached, so cheap.
    price_data = fetch_batch_prices(ticker_tuple)
    div_data = get_batch_dividend_details(ticker_tuple)
    return edf, tam_df, price_data, div_data


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

    # ── Load + enrich data (cached per-strategy) ───────────────────────────
    # Cache hits on strategy switch after first visit → instant.
    with st.spinner("Loading dividend intelligence..."):
        edf, tam_df, price_data, div_data = _enrich_for_strategy(
            tamarac_parsed, active_strategy
        )

    if edf is None:
        st.info("No holdings for this strategy in Tamarac file.")
        return

    # ── Sub-tabs ───────────────────────────────────────────────────────────
    sub_announce, sub_detail, sub_safety = st.tabs([
        "Announcements", "Dividend Detail", "Safety & Growth"
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
    # SUB-TAB 2: DIVIDEND DETAIL TABLE
    # ═══════════════════════════════════════════════════════════════════════
    with sub_detail:
        _render_dividend_detail(edf, active_strategy, strat_color)

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 3: SAFETY & GROWTH
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

    # Weighted average yield on cost (weight by portfolio weight, skip None rows)
    wtd_yoc = 0
    total_wt = edf["weight"].sum()
    _yoc_edf = edf[edf["yield_on_cost"].notna()]
    _yoc_wt = _yoc_edf["weight"].sum()
    if _yoc_wt > 0:
        wtd_yoc = (_yoc_edf["yield_on_cost"] * _yoc_edf["weight"]).sum() / _yoc_wt

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
    with k4: st.metric("Wtd 5Y Div CAGR", f"{wtd_growth_5y:+.2f}%")
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
        yoc_df = yoc_df[yoc_df["yield_on_cost"].notna()]
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
# SUB-TAB 2: DIVIDEND DETAIL TABLE (formerly sub-tab 3)
# ═══════════════════════════════════════════════════════════════════════════

def _render_dividend_detail(edf, active_strategy, strat_color):
    """Full sortable dividend metrics table with clickable rows for stock detail."""

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
    with d2: st.metric("Avg 1Y Div Growth", f"{avg_1y:+.2f}%")
    with d3: st.metric("Avg 3Y Div Growth", f"{avg_3y:+.2f}%")
    with d4: st.metric("Avg 5Y Div Growth", f"{avg_5y:+.2f}%")
    with d5: st.metric("Avg Consec. Years", f"{int(avg_consec)}")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    st.markdown(f"**Dividend Metrics — {STRATEGY_NAMES.get(active_strategy, active_strategy)}** · {len(edf)} holdings")
    st.markdown(
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:8px;'>"
        "Click any row to open stock detail page"
        "</div>",
        unsafe_allow_html=True,
    )

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
    if not detail_df.empty and "Company" in detail_df.columns:
        detail_df = detail_df.sort_values("Company", ascending=True).reset_index(drop=True)

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
            "Yield on Cost":  lambda v: "—" if v is None or pd.isna(v) else f"{v:.2f}%",
            "Div Amount":     "${:.2f}",
            "1Y Growth":      "{:+.2f}%",
            "3Y Growth":      "{:+.2f}%",
            "5Y Growth":      "{:+.2f}%",
            "10Y Growth":     lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) and v != 0 else "N/A",
            "Streak":         lambda v: f"{v:.0f}y" if isinstance(v, (int, float)) else str(v),
            "Recessions":     lambda v: str(v) if isinstance(v, (int, float)) else str(v),
            "Payout %":       "{:.0f}%",
        })
    )

    # Row-selection enabled dataframe — click a row to navigate to stock detail
    event = st.dataframe(
        styled, use_container_width=True, hide_index=True,
        height=(42 + len(detail_df) * 36),
        selection_mode="single-row",
        on_select="rerun",
        key="div_detail_table",
        column_config={
            "Symbol":        st.column_config.TextColumn("Symbol", width="small"),
            "Company":       st.column_config.TextColumn("Company", width="medium"),
            "Wt%":           st.column_config.NumberColumn("Wt%", format="%.2f%%"),
            "Curr Yield":    st.column_config.NumberColumn("Yield", format="%.2f%%"),
            "Yield on Cost": st.column_config.NumberColumn("YoC", format="%.2f%%"),
            "Div Amount":    st.column_config.NumberColumn("Div Amt", format="$%.2f"),
            "1Y Growth":     st.column_config.NumberColumn("1Y Gr", format="%+.2f%%"),
            "3Y Growth":     st.column_config.NumberColumn("3Y Gr", format="%+.2f%%"),
            "5Y Growth":     st.column_config.NumberColumn("5Y Gr", format="%+.2f%%"),
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

    # Navigate to stock detail when a row is selected
    if event and event.selection and event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_ticker = detail_df.iloc[selected_idx]["Symbol"]
        st.session_state["detail_ticker"] = selected_ticker
        st.query_params["ticker"] = selected_ticker
        st.switch_page("pages/2_Stock_Detail.py")

    # ── Current Yield vs Yield on Cost chart (moved from Income Dashboard) ─
    st.divider()
    col_yoc, col_streak = st.columns(2)

    with col_yoc:
        st.markdown("**Current Yield vs Yield on Cost**")
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            "YoC reflects dividend growth since purchase — the real compounding story"
            "</div>",
            unsafe_allow_html=True,
        )

        # Build comparison data. yield_on_cost is None when Tamarac doesn't
        # supply cost basis (current template 41 export) — filter those out.
        yoc_df = edf[["symbol", "current_yield", "yield_on_cost", "weight_pct"]].copy()
        yoc_df = yoc_df[yoc_df["yield_on_cost"].notna()]
        yoc_df = yoc_df.sort_values("yield_on_cost", ascending=True)

        if yoc_df.empty:
            st.markdown(
                "<div style='padding:40px 0;color:rgba(255,255,255,0.35);"
                "font-size:12px;text-align:center;'>"
                "Yield-on-cost data unavailable<br/>"
                "<span style='font-size:10px;opacity:0.6'>"
                "Tamarac cost basis not in current export"
                "</span></div>",
                unsafe_allow_html=True,
            )
        else:
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

    # ── Consecutive Increases chart (moved from Income Dashboard) ──────────
    with col_streak:
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

    # ── Dividend Yield by Holding ──────────────────────────────────────────
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


# ═══════════════════════════════════════════════════════════════════════════
# SUB-TAB 3: SAFETY & GROWTH ANALYTICS
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

    # ── Methodology Reference ────────────────────────────────────────────
    with st.expander("How are safety grades calculated?"):
        st.markdown("""
<div style="font-size:12px; color:rgba(255,255,255,0.65); line-height:1.7;">

Each holding receives a composite score (0–15 pts) from three equally weighted inputs, then mapped to a letter grade.

**Payout Ratio** — lower is safer (source: Fish CCC, fallback Supabase/yfinance)

<div style="margin-left:12px; color:rgba(255,255,255,0.5);">
&lt;40% → 5 pts &nbsp;·&nbsp; 40–55% → 4 pts &nbsp;·&nbsp; 55–70% → 3 pts &nbsp;·&nbsp; 70–85% → 2 pts &nbsp;·&nbsp; 85%+ → 1 pt &nbsp;·&nbsp; No data → 2 pts
</div>

**5-Year Dividend Growth Rate** — higher is safer (source: Fish CCC, fallback yfinance)

<div style="margin-left:12px; color:rgba(255,255,255,0.5);">
10%+ → 5 pts &nbsp;·&nbsp; 5–10% → 4 pts &nbsp;·&nbsp; 2–5% → 3 pts &nbsp;·&nbsp; 0–2% → 2 pts &nbsp;·&nbsp; Negative → 0 pts
<br>Non-Fish tickers (ADRs, foreign): mild negatives score 2 pts (FX/special div noise)
</div>

**Consecutive Years of Increases** — longer streak is safer (source: Fish CCC)

<div style="margin-left:12px; color:rgba(255,255,255,0.5);">
25+ yrs → 5 pts &nbsp;·&nbsp; 15–24 → 4 pts &nbsp;·&nbsp; 10–14 → 3 pts &nbsp;·&nbsp; 5–9 → 2 pts &nbsp;·&nbsp; &lt;5 → 1 pt &nbsp;·&nbsp; No data → 3 pts
</div>

**Grade Scale** (sum of three scores)

<div style="margin-left:12px; color:rgba(255,255,255,0.5);">
A+ = 14–15 &nbsp;·&nbsp; A = 12–13 &nbsp;·&nbsp; A- = 10–11 &nbsp;·&nbsp; B+ = 8–9 &nbsp;·&nbsp; B = 6–7 &nbsp;·&nbsp; B- = 4–5 &nbsp;·&nbsp; C = 0–3
</div>

</div>
""", unsafe_allow_html=True)

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
    st.markdown("**Dividend Risk Monitor**")
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
                concerns.append(f"Negative 5Y dividend growth ({r['growth_5y']:+.2f}%)")
            if r["growth_1y"] < -10:
                concerns.append(f"Significant 1Y decline ({r['growth_1y']:+.2f}%)")
        else:
            # yfinance fallback — use stricter thresholds to filter ADR/special noise
            if r["growth_5y"] < -10:
                concerns.append(f"Possible 5Y decline ({r['growth_5y']:+.2f}%) — verify (non-CCC)")
            if r["growth_1y"] < -20:
                concerns.append(f"Possible 1Y decline ({r['growth_1y']:+.2f}%) — verify (non-CCC)")

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
                "5Y Growth": "{:+.2f}%",
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
                "5Y Growth": st.column_config.NumberColumn("5Y Gr", format="%+.2f%%"),
                "Streak":    st.column_config.TextColumn("Streak", width="small"),
                "Concern":   st.column_config.TextColumn("Concern", width="large"),
            },
        )
    else:
        st.success("✅ No holdings currently flagged for dividend risk.")