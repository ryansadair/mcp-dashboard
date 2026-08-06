import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime
from utils.auth import check_password
from utils.styles import inject_global_css
from utils.config import STRATEGIES, SECTOR_COLORS, normalize_sector
from components.header import render_header
from components.market_ticker import render_market_ticker
from components.kpi_cards import render_kpi_cards

# ── Sprint 2 imports (graceful if not yet available) ──────────────────────
try:
    from data.tamarac_parser import (
        parse_tamarac_excel, get_holdings_for_strategy, get_cash_weight,
        STRATEGY_NAMES, STRATEGY_COLORS as STRAT_COLORS, STRATEGY_BENCHMARKS,
    )
    from data.market_data import fetch_batch_prices
    from data.dividends import (
        get_batch_dividend_details, compute_strategy_income, compute_weighted_yield,
    )
    SPRINT2_AVAILABLE = True
except ImportError:
    SPRINT2_AVAILABLE = False

# Sprint 19: intraday performance chart (Overview tab)
try:
    from data.intraday_chart import fetch_intraday_chart_data
    INTRADAY_CHART_AVAILABLE = True
except ImportError:
    INTRADAY_CHART_AVAILABLE = False

# Tamarac auto-detector (Sprint 5)
try:
    from data.tamarac_detector import (
        get_tamarac_status, find_best_tamarac_file, render_tamarac_status_banner,
    )
    DETECTOR_AVAILABLE = True
except ImportError:
    DETECTOR_AVAILABLE = False

# Notion proprietary metrics (Sprint 5)
try:
    from data.notion_metrics import fetch_notion_metrics
    NOTION_METRICS_AVAILABLE = True
except ImportError:
    NOTION_METRICS_AVAILABLE = False

# Watchlist (Excel-based, always available independently of Sprint 2)
try:
    from data.watchlist_tab import render_watchlist_tab
    WATCHLIST_AVAILABLE = True
except ImportError:
    WATCHLIST_AVAILABLE = False

# Dividend Announcement Calendar (from weekly dividend_calendar.py output)
try:
    from data.dividend_calendar_tab import render_dividend_calendar
    DIV_CALENDAR_AVAILABLE = True
except ImportError:
    DIV_CALENDAR_AVAILABLE = False

# Dividend Intelligence sub-tabs (Sprint 4)
try:
    from data.dividends_tab import render_dividends_tab
    DIV_TAB_AVAILABLE = True
except ImportError:
    DIV_TAB_AVAILABLE = False

# Warbook tab (Sprint 23B) — Strategy Overview + Attribution sub-tabs
try:
    from data.warbook_tab import render_warbook_tab
    WARBOOK_AVAILABLE = True
except ImportError:
    WARBOOK_AVAILABLE = False

# Macro Environment tab
try:
    from data.macro_tab import render_macro_tab
    MACRO_AVAILABLE = True
except ImportError:
    MACRO_AVAILABLE = False

# Markets tab (Sprint 5)
try:
    from data.markets_tab import render_markets_tab
    MARKETS_AVAILABLE = True
except ImportError:
    MARKETS_AVAILABLE = False

# Alerts tab (Sprint 6)
try:
    from data.alerts_tab import render_alerts_tab
    ALERTS_AVAILABLE = True
except ImportError:
    ALERTS_AVAILABLE = False

# Finviz enrichment (Sprint 7)
try:
    from data.finviz_tab import render_finviz_panel
    FINVIZ_AVAILABLE = True
except ImportError:
    FINVIZ_AVAILABLE = False

# Mobile responsiveness (Sprint 7)
try:
    from utils.mobile_css import inject_mobile_css
    MOBILE_CSS_AVAILABLE = True
except ImportError:
    MOBILE_CSS_AVAILABLE = False

# Composite Returns (Sprint 10)
try:
    from data.performance_tab import render_performance_tab
    COMPOSITE_AVAILABLE = True
except ImportError:
    COMPOSITE_AVAILABLE = False

# Monthly YTD returns from Tamarac (separate file Ryan updates)
try:
    from data.monthly_returns import STRATEGY_YTD, AS_OF_DATE
    MONTHLY_RETURNS_AVAILABLE = True
except ImportError:
    STRATEGY_YTD = {}
    AS_OF_DATE = ""
    MONTHLY_RETURNS_AVAILABLE = False

if not check_password():
    st.stop()

# ── Auto-refresh + disk cache strategy ────────────────────────────────────
# Two mechanisms work together to keep the dashboard fast and robust:
#
# 1. st_autorefresh (5 min):
#    - Reruns the script while the tab is visible
#    - Each rerun resets Streamlit Cloud's 10-min idle timeout → no eviction
#    - Refreshes prices/clock via @st.cache_data TTL expiry
#    - Browsers throttle this in hidden tabs (fine — we don't want
#      background reruns anyway)
#
# 2. Disk cache (utils/disk_cache.py):
#    - Heavy computations (performance metrics, dividend enrichment) are
#      persisted to data/cache/disk/ so they survive session eviction.
#    - When the tab comes back after the session was evicted, Streamlit's
#      WebSocket reconnects transparently and the script reruns against
#      the disk cache (~100ms) instead of recomputing from scratch.
#
# We deliberately do NOT force a reload on visibilitychange: it would
# re-trigger the login gate for users who were idle, which is worse UX
# than the rare "slightly slower first interaction after a long idle"
# that the disk cache already mostly fixes anyway.
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=300 * 1000, key="data_refresh")

inject_global_css()

# Sprint 7: mobile responsiveness
if MOBILE_CSS_AVAILABLE:
    inject_mobile_css()

render_header()
render_market_ticker()

# ── Data freshness + Tamarac status (combined, right-aligned) ─────────────
_status_parts = []

# Part 1: data freshness — live Finviz quote time when available (updated
# every ~60s by the price layer), otherwise the Supabase prefetch timestamp.
# On the very first render of a session the Finviz fetch hasn't happened
# yet (it fires inside the tab bodies below), so the stamp shows Supabase
# age once, then flips to the live time on the next rerun/autorefresh.
try:
    from data.market_data import get_cache_timestamp
    _raw_ts = get_cache_timestamp()
    _live_source = False
    try:
        from data.finviz_export import last_fetch_time
        _fv_epoch = last_fetch_time()
    except Exception:
        _fv_epoch = None
    if _raw_ts or _fv_epoch:
        from datetime import timedelta, timezone
        try:
            _parsed = None
            if _raw_ts:
                _parsed = datetime.fromisoformat(_raw_ts.replace("Z", "+00:00"))
                # Make _parsed timezone-aware UTC if it came in naive
                if _parsed.tzinfo is None:
                    _parsed = _parsed.replace(tzinfo=timezone.utc)
            if _fv_epoch:
                _fv_dt = datetime.fromtimestamp(_fv_epoch, tz=timezone.utc)
                if _parsed is None or _fv_dt > _parsed:
                    _parsed = _fv_dt
                    _live_source = True
            # Auto-detect PDT vs PST for display time
            _utc_now = datetime.now(timezone.utc)
            from zoneinfo import ZoneInfo
            _pacific = _parsed.astimezone(ZoneInfo("America/Los_Angeles"))
            _age_min = int((_utc_now - _parsed).total_seconds() / 60)
            _time_str = _pacific.strftime("%I:%M %p").lstrip("0")

            if _age_min <= 20:
                _status_dot = "#569542"
                _age_str = f"{_age_min}m ago" if _age_min >= 2 else "just now"
            elif _age_min <= 60:
                _status_dot = "#C9A84C"
                _age_str = f"{_age_min}m ago"
            else:
                _status_dot = "#c45454"
                _age_str = f"{_age_min // 60}h ago"

            # Sprint 26: wrap dot + text in inline-flex so they stay
            # together as a single wrap unit when the status strip wraps
            # to a second line on phone (no orphaned dot).
            _status_parts.append(
                f'<span style="display:inline-flex;align-items:center;gap:6px;">'
                f'<span style="width:6px;height:6px;border-radius:50%;background:{_status_dot};'
                f'display:inline-block;flex-shrink:0;"></span>'
                f'<span>{"Live quotes" if _live_source else "Data refreshed"} {_time_str} PT ({_age_str})</span>'
                f'</span>'
            )
        except Exception:
            pass
except ImportError:
    pass

