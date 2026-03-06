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

# Watchlist (Excel-based, always available independently of Sprint 2)
try:
    from data.watchlist_tab import render_watchlist_tab
    WATCHLIST_AVAILABLE = True
except ImportError:
    WATCHLIST_AVAILABLE = False

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

# ── Auto-refresh every 15 minutes to stay in sync with Task Scheduler ────
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=15 * 60 * 1000, key="data_refresh")

inject_global_css()

render_header()
render_market_ticker()

# ── Tamarac data loading (Sprint 2) ──────────────────────────────────────
import os

TAMARAC_PATHS = [
    "data/Tamarac_Holdings.xlsx",
    "Tamarac_Holdings.xlsx",
]

tamarac_parsed = None
if SPRINT2_AVAILABLE:
    for p in TAMARAC_PATHS:
        if os.path.exists(p):
            @st.cache_data(ttl=300)
            def _load_tamarac(path):
                return parse_tamarac_excel(path)
            tamarac_parsed = _load_tamarac(p)
            break

# ── Strategy Selector ──────────────────────────────────────────────────────
if "active_strategy" not in st.session_state:
    st.session_state["active_strategy"] = "QDVD"

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
current_idx  = strat_keys.index(st.session_state["active_strategy"])
selected_label = st.selectbox(
    "Strategy", options=strat_labels, index=current_idx,
    key="strategy_select", label_visibility="collapsed",
)
selected_key = strat_keys[strat_labels.index(selected_label)]
if selected_key != st.session_state["active_strategy"]:
    st.session_state["active_strategy"] = selected_key
    st.rerun()

active = st.session_state["active_strategy"]
strat = STRATEGIES[active]
kpis = get_strategy_kpis(active)
bench_ytd = get_benchmark_ytd(strat["bench_ticker"])

# ── Override KPIs with real data when Sprint 2 is available ───────────────
if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
    tam_kpi = get_holdings_for_strategy(tamarac_parsed, active)
    cash_kpi = get_cash_weight(tamarac_parsed, active)

    if not tam_kpi.empty:
        # Real holdings count (excluding cash)
        kpis = dict(kpis)  # copy so we don't mutate the cached dict
        kpis["holdings"] = len(tam_kpi)

        # Real dividend yield and daily return from yfinance
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

        # Dividend yield: weighted avg across equity holdings only
        if equity_weight > 0:
            kpis["div_yield"] = round(weighted_yield / equity_weight, 2)

        # Daily return: include cash (0% return) so total weights sum to 100%
        # Cash contributes nothing to return but dilutes the overall move
        cash_decimal = cash_kpi / 100  # cash_kpi is already a percentage
        total_portfolio_weight = equity_weight + cash_decimal
        if total_portfolio_weight > 0:
            kpis["daily_return"] = round(weighted_daily / total_portfolio_weight, 2)

        # Cash weight for KPI card
        kpis["cash_pct"] = round(cash_kpi, 1)

