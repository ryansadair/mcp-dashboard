import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime
from utils.auth import check_password
from utils.styles import inject_global_css
from utils.config import STRATEGIES, SECTOR_COLORS, BRAND
from components.header import render_header
from components.market_ticker import render_market_ticker
from components.kpi_cards import render_kpi_cards
from data.holdings import get_holdings
from data.performance import get_strategy_kpis, get_benchmark_ytd, get_perf_chart_data

# ── Sprint 2 imports (graceful if not yet available) ──────────────────────
try:
    from data.tamarac_parser import (
        parse_tamarac_excel, get_holdings_for_strategy, get_cash_weight,
        STRATEGY_NAMES, STRATEGY_COLORS as STRAT_COLORS, STRATEGY_BENCHMARKS,
    )
    from data.market_data import fetch_batch_prices, fetch_price_history
    from data.dividends import (
        get_batch_dividend_details, compute_strategy_income, compute_weighted_yield,
    )
    SPRINT2_AVAILABLE = True
except ImportError:
    SPRINT2_AVAILABLE = False

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

# ── Auto-refresh every 60 seconds ─────────────────────────────────────────
# Page reruns every minute (header time stays current).
# Market data only re-fetches when @st.cache_data TTL (15 min) expires.
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=60 * 1000, key="data_refresh")

inject_global_css()

# Sprint 7: mobile responsiveness
if MOBILE_CSS_AVAILABLE:
    inject_mobile_css()

render_header()
render_market_ticker()

# ── Data freshness + Tamarac status (combined, right-aligned) ─────────────
_status_parts = []