# Part 2: Tamarac file status
if DETECTOR_AVAILABLE:
    try:
        _tam_status = get_tamarac_status()
        if _tam_status["found"]:
            _tam_age = _tam_status["age_days"]
            _tam_dot = "#C9A84C" if _tam_status["stale"] else "rgba(86,149,66,0.7)"
            _tam_age_str = f"{_tam_age}d ago" if _tam_age > 0 else "today"
            # Show the internal "As of Date" from the Excel, not filesystem mtime
            _tam_date_str = ""
            if _tam_status.get("as_of_date"):
                _tam_date_str = f' · as-of {_tam_status["as_of_date"].strftime("%b %d")}'
            # Sprint 26: filename wrapped in .mcp-tamarac-filename so the
            # phone media query in mobile_css.py can hide it on narrow
            # viewports. Outer inline-flex span keeps the dot bound to its
            # text label when the status strip wraps on phone.
            _status_parts.append(
                f'<span style="display:inline-flex;align-items:center;gap:6px;">'
                f'<span style="width:6px;height:6px;border-radius:50%;background:{_tam_dot};'
                f'display:inline-block;flex-shrink:0;"></span>'
                f'<span>Tamarac: <span class="mcp-tamarac-filename">{_tam_status["filename"]}</span>{_tam_date_str} · {_tam_age_str}</span>'
                f'</span>'
            )
    except Exception:
        pass

# Part 3: Data canary status — the daily invariant checks (canary.py via
# GitHub Actions). Three states: green = all checks passed this morning,
# amber = passed with warnings OR the canary hasn't reported in >30h
# (i.e. the watcher itself is down — a missing canary must be as visible
# as a failing one), red = an invariant failed (details in the Actions
# log and the canary_status.failures column).
try:
    from data.market_data import _sb_get as _canary_sb_get
    _canary_rows = _canary_sb_get(
        "canary_status",
        select="run_at,status,failures",
        filters={"order": "run_at.desc", "limit": "1"},
    ) or []
    if not _canary_rows:
        # No rows readable — either the canary has never written or the
        # Supabase read is failing. Either way, SHOW it: the watcher's
        # display must not fail silent (which is exactly how the chip
        # vanished on 2026-08-04 instead of telling anyone why).
        _status_parts.append(
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="width:6px;height:6px;border-radius:50%;background:#C9A84C;'
            'display:inline-block;flex-shrink:0;"></span>'
            '<span>Canary status unreadable</span>'
            '</span>'
        )
    if _canary_rows:
        from datetime import timezone as _tz
        _c = _canary_rows[0]
        _c_dt = datetime.fromisoformat(_c["run_at"].replace("Z", "+00:00"))
        _c_age_h = (datetime.now(_tz.utc) - _c_dt).total_seconds() / 3600
        # Weekend allowance: Friday's run is the newest until Monday 6:50a.
        _overdue = _c_age_h > (78 if datetime.now(_tz.utc).weekday() == 0 else 30)
        if _c["status"] == "fail":
            _c_dot, _c_label = "#c45454", "Canary FAILED — see Actions log"
        elif _overdue:
            _c_dot, _c_label = "#C9A84C", f"Canary overdue ({_c_age_h:.0f}h)"
        elif _c["status"] == "warn":
            _c_dot, _c_label = "#C9A84C", "Canary ✓ (warnings)"
        else:
            _c_dot, _c_label = "rgba(86,149,66,0.7)", "Canary ✓"
        _status_parts.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{_c_dot};'
            f'display:inline-block;flex-shrink:0;"></span>'
            f'<span>{_c_label}</span>'
            f'</span>'
        )
except Exception:
    _status_parts.append(
        '<span style="display:inline-flex;align-items:center;gap:6px;">'
        '<span style="width:6px;height:6px;border-radius:50%;background:#C9A84C;'
        'display:inline-block;flex-shrink:0;"></span>'
        '<span>Canary status unreadable</span>'
        '</span>'
    )

if _status_parts:
    _divider = '<span style="opacity:0.2;margin:0 6px;">|</span>'
    # Sprint 26: flex-wrap:wrap lets the status strip break to a second line
    # on phone instead of overflowing the viewport.
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:flex-end;'
        f'flex-wrap:wrap;padding:4px 28px 2px;gap:6px;font-size:10px;'
        f'color:rgba(255,255,255,0.30);">'
        f'{_divider.join(_status_parts)}'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── Tamarac data loading (Sprint 5: auto-detect newest file) ─────────────
import os

tamarac_parsed = None
_tamarac_path = None

if SPRINT2_AVAILABLE:
    if DETECTOR_AVAILABLE:
        # Sprint 5: auto-detect newest Tamarac export
        _tam_status = get_tamarac_status()
        if _tam_status["found"]:
            _tamarac_path = _tam_status["path"]
    else:
        # Fallback: original hardcoded paths
        for p in ["data/Tamarac_Holdings.xlsx", "Tamarac_Holdings.xlsx"]:
            if os.path.exists(p):
                _tamarac_path = p
                break

    if _tamarac_path:
        @st.cache_data(ttl=300)
        def _load_tamarac(path, _mtime=0):
            return parse_tamarac_excel(path)
        _tam_mtime = os.path.getmtime(_tamarac_path)
        tamarac_parsed = _load_tamarac(_tamarac_path, _mtime=_tam_mtime)

# ── Top-Level Navigation Tabs (Sprint 7: promoted above strategy selector) ─
# Styled as a primary nav bar with gold active indicator
st.markdown("""
<style>
/* ── Top-level tab nav bar styling ─────────────────────────────────────── */
[data-testid="stTabs"] {
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 0px;
}
[data-testid="stTabs"] [role="tablist"] {
    gap: 0px !important;
    background: rgba(0,0,0,0.20);
    border-radius: 0;
    padding: 0 16px;
}
[data-testid="stTabs"] [role="tab"] {
    padding: 18px 24px !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.35) !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    transition: all 0.15s ease;
    white-space: nowrap;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: rgba(255,255,255,0.65) !important;
    background: rgba(255,255,255,0.02) !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: rgba(255,255,255,0.95) !important;
    border-bottom: 3px solid #C9A84C !important;
    background: rgba(201,168,76,0.04) !important;
}
/* Remove Streamlit's default tab underline */
[data-testid="stTabs"] [role="tablist"] {
    border-bottom: none !important;
}

/* ── Sub-tab styling (nested tabs inside tab panels) ──────────────────── */
/* Sub-tabs inherit the uppercase/no-emoji treatment but are more compact */
[data-testid="stTabs"] [data-testid="stTabs"] [role="tablist"] {
    background: rgba(255,255,255,0.02) !important;
    padding: 0 8px !important;
    border-radius: 6px !important;
    margin-bottom: 12px !important;
}
[data-testid="stTabs"] [data-testid="stTabs"] [role="tab"] {
    padding: 10px 16px !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.35) !important;
    border-bottom: 2px solid transparent !important;
}
[data-testid="stTabs"] [data-testid="stTabs"] [role="tab"]:hover {
    color: rgba(255,255,255,0.6) !important;
}
[data-testid="stTabs"] [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: rgba(255,255,255,0.9) !important;
    border-bottom: 2px solid #C9A84C !important;
    background: rgba(201,168,76,0.04) !important;
}
</style>
""", unsafe_allow_html=True)

# ── Strategy selector (single source of truth, above all tabs) ──────────
# One widget, one session-state key — eliminates the sync-across-tabs
# fragility that caused "need to refresh to switch strategy" bugs. The
# selectbox is rendered BEFORE st.tabs() so it appears above the tab row
# rather than below the tab panels.
if "active_strategy" not in st.session_state:
    st.session_state["active_strategy"] = "QDVD"

# Selectbox styling
st.markdown("""
<style>
[data-testid="stSelectbox"] { max-width: 460px; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(201,168,76,0.4) !important;
    border-radius: 8px !important;
    min-height: 58px !important;
    display: flex !important;
    align-items: center !important;
    transition: border-color 0.2s, background 0.2s;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child:hover {
    border-color: #C9A84C !important;
    background: rgba(201,168,76,0.06) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] div[class*="st-at"],
[data-testid="stSelectbox"] [data-baseweb="select"] div[class*="st-ax"] {
    color: rgba(255,255,255,0.92) !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    line-height: 1 !important;
}
[data-testid="stSelectbox"] svg[data-baseweb="icon"] {
    color: #C9A84C !important;
    fill: #C9A84C !important;
    width: 20px !important;
    height: 20px !important;
}
</style>
""", unsafe_allow_html=True)

strat_keys   = list(STRATEGIES.keys())
strat_labels = [f"{STRATEGIES[k]['full_name']}  ({k})" for k in strat_keys]

def _on_strategy_change():
    """Single callback — syncs the one selectbox value to active_strategy."""
    selected_label = st.session_state["strategy_select_main"]
    st.session_state["active_strategy"] = strat_keys[strat_labels.index(selected_label)]