# Override YTD with official Tamarac monthly numbers when available
if MONTHLY_RETURNS_AVAILABLE and active in STRATEGY_YTD:
    kpis = dict(kpis) if not isinstance(kpis, dict) else kpis
    kpis["ytd"] = STRATEGY_YTD[active]
    kpis["ytd_as_of"] = AS_OF_DATE

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── KPI Cards ──────────────────────────────────────────────────────────────
render_kpi_cards(active, kpis, bench_ytd)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────
tab_overview, tab_holdings, tab_perf, tab_divs, tab_watchlist = st.tabs([
    "📊 Overview", "📋 Holdings", "📈 Performance", "💰 Dividends", "🔍 Watchlist"
])

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
    left, right = st.columns([3, 2])

    with left:
        # Holdings Daily Return Heatmap
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
                    hm_rows.append({
                        "symbol": sym,
                        "weight": row["weight_pct"],
                        "daily_return": round(chg, 2),
                    })

                hm_df = pd.DataFrame(hm_rows).sort_values("weight", ascending=False)

                if len(hm_df) > 0:
                    bar_df = hm_df.sort_values("daily_return", ascending=True)
                    colors = ["#569542" if r >= 0 else "#c45454" for r in bar_df["daily_return"]]
                    fig_bar = go.Figure()
                    _bar_min = bar_df["daily_return"].min()
                    _bar_max = bar_df["daily_return"].max()
                    _bar_pad = max(abs(_bar_min), abs(_bar_max)) * 0.25
                    fig_bar.add_trace(go.Bar(
                        x=bar_df["daily_return"], y=bar_df["symbol"], orientation="h",
                        marker=dict(color=colors),
                        text=[f"{r:+.2f}%" for r in bar_df["daily_return"]],
                        textposition="outside",
                        textfont=dict(size=10, color="rgba(255,255,255,0.6)"),
                        cliponaxis=False,
                    ))
                    fig_bar.update_layout(
                        title=f"Today's Returns — {STRATEGY_NAMES.get(active, active)}",
                        paper_bgcolor="rgba(255,255,255,0.02)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
                        margin=dict(l=10, r=60, t=40, b=10),
                        height=max(250, len(bar_df) * 22 + 60),
                        xaxis=dict(
                            gridcolor="rgba(255,255,255,0.04)",
                            showline=False, ticksuffix="%", zeroline=True,
                            zerolinecolor="rgba(255,255,255,0.1)",
                            fixedrange=True,
                            range=[_bar_min - _bar_pad, _bar_max + _bar_pad],
                        ),
                        yaxis=dict(showgrid=False, showline=False, tickfont=dict(size=10), fixedrange=True),
                        showlegend=False,
                        dragmode=False,
                    )
                    st.plotly_chart(fig_bar, use_container_width=True, config=PLOTLY_CONFIG)
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
                xaxis=_XAXIS,
                yaxis={**_YAXIS, "ticksuffix": "%"},
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

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
                f"<div style='font-size:13px;color:rgba(255,255,255,0.5);width:38px;text-align:right;'>{float(row['weight']):.1f}%</div>"
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
                        f"<div style='flex:0 0 46px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h['weight_pct']:.1f}%</div>"
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
                        f"<div style='flex:0 0 46px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h.get('weight',0):.1f}%</div>"
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

    # ── Sprint 2: Tamarac + yfinance ─────────────────────────────────────
    if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        tam_df = get_holdings_for_strategy(tamarac_parsed, active)
        cash_wt = get_cash_weight(tamarac_parsed, active)

        if not tam_df.empty:
            tickers = tuple(tam_df["symbol"].tolist())
            with st.spinner("Fetching live prices..."):
                price_data = fetch_batch_prices(tickers)

            # Build merged table
            rows = []
            for _, h in tam_df.iterrows():
                sym = h["symbol"]
                mkt = price_data.get(sym, {})
                chg_val = mkt.get("change_1d_pct", 0) or 0
                yoc = h.get("yield_at_cost", 0) or 0
                rows.append({
                    "Company": h["description"],
                    "Symbol": sym,
                    "Sector": mkt.get("sector", ""),
                    "Weight %": round(h["weight_pct"], 2),
                    "1D Chg %": chg_val,
                    "Price": mkt.get("price", 0),
                    "Yield on Cost %": round(float(yoc) * 100, 2) if yoc else 0.0,
                    "Div Yield %": mkt.get("dividend_yield", 0),
                    "P/E": round(mkt.get("pe_ratio", 0), 1) if mkt.get("pe_ratio") else "—",
                    "52W High": mkt.get("52w_high", 0),
                    "52W Low":  mkt.get("52w_low", 0),
                })
            display_df = pd.DataFrame(rows)


            # Detail selector & sector filter — single row
            c_detail, c_sector = st.columns([3, 1])
            with c_detail:
                detail_ticker = st.selectbox(
                    "Ticker Detail",
                    options=display_df["Symbol"].tolist(),
                    key="holdings_detail_select",
                    label_visibility="collapsed",
                    index=None,
                    placeholder="Select a ticker for detail view...",
                )
                if detail_ticker:
                    st.session_state["detail_ticker"] = detail_ticker
                    st.query_params["ticker"] = detail_ticker
                    st.switch_page("pages/2_Stock_Detail.py")
            with c_sector:
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

            styled = filtered.style.map(_color_1d, subset=["1D Chg %"]).format({
                "Weight %": "{:.2f}",
                "Price": "${:.2f}",
                "1D Chg %": "{:+.2f}%",
                "Yield on Cost %": "{:.2f}%",
                "Div Yield %": "{:.2f}%",
                "52W High": "${:.2f}",
                "52W Low": "${:.2f}",
            })

            st.dataframe(
                styled, use_container_width=True, hide_index=True,
                height=(42 + len(filtered) * 36),
                column_config={
                    "Company": st.column_config.TextColumn("Company", width="medium"),
                    "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                    "Sector": st.column_config.TextColumn("Sector", width="medium"),
                    "Weight %": st.column_config.NumberColumn("Wt %", format="%.2f%%"),
                    "1D Chg %": st.column_config.NumberColumn("1D %", format="%+.2f%%"),
                    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "Yield on Cost %": st.column_config.NumberColumn("Yield on Cost", format="%.2f%%"),
                    "Div Yield %": st.column_config.NumberColumn("Curr Yield", format="%.2f%%"),
                    "P/E": st.column_config.NumberColumn("P/E"),
                    "52W High": st.column_config.NumberColumn("52W Hi", format="$%.2f"),
                    "52W Low": st.column_config.NumberColumn("52W Lo", format="$%.2f"),
                },
            )

            # Sector breakdown
            if len(filtered) > 0 and "Sector" in filtered.columns:
                st.divider()
                st.markdown("**Sector Breakdown**")
                sect_agg = filtered.groupby("Sector").agg(
                    Holdings=("Symbol", "count"),
                    Total_Weight=("Weight %", "sum"),
                    Avg_Yield=("Div Yield %", "mean"),
                    Avg_YoC=("Yield on Cost %", "mean"),
                ).round(2).sort_values("Total_Weight", ascending=False)
                st.dataframe(sect_agg, use_container_width=True, column_config={
                    "Total_Weight": st.column_config.NumberColumn("Weight %", format="%.2f%%"),
                    "Avg_Yield": st.column_config.NumberColumn("Avg Yield %", format="%.2f%%"),
                    "Avg_YoC": st.column_config.NumberColumn("Avg YoC %", format="%.2f%%"),
                })

            st.caption(f"Tamarac export + yfinance live prices • {datetime.now().strftime('%I:%M %p')}")

        else:
            st.info("No holdings in Tamarac file for this strategy.")

    # ── Sprint 1 fallback ─────────────────────────────────────────────────
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


