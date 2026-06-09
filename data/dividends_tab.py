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

from utils.config import BRAND, STRATEGIES, normalize_sector
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
from data.scorecard_loader import (
    load_scorecard,
    days_since,
    is_stale,
    format_as_of,
    get_mcp_detail_map,
    _normalize_ticker as _norm_sc_ticker,
    BUCKET_ORDER,
    BUCKET_COLORS,
    STALE_DAYS,
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

# Notion metrics — for "Paid Since" (manually curated, more reliable than
# Fish Historical which floors at 1999). Sprint 25-12: replaces the old
# Streak/Began column pair with Paid/Raised to match the Warbook QDG view.
try:
    from data.notion_metrics import fetch_notion_metrics
    _NOTION_AVAILABLE = True
except ImportError:
    _NOTION_AVAILABLE = False

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
    # Sprint 25-12: pull Notion metrics for paid_since (manually curated year
    # the company first paid a dividend). Matches the warbook QDG view's Paid
    # column. Notion's own fetch is cached so this is cheap on repeat calls.
    notion_data = {}
    if _NOTION_AVAILABLE:
        try:
            notion_data = fetch_notion_metrics()
        except Exception:
            pass

    rows = []
    for _, h in tam_df.iterrows():
        sym = h["symbol"]
        mkt = price_data.get(sym, {})
        dd  = div_data.get(sym, {})
        nm  = notion_data.get(sym, {})

        # Quantity from Tamarac (pulled early because annual_income derives from it,
        # and annual_income + cost_basis are used in the YoC fallback below)
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

        # Yield on Cost from Tamarac (decimal → percentage).
        # Tamarac API template 41 no longer returns yield_at_cost — it's 0 for
        # most holdings until we move to a richer template. Fallback chain:
        #   1. annual_income / cost_basis (when both are populated)
        #   2. annual_income / (qty × unit_cost) — unit_cost comes from
        #      Tamarac_Holdings_Manual.xlsx and is present for legacy positions
        #      (e.g. TTE) where cost_basis is zeroed out by template 41.
        # None signals "unavailable" so the UI can render em-dash instead of
        # a misleading 0.00%.
        yoc_raw = h.get("yield_at_cost", 0) or 0
        unit_cost = float(h.get("unit_cost", 0) or 0)
        if yoc_raw:
            yoc_pct = float(yoc_raw) * 100 if 0 < float(yoc_raw) < 1 else float(yoc_raw)
        elif cost_basis > 0 and annual_inc > 0:
            yoc_pct = (annual_inc / cost_basis) * 100
        elif unit_cost > 0 and qty > 0 and annual_inc > 0:
            yoc_pct = (annual_inc / (qty * unit_cost)) * 100
        else:
            yoc_pct = None

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

        # Sprint 25-13: when we've decided the growth data isn't trustworthy,
        # null the cells so they render as em dashes rather than showing
        # misleading negative numbers. This catches two ADR patterns:
        #
        #   (a) Fish CCC has the ticker but with negative growth and no real
        #       streak (FX-noise pattern) — KOF is the canonical example.
        #   (b) Fish doesn't carry the ticker at all, so growth fell back to
        #       Supabase/yfinance which also reports USD-converted negatives
        #       that may be pure FX. Same heuristic: significant negative
        #       growth + no Fish streak = treat as untrusted.
        #
        # Same goes for streak_began/recessions/consec_years — Fish's streak
        # fields are based on USD-converted dividend totals, so a "no streak"
        # finding on an ADR could just be FX noise rather than a real cut.
        _untrusted_from_fish = fish_has_any and not _fish_has_growth
        _untrusted_from_yf = (
            not fish_has_any                                 # no Fish data
            and consec_years < 5                             # no real streak
            and (growth_1y < 0 or growth_5y < 0)             # negative growth
        )
        _is_untrusted_adr = _untrusted_from_fish or _untrusted_from_yf
        if _is_untrusted_adr:
            growth_1y = None
            growth_3y = None
            growth_5y = None
            growth_10y = None
            streak_began = None
            recessions = 0
            consec_years = 0

        # Paid Since — manually curated in Notion (more reliable than Fish
        # Historical, which floors at 1999 and would produce misleading
        # values like "1999" for JNJ — real answer is 1944). Same source
        # the Warbook QDG Characteristics view uses.
        paid_since_raw = nm.get("paid_since")
        paid_since = None
        if paid_since_raw is not None:
            try:
                paid_since = int(float(str(paid_since_raw)))
            except (ValueError, TypeError):
                pass

        # Market data
        price  = mkt.get("price", 0) or 0
        sector = normalize_sector(mkt.get("sector", ""))
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
            "growth_1y":     round(growth_1y, 1) if growth_1y is not None else None,
            "growth_3y":     round(growth_3y, 1) if growth_3y is not None else None,
            "growth_5y":     round(growth_5y, 1) if growth_5y is not None else None,
            "growth_10y":    round(growth_10y, 1) if growth_10y is not None else None,
            "ex_date":       ex_date,
            # Fish-only fields
            "chowder":       round(chowder, 1),
            "streak_began":  streak_began,
            "paid_since":    paid_since,
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
@disk_cached(namespace="div_enriched_v5", ttl=1800, version=4)
def _enriched_df_for_strategy_v5(strategy, ticker_tuple, _tamarac_parsed):
    """Cached enrichment keyed on (strategy, ticker_tuple).

    Fetches price + dividend data from already-cached helpers, runs
    _build_enriched_df, and appends the safety/growth_tier computed columns.
    The _tamarac_parsed arg is passed through so we can reconstruct tam_df
    on cache misses; leading underscore tells Streamlit not to hash it.

    NOTE: Renamed from _enriched_df_for_strategy on 2026-04-23 to force cache
    invalidation after YoC fallback logic changes. Version params on the
    decorators weren't enough on Streamlit Cloud — function-level rename is
    the bulletproof path because Python can't serve a cache entry keyed on
    a function name that no longer exists.

    Sprint 25-12: bumped v2 -> v3 after adding the paid_since column to
    each row (from Notion). The old cached frames don't have the column,
    which made the new Paid display column read None for every ticker.

    Sprint 25-13a: bumped v3 -> v4 after nulling growth/streak fields for
    untrusted ADRs (KOF, etc.). Old cached frames have negative growth
    values that should now be None.

    Sprint 25-13b: bumped v4 -> v5 after extending the trust check to also
    catch ADRs where Fish has no data at all but Supabase is reporting
    FX-noise negatives (the actual KOF pattern — turned out it isn't in
    Fish, so the original v4 null-out didn't fire).
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
    edf = _enriched_df_for_strategy_v5(active_strategy, ticker_tuple, tamarac_parsed)

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
    # Sprint 25-13: growth_5y may be None for untrusted ADR rows where Fish's
    # USD-converted values were nulled out. Treat None as neutral (no data).
    if growth_5y is None:
        growth_5y = 0

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
    # Sprint 25-13: untrusted ADR rows have None — label them explicitly.
    if growth_5y is None:
        return "No CCC data"
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
# SUB-TAB 2: DIVIDEND DETAIL TABLE
# ═══════════════════════════════════════════════════════════════════════════

def _render_dividend_detail(edf, active_strategy, strat_color):
    """Full sortable dividend metrics table with clickable rows for stock detail."""

    # ── KPI summary row ────────────────────────────────────────────────────
    # Avg growth rates (exclude zeros and outliers)
    def _avg_col(col, lo=-50, hi=100):
        vals = edf[(edf[col] != 0) & (edf[col] > lo) & (edf[col] < hi)][col]
        return round(vals.mean(), 1) if not vals.empty else 0

    avg_1y  = _avg_col("growth_1y")
    avg_3y  = _avg_col("growth_3y")
    avg_5y  = _avg_col("growth_5y")
    avg_10y = _avg_col("growth_10y")

    consec = edf[edf["consec_years"] > 0]["consec_years"].tolist()
    avg_consec = round(sum(consec) / len(consec), 0) if consec else 0

    d1, d2, d3, d4, d5 = st.columns(5)
    with d1: st.metric("Avg 1Y Div Growth",  f"{avg_1y:+.2f}%")
    with d2: st.metric("Avg 3Y Div Growth",  f"{avg_3y:+.2f}%")
    with d3: st.metric("Avg 5Y Div Growth",  f"{avg_5y:+.2f}%")
    with d4: st.metric("Avg 10Y Div Growth", f"{avg_10y:+.2f}%")
    with d5: st.metric("Avg Consec. Years",  f"{int(avg_consec)}")

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
        # Sprint 25-12: Streak/Began columns retired in favor of Paid/Raised
        # to match the Warbook QDG Characteristics view.
        #   - Paid   = year company first paid a dividend (from Notion)
        #   - Raised = year current annual-increase streak began (from Fish)
        paid_raw = r.get("paid_since", None)
        try:
            paid_str = str(int(float(str(paid_raw)))) if paid_raw and str(paid_raw).strip() not in ("", "0", "None", "nan") else "—"
        except (ValueError, TypeError):
            paid_str = "—"

        raised_raw = r.get("streak_began", None)
        try:
            raised_str = str(int(float(str(raised_raw)))) if raised_raw and str(raised_raw).strip() not in ("", "0", "None", "nan") else "—"
        except (ValueError, TypeError):
            raised_str = "—"

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
            "Paid":           paid_str,
            "Raised":         raised_str,
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
            "Paid":          st.column_config.TextColumn("Paid", width="small", help="Year the company first paid a dividend (from Notion)"),
            "Raised":        st.column_config.TextColumn("Raised", width="small", help="Year the current annual increase streak began (from Fish CCC)"),
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


# ═══════════════════════════════════════════════════════════════════════════
# SUB-TAB 3: SAFETY & GROWTH ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════


def _render_safety_growth(edf, active_strategy, strat_color):
    """
    Sprint 21 rewrite — Dividend Distress Scorecard view.

    Reads data/dividend_scorecard_latest.json (written by run_scorecard.py
    in the Dividend Monitoring System project) and renders the 6-pillar
    framework: bucket distribution, full MCP scorecard table, per-ticker
    pillar breakdowns for flagged names, and broader-universe Red/Critical.

    Per Sprint 21 design: shows ALL MCP holdings regardless of active
    strategy (universe view) — `edf` and `active_strategy` parameters are
    retained for caller compatibility but no longer drive the data path.
    `strat_color` is unused; kept in signature so the caller doesn't break.
    """
    # Reduce noise — these are not used by the scorecard view
    _ = edf
    _ = active_strategy
    _ = strat_color

    scorecard = load_scorecard()

    # ── No file available → empty state with run instructions ────────────
    if scorecard is None:
        st.warning(
            "**Dividend Distress Scorecard not yet available.**\n\n"
            "The scorecard hasn't been generated, or the JSON copy in "
            "`data/dividend_scorecard_latest.json` is missing or unreadable.\n\n"
            "To populate this tab, run the scorecard pipeline:\n\n"
            "```\npython run_scorecard.py\n```\n\n"
            "(from the Dividend Monitoring System project). The script writes "
            "a copy into the dashboard repo automatically; commit and push "
            "to update Streamlit Cloud."
        )
        return

    as_of = scorecard.get("as_of_date", "")
    days_old = days_since(as_of)
    summary = scorecard.get("summary", {})
    mcp_rows = scorecard.get("mcp_rows", []) or []
    universe_flagged = scorecard.get("universe_flagged", []) or []
    detail_map = get_mcp_detail_map(scorecard)

    # Yield in the scorecard JSON is stored as a decimal fraction
    # (PitchBook convention: 0.043 = 4.3%). Multiply by 100 for display.
    # Helper is reused by both the MCP scorecard table and the universe
    # table so the conversion lives in one place. The bounds check
    # safely passes through anything that's already in percent form
    # (e.g. >1) so future format changes don't silently corrupt output.
    def _fmt_yield_pct(v):
        if not isinstance(v, (int, float)):
            return "—"
        # Decimal fraction (typical case): scale to percent
        if 0 <= v <= 1:
            return f"{v * 100:.1f}%"
        # Already in percent form (defensive)
        return f"{v:.1f}%"

    # ── Header strip: as-of date, scope, optional staleness warning ──────
    header_bits = [
        f"As of <strong>{format_as_of(as_of)}</strong>",
        f"<strong>{summary.get('mcp_count', len(mcp_rows))}</strong> MCP holdings",
        f"<strong>{summary.get('total_scored', 0)}</strong> total scored",
    ]
    if days_old is not None:
        header_bits.append(f"{days_old} day{'s' if days_old != 1 else ''} ago")

    st.markdown(
        f"<div style='font-size:13px;color:rgba(255,255,255,0.55);margin-bottom:8px;'>"
        f"{' &nbsp;·&nbsp; '.join(header_bits)}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if is_stale(as_of):
        st.warning(
            f"⚠️ Scorecard is **{days_old} days old** (threshold: {STALE_DAYS} days). "
            f"Re-run `python run_scorecard.py` to refresh."
        )

    # Methodology expander — lifted from the scorecard's docx methodology
    # section so users can see how to interpret the buckets without
    # opening the full PDF report.
    with st.expander("Methodology — six-pillar framework"):
        st.markdown("""
The **MCP Dividend Distress Scorecard** scores each dividend-paying
holding on six pillars derived from analysis of historical dividend
cuts. The framework was backtested against nine fundamentals-driven
cut events (INTC 2023, WBA 2024, GE 2017, T 2022, KHC 2019, MMM 2023,
COP 2016, MAT 2017, MAC 2018) and correctly flagged 9 of 9 at 12 months
pre-cut.

**Six Pillars**

1. **Yield Signal** — Is the yield elevated because the price is falling? Compares current yield to 5-year average and measures distance from 52-week high.
2. **Cash Flow Coverage** — Can FCF pay the dividend? FCF payout ratio, earnings payout, Morningstar Dividend Safety as fallbacks.
3. **Balance Sheet** — Does leverage threaten the dividend? Interest coverage 40%, Morningstar Financial Health (Distance-to-Default proxy) 60%.
4. **Business Quality** — Does the business earn excess returns? Morningstar Economic Moat, Capital Allocation rating, ROIC.
5. **Market Signal** — Is the market pricing in distress? Short interest, proximity to 52-week low, Morningstar star rating.
6. **Dividend Trajectory** — What has the dividend done historically? Detects freezes, recent cuts, decelerating growth, and variable-dividend policies using 10+ years of payout history.

**Composite & Risk Buckets**

Each pillar scores from −2 (severe stress) to +2 (healthy). Composite scales to a −10 to +10 range. A severity override ensures a single −2 pillar triggers at least Yellow, and two or more −2 pillars force at least Red.

| Bucket | Composite | Interpretation |
|---|---|---|
| **Critical** | ≤ −6 | Multiple severe pillars. Cut likely within 12 months if pressure persists. |
| **Red** | −3 to −5 | Significant stress across pillars. Cut risk elevated. Monitor closely. |
| **Yellow** | −1 to −2 | Emerging stress. Watch list candidate. |
| **Green** | 0 to +2 | Neutral to mildly healthy dividend. |
| **Strong** | ≥ +3 | Very healthy dividend with ample coverage and quality fundamentals. |
""")

    # ── Bucket distribution counter cards ────────────────────────────────
    st.markdown(
        "<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);"
        "margin-top:24px;margin-bottom:10px;'>MCP Holdings — Risk Bucket Distribution</div>",
        unsafe_allow_html=True,
    )

    by_bucket = summary.get("mcp_by_bucket", {}) or {}
    cols = st.columns(len(BUCKET_ORDER))
    for i, bucket in enumerate(BUCKET_ORDER):
        count = int(by_bucket.get(bucket, 0))
        color = BUCKET_COLORS.get(bucket, "rgba(255,255,255,0.3)")
        with cols[i]:
            st.markdown(
                f"<div style='background:rgba(255,255,255,0.02);"
                f"border:1px solid {color}33;border-left:3px solid {color};"
                f"border-radius:8px;padding:14px 14px;'>"
                f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:0.08em;"
                f"color:{color};font-weight:700;'>{bucket}</div>"
                f"<div style='font-size:28px;font-weight:700;color:rgba(255,255,255,0.9);"
                f"font-family:\"DM Serif Display\",serif;line-height:1.2;margin-top:4px;'>{count}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── MCP Holdings — Full Scorecard table ───────────────────────────────
    st.markdown(
        "<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);"
        "margin-top:24px;margin-bottom:10px;'>MCP Holdings — Full Scorecard</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
        "All MCP holdings sorted by composite score (most distressed first). "
        "Sectors normalized to MCP convention. Yellow/Red/Critical names "
        "have an expandable per-pillar breakdown below the table."
        "</div>",
        unsafe_allow_html=True,
    )

    # Build display dataframe with normalized sectors and bucket sort key
    bucket_sort_key = {b: i for i, b in enumerate(BUCKET_ORDER)}
    rows = []
    for r in mcp_rows:
        bucket = r.get("bucket", "")
        rows.append({
            "Ticker":      _norm_sc_ticker(r.get("ticker", "")),
            "Company":     r.get("company", "") or "",
            "Sector":      normalize_sector(r.get("sector", "")),
            "Yield":       r.get("yield"),
            "Composite":   r.get("composite"),
            "Bucket":      bucket,
            "Trajectory":  r.get("trajectory_pattern", "") or "",
            "Key Signal":  r.get("key_signal", "") or "",
            "_bucket_sort": bucket_sort_key.get(bucket, 99),
            "_composite_sort": r.get("composite") if r.get("composite") is not None else 99,
        })
    sc_df = pd.DataFrame(rows)
    if not sc_df.empty:
        sc_df = sc_df.sort_values(["_bucket_sort", "_composite_sort"]).reset_index(drop=True)

    # Styled bucket badges via cell-level Styler.map
    def _bucket_badge(val):
        color = BUCKET_COLORS.get(val, "rgba(255,255,255,0.3)")
        # Use a CSS background tint + matching text color
        return f"background-color: {color}22; color: {color}; font-weight: 600;"

    def _yield_color(val):
        return f"color: {BRAND['gold']};"

    def _composite_color(val):
        try:
            v = float(val)
        except (ValueError, TypeError):
            return ""
        if v >= 3:
            return f"color: {BRAND['green']}; font-weight: 600;"
        if v >= 0:
            return "color: rgba(255,255,255,0.75);"
        if v >= -2:
            return f"color: {BRAND['gold']}; font-weight: 600;"
        return f"color: {BRAND['red']}; font-weight: 600;"

    if not sc_df.empty:
        display_df = sc_df.drop(columns=["_bucket_sort", "_composite_sort"])
        styled = (
            display_df.style
            .map(_bucket_badge, subset=["Bucket"])
            .map(_yield_color, subset=["Yield"])
            .map(_composite_color, subset=["Composite"])
            .format({
                "Yield":     _fmt_yield_pct,
                "Composite": lambda v: f"{v:+.1f}" if isinstance(v, (int, float)) else "—",
            })
        )
        st.dataframe(
            styled, width="stretch", hide_index=True,
            height=min(80 + len(display_df) * 36, 1200),
            column_config={
                "Ticker":     st.column_config.TextColumn("Ticker", width="small"),
                "Company":    st.column_config.TextColumn("Company", width="medium"),
                "Sector":     st.column_config.TextColumn("Sector", width="medium"),
                "Yield":      st.column_config.TextColumn("Yield", width="small"),
                "Composite":  st.column_config.TextColumn("Score", width="small"),
                "Bucket":     st.column_config.TextColumn("Risk", width="small"),
                "Trajectory": st.column_config.TextColumn("Trajectory", width="small"),
                "Key Signal": st.column_config.TextColumn("Key Signal", width="large"),
            },
        )
    else:
        st.info("No MCP holdings in the latest scorecard run.")

    # ── Per-ticker pillar breakdown (Yellow/Red/Critical only) ────────────
    flagged_buckets = {"Yellow", "Red", "Critical"}
    flagged_rows = [r for r in mcp_rows if r.get("bucket") in flagged_buckets]

    st.markdown(
        "<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);"
        "margin-top:28px;margin-bottom:10px;'>MCP Holdings Requiring Attention — Pillar Detail</div>",
        unsafe_allow_html=True,
    )

    if not flagged_rows:
        st.success(
            "✅ All MCP holdings currently rated **Green** or **Strong**. "
            "No Yellow / Red / Critical names in the latest scorecard run."
        )
    else:
        st.markdown(
            "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
            f"{len(flagged_rows)} holding(s) flagged. Click any row to expand the six-pillar breakdown."
            "</div>",
            unsafe_allow_html=True,
        )

        # Sort flagged rows by composite ascending (worst first) — matches docx
        flagged_rows = sorted(
            flagged_rows,
            key=lambda r: (r.get("composite") if r.get("composite") is not None else 99),
        )

        pillar_names = [
            "Yield Signal",
            "Cash Flow Coverage",
            "Balance Sheet",
            "Business Quality",
            "Market Signal",
            "Dividend Trajectory",
        ]

        for r in flagged_rows:
            sym_norm = _norm_sc_ticker(r.get("ticker", ""))
            company = r.get("company", "") or ""
            bucket = r.get("bucket", "")
            composite = r.get("composite")
            sector_norm = normalize_sector(r.get("sector", ""))
            color = BUCKET_COLORS.get(bucket, "rgba(255,255,255,0.3)")

            # Expander header — ticker, company, bucket badge, composite
            comp_str = f"{composite:+.1f}" if isinstance(composite, (int, float)) else "—"
            expander_label = f"{sym_norm} · {company} · {bucket} · {comp_str}"

            with st.expander(expander_label):
                # Top-line meta
                st.markdown(
                    f"<div style='display:flex;gap:18px;flex-wrap:wrap;font-size:12px;"
                    f"color:rgba(255,255,255,0.55);margin-bottom:14px;'>"
                    f"<div><span style='color:rgba(255,255,255,0.35);'>Composite:</span> "
                    f"<strong style='color:{color};'>{comp_str}</strong></div>"
                    f"<div><span style='color:rgba(255,255,255,0.35);'>Bucket:</span> "
                    f"<strong style='color:{color};'>{bucket}</strong></div>"
                    f"<div><span style='color:rgba(255,255,255,0.35);'>Sector:</span> "
                    f"<strong>{sector_norm}</strong></div>"
                    f"<div><span style='color:rgba(255,255,255,0.35);'>Trajectory:</span> "
                    f"<strong>{r.get('trajectory_pattern') or '—'}</strong></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Pull the matching detail record (six pillar scores +
                # narratives). detail_map is keyed by normalized ticker so
                # NYS:KOF and KOF both resolve.
                detail = detail_map.get(sym_norm)
                if not detail:
                    st.caption("Per-pillar detail unavailable in this scorecard run.")
                    continue

                # Build the pillar table
                pillar_rows = []
                for p in pillar_names:
                    score = detail.get(f"{p} Score")
                    narrative = detail.get(f"{p} Narrative") or ""
                    pillar_rows.append({
                        "Pillar":    p,
                        "Score":     score,
                        "Signal":    narrative,
                    })

                pillar_df = pd.DataFrame(pillar_rows)

                def _pillar_score_color(val):
                    if val is None:
                        return "color: rgba(255,255,255,0.3); font-style: italic;"
                    try:
                        v = int(val)
                    except (ValueError, TypeError):
                        return ""
                    if v >= 1:
                        return f"color: {BRAND['green']}; font-weight: 600;"
                    if v == 0:
                        return "color: rgba(255,255,255,0.65);"
                    if v == -1:
                        return f"color: {BRAND['gold']}; font-weight: 600;"
                    return f"color: {BRAND['red']}; font-weight: 700;"

                def _fmt_pillar_score(v):
                    # Pillar scores are -1 / 0 / +1 but can arrive as numpy
                    # float64/int64, None, or NaN (e.g. a pillar with no score
                    # in this scorecard run). The ":d" code only accepts a true
                    # Python int, so coerce defensively and fall back to an em
                    # dash for anything non-numeric or blank.
                    try:
                        if v is None or pd.isna(v):
                            return "—"
                    except (TypeError, ValueError):
                        pass
                    try:
                        return f"{int(round(float(v))):+d}"
                    except (TypeError, ValueError):
                        return "—"

                styled_p = (
                    pillar_df.style
                    .map(_pillar_score_color, subset=["Score"])
                    .format({"Score": _fmt_pillar_score})
                )
                st.dataframe(
                    styled_p, width="stretch", hide_index=True,
                    height=42 + len(pillar_df) * 36,
                    column_config={
                        "Pillar": st.column_config.TextColumn("Pillar", width="small"),
                        "Score":  st.column_config.TextColumn("Score", width="small"),
                        "Signal": st.column_config.TextColumn("Signal", width="large"),
                    },
                )

    # ── Broader Universe — Red & Critical (collapsible) ──────────────────
    st.markdown(
        "<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);"
        "margin-top:28px;margin-bottom:10px;'>Broader Universe — Red &amp; Critical</div>",
        unsafe_allow_html=True,
    )

    if not universe_flagged:
        st.caption("No Red or Critical names flagged in the broader universe.")
    else:
        with st.expander(
            f"Show {len(universe_flagged)} flagged universe name(s)",
            expanded=False,
        ):
            uni_rows = []
            for r in universe_flagged:
                bucket = r.get("bucket", "")
                uni_rows.append({
                    "Ticker":     _norm_sc_ticker(r.get("ticker", "")),
                    "Company":    r.get("company", "") or "",
                    "Sector":     normalize_sector(r.get("sector", "")),
                    "Yield":      r.get("yield"),
                    "Composite":  r.get("composite"),
                    "Bucket":     bucket,
                    "Trajectory": r.get("trajectory_pattern", "") or "",
                    "Key Signal": r.get("key_signal", "") or "",
                    "_bucket_sort": bucket_sort_key.get(bucket, 99),
                    "_composite_sort": r.get("composite") if r.get("composite") is not None else 99,
                })
            uni_df = pd.DataFrame(uni_rows).sort_values(
                ["_bucket_sort", "_composite_sort"]
            ).reset_index(drop=True).drop(columns=["_bucket_sort", "_composite_sort"])

            uni_styled = (
                uni_df.style
                .map(_bucket_badge, subset=["Bucket"])
                .map(_yield_color, subset=["Yield"])
                .map(_composite_color, subset=["Composite"])
                .format({
                    "Yield":     _fmt_yield_pct,
                    "Composite": lambda v: f"{v:+.1f}" if isinstance(v, (int, float)) else "—",
                })
            )
            st.dataframe(
                uni_styled, width="stretch", hide_index=True,
                height=min(80 + len(uni_df) * 36, 1200),
                column_config={
                    "Ticker":     st.column_config.TextColumn("Ticker", width="small"),
                    "Company":    st.column_config.TextColumn("Company", width="medium"),
                    "Sector":     st.column_config.TextColumn("Sector", width="medium"),
                    "Yield":      st.column_config.TextColumn("Yield", width="small"),
                    "Composite":  st.column_config.TextColumn("Score", width="small"),
                    "Bucket":     st.column_config.TextColumn("Risk", width="small"),
                    "Trajectory": st.column_config.TextColumn("Trajectory", width="small"),
                    "Key Signal": st.column_config.TextColumn("Key Signal", width="large"),
                },
            )

    # ── Footer attribution ───────────────────────────────────────────────
    st.markdown(
        f"<div style='font-size:10px;color:rgba(255,255,255,0.3);margin-top:24px;text-align:right;'>"
        f"Source: MCP Dividend Distress Scorecard · PitchBook + Morningstar + Fish CCC · "
        f"Generated {format_as_of(as_of)}"
        f"</div>",
        unsafe_allow_html=True,
    )