# Part 1: Supabase data freshness
try:
    from data.market_data import get_cache_timestamp
    _raw_ts = get_cache_timestamp()
    if _raw_ts:
        from datetime import timedelta, timezone
        try:
            _parsed = datetime.fromisoformat(_raw_ts.replace("Z", "+00:00"))
            # Make _parsed timezone-aware UTC if it came in naive
            if _parsed.tzinfo is None:
                _parsed = _parsed.replace(tzinfo=timezone.utc)
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

            _status_parts.append(
                f'<span style="width:6px;height:6px;border-radius:50%;background:{_status_dot};'
                f'display:inline-block;"></span>'
                f'<span>Data refreshed {_time_str} PT ({_age_str})</span>'
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
            _status_parts.append(
                f'<span style="width:6px;height:6px;border-radius:50%;background:{_tam_dot};'
                f'display:inline-block;"></span>'
                f'<span>Tamarac: {_tam_status["filename"]}{_tam_date_str} · {_tam_age_str}</span>'
            )
    except Exception:
        pass

if _status_parts:
    _divider = '<span style="opacity:0.2;margin:0 6px;">|</span>'
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:flex-end;'
        f'padding:4px 28px 2px;gap:6px;font-size:10px;color:rgba(255,255,255,0.30);">'
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

tab_overview, tab_holdings, tab_perf, tab_divs, tab_watchlist, tab_macro, tab_markets, tab_alerts = st.tabs([
    "Overview", "Holdings", "Performance", "Dividends", "Watchlist", "Macro", "Markets", "News & Alerts"
])

# ── Strategy selector ─────────────────────────────────────────────────────
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

def _on_strategy_change(tab_key):
    """Callback for strategy selectbox — syncs widget value to session state
    and updates other tabs' selectbox values to match."""
    widget_key = f"strategy_select_{tab_key}"
    selected_label = st.session_state[widget_key]
    selected_key = strat_keys[strat_labels.index(selected_label)]
    st.session_state["active_strategy"] = selected_key
    # Sync other tabs' selectbox keys so they show the correct strategy
    all_tab_keys = ["overview", "holdings", "perf", "divs", "watchlist", "macro", "markets", "alerts"]
    for tk in all_tab_keys:
        other_key = f"strategy_select_{tk}"
        if other_key != widget_key and other_key in st.session_state:
            st.session_state[other_key] = selected_label

def _render_strategy_header(tab_key):
    """Render strategy selector + KPI cards inside a tab."""
    current_idx = strat_keys.index(st.session_state["active_strategy"])
    st.selectbox(
        "Strategy", options=strat_labels, index=current_idx,
        key=f"strategy_select_{tab_key}", label_visibility="collapsed",
        on_change=_on_strategy_change, args=(tab_key,),
    )

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    render_kpi_cards(active, kpis, bench_ytd)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# Pre-compute active strategy data (used by _render_strategy_header and tab content)
active = st.session_state["active_strategy"]
strat = STRATEGIES[active]
kpis = get_strategy_kpis(active)
bench_ytd = get_benchmark_ytd(strat["bench_ticker"])

# ── Override KPIs with real data when Sprint 2 is available ───────────────
if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
    tam_kpi = get_holdings_for_strategy(tamarac_parsed, active)
    cash_kpi = get_cash_weight(tamarac_parsed, active)

    if not tam_kpi.empty:
        kpis = dict(kpis)
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
    kpis = dict(kpis) if not isinstance(kpis, dict) else kpis
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
    _render_strategy_header("overview")
    left, right = st.columns([3, 2])

    with left:
        # Holdings Daily Return Treemap
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
                    sector = mkt.get("sector", "") or "Other"
                    hm_rows.append({
                        "symbol": sym,
                        "description": row["description"],
                        "weight": row["weight_pct"],
                        "daily_return": round(chg, 2),
                        "sector": sector,
                    })

                hm_df = pd.DataFrame(hm_rows).sort_values("weight", ascending=False)

                # ── Today's Movers — top contributors & detractors ────
                if len(hm_df) > 0:
                    hm_df["contrib"] = (hm_df["weight"] * hm_df["daily_return"] / 100).round(4)
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

                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

                if len(hm_df) > 0:
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

                    # Sector parent nodes
                    for sector in hm_df["sector"].unique():
                        tm_ids.append(f"sector_{sector}")
                        tm_labels.append(sector)
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
                    st.plotly_chart(fig_tm, use_container_width=True, config=PLOTLY_CONFIG)
                else:
                    st.info("No holdings data available.")
            else:
                st.info("No holdings for this strategy.")
        else:
            # Sprint 1 fallback
            perf_df = get_perf_chart_data(active, strat["bench_ticker"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=perf_df["month"], y=perf_df["strategy"],
                name=active,
                line=dict(color=strat["color"], width=2.5),
                mode="lines+markers", marker=dict(size=4),
            ))
            fig.add_trace(go.Scatter(
                x=perf_df["month"], y=perf_df["benchmark"],
                name=strat["bench"],
                line=dict(color="rgba(255,255,255,0.3)", width=1.5, dash="dot"),
                mode="lines",
            ))
            fig.update_layout(
                title="YTD Cumulative Performance",
                **PLOTLY_DARK,
                xaxis={**_XAXIS, "fixedrange": True, "showspikes": True, "spikecolor": "rgba(255,255,255,0.15)", "spikethickness": 1, "spikemode": "across", "spikedash": "solid"},
                yaxis={**_YAXIS, "ticksuffix": "%", "fixedrange": True, "showspikes": True, "spikecolor": "rgba(255,255,255,0.15)", "spikethickness": 1, "spikemode": "across", "spikedash": "solid"},
                height=280,
                hovermode="x unified",
                dragmode=False,
            )
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG_HOVER)

    with right:
        st.markdown("<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:12px;'>Sector Allocation</div>", unsafe_allow_html=True)

        # Sprint 2: build sector data from Tamarac + yfinance
        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            tam_ov = get_holdings_for_strategy(tamarac_parsed, active)
            cash_ov = get_cash_weight(tamarac_parsed, active)
            if not tam_ov.empty:
                ov_tickers = tuple(tam_ov["symbol"].tolist())
                ov_prices = fetch_batch_prices(ov_tickers)
                sector_rows = []
                for _, h in tam_ov.iterrows():
                    sym = h["symbol"]
                    sect = ov_prices.get(sym, {}).get("sector", "Other")
                    sector_rows.append({"sector": sect or "Other", "weight": h["weight_pct"]})
                if cash_ov > 0:
                    sector_rows.append({"sector": "Cash", "weight": cash_ov})
                sector_df = pd.DataFrame(sector_rows).groupby("sector")["weight"].sum().reset_index().sort_values("weight", ascending=False)
            else:
                sector_df = pd.DataFrame([{"sector": "No data", "weight": 100}])
        else:
            # Sprint 1 fallback
            holdings_df = get_holdings(active)
            if not holdings_df.empty and "sector" in holdings_df.columns:
                sector_df = holdings_df.groupby("sector")["weight"].sum().reset_index().sort_values("weight", ascending=False)
            else:
                sector_df = pd.DataFrame([
                    {"sector": "Healthcare",       "weight": 24.5},
                    {"sector": "Consumer Staples", "weight": 22.8},
                    {"sector": "Technology",       "weight": 18.2},
                    {"sector": "Industrials",      "weight": 16.4},
                    {"sector": "Financials",       "weight": 10.1},
                    {"sector": "Energy",           "weight": 5.2},
                    {"sector": "Cash",             "weight": 2.8},
                ])

        for _, row in sector_df.iterrows():
            color = SECTOR_COLORS.get(row["sector"], "#888")
            st.markdown(
                f"<div style='display:flex;align-items:center;margin-bottom:10px;gap:10px;'>"
                f"<div style='width:10px;height:10px;border-radius:2px;background:{color};flex-shrink:0;'></div>"
                f"<div style='flex:1;font-size:13px;color:rgba(255,255,255,0.7);'>{row['sector']}</div>"
                f"<div style='width:120px;background:rgba(255,255,255,0.06);border-radius:3px;height:6px;overflow:hidden;'>"
                f"<div style='width:{min(float(row['weight'])*2.5,100):.1f}%;height:6px;border-radius:3px;background:{color};'></div></div>"
                f"<div style='font-size:13px;color:rgba(255,255,255,0.5);width:54px;text-align:right;white-space:nowrap;'>{float(row['weight']):.2f}%</div>"
                f"</div>",
                unsafe_allow_html=True
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
        else:
            holdings_df = get_holdings(active)
            if not holdings_df.empty:
                for _, h in holdings_df.head(10).iterrows():
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);'>"
                        f"<div style='flex:0 0 50px;font-size:12px;font-weight:600;color:#C9A84C;'>{h.get('ticker','')}</div>"
                        f"<div style='flex:1;font-size:11px;color:rgba(255,255,255,0.45);'>{h.get('name','')}</div>"
                        f"<div style='flex:0 0 46px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h.get('weight',0):.2f}%</div>"
                        f"<div style='flex:0 0 65px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>${h.get('price',0):.2f}</div>"
                        f"<div style='flex:0 0 52px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h.get('chg1d',0):+.2f}%</div>"
                        f"<div style='flex:0 0 52px;font-size:12px;color:#C9A84C;text-align:right;'>—</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