# ══════════════════════════════════════════════════════════════════════════
# PERFORMANCE — Powered by Strategy_Returns.xlsx
# ══════════════════════════════════════════════════════════════════════════
with tab_perf:
    from data.performance import load_strategy_returns, get_benchmark_ytd

    all_returns = load_strategy_returns()
    strat_df    = all_returns.get(active)
    bench_info  = STRATEGY_BENCHMARKS.get(active, {"name": "S&P 500", "ticker": "^GSPC"})
    strat_color = strat["color"]

    # ── Period selector ───────────────────────────────────────────────────
    period = st.selectbox("Time Period", ["YTD", "1Y", "3Y", "5Y", "ITD"], index=0, key="perf_period")

    if strat_df is None or strat_df.empty:
        st.info(f"No return data available for {active}. Add data to Strategy_Returns.xlsx.")
    else:
        # Filter to period
        today  = pd.Timestamp.today()
        cutoff = {
            "YTD": pd.Timestamp(today.year, 1, 1),
            "1Y":  today - pd.DateOffset(years=1),
            "3Y":  today - pd.DateOffset(years=3),
            "5Y":  today - pd.DateOffset(years=5),
            "ITD": strat_df["date"].min(),
        }.get(period, pd.Timestamp(today.year, 1, 1))

        pf = strat_df[strat_df["date"] >= cutoff].copy()
        if pf.empty:
            st.info(f"No data for {active} in the selected period.")
        else:
            # Rebase cumulative from period start
            pf["strat_cum"] = (1 + pf["ret"]).cumprod()
            pf["strat_cum"] = (pf["strat_cum"] / pf["strat_cum"].iloc[0] - 1) * 100

            # ── Chart ─────────────────────────────────────────────────────
            fig2 = go.Figure()
            r, g, b = int(strat_color[1:3],16), int(strat_color[3:5],16), int(strat_color[5:7],16)
            fig2.add_trace(go.Scatter(
                x=pf["date"], y=pf["strat_cum"],
                name=STRATEGY_NAMES.get(active, active),
                fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.08)",
                line=dict(color=strat_color, width=2.5),
                hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>",
            ))

            # Benchmark from Supabase history
            try:
                from data.performance import _sb_get_benchmark_history
                bench_hist = _sb_get_benchmark_history(bench_info["ticker"])
                if bench_hist is not None and not bench_hist.empty:
                    bench_hist["date"] = pd.to_datetime(bench_hist["date"])
                    bench_hist = bench_hist[bench_hist["date"] >= cutoff].sort_values("date")
                    if not bench_hist.empty:
                        bench_hist["bench_cum"] = (bench_hist["close"] / bench_hist["close"].iloc[0] - 1) * 100
                        fig2.add_trace(go.Scatter(
                            x=bench_hist["date"], y=bench_hist["bench_cum"],
                            name=bench_info["name"],
                            line=dict(color="rgba(255,255,255,0.3)", width=1.5, dash="dot"),
                            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>",
                        ))
            except Exception:
                pass

            fig2.update_layout(
                title=f"Cumulative Return — {period}",
                **PLOTLY_DARK,
                xaxis={**_XAXIS, "fixedrange": True},
                yaxis={**_YAXIS, "ticksuffix": "%", "fixedrange": True},
                height=360,
                hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG_HOVER)

            # ── KPIs ──────────────────────────────────────────────────────
            port_total  = round(float(pf["strat_cum"].iloc[-1]), 2)
            bench_ytd   = get_benchmark_ytd(bench_info["ticker"]) if period == "YTD" else 0
            alpha_val   = round(port_total - bench_ytd, 2) if period == "YTD" else 0

            # Risk metrics from period returns
            rets        = pf["ret"]
            ann_vol     = round(float(rets.std() * (4 ** 0.5) * 100), 2)  # quarterly vol annualised
            ann_return  = round(float((1 + rets).prod() ** (4 / len(rets)) - 1) * 100, 2) if len(rets) > 1 else 0
            sharpe      = round(ann_return / ann_vol, 2) if ann_vol > 0 else 0
            cum_w       = (1 + rets).cumprod()
            run_max     = cum_w.cummax()
            drawdown    = (cum_w - run_max) / run_max
            max_dd      = round(float(drawdown.min()) * 100, 2)
            downside    = rets[rets < 0]
            ds_std      = float(downside.std() * (4 ** 0.5) * 100) if len(downside) > 1 else 0
            sortino     = round(ann_return / ds_std, 2) if ds_std > 0 else 0

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            with m1: st.metric("Strategy Return", f"{port_total:+.2f}%")
            with m2: st.metric("Benchmark YTD", f"{bench_ytd:+.2f}%" if period == "YTD" else "—")
            with m3: st.metric("Alpha", f"{alpha_val:+.2f}%" if period == "YTD" else "—")
            with m4: st.metric("Sharpe", f"{sharpe:.2f}")
            with m5: st.metric("Max Drawdown", f"{max_dd:.2f}%")
            with m6: st.metric("Ann. Volatility", f"{ann_vol:.1f}%")

            # ── Risk metrics table ────────────────────────────────────────
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Risk Metrics**")
                st.dataframe(pd.DataFrame({
                    "Metric": ["Ann. Return","Ann. Volatility","Sharpe Ratio","Sortino Ratio","Max Drawdown"],
                    "Value":  [f"{ann_return:+.2f}%", f"{ann_vol:.1f}%", f"{sharpe:.2f}", f"{sortino:.2f}", f"{max_dd:.2f}%"],
                }), hide_index=True, use_container_width=True)

            with c2:
                st.markdown("**Period Summary**")
                st.dataframe(pd.DataFrame({
                    "Metric": ["Periods", "Start Date", "End Date", "Total Return"],
                    "Value":  [
                        str(len(pf)),
                        pf["date"].iloc[0].strftime("%b %Y"),
                        pf["date"].iloc[-1].strftime("%b %Y"),
                        f"{port_total:+.2f}%",
                    ],
                }), hide_index=True, use_container_width=True)

            # ── Drawdown chart ────────────────────────────────────────────
            st.divider()
            st.markdown("**Drawdown**")
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=pf["date"], y=drawdown.values * 100,
                fill="tozeroy", fillcolor="rgba(196,84,84,0.15)",
                line=dict(color="#c45454", width=1.5), name="Drawdown",
            ))
            fig_dd.update_layout(**PLOTLY_DARK, xaxis={**_XAXIS, "fixedrange": True}, yaxis={**_YAXIS, "ticksuffix": "%", "fixedrange": True}, height=220, showlegend=False, hovermode="x unified")
            st.plotly_chart(fig_dd, use_container_width=True, config=PLOTLY_CONFIG_HOVER)

            # ── Monthly returns heatmap ───────────────────────────────────
            if len(pf) >= 12:
                st.divider()
                st.markdown("**Quarterly Returns**")
                hm_df = pd.DataFrame({
                    "Year":    pf["date"].dt.year,
                    "Quarter": pf["date"].dt.quarter.map({1:"Q1",2:"Q2",3:"Q3",4:"Q4"}),
                    "Return":  (pf["ret"] * 100).round(2),
                })
                pivot = hm_df.pivot_table(index="Year", columns="Quarter", values="Return")
                pivot = pivot.reindex(columns=["Q1","Q2","Q3","Q4"])

                fig_hm = go.Figure(go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns.tolist(),
                    y=pivot.index.tolist(),
                    colorscale=[[0,"#c45454"],[0.5,"rgba(255,255,255,0.05)"],[1,"#569542"]],
                    zmid=0,
                    text=[[f"{v:.1f}%" if not pd.isna(v) else "" for v in row] for row in pivot.values],
                    texttemplate="%{text}",
                    textfont=dict(size=11),
                    showscale=False,
                    hovertemplate="Year: %{y}<br>%{x}: %{z:.2f}%<extra></extra>",
                ))
                _hm_layout = {**PLOTLY_DARK}
                _hm_layout["margin"] = dict(l=10, r=10, t=30, b=10)
                fig_hm.update_layout(
                    **_hm_layout,
                    height=max(200, len(pivot) * 28 + 80),
                    xaxis=dict(side="top", fixedrange=True),
                    yaxis=dict(autorange="reversed", fixedrange=True),
                )
                st.plotly_chart(fig_hm, use_container_width=True, config=PLOTLY_CONFIG_HOVER)

    st.caption(f"Source: Strategy_Returns.xlsx • Quarterly returns • Updated manually")