def _on_ticker_search():
    """Sprint 26: free-text ticker search (Finviz-style) — type any symbol,
    hit Enter, land on the (now fast) Stock Detail page. Holdings load
    instantly from Supabase, watchlist names are prewarmed by the prefetch,
    and randoms take ~5s cold via the parallel fetch.

    Stash-and-navigate pattern: the actual switch_page happens in the main
    script body below — st.switch_page can't be called from inside a
    callback because it triggers st.rerun() internally, which is a no-op
    in callbacks. Clearing the widget key here (allowed inside its own
    callback) means back-navigation doesn't instantly re-fire the search.
    """
    raw = (st.session_state.get("ticker_search_main", "") or "").strip().upper()
    st.session_state["ticker_search_main"] = ""  # reset so back-nav works
    if not raw:
        return
    if len(raw) > 6 or not raw.replace(".", "").replace("-", "").isalnum():
        st.session_state["_ticker_nav_error"] = raw
        return
    st.session_state["_pending_ticker_nav"] = raw

# Render selector + ticker search side-by-side above the tab row.
# Column ratio [1, 2, 1] keeps the strategy dropdown comfortably wide and
# anchors the search box on the right. On mobile Streamlit stacks them
# vertically — strategy selector ends up on top, search below.
_sel_col, _spacer_col, _search_col = st.columns([1, 2, 1])
with _sel_col:
    _current_idx = strat_keys.index(st.session_state["active_strategy"])
    st.selectbox(
        "Strategy",
        options=strat_labels,
        index=_current_idx,
        key="strategy_select_main",
        label_visibility="collapsed",
        on_change=_on_strategy_change,
    )
with _search_col:
    # Free-text search — any US-listed symbol, not just holdings. Enter
    # navigates; invalid input toasts and stays put.
    st.text_input(
        "Ticker Search",
        key="ticker_search_main",
        label_visibility="collapsed",
        on_change=_on_ticker_search,
        placeholder="Search ticker — e.g. NVDA",
    )

# Handle pending ticker navigation set by the search callback above.
# This runs in the main script body where st.switch_page is allowed.
_pending = st.session_state.pop("_pending_ticker_nav", None)
if _pending:
    st.session_state["detail_ticker"] = _pending
    st.query_params["ticker"] = _pending
    st.switch_page("pages/2_Stock_Detail.py")
_terr = st.session_state.pop("_ticker_nav_error", None)
if _terr:
    st.toast(f"'{_terr}' doesn't look like a ticker symbol", icon="⚠️")

tab_overview, tab_holdings, tab_warbook, tab_perf, tab_divs, tab_watchlist, tab_macro, tab_markets, tab_alerts = st.tabs([
    "Overview", "Holdings", "Warbook", "Performance", "Dividends", "Watchlist", "Macro", "Markets", "News & Alerts"
])

def _render_strategy_header():
    """Render KPI cards inside a tab. The strategy selector itself lives
    once at the top of the page (above the tab row), so this only emits
    the KPI row."""
    render_kpi_cards(active, kpis)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# Pre-compute active strategy data (used by KPI cards and all tab content)
active = st.session_state["active_strategy"]
strat = STRATEGIES[active]
# Sprint 25: get_strategy_kpis removed (it always returned {"ytd": 0} —
# the Strategy_Returns.xlsx it read no longer exists). KPIs now bootstrap
# as an empty dict and get populated below from Tamarac + monthly_returns.
kpis = {}

# ── Override KPIs with real data when Sprint 2 is available ───────────────
if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
    tam_kpi = get_holdings_for_strategy(tamarac_parsed, active)
    cash_kpi = get_cash_weight(tamarac_parsed, active)

    if not tam_kpi.empty:
        kpis["holdings"] = len(tam_kpi)

        kpi_tickers = tuple(tam_kpi["symbol"].tolist())
        kpi_prices = fetch_batch_prices(kpi_tickers)

        equity_weight = 0.0
        weighted_yield = 0.0
        weighted_daily = 0.0
        for _, row in tam_kpi.iterrows():
            sym = row["symbol"]
            wt = row["weight"]
            mkt = kpi_prices.get(sym, {})
            yld = mkt.get("dividend_yield", 0) or 0
            chg = mkt.get("change_1d_pct", 0) or 0
            weighted_yield += wt * yld
            weighted_daily += wt * chg
            equity_weight += wt

        if equity_weight > 0:
            kpis["div_yield"] = round(weighted_yield / equity_weight, 2)

        cash_decimal = cash_kpi / 100
        total_portfolio_weight = equity_weight + cash_decimal
        if total_portfolio_weight > 0:
            kpis["daily_return"] = round(weighted_daily / total_portfolio_weight, 2)

        kpis["cash_pct"] = round(cash_kpi, 2)

# Override YTD with official Tamarac monthly numbers when available
if MONTHLY_RETURNS_AVAILABLE and active in STRATEGY_YTD:
    kpis["ytd"] = STRATEGY_YTD[active]
    kpis["ytd_as_of"] = AS_OF_DATE

# ── Plotly dark theme (reused across tabs) ─────────────────────────────────
PLOTLY_DARK = dict(
    paper_bgcolor="rgba(255,255,255,0.02)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    margin=dict(l=10, r=10, t=40, b=10),
)

# Shared Plotly config — disables toolbar, hover tooltip, and zoom/pan
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "staticPlot": True,
}

# Hover-enabled config for performance charts (tooltips only, no zoom/pan)
PLOTLY_CONFIG_HOVER = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "staticPlot": False,
}

# Reusable axis style dicts — apply per-chart to avoid conflicts with **PLOTLY_DARK
_XAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))
_YAXIS = dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10))