# ══════════════════════════════════════════════════════════════════════════
# HOLDINGS — Sprint 2 upgrade: real Tamarac + live yfinance
# ══════════════════════════════════════════════════════════════════════════
with tab_holdings:
    _render_strategy_header("holdings")

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
                    yoc = h.get("yield_at_cost", 0) or 0
                    # yoc may be decimal (0.0558) or already percentage (5.58)
                    yoc_pct = float(yoc) * 100 if 0 < float(yoc) < 1 else float(yoc)

                    # Notion proprietary metrics
                    nm = notion_data.get(sym.upper(), {})

                    rows.append({
                        "Company": h["description"],
                        "Symbol": sym,
                        "Sector": mkt.get("sector", ""),
                        "Weight %": round(h["weight_pct"], 2),
                        "1D Chg %": chg_val,
                        "Price": mkt.get("price", 0),
                        "Yield on Cost %": round(yoc_pct, 2),
                        "Div Yield %": mkt.get("dividend_yield", 0),
                        "MCP Target": nm.get("mcp_target") if nm.get("mcp_target") is not None else "—",
                        "Baseline": nm.get("div_baseline") if nm.get("div_baseline") is not None else "—",
                        "Style": nm.get("style_bucket", "—") or "—",
                        "P/E": round(mkt.get("pe_ratio", 0), 1) if mkt.get("pe_ratio") else "—",
                        "Unit Cost": round(float(h.get("unit_cost", 0) or 0), 2),
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
                    "Yield on Cost %": "{:.2f}%",
                    "Div Yield %": "{:.2f}%",
                    "MCP Target": lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else v,
                    "Unit Cost": "${:.2f}",
                    "% From 52W Hi": "{:+.2f}%",
                })

                # Row-selection enabled — click a row to navigate to stock detail
                # Height: generous calculation to prevent internal scrollbar on mobile
                _df_height = min(80 + len(filtered) * 40, 2000)
                event = st.dataframe(
                    styled, use_container_width=True, hide_index=True,
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
                        "Baseline": st.column_config.TextColumn("Baseline", width="small"),
                        "Style": st.column_config.TextColumn("Style", width="small"),
                        "P/E": st.column_config.NumberColumn("P/E"),
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
                        st.dataframe(sect_agg, use_container_width=True, height=(80 + len(sect_agg) * 40), column_config={
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
                        st.plotly_chart(fig_pie, use_container_width=True, config=PLOTLY_CONFIG)

                # ── Finviz Analyst Enrichment (Sprint 7) ─────────────────
                if FINVIZ_AVAILABLE:
                    st.divider()
                    render_finviz_panel(tam_df, price_data, notion_data=notion_data)

                st.caption(f"Tamarac export + yfinance live prices • {datetime.now().strftime('%I:%M %p')}")

            else:
                st.info("No holdings in Tamarac file for this strategy.")

        # ── Sprint 1 fallback ─────────────────────────────────────────────
        else:
            search = st.text_input("🔍 Search ticker or company", placeholder="JNJ, Coca-Cola...", key="holdings_search")
            holdings_df = get_holdings(active)

            if holdings_df.empty:
                st.info("No holdings data. Upload a Tamarac export below.")
            else:
                if search:
                    mask = (
                        holdings_df["ticker"].str.lower().str.contains(search.lower(), na=False) |
                        holdings_df["name"].str.lower().str.contains(search.lower(), na=False)
                    )
                    holdings_df = holdings_df[mask]

                sort_opts = [c for c in ["weight","ytd","div_yield","quality","chg1d"] if c in holdings_df.columns]
                c1, c2 = st.columns([2,1])
                with c1: sort_by = st.selectbox("Sort by", sort_opts)
                with c2: sort_asc = st.checkbox("Ascending", value=False)
                holdings_df = holdings_df.sort_values(sort_by, ascending=sort_asc)

                display_cols = ["ticker","name","weight","price","chg1d","ytd","div_yield","div_growth_5y","sector","div_culture","quality"]
                available = [c for c in display_cols if c in holdings_df.columns]
                show_df = holdings_df[available].copy()
                for col in ["weight","chg1d","ytd","div_yield","div_growth_5y"]:
                    if col in show_df.columns:
                        show_df[col] = show_df[col].apply(lambda x: f"+{x:.2f}%" if pd.notna(x) and float(x) >= 0 else f"{x:.2f}%" if pd.notna(x) else "—")
                if "price" in show_df.columns:
                    show_df["price"] = show_df["price"].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
                show_df.columns = [c.replace("_"," ").title() for c in show_df.columns]
                st.dataframe(show_df, use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════
    # SUB-TAB 2: PRICE CHARTS GRID
    # ═══════════════════════════════════════════════════════════════════════
    with sub_charts:
        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            _charts_tam = get_holdings_for_strategy(tamarac_parsed, active)
            if not _charts_tam.empty:
                _charts_tam = _charts_tam.sort_values("description", ascending=True)
                _chart_tickers = _charts_tam["symbol"].tolist()
                _chart_names = dict(zip(_charts_tam["symbol"], _charts_tam["description"]))

                # Period selector — matches Stock Detail page
                _period_map = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "2Y": 504, "3Y": 756, "5Y": 1260, "Max": 0}
                if "hc_period" not in st.session_state:
                    st.session_state["hc_period"] = "1Y"

                _pcols = st.columns(len(_period_map))
                for _pi, (_plabel, _) in enumerate(_period_map.items()):
                    with _pcols[_pi]:
                        if st.button(_plabel, key=f"hc_p_{_plabel}", use_container_width=True,
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
                                            "%b '%y" if _sel_label in ("6M", "YTD", "1Y") else
                                            "%Y" if _sel_label in ("2Y", "3Y", "5Y", "Max") else
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
                                        _fig, use_container_width=True,
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
# PERFORMANCE — Composite Returns (Sprint 10)
# ══════════════════════════════════════════════════════════════════════════
with tab_perf:
    _render_strategy_header("perf")
    if COMPOSITE_AVAILABLE:
        render_performance_tab(active)
    else:
        st.info("Performance module not available. Ensure data/composite_returns.py and data/performance_tab.py are present.")


# ══════════════════════════════════════════════════════════════════════════
# DIVIDENDS — Sprint 4: full dividend intelligence with sub-tabs
# ══════════════════════════════════════════════════════════════════════════
with tab_divs:
    _render_strategy_header("divs")

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
        # Sprint 1 fallback
        d1, d2, d3, d4 = st.columns(4)
        with d1: st.metric("Wtd Avg Yield", f"{float(kpis.get('div_yield', 0)):.2f}%")
        with d2: st.metric("Yield on Cost", "—")
        with d3: st.metric("5Y Div CAGR", "—")
        with d4: st.metric("Annual Income Est.", "—")

        st.markdown("**Estimated Dividend Increase Announcements**")
        if DIV_CALENDAR_AVAILABLE:
            render_dividend_calendar()
        else:
            st.info("Dividend calendar not yet available. Run `dividend_calendar.py` to generate data.")


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
st.markdown("<div style='margin-top:-16px'></div>", unsafe_allow_html=True)
if st.button("Documentation", key="footer_docs_btn", use_container_width=True):
    st.switch_page("pages/3_Documentation.py")