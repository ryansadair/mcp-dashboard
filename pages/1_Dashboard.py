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

cols = st.columns(len(STRATEGIES))
for i, (key, s) in enumerate(STRATEGIES.items()):
    with cols[i]:
        is_active = st.session_state["active_strategy"] == key
        if st.button(
            f"**{key}**  \n{s['name']}",
            key=f"strat_{key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["active_strategy"] = key
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
                    fig_bar.add_trace(go.Bar(
                        x=bar_df["daily_return"], y=bar_df["symbol"], orientation="h",
                        marker=dict(color=colors),
                        text=[f"{r:+.2f}%" for r in bar_df["daily_return"]],
                        textposition="outside",
                        textfont=dict(size=10, color="rgba(255,255,255,0.6)"),
                    ))
                    fig_bar.update_layout(
                        title=f"Today's Returns — {STRATEGY_NAMES.get(active, active)}",
                        paper_bgcolor="rgba(255,255,255,0.02)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
                        margin=dict(l=10, r=50, t=40, b=10),
                        height=max(250, len(bar_df) * 22 + 60),
                        xaxis=dict(
                            gridcolor="rgba(255,255,255,0.04)",
                            showline=False, ticksuffix="%", zeroline=True,
                            zerolinecolor="rgba(255,255,255,0.1)",
                        ),
                        yaxis=dict(showgrid=False, showline=False, tickfont=dict(size=10)),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
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
            st.plotly_chart(fig, use_container_width=True)

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

        # Top 5 Holdings — compact display
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:14px;font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:10px;'>Top Holdings</div>", unsafe_allow_html=True)

        if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
            tam_top5 = get_holdings_for_strategy(tamarac_parsed, active)
            if not tam_top5.empty:
                top5_tickers = tuple(tam_top5["symbol"].head(5).tolist())
                top5_prices = fetch_batch_prices(top5_tickers)
                for _, h in tam_top5.head(5).iterrows():
                    sym = h["symbol"]
                    mkt = top5_prices.get(sym, {})
                    price = mkt.get("price", 0)
                    chg = mkt.get("change_1d_pct", 0) or 0
                    chg_color = "#569542" if chg >= 0 else "#c45454"
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);'>"
                        f"<div style='flex:0 0 50px;font-size:12px;font-weight:600;color:#C9A84C;'>{sym}</div>"
                        f"<div style='flex:1;font-size:11px;color:rgba(255,255,255,0.45);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{h['description']}</div>"
                        f"<div style='flex:0 0 55px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h['weight_pct']:.1f}%</div>"
                        f"<div style='flex:0 0 65px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>${price:.2f}</div>"
                        f"<div style='flex:0 0 55px;font-size:12px;color:{chg_color};text-align:right;font-weight:500;'>{chg:+.2f}%</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        else:
            holdings_df = get_holdings(active)
            if not holdings_df.empty:
                for _, h in holdings_df.head(5).iterrows():
                    st.markdown(
                        f"<div style='display:flex;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);'>"
                        f"<div style='flex:0 0 50px;font-size:12px;font-weight:600;color:#C9A84C;'>{h.get('ticker','')}</div>"
                        f"<div style='flex:1;font-size:11px;color:rgba(255,255,255,0.45);'>{h.get('name','')}</div>"
                        f"<div style='flex:0 0 55px;font-size:12px;color:rgba(255,255,255,0.7);text-align:right;'>{h.get('weight',0):.1f}%</div>"
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
                rows.append({
                    "Symbol": sym,
                    "Company": h["description"],
                    "Weight %": round(h["weight_pct"], 2),
                    "Shares": int(h["quantity"]) if h["quantity"] == int(h["quantity"]) else h["quantity"],
                    "Price": mkt.get("price", 0),
                    "1D Chg %": chg_val,
                    "Div Yield %": mkt.get("dividend_yield", 0),
                    "P/E": round(mkt.get("pe_ratio", 0), 1) if mkt.get("pe_ratio") else "—",
                    "Sector": mkt.get("sector", ""),
                    "52W High": mkt.get("52w_high", 0),
                    "52W Low":  mkt.get("52w_low", 0),
                })
            display_df = pd.DataFrame(rows)

            # KPI summary
            num_h = len(display_df)
            invested = round(100 - cash_wt, 1)
            avg_yield = round(display_df["Div Yield %"].mean(), 2) if num_h > 0 else 0
            top_wt = display_df["Weight %"].max() if num_h > 0 else 0

            k1, k2, k3, k4, k5 = st.columns(5)
            with k1: st.metric("Holdings", num_h)
            with k2: st.metric("Invested", f"{invested}%")
            with k3: st.metric("Cash", f"{cash_wt:.1f}%")
            with k4: st.metric("Avg Yield", f"{avg_yield}%")
            with k5: st.metric("Top Wt", f"{top_wt:.1f}%")

            # Detail selector & sector filter — single row
            c_detail, c_go, c_sector = st.columns([3, 1, 1])
            with c_detail:
                detail_ticker = st.selectbox(
                    "Ticker Detail",
                    options=display_df["Symbol"].tolist(),
                    key="holdings_detail_select",
                    label_visibility="collapsed",
                    index=None,
                    placeholder="Select a ticker for detail view...",
                )
            with c_go:
                if detail_ticker:
                    if st.button(f"📊 Open {detail_ticker}", key="go_detail_btn", use_container_width=True):
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
                "Div Yield %": "{:.2f}",
                "52W High": "${:.2f}",
                "52W Low": "${:.2f}",
            })

            st.dataframe(
                styled, use_container_width=True, hide_index=True,
                height=min(600, 42 + len(filtered) * 36),
                column_config={
                    "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                    "Company": st.column_config.TextColumn("Company", width="medium"),
                    "Weight %": st.column_config.NumberColumn("Wt %", format="%.2f"),
                    "Shares": st.column_config.NumberColumn("Shares", format="%d"),
                    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "1D Chg %": st.column_config.NumberColumn("1D %", format="%+.2f%%"),
                    "Div Yield %": st.column_config.NumberColumn("Yield %", format="%.2f"),
                    "Sector": st.column_config.TextColumn("Sector", width="medium"),
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
                ).round(2).sort_values("Total_Weight", ascending=False)
                st.dataframe(sect_agg, use_container_width=True, column_config={
                    "Total_Weight": st.column_config.NumberColumn("Weight %", format="%.2f"),
                    "Avg_Yield": st.column_config.NumberColumn("Avg Yield %", format="%.2f"),
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
            st.dataframe(show_df, use_container_width=True, hide_index=True, height=500)


# ══════════════════════════════════════════════════════════════════════════
# PERFORMANCE — Sprint 2 upgrade: weighted returns from Tamarac + yfinance
# ══════════════════════════════════════════════════════════════════════════
with tab_perf:

    if SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed:
        tam_df = get_holdings_for_strategy(tamarac_parsed, active)
        bench_info = STRATEGY_BENCHMARKS.get(active, {"name": "S&P 500", "ticker": "^GSPC"})
        strat_color = strat["color"]

        # Period selector
        period = st.selectbox("Time Period", ["1mo", "3mo", "6mo", "YTD", "1y"], index=3, key="perf_period")
        period_map = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "YTD": "ytd", "1y": "1y"}
        yf_period = period_map.get(period, "ytd")

        # Compute weighted portfolio returns
        @st.cache_data(ttl=900, show_spinner="Computing portfolio returns...")
        def _compute_perf(holdings_tuple, bench_ticker, yf_period):
            holdings = list(holdings_tuple)
            symbols = [h[0] for h in holdings]
            weights = {h[0]: h[1] for h in holdings}
            all_hist = {}
            for t in symbols + [bench_ticker]:
                hist = fetch_price_history(t, period=yf_period)
                if hist is not None and not hist.empty:
                    # yfinance returns a DatetimeIndex already — no need to set_index
                    close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
                    close.index = pd.to_datetime(close.index).tz_localize(None)
                    all_hist[t] = close
            if len(all_hist) < 2:
                return None, None, None
            price_df = pd.DataFrame(all_hist).dropna(how="all").ffill()
            returns_df = price_df.pct_change().fillna(0)
            port_syms = [s for s in symbols if s in returns_df.columns]
            if not port_syms:
                return None, None, None
            avail_w = sum(weights[s] for s in port_syms)
            norm_w = {s: weights[s] / avail_w for s in port_syms} if avail_w > 0 else {}
            port_ret = sum(returns_df[s] * norm_w[s] for s in port_syms)
            port_cum = (1 + port_ret).cumprod() - 1
            bench_cum = None
            if bench_ticker in returns_df.columns:
                bench_cum = (1 + returns_df[bench_ticker]).cumprod() - 1
            return port_cum, bench_cum, returns_df

        holdings_for_perf = tuple(
            (row["symbol"], row["weight"])
            for _, row in tam_df.iterrows()
            if row["symbol"] not in ["CASH", ""]
        )

        port_cum, bench_cum, returns_df = _compute_perf(
            holdings_for_perf, bench_info["ticker"], yf_period
        )

        if port_cum is not None:
            # Cumulative return chart
            fig2 = go.Figure()
            r, g, b = int(strat_color[1:3],16), int(strat_color[3:5],16), int(strat_color[5:7],16)
            fig2.add_trace(go.Scatter(
                x=port_cum.index, y=port_cum.values * 100,
                name=STRATEGY_NAMES.get(active, active),
                fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.08)",
                line=dict(color=strat_color, width=2.5),
            ))
            if bench_cum is not None:
                fig2.add_trace(go.Scatter(
                    x=bench_cum.index, y=bench_cum.values * 100,
                    name=bench_info["name"],
                    line=dict(color="rgba(255,255,255,0.3)", width=1.5, dash="dot"),
                ))
            fig2.update_layout(
                title=f"Cumulative Return — {period}",
                **PLOTLY_DARK,
                xaxis=_XAXIS,
                yaxis={**_YAXIS, "ticksuffix": "%"},
                height=360,
                hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True)

            # KPIs
            port_total = round(float(port_cum.iloc[-1]) * 100, 2)
            bench_total = round(float(bench_cum.iloc[-1]) * 100, 2) if bench_cum is not None else 0
            alpha_val = round(port_total - bench_total, 2)

            # Risk calcs
            port_syms = [s for s, w in holdings_for_perf if s in returns_df.columns]
            avail_w = sum(w for s, w in holdings_for_perf if s in returns_df.columns)
            norm_w = {s: w / avail_w for s, w in holdings_for_perf if s in returns_df.columns} if avail_w > 0 else {}
            port_daily = sum(returns_df[s] * norm_w[s] for s in port_syms) if port_syms else pd.Series([0])

            ann_vol = float(port_daily.std() * np.sqrt(252) * 100) if len(port_daily) > 1 else 0
            ann_return = float(port_total * (252 / max(len(port_daily), 1)))
            sharpe = round(ann_return / ann_vol, 2) if ann_vol > 0 else 0

            cum_wealth = (1 + port_daily).cumprod()
            running_max = cum_wealth.cummax()
            drawdown = (cum_wealth - running_max) / running_max
            max_dd = round(float(drawdown.min()) * 100, 2)

            beta_val = 0
            if bench_info["ticker"] in returns_df.columns:
                bench_daily = returns_df[bench_info["ticker"]]
                cov = port_daily.cov(bench_daily)
                var = bench_daily.var()
                beta_val = round(cov / var, 2) if var > 0 else 0

            downside = port_daily[port_daily < 0]
            ds_std = float(downside.std() * np.sqrt(252) * 100) if len(downside) > 1 else 0
            sortino = round(ann_return / ds_std, 2) if ds_std > 0 else 0

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            with m1: st.metric("Strategy Return", f"{port_total:+.2f}%")
            with m2: st.metric("Benchmark", f"{bench_total:+.2f}%")
            with m3: st.metric("Alpha", f"{alpha_val:+.2f}%")
            with m4: st.metric("Sharpe", f"{sharpe}")
            with m5: st.metric("Max Drawdown", f"{max_dd}%")
            with m6: st.metric("Beta", f"{beta_val}")

            # Attribution + Risk detail
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Top Contributors**")
                contribs = []
                for sym in port_syms:
                    if sym in returns_df.columns:
                        total_r = float((1 + returns_df[sym]).prod() - 1) * 100
                        wt = norm_w.get(sym, 0)
                        contribs.append({
                            "Symbol": sym,
                            "Weight %": round(wt * 100, 2),
                            "Return %": round(total_r, 2),
                            "Contribution %": round(total_r * wt, 3),
                        })
                contrib_df = pd.DataFrame(contribs).sort_values("Contribution %", ascending=False)
                st.dataframe(contrib_df.head(10), hide_index=True, use_container_width=True,
                    column_config={
                        "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Contribution %": st.column_config.NumberColumn(format="%.3f%%"),
                        "Weight %": st.column_config.NumberColumn(format="%.2f%%"),
                    })

            with c2:
                st.markdown("**Risk Metrics**")
                st.dataframe(pd.DataFrame({
                    "Metric": ["Sharpe Ratio","Sortino Ratio","Beta","Max Drawdown","Ann. Volatility"],
                    "Value": [f"{sharpe:.2f}", f"{sortino:.2f}", f"{beta_val:.2f}", f"{max_dd:.2f}%", f"{ann_vol:.1f}%"],
                }), hide_index=True, use_container_width=True)

            # Drawdown chart
            if len(port_daily) > 1:
                st.divider()
                st.markdown("**Drawdown**")
                fig_dd = go.Figure()
                fig_dd.add_trace(go.Scatter(
                    x=drawdown.index, y=drawdown.values * 100,
                    fill="tozeroy", fillcolor="rgba(196,84,84,0.15)",
                    line=dict(color="#c45454", width=1.5), name="Drawdown",
                ))
                fig_dd.update_layout(**PLOTLY_DARK, xaxis=_XAXIS, yaxis={**_YAXIS, "ticksuffix": "%"}, height=220, showlegend=False)
                st.plotly_chart(fig_dd, use_container_width=True)

            # Monthly Returns Heatmap
            if port_daily is not None and len(port_daily) > 20:
                st.divider()
                st.markdown("**Monthly Returns Heatmap**")

                monthly_ret = port_daily.resample("ME").apply(lambda x: (1 + x).prod() - 1) * 100
                hm_df = pd.DataFrame({
                    "year": monthly_ret.index.year,
                    "month": monthly_ret.index.month,
                    "return": monthly_ret.values,
                })
                month_labels = ["Jan","Feb","Mar","Apr","May","Jun",
                                "Jul","Aug","Sep","Oct","Nov","Dec"]

                # Only show full years (all 12 months present)
                year_counts = hm_df.groupby("year")["month"].count()
                full_years = year_counts[year_counts == 12].index.tolist()

                # Also include current year even if partial
                current_year = datetime.now().year
                if current_year not in full_years:
                    if current_year in hm_df["year"].values:
                        full_years.append(current_year)
                        full_years.sort()

                hm_filtered = hm_df[hm_df["year"].isin(full_years)]

                if len(hm_filtered) > 0:
                    pivot = hm_filtered.pivot(index="year", columns="month", values="return")
                    pivot.columns = [month_labels[m-1] for m in pivot.columns]

                    colorscale = [
                        [0.0, "#c45454"], [0.35, "#c45454"],
                        [0.45, "#1a1a2e"], [0.5, "#1a1a2e"], [0.55, "#1a1a2e"],
                        [0.65, "#569542"], [1.0, "#569542"],
                    ]
                    text_vals = [[f"{v:+.1f}%" if pd.notna(v) else "" for v in row] for row in pivot.values]

                    fig_hm = go.Figure(data=go.Heatmap(
                        z=pivot.values,
                        x=pivot.columns.tolist(),
                        y=[str(y) for y in pivot.index.tolist()],
                        text=text_vals,
                        texttemplate="%{text}",
                        textfont=dict(size=11, color="rgba(255,255,255,0.8)"),
                        colorscale=colorscale,
                        zmid=0,
                        showscale=False,
                        hovertemplate="%{y} %{x}: %{text}<extra></extra>",
                        xgap=3, ygap=3,
                    ))
                    fig_hm.update_layout(
                        paper_bgcolor="rgba(255,255,255,0.02)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
                        margin=dict(l=10, r=10, t=10, b=10),
                        height=max(120, len(full_years) * 50 + 60),
                        yaxis=dict(
                            autorange="reversed",
                            gridcolor="rgba(255,255,255,0.04)",
                            showline=False, tickfont=dict(size=11),
                        ),
                        xaxis=dict(
                            gridcolor="rgba(255,255,255,0.04)",
                            showline=False, tickfont=dict(size=10),
                            side="top",
                        ),
                    )
                    st.plotly_chart(fig_hm, use_container_width=True)

            st.caption(f"Weighted returns using Tamarac holdings • {datetime.now().strftime('%I:%M %p')}")

        else:
            st.warning("Unable to compute returns — yfinance may be unreachable.")

    # ── Sprint 1 fallback ─────────────────────────────────────────────────
    else:
        perf_df = get_perf_chart_data(active, strat["bench_ticker"])
        alpha = round(float(kpis.get("ytd", 0)) - float(bench_ytd), 2)

        fig2 = go.Figure()
        r, g, b = int(strat["color"][1:3],16), int(strat["color"][3:5],16), int(strat["color"][5:7],16)
        fig2.add_trace(go.Scatter(
            x=perf_df["month"], y=perf_df["strategy"],
            name=active, fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},0.08)",
            line=dict(color=strat["color"], width=2.5),
        ))
        fig2.add_trace(go.Scatter(
            x=perf_df["month"], y=perf_df["benchmark"],
            name=strat["bench"],
            line=dict(color="rgba(255,255,255,0.3)", width=1.5, dash="dot"),
        ))
        fig2.update_layout(
            title="YTD Cumulative Return — Strategy vs Benchmark",
            **PLOTLY_DARK,
            xaxis=_XAXIS,
            yaxis={**_YAXIS, "ticksuffix": "%"},
            height=320,
        )
        st.plotly_chart(fig2, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Return Attribution**")
            st.dataframe(pd.DataFrame({
                "Source": ["Security Selection","Sector Allocation","Interaction Effect","Total Alpha"],
                "Contribution": ["+0.84%","+0.31%","+0.12%",f"+{alpha:.2f}%"],
            }), hide_index=True, use_container_width=True)
        with c2:
            st.markdown("**Risk Metrics**")
            st.dataframe(pd.DataFrame({
                "Metric": ["Sharpe Ratio","Sortino Ratio","Beta","Max Drawdown","Tracking Error","Info Ratio"],
                "Value": ["1.42","1.87","0.82","-6.2%","3.41%","0.37"],
            }), hide_index=True, use_container_width=True)


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
            def _avg_growth(key, min_years):
                vals = [div_data[t].get(key, 0) for t in tickers
                        if t in div_data
                        and div_data[t].get(key, 0) != 0
                        and div_data[t].get("div_growth_years", 0) >= min_years
                        and -50 < div_data[t].get(key, 0) < 100]
                return round(sum(vals) / len(vals), 1) if vals else 0

            avg_growth_1y = _avg_growth("div_growth_1y", 2)
            avg_growth_3y = _avg_growth("div_growth_3y", 4)
            avg_growth_5y = _avg_growth("div_growth_5y", 6)

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
                st.plotly_chart(fig3, use_container_width=True)

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
                st.plotly_chart(fig4, use_container_width=True)

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
        ]), hide_index=True, use_container_width=True)

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
            st.plotly_chart(fig3, use_container_width=True)


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