# ══════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════
with tab_overview:
    _render_strategy_header()

    # ── Shared data for both columns ──────────────────────────────────────
    # Compute hm_df ONCE, before the columns split, so both the left column
    # (heatmap) and the right column (Top Contributors / Detractors) can
    # read it without duplicating work or fetching prices twice.
    tam_ov_hm = None
    hm_df = None
    if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        tam_ov_hm = get_holdings_for_strategy(tamarac_parsed, active)
        if not tam_ov_hm.empty:
            ov_hm_tickers = tuple(tam_ov_hm["symbol"].tolist())
            ov_hm_prices = fetch_batch_prices(ov_hm_tickers)

            hm_rows = []
            for _, row in tam_ov_hm.iterrows():
                sym = row["symbol"]
                mkt = ov_hm_prices.get(sym, {})
                chg = mkt.get("change_1d_pct", 0) or 0
                sector = normalize_sector(mkt.get("sector", ""))
                hm_rows.append({
                    "symbol": sym,
                    "description": row["description"],
                    "weight": row["weight_pct"],
                    "daily_return": round(chg, 2),
                    "sector": sector,
                })
            hm_df = pd.DataFrame(hm_rows).sort_values("weight", ascending=False)
            if len(hm_df) > 0:
                hm_df["contrib"] = (hm_df["weight"] * hm_df["daily_return"] / 100).round(4)

    # Sector-level rollup (Sprint 20): weight totals for heatmap parent
    # labels and contribution totals (sum of weight × daily_return) for the
    # right-column Top Contributing / Detracting Sectors panel. Computed
    # here so both columns can read the same series.
    sector_weights = None
    sector_contribs = None
    if hm_df is not None and len(hm_df) > 0:
        sector_weights = hm_df.groupby("sector")["weight"].sum()
        sector_contribs = hm_df.groupby("sector")["contrib"].sum().sort_values(ascending=False)

    left, right = st.columns([3, 2])

    with left:
        # ── Today's Intraday Performance Chart (Sprint 19) ────────────────
        # Strategy line + 3 index reference lines, normalized to % change
        # from previous close. Strategy line uses the same cash-included
        # weighting as the Daily Return KPI; index lines pull from the same
        # yfinance cache as the ticker bar so endpoint values match exactly.
        # Sized to fit the 3-wide left column: 220px tall, 2-hour x-ticks
        # to prevent label crowding.
        if INTRADAY_CHART_AVAILABLE and SPRINT2_AVAILABLE and tamarac_parsed:
            with st.spinner("Loading intraday performance..."):
                _intra = fetch_intraday_chart_data(active, tamarac_parsed)

            _strat_color = STRAT_COLORS.get(active, "#569542")
            _open_pt, _close_pt = _intra["session"]
            _strat_series = _intra["strategy"]
            _idx_series = _intra["indices"]

            _has_data = bool(_strat_series["x"]) or any(s["x"] for s in _idx_series)

            if not _has_data:
                # Never vanish silently: in the first minutes of a session
                # (or on days Yahoo withholds intraday bars) say so instead
                # of leaving an unexplained gap between the KPIs and the
                # heatmap.
                st.markdown(
                    '<div style="font-size:11px;color:rgba(255,255,255,0.3);'
                    'padding:18px 4px;">Intraday chart populates a few '
                    'minutes after the open — no 5-minute bars available '
                    'yet for today\'s session.</div>',
                    unsafe_allow_html=True,
                )

            if _has_data:
                fig_intra = go.Figure()

                # Helper: build legend label with the most recent % value appended.
                # Matches the Koyfin convention "S&P 500  +0.10%" so users can read
                # the current move without hovering.
                def _last_y(y_list):
                    return y_list[-1] if y_list else None

                # Sprint 20: dropped ^NDX / ^DJI; chart now shows S&P 500
                # and SPYD against the active strategy. SPYD reads as a
                # peer (high-dividend ETF) so it gets a slightly stronger
                # opacity than the broad-market reference.
                _idx_styles = {
                    "^GSPC": {"color": "rgba(255,255,255,0.55)", "width": 1.5},
                    "SPYD":  {"color": "rgba(201,168,76,0.65)", "width": 1.5},
                }

                # Build a list of all traces (indices + strategy) and sort
                # by latest value descending. Plotly's "x unified" hovermode
                # lists traces in the order they were added to the figure,
                # so adding them in highest→lowest order makes the tooltip
                # rows match the visual stacking on screen at the right
                # edge of the chart. Intraday rank flips are rare within a
                # session, so this stays accurate across most hover points.
                _traces_to_add = []
                for s in _idx_series:
                    if not s["x"]:
                        continue
                    _last = _last_y(s["y"])
                    if _last is None:
                        continue
                    style = _idx_styles.get(s["ticker"], {"color": "rgba(255,255,255,0.4)", "width": 1.5})
                    _traces_to_add.append({
                        "sort_key": _last,
                        "label": s["label"],
                        "x": s["x"], "y": s["y"],
                        "color": style["color"], "width": style["width"],
                        "is_strategy": False,
                    })

                if _strat_series["x"]:
                    _strat_label = STRATEGY_NAMES.get(active, active)
                    _last = _last_y(_strat_series["y"])
                    if _last is not None:
                        _traces_to_add.append({
                            "sort_key": _last,
                            "label": _strat_label,
                            "x": _strat_series["x"], "y": _strat_series["y"],
                            "color": _strat_color, "width": 2.5,
                            "is_strategy": True,
                        })

                # Sort highest-to-lowest by latest %. Then add traces in
                # that order. Visually, the strategy line still draws on
                # top of the indices because its line width is greater and
                # its color is more saturated — Plotly's painter order is
                # by trace index, so we accept the trade-off in exchange
                # for a sorted hover tooltip.
                _traces_to_add.sort(key=lambda t: t["sort_key"], reverse=True)

                for t in _traces_to_add:
                    _legend_name = f"{t['label']}  {t['sort_key']:+.2f}%"
                    fig_intra.add_trace(go.Scatter(
                        x=t["x"], y=t["y"],
                        name=_legend_name,
                        mode="lines",
                        line=dict(color=t["color"], width=t["width"]),
                        hovertemplate=f"{t['label']}: %{{y:+.2f}}%<extra></extra>",
                    ))

                # Faint zero line so % moves above/below 0 read clearly
                fig_intra.add_hline(
                    y=0, line_width=1,
                    line_color="rgba(255,255,255,0.15)",
                    line_dash="dot",
                )

                fig_intra.update_layout(
                    **PLOTLY_DARK,
                    xaxis={
                        **_XAXIS,
                        "range": [_open_pt, _close_pt],
                        "fixedrange": True,
                        "tickformat": "%-I %p",
                        "dtick": 7200000,  # 2 hours in milliseconds — prevents label crowding in narrower column
                        "showspikes": True,
                        "spikecolor": "rgba(255,255,255,0.15)",
                        "spikethickness": 1,
                        "spikemode": "across",
                        "spikedash": "solid",
                    },
                    yaxis={
                        **_YAXIS,
                        "ticksuffix": "%",
                        "fixedrange": True,
                        "showspikes": True,
                        "spikecolor": "rgba(255,255,255,0.15)",
                        "spikethickness": 1,
                        "spikemode": "across",
                        "spikedash": "solid",
                    },
                    height=220,
                    hovermode="x unified",
                    dragmode=False,
                )
                # Legend overrides PLOTLY_DARK's default legend dict — applied
                # separately because passing legend= alongside **PLOTLY_DARK
                # raises TypeError (PLOTLY_DARK already contains a 'legend' key).
                fig_intra.update_layout(legend=dict(
                    orientation="h",
                    yanchor="bottom", y=1.02,
                    xanchor="right",  x=1,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11),
                ))
                st.plotly_chart(fig_intra, width="stretch", config=PLOTLY_CONFIG_HOVER)

            # Debug: append ?debug=1 to the URL to see what _fetch_intraday_5m
            # returned for indices vs holdings. Helpful when the strategy line
            # is unexpectedly empty.
            if st.query_params.get("debug") == "1" and "diag" in _intra:
                with st.expander("🔧 Intraday chart diagnostics", expanded=False):
                    st.write("**Indices batch:**", _intra["diag"].get("indices_5m"))
                    st.write("**Holdings batch:**", _intra["diag"].get("holdings_5m"))
                    st.write("**Strategy series length:**", len(_strat_series.get("x", [])))
                    st.write("**Index series lengths:**", {s["ticker"]: len(s["x"]) for s in _idx_series})

        # ── Holdings Daily Return Treemap ────────────────────────────────
        if hm_df is not None and len(hm_df) > 0:
            # Build treemap: grouped by sector, sorted by return within each sector
            # Color scale: red (negative) → dark neutral → green (positive)
            _tm_max = max(abs(hm_df["daily_return"].min()), abs(hm_df["daily_return"].max()), 1.0)

            # Sort within each sector by daily return (best first)
            hm_df = hm_df.sort_values(["sector", "daily_return"], ascending=[True, False])

            strat_label = STRATEGY_NAMES.get(active, active)

            # Build hierarchical ids/labels/parents for sector grouping
            # Structure: root → sector → ticker
            # Use unique ids to avoid conflicts (e.g. ticker name = sector name)
            tm_ids = []
            tm_labels = []
            tm_parents = []
            tm_values = []
            tm_text = []
            tm_colors = []

            # Root node
            tm_ids.append("root")
            tm_labels.append(strat_label)
            tm_parents.append("")
            tm_values.append(0)
            tm_text.append("")
            tm_colors.append(0)

            # Sector parent nodes — label includes weight % so the heatmap
            # banner reads "Financials (14.00%)" etc. Weight is the sum of
            # holding weights within that sector (cash excluded, since cash
            # isn't in hm_df).
            for sector in hm_df["sector"].unique():
                _sw = sector_weights.get(sector, 0) if sector_weights is not None else 0
                tm_ids.append(f"sector_{sector}")
                tm_labels.append(f"{sector} ({_sw:.2f}%)")
                tm_parents.append("root")
                tm_values.append(0)
                tm_text.append("")
                tm_colors.append(0)

            # Ticker leaf nodes under their sector
            for _, row in hm_df.iterrows():
                tm_ids.append(f"tick_{row['symbol']}")
                tm_labels.append(row["symbol"])
                tm_parents.append(f"sector_{row['sector']}")
                tm_values.append(row["weight"])
                tm_text.append(f"{row['daily_return']:+.2f}%")
                tm_colors.append(row["daily_return"])

            fig_tm = go.Figure(go.Treemap(
                ids=tm_ids,
                labels=tm_labels,
                parents=tm_parents,
                values=tm_values,
                text=tm_text,
                branchvalues="remainder",
                texttemplate="<b>%{label}</b><br>%{text}",
                textfont=dict(size=13, family="DM Sans"),
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "Weight: %{value:.2f}%<br>"
                    "Return: %{text}<extra></extra>"
                ),
                marker=dict(
                    colors=tm_colors,
                    colorscale=[
                        [0.0, "#c45454"],           # most negative → red
                        [0.35, "#8a3a3a"],          # mild negative
                        [0.5, "rgba(40,40,50,1)"],  # zero → dark neutral
                        [0.65, "#3a6a30"],          # mild positive
                        [1.0, "#569542"],           # most positive → green
                    ],
                    cmid=0,
                    cmin=-_tm_max,
                    cmax=_tm_max,
                    line=dict(width=2, color="rgba(12,17,23,0.8)"),
                    showscale=False,
                ),
                tiling=dict(pad=3),
                pathbar=dict(visible=False),
            ))

            # Start at root level so sectors show as groups
            fig_tm.update_traces(level="root")

            _tm_layout = {**PLOTLY_DARK}
            _tm_layout["margin"] = dict(l=0, r=0, t=36, b=0)
            fig_tm.update_layout(
                **_tm_layout,
                title=f"Today's Returns — {strat_label}",
                height=max(550, len(hm_df) * 18 + 100),
            )
            st.plotly_chart(fig_tm, width="stretch", config=PLOTLY_CONFIG)
        # If hm_df is unavailable (Tamarac data missing), the left column
        # simply ends with the intraday chart — no fallback chart rendered.
        # Better to show nothing than to render placeholder data.

    with right:
        # ── Today's Movers — Top Contributors & Detractors ───────────────
        # Reads hm_df (computed above the column split) so we don't refetch
        # prices. Contributors and detractors stay side-by-side as the user
        # had them — the right column is wide enough at 2/5 of page width
        # for the compact ticker-percent-bp layout.
        if hm_df is not None and len(hm_df) > 0:
            movers_sorted = hm_df.sort_values("contrib", ascending=False)
            top3 = movers_sorted.head(3)
            bot3 = movers_sorted.tail(3).iloc[::-1]

            col_top, col_bot = st.columns(2)
            with col_top:
                st.markdown(
                    "<div style='font-size:10px;color:rgba(86,149,66,0.8);text-transform:uppercase;"
                    "letter-spacing:0.06em;margin-bottom:6px;font-weight:700;'>▲ Top Contributors</div>",
                    unsafe_allow_html=True,
                )
                for _, m in top3.iterrows():
                    _c_color = "#569542" if m["daily_return"] >= 0 else "#c45454"
                    _c_bp = m["contrib"] * 100
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.03);gap:8px;'>"
                        f"<div style='flex:0 0 42px;font-size:12px;font-weight:600;color:#C9A84C;'>{m['symbol']}</div>"
                        f"<div style='font-size:12px;color:{_c_color};font-weight:600;'>{m['daily_return']:+.2f}%</div>"
                        f"<div style='font-size:11px;color:rgba(255,255,255,0.3);'>{_c_bp:+.1f}bp</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            with col_bot:
                st.markdown(
                    "<div style='font-size:10px;color:rgba(196,84,84,0.8);text-transform:uppercase;"
                    "letter-spacing:0.06em;margin-bottom:6px;font-weight:700;'>▼ Top Detractors</div>",
                    unsafe_allow_html=True,
                )
                for _, m in bot3.iterrows():
                    _d_color = "#569542" if m["daily_return"] >= 0 else "#c45454"
                    _d_bp = m["contrib"] * 100
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.03);gap:8px;'>"
                        f"<div style='flex:0 0 42px;font-size:12px;font-weight:600;color:#C9A84C;'>{m['symbol']}</div>"
                        f"<div style='font-size:12px;color:{_d_color};font-weight:600;'>{m['daily_return']:+.2f}%</div>"
                        f"<div style='font-size:11px;color:rgba(255,255,255,0.3);'>{_d_bp:+.1f}bp</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # ── Sector Contributors & Detractors (Sprint 20) ──────────────────
        # Mirrors the ticker-level Top Contributors / Top Detractors layout
        # above, but rolled up to the sector level. Reuses sector_contribs
        # (sum of weight × daily_return per sector) computed above the
        # column split. Sector weights now live in the heatmap parent labels
        # so we no longer render the standalone weight bars here.
        if sector_contribs is not None and len(sector_contribs) > 0:
            # Split by sign: positive contributions on the left, negative on
            # the right. Sectors with exactly zero contribution are dropped
            # (they neither contributed nor detracted). Each list is sorted
            # by magnitude — best first on the left, worst first on the right.
            top_sect = sector_contribs[sector_contribs > 0]
            bot_sect = sector_contribs[sector_contribs < 0].sort_values(ascending=True)

            col_st, col_sb = st.columns(2)
            with col_st:
                st.markdown(
                    "<div style='font-size:10px;color:rgba(86,149,66,0.8);text-transform:uppercase;"
                    "letter-spacing:0.06em;margin-bottom:6px;font-weight:700;'>▲ Top Contributing Sectors</div>",
                    unsafe_allow_html=True,
                )
                for sect_name, sect_contrib in top_sect.items():
                    _sc_color = "#569542" if sect_contrib >= 0 else "#c45454"
                    _sc_bp = sect_contrib * 100
                    _sc_dot = SECTOR_COLORS.get(sect_name, "#888")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.03);gap:8px;'>"
                        f"<div style='width:8px;height:8px;border-radius:2px;background:{_sc_dot};flex-shrink:0;'></div>"
                        f"<div style='flex:1;font-size:12px;font-weight:600;color:rgba(255,255,255,0.8);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{sect_name}</div>"
                        f"<div style='font-size:11px;color:{_sc_color};font-weight:600;white-space:nowrap;'>{_sc_bp:+.1f}bp</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                if len(top_sect) == 0:
                    st.markdown(
                        "<div style='padding:5px 0;font-size:12px;color:rgba(255,255,255,0.3);font-style:italic;'>No contributing sectors today.</div>",
                        unsafe_allow_html=True,
                    )

            with col_sb:
                st.markdown(
                    "<div style='font-size:10px;color:rgba(196,84,84,0.8);text-transform:uppercase;"
                    "letter-spacing:0.06em;margin-bottom:6px;font-weight:700;'>▼ Top Detracting Sectors</div>",
                    unsafe_allow_html=True,
                )
                for sect_name, sect_contrib in bot_sect.items():
                    _sd_color = "#569542" if sect_contrib >= 0 else "#c45454"
                    _sd_bp = sect_contrib * 100
                    _sd_dot = SECTOR_COLORS.get(sect_name, "#888")
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.03);gap:8px;'>"
                        f"<div style='width:8px;height:8px;border-radius:2px;background:{_sd_dot};flex-shrink:0;'></div>"
                        f"<div style='flex:1;font-size:12px;font-weight:600;color:rgba(255,255,255,0.8);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{sect_name}</div>"
                        f"<div style='font-size:11px;color:{_sd_color};font-weight:600;white-space:nowrap;'>{_sd_bp:+.1f}bp</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                if len(bot_sect) == 0:
                    st.markdown(
                        "<div style='padding:5px 0;font-size:12px;color:rgba(255,255,255,0.3);font-style:italic;'>No detracting sectors today.</div>",
                        unsafe_allow_html=True,
                    )

        # Top 10 Holdings — compact display with headers
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:10px;'>Top Holdings</div>", unsafe_allow_html=True)

        # Header row
        st.markdown(
            "<div style='display:flex;align-items:center;padding:4px 0 6px 0;border-bottom:1px solid rgba(255,255,255,0.10);margin-bottom:2px;'>"
            "<div style='flex:0 0 50px;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;'>Ticker</div>"
            "<div style='flex:1;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;'></div>"
            "<div style='flex:0 0 46px;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;text-align:right;'>Wt%</div>"
            "<div style='flex:0 0 65px;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;text-align:right;'>Price</div>"
            "<div style='flex:0 0 52px;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;text-align:right;'>1D Chg</div>"
            "<div style='flex:0 0 52px;font-size:10px;font-weight:600;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;text-align:right;'>Yield</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            tam_top10 = get_holdings_for_strategy(tamarac_parsed, active)
            if not tam_top10.empty:
                top10_tickers = tuple(tam_top10["symbol"].head(10).tolist())
                top10_prices = fetch_batch_prices(top10_tickers)
                for _, h in tam_top10.head(10).iterrows():
                    sym = h["symbol"]
                    mkt = top10_prices.get(sym, {})
                    price = mkt.get("price", 0)
                    chg = mkt.get("change_1d_pct", 0) or 0
                    yld = mkt.get("dividend_yield", 0) or 0
                    chg_color = "#569542" if chg >= 0 else "#c45454"
                    yld_str = f"{yld:.2f}%" if yld > 0 else "—"
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);'>"
                        f"<div style='flex:0 0 50px;font-size:12px;font-weight:600;color:#C9A84C;'>{sym}</div>"
                        f"<div style='flex:1;font-size:11px;color:rgba(255,255,255,0.45);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{h['description']}</div>"
                        f"<div style='flex:0 0 46px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h['weight_pct']:.2f}%</div>"
                        f"<div style='flex:0 0 65px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>${price:.2f}</div>"
                        f"<div style='flex:0 0 52px;font-size:12px;color:{chg_color};text-align:right;font-weight:500;'>{chg:+.2f}%</div>"
                        f"<div style='flex:0 0 52px;font-size:12px;color:#C9A84C;text-align:right;'>{yld_str}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        # If Tamarac data unavailable, the Top Holdings table renders with
        # only the header row — better than placeholder data.


