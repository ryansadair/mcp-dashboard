"""
Martin Capital Partners — Stock Detail Page
pages/2_Stock_Detail.py

Dedicated detail page for individual holdings.
Accessed via ticker selector or linked from Holdings tab.

Sections:
  1. Company Profile header
  2. Price chart with 50/200 day moving averages
  3. Dividend history (annual payments + growth)
  4. Valuation metrics
  5. Revenue / earnings / margins
  6. Analyst targets & recommendations
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from utils.auth import check_password
from utils.styles import inject_global_css
from utils.config import BRAND
from components.header import render_header
from components.market_ticker import render_market_ticker

if not check_password():
    st.stop()

inject_global_css()
render_header()
render_market_ticker()

# ── Brand constants ───────────────────────────────────────────────────────
GREEN = BRAND.get("green", "#569542")
BLUE = BRAND.get("blue", "#07415A")
GOLD = BRAND.get("gold", "#C9A84C")
BG = "#0c1117"

PLOTLY_DARK = dict(
    paper_bgcolor="rgba(255,255,255,0.02)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10)),
    yaxis=dict(gridcolor="rgba(255,255,255,0.04)", showline=False, tickfont=dict(size=10)),
    margin=dict(l=10, r=10, t=40, b=10),
)

# ── Get all holdings tickers for the selector ─────────────────────────────
available_tickers = []
try:
    from data.tamarac_parser import parse_tamarac_excel
    import os
    for p in ["data/Tamarac_Holdings.xlsx", "Tamarac_Holdings.xlsx"]:
        if os.path.exists(p):
            @st.cache_data(ttl=300)
            def _load(path):
                return parse_tamarac_excel(path)
            parsed = _load(p)
            # Collect all unique tickers across strategies
            for strat_key, strat_data in parsed.items():
                if isinstance(strat_data, pd.DataFrame) and "symbol" in strat_data.columns:
                    available_tickers.extend(strat_data["symbol"].tolist())
                elif isinstance(strat_data, dict) and "holdings" in strat_data:
                    available_tickers.extend([h["symbol"] for h in strat_data["holdings"]])
            available_tickers = sorted(set(available_tickers))
            break
except Exception:
    pass

# ── Ticker Selector ───────────────────────────────────────────────────────
col_sel, col_back = st.columns([3, 1])
with col_sel:
    # Check if coming from Holdings tab with a pre-selected ticker
    default_ticker = st.query_params.get("ticker", "AMGN").upper()
    ticker_input = st.text_input(
        "Enter Ticker Symbol",
        value=default_ticker,
        placeholder="e.g. AMGN, MSFT, JNJ...",
        key="detail_ticker_input",
    ).strip().upper()
with col_back:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("← Back to Dashboard", key="back_btn"):
        st.switch_page("pages/1_Dashboard.py")

if not ticker_input:
    st.info("Enter a ticker symbol above to view stock details.")
    st.stop()


# ── Fetch all data ────────────────────────────────────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def fetch_stock_data(ticker):
    """Fetch comprehensive stock data from yfinance."""
    tk = yf.Ticker(ticker)
    info = tk.info or {}

    # Price history (2 years for chart + MAs)
    hist = tk.history(period="2y")

    # Longer history for dividends
    div_hist = tk.dividends

    # Financials
    try:
        financials = tk.financials
    except Exception:
        financials = pd.DataFrame()

    try:
        quarterly_financials = tk.quarterly_financials
    except Exception:
        quarterly_financials = pd.DataFrame()

    # Recommendations
    try:
        recs = tk.recommendations
    except Exception:
        recs = pd.DataFrame()

    return {
        "info": info,
        "history": hist,
        "dividends": div_hist,
        "financials": financials,
        "quarterly_financials": quarterly_financials,
        "recommendations": recs,
    }


with st.spinner(f"Loading {ticker_input}..."):
    try:
        data = fetch_stock_data(ticker_input)
    except Exception as e:
        st.error(f"Could not fetch data for '{ticker_input}': {e}")
        st.stop()

info = data["info"]
hist = data["history"]
divs = data["dividends"]

if not info.get("longName") and not info.get("shortName"):
    st.error(f"No data found for '{ticker_input}'. Check the ticker symbol.")
    st.stop()

# ── Helper ────────────────────────────────────────────────────────────────
def g(key, default=""):
    val = info.get(key, default)
    return val if val is not None else default


# ══════════════════════════════════════════════════════════════════════════
# 1. COMPANY PROFILE HEADER
# ══════════════════════════════════════════════════════════════════════════
company_name = g("longName") or g("shortName", ticker_input)
sector = g("sector", "—")
industry = g("industry", "—")
price = g("currentPrice", 0) or g("regularMarketPrice", 0)
prev_close = g("previousClose", 0)
change = price - prev_close if price and prev_close else 0
change_pct = (change / prev_close * 100) if prev_close else 0
chg_color = GREEN if change >= 0 else "#c45454"

# Market cap
mc_raw = g("marketCap", 0)
if mc_raw >= 1e12:
    mc_str = f"${mc_raw/1e12:.2f}T"
elif mc_raw >= 1e9:
    mc_str = f"${mc_raw/1e9:.1f}B"
elif mc_raw >= 1e6:
    mc_str = f"${mc_raw/1e6:.0f}M"
else:
    mc_str = "—"

# Dividend yield (safe)
div_rate = g("dividendRate", 0) or 0
div_yield = round((div_rate / price) * 100, 2) if div_rate > 0 and price > 0 and (div_rate / price * 100) <= 15 else 0

st.markdown(
    f"<div style='padding:16px 20px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
    f"border-radius:12px;margin-bottom:16px;'>"
    f"<div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;'>"
    f"<div>"
    f"<div style='font-size:24px;font-weight:700;color:{GOLD};letter-spacing:0.04em;font-family:DM Serif Display,serif;'>{ticker_input}</div>"
    f"<div style='font-size:16px;color:rgba(255,255,255,0.8);margin-top:2px;'>{company_name}</div>"
    f"<div style='font-size:12px;color:rgba(255,255,255,0.35);margin-top:4px;'>{sector} · {industry}</div>"
    f"</div>"
    f"<div style='text-align:right;'>"
    f"<div style='font-size:28px;font-weight:700;color:rgba(255,255,255,0.95);font-family:DM Serif Display,serif;'>${price:.2f}</div>"
    f"<div style='font-size:14px;color:{chg_color};font-weight:600;'>{change:+.2f} ({change_pct:+.2f}%)</div>"
    f"</div>"
    f"</div>"
    f"</div>",
    unsafe_allow_html=True,
)

# Quick stats row
qs1, qs2, qs3, qs4, qs5, qs6 = st.columns(6)
qs1.metric("Mkt Cap", mc_str)
qs2.metric("Div Yield", f"{div_yield:.2f}%" if div_yield > 0 else "—")
qs3.metric("Div Rate", f"${div_rate:.2f}" if div_rate > 0 else "—")
qs4.metric("P/E", f"{g('trailingPE', 0):.1f}" if g("trailingPE", 0) else "—")
qs5.metric("52W High", f"${g('fiftyTwoWeekHigh', 0):.2f}" if g("fiftyTwoWeekHigh", 0) else "—")
qs6.metric("52W Low", f"${g('fiftyTwoWeekLow', 0):.2f}" if g("fiftyTwoWeekLow", 0) else "—")


# ══════════════════════════════════════════════════════════════════════════
# 2. PRICE CHART WITH MOVING AVERAGES
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 📈 Price Chart")

if not hist.empty:
    period_options = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "2Y": 504}
    period_cols = st.columns(len(period_options))
    if "chart_period" not in st.session_state:
        st.session_state["chart_period"] = "1Y"
    for i, (label, _) in enumerate(period_options.items()):
        with period_cols[i]:
            if st.button(label, key=f"period_{label}", use_container_width=True,
                         type="primary" if st.session_state["chart_period"] == label else "secondary"):
                st.session_state["chart_period"] = label
                st.rerun()

    selected_period = st.session_state["chart_period"]

    chart_hist = hist.copy()
    if selected_period == "YTD":
        year_start = datetime(datetime.now().year, 1, 1)
        chart_hist = chart_hist[chart_hist.index >= year_start.strftime("%Y-%m-%d")]
    elif period_options[selected_period]:
        chart_hist = chart_hist.tail(period_options[selected_period])

    # Calculate MAs on full history, then slice for display
    hist["MA50"] = hist["Close"].rolling(50).mean()
    hist["MA200"] = hist["Close"].rolling(200).mean()
    chart_ma = hist.loc[chart_hist.index]

    fig_price = go.Figure()

    # Price line
    fig_price.add_trace(go.Scatter(
        x=chart_ma.index, y=chart_ma["Close"],
        mode="lines", name="Price",
        line=dict(color=GREEN, width=2),
    ))

    # 50-day MA
    if not chart_ma["MA50"].isna().all():
        fig_price.add_trace(go.Scatter(
            x=chart_ma.index, y=chart_ma["MA50"],
            mode="lines", name="50 MA",
            line=dict(color=GOLD, width=1, dash="dot"),
        ))

    # 200-day MA
    if not chart_ma["MA200"].isna().all():
        fig_price.add_trace(go.Scatter(
            x=chart_ma.index, y=chart_ma["MA200"],
            mode="lines", name="200 MA",
            line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dash"),
        ))

    fig_price.update_layout(
        **PLOTLY_DARK,
        height=350,
        hovermode="x unified",
        yaxis_title="Price ($)",
    )
    st.plotly_chart(fig_price, use_container_width=True)
else:
    st.info("No price history available.")


# ══════════════════════════════════════════════════════════════════════════
# 3. DIVIDEND HISTORY
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 💰 Dividend History")

if not divs.empty and len(divs) >= 2:
    div_df = divs.reset_index()
    div_df.columns = ["date", "amount"]
    div_df["year"] = pd.to_datetime(div_df["date"]).dt.year
    annual_divs = div_df.groupby("year")["amount"].sum().reset_index()
    annual_divs.columns = ["Year", "Annual Dividend"]

    col_div_chart, col_div_stats = st.columns([2, 1])

    with col_div_chart:
        # Annual dividend bar chart
        colors = [GREEN if i == len(annual_divs) - 1 else BLUE for i in range(len(annual_divs))]
        fig_div = go.Figure()
        fig_div.add_trace(go.Bar(
            x=annual_divs["Year"],
            y=annual_divs["Annual Dividend"],
            marker_color=colors,
            text=[f"${d:.2f}" for d in annual_divs["Annual Dividend"]],
            textposition="outside",
            textfont=dict(size=10, color="rgba(255,255,255,0.5)"),
        ))
        fig_div.update_layout(
            **PLOTLY_DARK,
            height=300,
            title="Annual Dividends Per Share",
            yaxis_title="$/Share",
            showlegend=False,
        )
        st.plotly_chart(fig_div, use_container_width=True)

    with col_div_stats:
        # Growth stats
        current_year = datetime.now().year
        completed = annual_divs[annual_divs["Year"] < current_year]

        if len(completed) >= 2:
            latest = completed.iloc[-1]["Annual Dividend"]
            prev = completed.iloc[-2]["Annual Dividend"]
            yoy = ((latest / prev) - 1) * 100 if prev > 0 else 0
            st.metric("Latest Annual Div", f"${latest:.2f}")
            st.metric("YoY Growth", f"{yoy:+.1f}%")

        if len(completed) >= 4:
            y3 = completed.iloc[-4]["Annual Dividend"]
            cagr3 = ((completed.iloc[-1]["Annual Dividend"] / y3) ** (1/3) - 1) * 100 if y3 > 0 else 0
            st.metric("3Y CAGR", f"{cagr3:+.1f}%")

        if len(completed) >= 6:
            y5 = completed.iloc[-6]["Annual Dividend"]
            cagr5 = ((completed.iloc[-1]["Annual Dividend"] / y5) ** (1/5) - 1) * 100 if y5 > 0 else 0
            st.metric("5Y CAGR", f"{cagr5:+.1f}%")

        # Consecutive years
        if len(completed) >= 2:
            consec = 0
            for i in range(len(completed) - 1, 0, -1):
                if completed.iloc[i]["Annual Dividend"] > completed.iloc[i-1]["Annual Dividend"] * 0.99:
                    consec += 1
                else:
                    break
            st.metric("Consec. Increases", f"{consec} yrs")

        # Ex-date
        ex_str = ""
        ex_div = info.get("exDividendDate")
        if ex_div and isinstance(ex_div, (int, float)):
            try:
                ex_str = datetime.fromtimestamp(ex_div).strftime("%b %d, %Y")
            except Exception:
                pass
        if ex_str:
            st.metric("Next Ex-Date", ex_str)

else:
    st.info("No dividend history available for this ticker.")


# ══════════════════════════════════════════════════════════════════════════
# 4. VALUATION METRICS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 📊 Valuation")

v1, v2, v3, v4, v5, v6 = st.columns(6)
v1.metric("P/E (TTM)", f"{g('trailingPE', 0):.1f}" if g("trailingPE", 0) else "—")
v2.metric("Fwd P/E", f"{g('forwardPE', 0):.1f}" if g("forwardPE", 0) else "—")
v3.metric("PEG Ratio", f"{g('pegRatio', 0):.2f}" if g("pegRatio", 0) else "—")
v4.metric("P/B", f"{g('priceToBook', 0):.2f}" if g("priceToBook", 0) else "—")
v5.metric("P/S (TTM)", f"{g('priceToSalesTrailing12Months', 0):.2f}" if g("priceToSalesTrailing12Months", 0) else "—")
v6.metric("EV/EBITDA", f"{g('enterpriseToEbitda', 0):.1f}" if g("enterpriseToEbitda", 0) else "—")

# Second row
vv1, vv2, vv3, vv4, vv5, vv6 = st.columns(6)
vv1.metric("Beta", f"{g('beta', 0):.2f}" if g("beta", 0) else "—")

payout_raw = g("payoutRatio", 0)
payout_pct = round(payout_raw * 100, 1) if isinstance(payout_raw, (int, float)) and 0 < payout_raw < 5 else 0
vv2.metric("Payout Ratio", f"{payout_pct:.1f}%" if payout_pct > 0 else "—")

# EV formatting
ev_raw = g("enterpriseValue", 0)
if ev_raw >= 1e12:
    ev_str = f"${ev_raw/1e12:.2f}T"
elif ev_raw >= 1e9:
    ev_str = f"${ev_raw/1e9:.1f}B"
else:
    ev_str = "—"
vv3.metric("Enterprise Value", ev_str)

vv4.metric("ROE", f"{g('returnOnEquity', 0)*100:.1f}%" if isinstance(g("returnOnEquity", 0), (int, float)) and g("returnOnEquity", 0) else "—")
vv5.metric("Debt/Equity", f"{g('debtToEquity', 0):.0f}%" if g("debtToEquity", 0) else "—")
vv6.metric("Current Ratio", f"{g('currentRatio', 0):.2f}" if g("currentRatio", 0) else "—")


# ══════════════════════════════════════════════════════════════════════════
# 5. REVENUE / EARNINGS / MARGINS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 💵 Financials")

financials = data.get("financials", pd.DataFrame())

if not financials.empty:
    try:
        # yfinance financials are columns = dates, rows = line items
        fin = financials.T.sort_index()

        rev_row = None
        for label in ["Total Revenue", "Operating Revenue"]:
            if label in financials.index:
                rev_row = label
                break

        ni_row = None
        for label in ["Net Income", "Net Income Common Stockholders"]:
            if label in financials.index:
                ni_row = label
                break

        gp_row = "Gross Profit" if "Gross Profit" in financials.index else None
        op_row = None
        for label in ["Operating Income", "EBIT"]:
            if label in financials.index:
                op_row = label
                break

        if rev_row:
            rev_data = fin[rev_row].dropna()
            years = [d.strftime("%Y") for d in rev_data.index]
            rev_vals = (rev_data / 1e9).round(2)  # Convert to billions

            col_rev, col_margin = st.columns([2, 1])

            with col_rev:
                fig_fin = go.Figure()
                fig_fin.add_trace(go.Bar(
                    x=years, y=rev_vals,
                    name="Revenue",
                    marker_color=BLUE,
                    text=[f"${v:.1f}B" for v in rev_vals],
                    textposition="outside",
                    textfont=dict(size=10, color="rgba(255,255,255,0.5)"),
                ))
                if ni_row:
                    ni_data = fin[ni_row].dropna()
                    ni_vals = (ni_data / 1e9).round(2)
                    fig_fin.add_trace(go.Bar(
                        x=years, y=ni_vals,
                        name="Net Income",
                        marker_color=GREEN,
                        text=[f"${v:.1f}B" for v in ni_vals],
                        textposition="outside",
                        textfont=dict(size=10, color="rgba(255,255,255,0.5)"),
                    ))
                fig_fin.update_layout(
                    **PLOTLY_DARK,
                    height=300,
                    title="Revenue & Net Income ($B)",
                    barmode="group",
                    showlegend=True,
                )
                st.plotly_chart(fig_fin, use_container_width=True)

            with col_margin:
                st.markdown("**Margins**")
                # Gross margin
                if gp_row and rev_row:
                    gm = fin[gp_row].iloc[-1] / fin[rev_row].iloc[-1] * 100 if fin[rev_row].iloc[-1] > 0 else 0
                    st.metric("Gross Margin", f"{gm:.1f}%")
                # Operating margin
                if op_row and rev_row:
                    om = fin[op_row].iloc[-1] / fin[rev_row].iloc[-1] * 100 if fin[rev_row].iloc[-1] > 0 else 0
                    st.metric("Operating Margin", f"{om:.1f}%")
                # Net margin
                if ni_row and rev_row:
                    nm = fin[ni_row].iloc[-1] / fin[rev_row].iloc[-1] * 100 if fin[rev_row].iloc[-1] > 0 else 0
                    st.metric("Net Margin", f"{nm:.1f}%")
                # FCF
                fcf = g("freeCashflow", 0)
                if fcf:
                    if fcf >= 1e9:
                        st.metric("Free Cash Flow", f"${fcf/1e9:.1f}B")
                    elif fcf >= 1e6:
                        st.metric("Free Cash Flow", f"${fcf/1e6:.0f}M")
    except Exception as e:
        st.caption(f"Could not parse financials: {e}")
else:
    st.info("Financial data not available for this ticker.")


# ══════════════════════════════════════════════════════════════════════════
# 6. ANALYST TARGETS & RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 🎯 Analyst Estimates")

target_high = g("targetHighPrice", 0)
target_low = g("targetLowPrice", 0)
target_mean = g("targetMeanPrice", 0)
target_median = g("targetMedianPrice", 0)
num_analysts = g("numberOfAnalystOpinions", 0)
rec = g("recommendationKey", "")

if target_mean and price:
    col_target, col_rec = st.columns([2, 1])

    with col_target:
        # Price target visual
        fig_target = go.Figure()

        # Range bar
        fig_target.add_trace(go.Bar(
            y=["Target"],
            x=[target_high - target_low],
            base=[target_low],
            orientation="h",
            marker_color="rgba(255,255,255,0.06)",
            showlegend=False,
            hoverinfo="skip",
        ))

        # Current price marker
        fig_target.add_trace(go.Scatter(
            x=[price], y=["Target"],
            mode="markers",
            marker=dict(color=GREEN, size=14, symbol="diamond"),
            name=f"Current: ${price:.2f}",
        ))

        # Mean target marker
        fig_target.add_trace(go.Scatter(
            x=[target_mean], y=["Target"],
            mode="markers",
            marker=dict(color=GOLD, size=14, symbol="star"),
            name=f"Mean Target: ${target_mean:.2f}",
        ))

        # Low/High annotations
        fig_target.add_annotation(x=target_low, y="Target", text=f"${target_low:.0f}", showarrow=False, yshift=-20,
                                  font=dict(size=10, color="rgba(255,255,255,0.4)"))
        fig_target.add_annotation(x=target_high, y="Target", text=f"${target_high:.0f}", showarrow=False, yshift=-20,
                                  font=dict(size=10, color="rgba(255,255,255,0.4)"))

        fig_target.update_layout(
            **PLOTLY_DARK,
            height=120,
            title=f"Analyst Price Targets ({num_analysts} analysts)",
            yaxis=dict(visible=False),
            xaxis=dict(title="Price ($)", gridcolor="rgba(255,255,255,0.04)"),
            margin=dict(l=10, r=10, t=40, b=30),
        )
        st.plotly_chart(fig_target, use_container_width=True)

    with col_rec:
        upside = ((target_mean - price) / price) * 100 if price > 0 else 0
        upside_color = GREEN if upside >= 0 else "#c45454"
        st.metric("Consensus", rec.replace("_", " ").title() if rec else "—")
        st.metric("Mean Target", f"${target_mean:.2f}")
        st.metric("Upside/Downside", f"{upside:+.1f}%")
        st.metric("Median Target", f"${target_median:.2f}")

else:
    st.info("No analyst estimates available for this ticker.")


# ══════════════════════════════════════════════════════════════════════════
# COMPANY DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════
desc = g("longBusinessSummary", "")
if desc:
    st.markdown("---")
    with st.expander("📄 Company Description", expanded=False):
        st.markdown(f"<div style='font-size:13px;color:rgba(255,255,255,0.6);line-height:1.7;'>{desc}</div>",
                    unsafe_allow_html=True)

        # Extra details
        ed1, ed2, ed3 = st.columns(3)
        employees = g("fullTimeEmployees", 0)
        ed1.metric("Employees", f"{employees:,}" if employees else "—")
        ed2.metric("Country", g("country", "—"))
        ed3.metric("Website", g("website", "—"))


# ── Footer ────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='display:flex;gap:12px;justify-content:center;padding:16px 28px;margin-top:20px;"
    "border-top:1px solid rgba(255,255,255,0.04);font-size:11px;color:rgba(255,255,255,0.2);'>"
    "<span>© 2026 Martin Capital Partners LLC</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Data: yfinance</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Internal use only</span>"
    "</div>",
    unsafe_allow_html=True,
)