# ══════════════════════════════════════════════════════════════════════════
# DIVIDENDS — Sprint 2 upgrade: live dividend data from yfinance
# ══════════════════════════════════════════════════════════════════════════
with tab_divs:

    if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        tam_df = get_holdings_for_strategy(tamarac_parsed, active)
        strat_color = strat["color"]

        if not tam_df.empty:
            tickers = tuple(tam_df["symbol"].tolist())

            with st.spinner("Fetching dividend data..."):
                price_data = fetch_batch_prices(tickers)
                div_data = get_batch_dividend_details(tickers)

            # KPIs
            wtd_yield = compute_weighted_yield(tam_df, div_data)

            # Helper: compute average growth for a given period key, filtering bad data
            def _avg_growth(key):
                vals = [div_data[t].get(key, 0) for t in tickers
                        if t in div_data
                        and div_data[t].get(key, 0) != 0
                        and -50 < div_data[t].get(key, 0) < 100]
                return round(sum(vals) / len(vals), 1) if vals else 0

            avg_growth_1y = _avg_growth("div_growth_1y")
            avg_growth_3y = _avg_growth("div_growth_3y")
            avg_growth_5y = _avg_growth("div_growth_5y")

            # Avg consecutive years: only include tickers with meaningful history
            consec = [div_data[t].get("consecutive_years", 0) for t in tickers
                      if t in div_data and div_data[t].get("consecutive_years", 0) > 0]
            avg_consec = round(sum(consec) / len(consec), 0) if consec else 0

            d1, d2, d3, d4, d5 = st.columns(5)
            with d1: st.metric("Wtd Avg Yield", f"{wtd_yield}%")
            with d2: st.metric("Avg 1Y Div Growth", f"{avg_growth_1y:+.1f}%")
            with d3: st.metric("Avg 3Y Div Growth", f"{avg_growth_3y:+.1f}%")
            with d4: st.metric("Avg 5Y Div Growth", f"{avg_growth_5y:+.1f}%")
            with d5: st.metric("Avg Consec. Years", f"{int(avg_consec)}")

            # Upcoming ex-dates
            st.markdown("**Upcoming Ex-Dividend Dates**")
            ex_rows = []
            today = datetime.now()
            for _, row in tam_df.iterrows():
                sym = row["symbol"]
                dd = div_data.get(sym, {})
                ex_str = dd.get("ex_dividend_date", "")
                if ex_str:
                    try:
                        ex_dt = datetime.strptime(ex_str, "%Y-%m-%d")
                        days = (ex_dt - today).days
                        ex_rows.append({
                            "Symbol": sym,
                            "Company": row["description"],
                            "Ex-Date": ex_str,
                            "Days Until": days,
                            "Div Rate": f"${dd.get('dividend_rate', 0):.2f}",
                            "Yield %": dd.get("dividend_yield", 0),
                            "Consec Yrs": dd.get("consecutive_years", 0),
                            "Payout %": dd.get("payout_ratio", 0),
                        })
                    except ValueError:
                        pass

            if ex_rows:
                ex_df = pd.DataFrame(ex_rows).sort_values("Days Until")
                upcoming = ex_df[(ex_df["Days Until"] >= -7) & (ex_df["Days Until"] <= 90)]
                if len(upcoming) > 0:
                    st.dataframe(upcoming, use_container_width=True, hide_index=True,
                        height=42 + len(upcoming) * 36,
                        column_config={
                            "Yield %": st.column_config.NumberColumn(format="%.2f%%"),
                            "Payout %": st.column_config.NumberColumn(format="%.1f%%"),
                        })
                else:
                    st.info("No upcoming ex-dates in the next 90 days.")
            else:
                st.info("No ex-dividend date data available.")

            # Yield chart
            st.divider()
            st.markdown("**Dividend Yield by Holding**")
            yield_rows = []
            for _, row in tam_df.iterrows():
                sym = row["symbol"]
                dd = div_data.get(sym, {})
                yld = dd.get("dividend_yield", 0)
                if yld > 0:
                    yield_rows.append({"symbol": sym, "yield": yld})
            if yield_rows:
                yield_df = pd.DataFrame(yield_rows).sort_values("yield", ascending=True)
                fig3 = go.Figure()
                fig3.add_trace(go.Bar(
                    x=yield_df["yield"], y=yield_df["symbol"], orientation="h",
                    marker=dict(
                        color=yield_df["yield"],
                        colorscale=[[0, "#07415A"], [0.5, "#C9A84C"], [1, "#569542"]],
                    ),
                    text=[f"{y:.2f}%" for y in yield_df["yield"]],
                    textposition="outside",
                    textfont=dict(size=11, color="rgba(255,255,255,0.6)"),
                ))
                fig3.update_layout(
                    **PLOTLY_DARK,
                    title="Current Dividend Yield (%)",
                    xaxis={**_XAXIS, "title": "Yield %"},
                    yaxis=_YAXIS,
                    height=max(300, len(yield_df) * 28 + 80),
                    showlegend=False,
                )
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG)

            # Growth chart
            st.divider()
            st.markdown("**5-Year Dividend Growth Rate**")
            growth_rows = []
            for _, row in tam_df.iterrows():
                sym = row["symbol"]
                dd = div_data.get(sym, {})
                gr = dd.get("div_growth_5y", 0)
                if gr != 0:
                    growth_rows.append({"symbol": sym, "growth": gr})
            if growth_rows:
                growth_df = pd.DataFrame(growth_rows).sort_values("growth", ascending=True)
                colors = ["#569542" if g >= 0 else "#c45454" for g in growth_df["growth"]]
                fig4 = go.Figure()
                fig4.add_trace(go.Bar(
                    x=growth_df["growth"], y=growth_df["symbol"], orientation="h",
                    marker=dict(color=colors),
                    text=[f"{g:+.1f}%" for g in growth_df["growth"]],
                    textposition="outside",
                    textfont=dict(size=11, color="rgba(255,255,255,0.6)"),
                ))
                fig4.update_layout(
                    **PLOTLY_DARK,
                    title="5-Year Dividend CAGR (%)",
                    xaxis=_XAXIS,
                    yaxis=_YAXIS,
                    height=max(300, len(growth_df) * 28 + 80),
                    showlegend=False,
                )
                st.plotly_chart(fig4, use_container_width=True, config=PLOTLY_CONFIG)

            st.caption(f"Dividend data via yfinance • {datetime.now().strftime('%I:%M %p')}")

        else:
            st.info("No holdings for this strategy in Tamarac file.")

    # ── Sprint 1 fallback ─────────────────────────────────────────────────
    else:
        d1, d2, d3, d4 = st.columns(4)
        with d1: st.metric("Wtd Avg Yield", f"{float(kpis.get('div_yield', 0)):.2f}%")
        with d2: st.metric("Yield on Cost", "3.67%")
        with d3: st.metric("5Y Div CAGR", "7.2%")
        with d4: st.metric("Annual Income Est.", "$1.32M")

        st.markdown("**Upcoming Ex-Dividend Dates**")
        st.dataframe(pd.DataFrame([
            {"Ticker":"JNJ","Ex-Date":"Mar 10","Amount":"$1.24","Yield":"3.01%","Consecutive Years":62,"Payout Ratio":"44%"},
            {"Ticker":"PG", "Ex-Date":"Mar 15","Amount":"$1.01","Yield":"2.45%","Consecutive Years":68,"Payout Ratio":"59%"},
            {"Ticker":"KO", "Ex-Date":"Mar 18","Amount":"$0.49","Yield":"2.98%","Consecutive Years":62,"Payout Ratio":"66%"},
            {"Ticker":"ABT","Ex-Date":"Mar 22","Amount":"$0.55","Yield":"1.92%","Consecutive Years":52,"Payout Ratio":"48%"},
            {"Ticker":"TXN","Ex-Date":"Apr 01","Amount":"$1.34","Yield":"2.67%","Consecutive Years":21,"Payout Ratio":"62%"},
        ]), hide_index=True, use_container_width=True, config=PLOTLY_CONFIG)

        holdings_df = get_holdings(active)
        if not holdings_df.empty and "div_yield" in holdings_df.columns:
            chart_df = holdings_df.sort_values("div_yield", ascending=True).tail(12)
            fig3 = px.bar(
                chart_df, x="div_yield", y="ticker", orientation="h",
                color_discrete_sequence=[BRAND["gold"]],
                labels={"div_yield": "Dividend Yield (%)", "ticker": ""},
                title="Dividend Yield by Holding",
            )
            fig3.update_layout(**PLOTLY_DARK, xaxis={**_XAXIS, "ticksuffix": "%"}, yaxis=_YAXIS, height=320)
            st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG)


# ══════════════════════════════════════════════════════════════════════════
# WATCHLIST
# ══════════════════════════════════════════════════════════════════════════
with tab_watchlist:
    if WATCHLIST_AVAILABLE:
        render_watchlist_tab()
    else:
        st.info("Watchlist module not found. Ensure `data/watchlist.py` and `data/watchlist_tab.py` are in the data folder.")


# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='display:flex;gap:12px;justify-content:center;padding:16px 28px;margin-top:20px;"
    "border-top:1px solid rgba(255,255,255,0.04);font-size:11px;color:rgba(255,255,255,0.2);'>"
    "<span>© 2026 Martin Capital Partners LLC</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Data: yfinance · FRED · Notion</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Internal use only</span>"
    "</div>",
    unsafe_allow_html=True
)