# ══════════════════════════════════════════════════════════════════════════
# HOLDINGS — Sprint 2 upgrade: real Tamarac + live yfinance
# ══════════════════════════════════════════════════════════════════════════
with tab_holdings:
    _render_strategy_header()

    # ── Sub-tabs: Holdings Detail | Price Charts ──────────────────────────
    sub_detail, sub_charts = st.tabs(["Holdings Detail", "Price Charts"])

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 1: HOLDINGS DETAIL (existing)
    # ═══════════════════════════════════════════════════════════════════════
    with sub_detail:

        # ── Sprint 2: Tamarac + yfinance ─────────────────────────────────
        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            tam_df = get_holdings_for_strategy(tamarac_parsed, active)
            cash_wt = get_cash_weight(tamarac_parsed, active)

            if not tam_df.empty:
                tickers = tuple(tam_df["symbol"].tolist())
                with st.spinner("Fetching live prices..."):
                    price_data = fetch_batch_prices(tickers)

                # Fetch Notion proprietary metrics (Sprint 5)
                notion_data = {}
                if NOTION_METRICS_AVAILABLE:
                    try:
                        notion_data = fetch_notion_metrics()
                    except Exception:
                        notion_data = {}

                # Build merged table
                rows = []
                for _, h in tam_df.iterrows():
                    sym = h["symbol"]
                    mkt = price_data.get(sym, {})
                    chg_val = mkt.get("change_1d_pct", 0) or 0
                    # Yield on Cost & Unit Cost come from Tamarac_Holdings_Manual.xlsx
                    # (the merged fallback data). When absent, show em-dash.
                    yoc_raw = h.get("yield_at_cost", 0) or 0
                    yoc_pct = (float(yoc_raw) * 100 if 0 < float(yoc_raw) < 1
                               else float(yoc_raw)) if yoc_raw else None
                    unit_cost_val = h.get("unit_cost", 0) or 0
                    unit_cost = float(unit_cost_val) if unit_cost_val else None

                    # Notion proprietary metrics
                    nm = notion_data.get(sym.upper(), {})

                    rows.append({
                        "Company": h["description"],
                        "Symbol": sym,
                        "Sector": normalize_sector(mkt.get("sector", "")),
                        "Weight %": round(h["weight_pct"], 2),
                        "1D Chg %": chg_val,
                        "Price": mkt.get("price", 0),
                        "Yield on Cost %": round(yoc_pct, 2) if yoc_pct is not None else None,
                        "Div Yield %": mkt.get("dividend_yield", 0),
                        "MCP Target": nm.get("mcp_target") if nm.get("mcp_target") is not None else "—",
                        "P/E": round(mkt.get("pe_ratio", 0), 1) if mkt.get("pe_ratio") else "—",
                        "Unit Cost": round(unit_cost, 2) if unit_cost is not None else None,
                        "% From 52W Hi": round(
                            ((mkt.get("price", 0) - mkt.get("52w_high", 0)) / mkt.get("52w_high", 1)) * 100, 1
                        ) if mkt.get("52w_high") else 0,
                    })
                display_df = pd.DataFrame(rows)
                if not display_df.empty and "Company" in display_df.columns:
                    display_df = display_df.sort_values("Company", ascending=True).reset_index(drop=True)


                # Sector filter
                sectors = ["All"] + sorted(display_df["Sector"].dropna().unique().tolist())
                sector_filter = st.selectbox("Sector", sectors, key="s2_sector", label_visibility="collapsed")

                filtered = display_df.copy()
                if sector_filter != "All":
                    filtered = filtered[filtered["Sector"] == sector_filter]

                st.markdown(f"**{len(filtered)}** positions in **{STRATEGY_NAMES.get(active, active)}**")

                # Color-code the 1D change column
                def _color_1d(val):
                    try:
                        v = float(val)
                        color = "#569542" if v >= 0 else "#c45454"
                        return f"color: {color}; font-weight: 500"
                    except (ValueError, TypeError):
                        return ""

                styled = filtered.style.map(_color_1d, subset=["1D Chg %"]).map(
                    _color_1d, subset=["% From 52W Hi"]
                ).format({
                    "Weight %": "{:.2f}",
                    "Price": "${:.2f}",
                    "1D Chg %": "{:+.2f}%",
                    "Yield on Cost %": lambda v: "—" if v is None or pd.isna(v) else f"{v:.2f}%",
                    "Div Yield %": "{:.2f}%",
                    "MCP Target": lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else v,
                    "Unit Cost": lambda v: "—" if v is None or pd.isna(v) else f"${v:.2f}",
                    "% From 52W Hi": "{:+.2f}%",
                })

                # Row-selection enabled — click a row to navigate to stock detail
                # Height: generous calculation to prevent internal scrollbar on mobile
                _df_height = min(80 + len(filtered) * 40, 2000)
                event = st.dataframe(
                    styled, width="stretch", hide_index=True,
                    height=_df_height,
                    selection_mode="single-row",
                    on_select="rerun",
                    key="holdings_table",
                    column_config={
                        "Company": st.column_config.TextColumn("Company", width="medium"),
                        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                        "Sector": st.column_config.TextColumn("Sector", width="medium"),
                        "Weight %": st.column_config.NumberColumn("Wt %", format="%.2f%%"),
                        "1D Chg %": st.column_config.NumberColumn("1D %", format="%+.2f%%"),
                        "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                        "Yield on Cost %": st.column_config.NumberColumn("Yield on Cost", format="%.2f%%"),
                        "Div Yield %": st.column_config.NumberColumn("Curr Yield", format="%.2f%%"),
                        "MCP Target": st.column_config.TextColumn("MCP Target", width="small"),
                        "P/E": st.column_config.NumberColumn("P/E", format="%.2f"),
                        "Unit Cost": st.column_config.NumberColumn("Unit Cost", format="$%.2f"),
                        "% From 52W Hi": st.column_config.NumberColumn("% From Hi", format="%+.2f%%"),
                    },
                )

                # Navigate to stock detail when a row is selected
                if event and event.selection and event.selection.rows:
                    selected_idx = event.selection.rows[0]
                    selected_ticker = filtered.iloc[selected_idx]["Symbol"]
                    st.session_state["detail_ticker"] = selected_ticker
                    st.query_params["ticker"] = selected_ticker
                    st.switch_page("pages/2_Stock_Detail.py")

                # Sector breakdown — compact table + pie chart
                if len(filtered) > 0 and "Sector" in filtered.columns:
                    st.divider()
                    st.markdown("**Sector Breakdown**")
                    sect_agg = filtered.groupby("Sector").agg(
                        Holdings=("Symbol", "count"),
                        Total_Weight=("Weight %", "sum"),
                        Avg_Yield=("Div Yield %", "mean"),
                    ).round(2).sort_values("Total_Weight", ascending=False)

                    col_tbl, col_pie = st.columns([3, 2])
                    with col_tbl:
                        st.dataframe(sect_agg, width="stretch", height=(80 + len(sect_agg) * 40), column_config={
                            "Holdings": st.column_config.NumberColumn("#", width="small"),
                            "Total_Weight": st.column_config.NumberColumn("Wt %", format="%.2f%%", width="small"),
                            "Avg_Yield": st.column_config.NumberColumn("Avg Yld %", format="%.2f%%", width="small"),
                        })
                    with col_pie:
                        pie_colors = [SECTOR_COLORS.get(s, "#888") for s in sect_agg.index]
                        _n_sectors = len(sect_agg)
                        _pie_labels = sect_agg.index.tolist()
                        _pie_vals = sect_agg["Total_Weight"].tolist()

                        # Pull out smaller slices slightly for visual separation
                        _total = sum(_pie_vals) if sum(_pie_vals) > 0 else 1
                        _pull = [0.03 if v / _total < 0.05 else 0 for v in _pie_vals]

                        fig_pie = go.Figure(go.Pie(
                            labels=_pie_labels,
                            values=_pie_vals,
                            marker=dict(
                                colors=pie_colors,
                                line=dict(color="rgba(12,17,23,0.8)", width=1.5),
                            ),
                            hole=0.5,
                            pull=_pull,
                            textinfo="label+percent",
                            textposition="outside",
                            textfont=dict(size=11, color="rgba(255,255,255,0.7)"),
                            outsidetextfont=dict(size=10, color="rgba(255,255,255,0.6)"),
                            hovertemplate="<b>%{label}</b><br>%{value:.2f}% of portfolio<extra></extra>",
                            sort=False,
                            direction="clockwise",
                            rotation=90,
                        ))
                        _pie_layout = {**PLOTLY_DARK}
                        _pie_layout["margin"] = dict(l=60, r=60, t=30, b=30)
                        fig_pie.update_layout(
                            **_pie_layout,
                            height=max(320, _n_sectors * 28 + 120),
                            showlegend=False,
                            uniformtext_minsize=9,
                            uniformtext_mode="hide",
                        )
                        st.plotly_chart(fig_pie, width="stretch", config=PLOTLY_CONFIG)

                # ── Finviz Analyst Enrichment (Sprint 7) ─────────────────
                if FINVIZ_AVAILABLE:
                    st.divider()
                    render_finviz_panel(tam_df, price_data, notion_data=notion_data)

                st.caption(f"Tamarac export + yfinance live prices • {datetime.now().strftime('%I:%M %p')}")

            else:
                st.info("No holdings in Tamarac file for this strategy.")

        # If Tamarac data is unavailable, show a clean empty state. Better
        # than rendering placeholder holdings.
        else:
            st.info("Tamarac data unavailable. Drop the latest Tamarac Holdings export in the data/ folder.")

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 2: PRICE CHARTS GRID — lazy-loaded (Sprint 17)
    # ───────────────────────────────────────────────────────────────────────
    # Why gated: this grid runs on every top-level interaction (Streamlit's
    # st.tabs() renders all tabs every rerun), burning 20-35s on yfinance
    # fetches + Plotly rendering for 18 charts. Since users rarely need all
    # charts simultaneously, we gate behind an explicit "Load charts" click.
    # The flag is keyed to active strategy — swapping strategies resets it.
    # ═══════════════════════════════════════════════════════════════════════
    with sub_charts:
        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            _charts_tam = get_holdings_for_strategy(tamarac_parsed, active)
            if not _charts_tam.empty:
                # ── Lazy-load gate ──────────────────────────────────────────
                # Only render the heavy chart grid if user has explicitly
                # loaded charts for the CURRENT strategy this session.
                _loaded_key = "hc_loaded_for"
                _charts_active = st.session_state.get(_loaded_key) == active

                if not _charts_active:
                    st.markdown(
                        f"<div style='padding:40px 20px;text-align:center;"
                        f"background:rgba(255,255,255,0.02);border-radius:10px;"
                        f"border:1px solid rgba(255,255,255,0.05);margin:12px 0;'>"
                        f"<div style='font-size:14px;color:rgba(255,255,255,0.7);"
                        f"margin-bottom:8px;font-weight:600;'>"
                        f"Price charts for {len(_charts_tam)} holdings</div>"
                        f"<div style='font-size:12px;color:rgba(255,255,255,0.4);"
                        f"margin-bottom:18px;'>"
                        f"Loading charts takes ~20-30 seconds on first view per strategy."
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    _bcol1, _bcol2, _bcol3 = st.columns([1, 1, 1])
                    with _bcol2:
                        if st.button(
                            "Load charts",
                            key=f"hc_load_{active}",
                            type="primary",
                            width="stretch",
                        ):
                            st.session_state[_loaded_key] = active
                            st.rerun()
                else:
                    # ── Charts loaded — render normally ─────────────────────
                    _charts_tam = _charts_tam.sort_values("description", ascending=True)
                    _chart_tickers = _charts_tam["symbol"].tolist()
                    _chart_names = dict(zip(_charts_tam["symbol"], _charts_tam["description"]))

                    # Optional: small "unload" button so user can free up rerun speed.
                    # [3, 1] + no stretch keeps "Hide charts" on one line across
                    # desktop and mobile widths.
                    _hdr_left, _hdr_right = st.columns([3, 1])
                    with _hdr_right:
                        if st.button("Hide charts", key=f"hc_hide_{active}",
                                     type="secondary"):
                            st.session_state.pop(_loaded_key, None)
                            st.rerun()

                    # Period selector — matches Stock Detail page
                    _period_map = {"1M": 21, "3M": 63, "YTD": None, "1Y": 252, "2Y": 504, "3Y": 756, "5Y": 1260, "10Y": 2520, "Max": 0}
                    if "hc_period" not in st.session_state:
                        st.session_state["hc_period"] = "1Y"

                    _pcols = st.columns(len(_period_map))
                    for _pi, (_plabel, _) in enumerate(_period_map.items()):
                        with _pcols[_pi]:
                            if st.button(_plabel, key=f"hc_p_{_plabel}", width="stretch",
                                         type="primary" if st.session_state["hc_period"] == _plabel else "secondary"):
                                st.session_state["hc_period"] = _plabel
                                st.rerun()

                    # Batch download max history — slice client-side per period
                    @st.cache_data(ttl=900, show_spinner=False)
                    def _fetch_chart_batch(tickers_tuple, _v=2):
                        import yfinance as yf
                        try:
                            return yf.download(
                                " ".join(tickers_tuple),
                                period="max",
                                interval="1d",
                                group_by="ticker",
                                progress=False,
                                threads=True,
                            )
                        except Exception:
                            return None

                    with st.spinner(f"Loading {len(_chart_tickers)} charts..."):
                        _batch_data = _fetch_chart_batch(tuple(_chart_tickers))

                    if _batch_data is not None and not _batch_data.empty:
                        _sel_label = st.session_state["hc_period"]
                        _sel_days = _period_map[_sel_label]

                        # Render 4-column grid of mini charts
                        _ncols = 4
                        _rows_of_tickers = [_chart_tickers[i:i + _ncols] for i in range(0, len(_chart_tickers), _ncols)]

                        for _row_tickers in _rows_of_tickers:
                            _cols = st.columns(_ncols)
                            for _ci, _tk in enumerate(_row_tickers):
                                with _cols[_ci]:
                                    try:
                                        if len(_chart_tickers) == 1:
                                            _tk_full = _batch_data
                                        else:
                                            _tk_full = _batch_data[_tk] if _tk in _batch_data.columns.get_level_values(0) else None

                                        if _tk_full is None or _tk_full.empty or _tk_full.dropna(subset=["Close"]).empty:
                                            st.caption(f"{_tk} — no data")
                                            continue

                                        _tk_full = _tk_full.dropna(subset=["Close"]).copy()

                                        # Compute MAs on full history before slicing
                                        _tk_full["MA50"] = _tk_full["Close"].rolling(50).mean()
                                        _tk_full["MA200"] = _tk_full["Close"].rolling(200).mean()

                                        # Slice to selected period
                                        if _sel_label == "YTD":
                                            _year_start = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
                                            _tk_df = _tk_full[_tk_full.index >= _year_start]
                                        elif _sel_label == "Max" or _sel_days == 0:
                                            _tk_df = _tk_full
                                        else:
                                            _tk_df = _tk_full.tail(_sel_days)

                                        if _tk_df.empty:
                                            st.caption(f"{_tk} — no data")
                                            continue

                                        _close = _tk_df["Close"]
                                        _first = float(_close.iloc[0])
                                        _last = float(_close.iloc[-1])
                                        _chg_pct = ((_last - _first) / _first * 100) if _first > 0 else 0
                                        _chg_color = "#569542" if _chg_pct >= 0 else "#c45454"

                                        # Compact header: TICKER  +X.X%  $Price
                                        st.markdown(
                                            f"<div style='display:flex;align-items:baseline;gap:8px;padding:2px 0 0;'>"
                                            f"<span style='font-size:13px;font-weight:700;color:#C9A84C;'>{_tk}</span>"
                                            f"<span style='font-size:12px;font-weight:600;color:{_chg_color};'>{_chg_pct:+.2f}%</span>"
                                            f"<span style='font-size:11px;color:rgba(255,255,255,0.4);'>${_last:,.2f}</span>"
                                            f"</div>"
                                            f"<div style='font-size:10px;color:rgba(255,255,255,0.3);margin-bottom:2px;'>"
                                            f"{_chart_names.get(_tk, '')[:30]}</div>",
                                            unsafe_allow_html=True,
                                        )

                                        # Mini price chart with MAs
                                        _fig = go.Figure()

                                        # For Max period, fill from zero; otherwise fill from period low
                                        _use_zero_base = (_sel_label == "Max")
                                        _all_vals = _close.dropna()
                                        _y_min = 0 if _use_zero_base else float(_all_vals.min())
                                        _y_max = float(_all_vals.max())

                                        if _use_zero_base:
                                            _fig.add_trace(go.Scatter(
                                                x=_tk_df.index, y=_close,
                                                mode="lines", name="Price",
                                                line=dict(color=_chg_color, width=1.5),
                                                fill="tozeroy",
                                                fillcolor=("rgba(86,149,66,0.06)" if _chg_pct >= 0 else "rgba(196,84,84,0.06)"),
                                                hovertemplate="%{x|%b %d}<br>$%{y:.2f}<extra></extra>",
                                            ))
                                        else:
                                            _price_range = _y_max - _y_min if _y_max > _y_min else 1
                                            _y_floor = max(0, _y_min - _price_range * 0.05)

                                            _fig.add_trace(go.Scatter(
                                                x=_tk_df.index,
                                                y=[_y_floor] * len(_tk_df),
                                                mode="lines", name="_base",
                                                line=dict(width=0), showlegend=False,
                                                hoverinfo="skip",
                                            ))
                                            _fig.add_trace(go.Scatter(
                                                x=_tk_df.index, y=_close,
                                                mode="lines", name="Price",
                                                line=dict(color=_chg_color, width=1.5),
                                                fill="tonexty",
                                                fillcolor=("rgba(86,149,66,0.06)" if _chg_pct >= 0 else "rgba(196,84,84,0.06)"),
                                                hovertemplate="%{x|%b %d}<br>$%{y:.2f}<extra></extra>",
                                            ))

                                        # 50-day MA
                                        if not _tk_df["MA50"].isna().all():
                                            _fig.add_trace(go.Scatter(
                                                x=_tk_df.index, y=_tk_df["MA50"],
                                                mode="lines", name="50 MA",
                                                line=dict(color="#C9A84C", width=1, dash="dot"),
                                                hoverinfo="skip",
                                            ))

                                        # 200-day MA
                                        if not _tk_df["MA200"].isna().all():
                                            _fig.add_trace(go.Scatter(
                                                x=_tk_df.index, y=_tk_df["MA200"],
                                                mode="lines", name="200 MA",
                                                line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dash"),
                                                hoverinfo="skip",
                                            ))

                                        _fig_layout = {**PLOTLY_DARK}
                                        _fig_layout["margin"] = dict(l=0, r=42, t=0, b=20)
                                        _fig.update_layout(
                                            **_fig_layout,
                                            height=160,
                                            showlegend=False,
                                            hovermode="x unified",
                                            dragmode=False,
                                        )
                                        _fig.update_xaxes(
                                            visible=True,
                                            fixedrange=True,
                                            showgrid=False,
                                            showline=False,
                                            tickfont=dict(size=9, color="rgba(255,255,255,0.25)"),
                                            nticks=4,
                                            tickformat=(
                                                "%b %d" if _sel_label in ("1M", "3M") else
                                                "%b '%y" if _sel_label in ("YTD", "1Y") else
                                                "%Y" if _sel_label in ("2Y", "3Y", "5Y", "10Y", "Max") else
                                                "%b %d"
                                            ),
                                        )
                                        _fig.update_yaxes(
                                            visible=True,
                                            fixedrange=True,
                                            side="right",
                                            showgrid=True,
                                            gridcolor="rgba(255,255,255,0.04)",
                                            showline=False,
                                            tickfont=dict(size=9, color="rgba(255,255,255,0.25)"),
                                            tickprefix="$",
                                            nticks=4,
                                        )
                                        st.plotly_chart(
                                            _fig, width="stretch",
                                            config=PLOTLY_CONFIG_HOVER,
                                            key=f"hc_{_tk}_{st.session_state['hc_period']}",
                                        )
                                    except Exception:
                                        st.caption(f"{_tk} — chart error")

                        st.caption(f"{len(_chart_tickers)} holdings · {st.session_state['hc_period']} · yfinance · {datetime.now().strftime('%I:%M %p')}")
                    else:
                        st.warning("Could not load chart data. Try refreshing.")
            else:
                st.info("No holdings in Tamarac file for this strategy.")
        else:
            st.info("Price charts require Tamarac holdings data.")


# ══════════════════════════════════════════════════════════════════════════
# WARBOOK — Sprint 23B: Strategy Overview + Attribution sub-tabs
# Replaces the printed warbook spreadsheets (DAC, OR, QDVD, SMID).
# DCP excluded — MCP doesn't maintain a warbook for that strategy.
# ══════════════════════════════════════════════════════════════════════════
with tab_warbook:
    _render_strategy_header()

    if WARBOOK_AVAILABLE and SPRINT2_AVAILABLE and tamarac_parsed:
        render_warbook_tab(tamarac_parsed, active, strat)
    elif not WARBOOK_AVAILABLE:
        st.error(
            "Warbook module not available. Ensure `data/warbook_tab.py` and "
            "`data/warbook_metrics.py` are present."
        )
    else:
        st.info("Warbook requires Tamarac holdings data.")


# ══════════════════════════════════════════════════════════════════════════
# DIVIDENDS — Sprint 4: full dividend intelligence with sub-tabs
# ══════════════════════════════════════════════════════════════════════════
with tab_divs:
    _render_strategy_header()

    if DIV_TAB_AVAILABLE and SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        render_dividends_tab(tamarac_parsed, active, strat, kpis)

    elif SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        # Fallback: Sprint 2 style (dividends_tab.py not available)
        tam_df = get_holdings_for_strategy(tamarac_parsed, active)
        if not tam_df.empty:
            tickers = tuple(tam_df["symbol"].tolist())
            with st.spinner("Fetching dividend data..."):
                price_data = fetch_batch_prices(tickers)
                div_data = get_batch_dividend_details(tickers)
            wtd_yield = compute_weighted_yield(tam_df, div_data)
            d1, d2, d3 = st.columns(3)
            with d1: st.metric("Wtd Avg Yield", f"{wtd_yield}%")
            with d2: st.metric("Holdings", str(len(tam_df)))
            with d3: st.metric("Strategy", STRATEGY_NAMES.get(active, active))

            if DIV_CALENDAR_AVAILABLE:
                st.divider()
                st.markdown("**Estimated Dividend Increase Announcements**")
                render_dividend_calendar()
        else:
            st.info("No holdings for this strategy in Tamarac file.")

    else:
        # Tamarac data unavailable. Show empty state for KPIs but keep the
        # dividend calendar — that's sourced independently from a real Excel
        # file, not Sprint 1 placeholder data.
        st.info("Tamarac data unavailable. Drop the latest Tamarac Holdings export in the data/ folder.")

        if DIV_CALENDAR_AVAILABLE:
            st.markdown("**Estimated Dividend Increase Announcements**")
            render_dividend_calendar()


# ══════════════════════════════════════════════════════════════════════════
# WATCHLIST
# ══════════════════════════════════════════════════════════════════════════
with tab_watchlist:
    if WATCHLIST_AVAILABLE:
        render_watchlist_tab()
    else:
        st.info("Watchlist module not found. Ensure `data/watchlist.py` and `data/watchlist_tab.py` are in the data folder.")


# ══════════════════════════════════════════════════════════════════════════
# MACRO
# ══════════════════════════════════════════════════════════════════════════
with tab_macro:
    if MACRO_AVAILABLE:
        # Pass QDVD yield so the context box can show it
        qdvd_yield = None
        if SPRINT2_AVAILABLE and tamarac_parsed and "QDVD" in tamarac_parsed:
            from data.dividends import compute_weighted_yield as _cwy
            _qdvd_tam = get_holdings_for_strategy(tamarac_parsed, "QDVD")
            if not _qdvd_tam.empty:
                _qdvd_tickers = tuple(_qdvd_tam["symbol"].tolist())
                _qdvd_div = get_batch_dividend_details(_qdvd_tickers)
                qdvd_yield = _cwy(_qdvd_tam, _qdvd_div)
        render_macro_tab(qdvd_yield=qdvd_yield)
    else:
        st.info("Macro module not found. Ensure `data/macro_tab.py` is in the data folder.")


# ══════════════════════════════════════════════════════════════════════════
# MARKETS
# ══════════════════════════════════════════════════════════════════════════
with tab_markets:
    if MARKETS_AVAILABLE:
        render_markets_tab()
    else:
        st.info("Markets module not found. Ensure `data/markets_tab.py` is in the data folder.")


# ══════════════════════════════════════════════════════════════════════════
# ALERTS
# ══════════════════════════════════════════════════════════════════════════
with tab_alerts:
    if ALERTS_AVAILABLE and SPRINT2_AVAILABLE and tamarac_parsed:
        render_alerts_tab(tamarac_parsed, active)
    elif not ALERTS_AVAILABLE:
        st.info("Alerts module not found. Ensure `data/alerts_tab.py` is in the data folder.")
    else:
        st.info("Alerts require Tamarac holdings data. Upload a Tamarac export to enable alerts.")


# ══════════════════════════════════════════════════════════════════════════
# PERFORMANCE — Composite Returns (Sprint 10)
# ──────────────────────────────────────────────────────────────────────────
# Rendered LAST in script execution order (even though it appears 3rd in
# the visual tab row) so that if Performance is slow — e.g. on a cold
# return from idle where disk-cache I/O dominates — no other tab blocks
# waiting for it. Streamlit's st.tabs() runs every tab body top-to-bottom
# on each rerun regardless of which is visible; ordering Performance last
# means Dividends/Watchlist/Macro/Markets/Alerts all render before it.
# ══════════════════════════════════════════════════════════════════════════
with tab_perf:
    _render_strategy_header()
    if COMPOSITE_AVAILABLE:
        render_performance_tab(active)
    else:
        st.info("Performance module not available. Ensure data/composite_returns.py and data/performance_tab.py are present.")


# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='display:flex;gap:12px;justify-content:center;padding:16px 28px;margin-top:20px;"
    "border-top:1px solid rgba(255,255,255,0.04);font-size:11px;color:rgba(255,255,255,0.2);'>"
    "<span>© 2026 Martin Capital Partners LLC</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Data: yfinance · FRED · Notion · Finviz</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Internal use only</span>"
    "</div>",
    unsafe_allow_html=True
)
# Documentation link — centered below footer
# Sprint 26: wrapped in 3 columns so the button stays ~33% width on
# desktop and stacks to full-width on phone (after mobile_css collapses
# columns to 100%) — avoids the previous look of a full-viewport CTA.
st.markdown("<div style='margin-top:-16px'></div>", unsafe_allow_html=True)
_doc_l, _doc_c, _doc_r = st.columns([1, 2, 1])
with _doc_c:
    if st.button("Documentation", key="footer_docs_btn", width="stretch"):
        st.switch_page("pages/3_Documentation.py")