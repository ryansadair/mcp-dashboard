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
import requests
import yfinance as yf
from datetime import datetime, timedelta
from utils.auth import check_password
from utils.styles import inject_global_css
from utils.config import BRAND
from components.header import render_header
from components.market_ticker import render_market_ticker

# Fish CCC data (authoritative dividend history + streaks)
try:
    from data.dividend_streaks import get_all_fish_data, get_dividend_history as get_fish_history
    _FISH_AVAILABLE = True
except ImportError:
    _FISH_AVAILABLE = False

# ── Supabase config ────────────────────────────────────────────────────────
SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
SUPABASE_KEY = "sb_secret_P1XNpklX_g_gcMamZb0qqw_udXSu8T7"   # paste your service role key here

_SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def _sb_get_ticker(ticker):
    """
    Pull price + dividend data from Supabase for a single ticker.
    Returns a partial `info` dict compatible with yfinance's tk.info format.
    """
    try:
        # Prices
        pr = requests.get(
            f"{SUPABASE_URL}/rest/v1/prices",
            headers=_SB_HEADERS,
            params={"select": "*", "ticker": f"eq.{ticker}"},
            timeout=10,
        ).json()

        # Dividends
        dv = requests.get(
            f"{SUPABASE_URL}/rest/v1/dividends",
            headers=_SB_HEADERS,
            params={"select": "*", "ticker": f"eq.{ticker}"},
            timeout=10,
        ).json()

        if not pr:
            return {}

        p = pr[0]
        d = dv[0] if dv else {}

        # Map Supabase fields → yfinance info keys so rest of page works unchanged
        return {
            "longName":                          p.get("long_name") or p.get("name", ticker),
            "shortName":                         p.get("name", ticker),
            "sector":                            p.get("sector", ""),
            "industry":                          p.get("industry", ""),
            "currentPrice":                      p.get("price", 0),
            "previousClose":                     p.get("previous_close", 0),
            "regularMarketPrice":                p.get("price", 0),
            "marketCap":                         p.get("market_cap", 0),
            "trailingPE":                        p.get("pe_ratio", 0),
            "forwardPE":                         p.get("forward_pe", 0),
            "priceToBook":                       p.get("price_to_book", 0),
            "beta":                              p.get("beta", 0),
            "fiftyTwoWeekHigh":                  p.get("week52_high", 0),
            "fiftyTwoWeekLow":                   p.get("week52_low", 0),
            # Valuation
            "pegRatio":                          p.get("peg_ratio", 0),
            "priceToSalesTrailing12Months":       p.get("price_to_sales", 0),
            "enterpriseToEbitda":                p.get("ev_ebitda", 0),
            "enterpriseValue":                   p.get("enterprise_value", 0),
            "returnOnEquity":                    p.get("return_on_equity", 0),
            "debtToEquity":                      p.get("debt_to_equity", 0),
            "currentRatio":                      p.get("current_ratio", 0),
            "freeCashflow":                      p.get("free_cashflow", 0),
            "grossMargins":                      p.get("gross_margins", 0),
            "operatingMargins":                  p.get("operating_margins", 0),
            "profitMargins":                     p.get("profit_margins", 0),
            # Company profile
            "longBusinessSummary":               p.get("long_business_summary", ""),
            "fullTimeEmployees":                 p.get("full_time_employees", 0),
            "country":                           p.get("country", ""),
            "website":                           p.get("website", ""),
            # Dividends
            "dividendYield":                     (d.get("dividend_yield", 0) or 0) / 100,
            "dividendRate":                      d.get("dividend_rate", 0),
            "payoutRatio":                       (d.get("payout_ratio", 0) or 0) / 100,
            "exDividendDate":                    d.get("ex_dividend_date", ""),
            "fiveYearAvgDividendYield":          d.get("five_year_avg_yield", 0),
            "_from_supabase":                    True,
        }
    except Exception:
        return {}

def _sb_get_price_history(ticker):
    """Fetch full price history from Supabase for a ticker using limit/offset pagination."""
    try:
        all_rows = []
        offset = 0
        batch = 1000
        while True:
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/price_history",
                headers=_SB_HEADERS,
                params={
                    "select": "date,open,high,low,close,volume",
                    "ticker": f"eq.{ticker}",
                    "order": "date.asc",
                    "limit": str(batch),
                    "offset": str(offset),
                },
                timeout=20,
            )
            if resp.status_code != 200:
                break
            batch_rows = resp.json()
            if not batch_rows:
                break
            all_rows.extend(batch_rows)
            if len(batch_rows) < batch:
                break
            offset += batch
        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows)
        df["Date"] = pd.to_datetime(df["date"])
        df = df.set_index("Date")
        df = df.drop(columns=["date"], errors="ignore")
        df.columns = [c.capitalize() for c in df.columns]
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def _sb_get_dividend_history(ticker):
    """Fetch annual dividend history from Supabase for a ticker."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/dividend_history",
            headers=_SB_HEADERS,
            params={"select": "year,amount", "ticker": f"eq.{ticker}", "order": "year.asc"},
            timeout=10,
        )
        rows = resp.json() if resp.status_code == 200 else []
        if not rows:
            return pd.Series(dtype=float)
        df = pd.DataFrame(rows)
        s = pd.Series(df["amount"].values, index=pd.to_datetime(df["year"].astype(str)))
        return s
    except Exception:
        return pd.Series(dtype=float)


def _sb_get_financials(ticker):
    """Fetch quarterly financials from Supabase for a ticker."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/financials",
            headers=_SB_HEADERS,
            params={"select": "period,revenue,gross_profit,net_income,operating_income,ebitda,gross_margin,net_margin,op_margin",
                    "ticker": f"eq.{ticker}", "order": "period.desc", "limit": "12"},
            timeout=10,
        )
        rows = resp.json() if resp.status_code == 200 else []
        if not rows:
            return pd.DataFrame(), pd.DataFrame()
        df = pd.DataFrame(rows)
        df["period"] = pd.to_datetime(df["period"])
        df = df.set_index("period").sort_index()
        # Return same format as yfinance: rows=metrics, cols=dates
        num_cols = ["revenue","gross_profit","net_income","operating_income","ebitda"]
        fins = df[num_cols].T if num_cols[0] in df.columns else pd.DataFrame()
        fins.index = ["Total Revenue","Gross Profit","Net Income","Operating Income","EBITDA"]
        return fins, df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


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

PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "staticPlot": True,
}

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
    default_ticker = (
        st.query_params.get("ticker")
        or st.session_state.get("detail_ticker")
        or ""
    ).upper()
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
def _fetch_yfinance_with_retry(ticker, max_retries=3, delay=2):
    """
    Call yfinance with retry logic for rate limit (429) errors.
    Returns (yf_info, hist, div_hist, financials, quarterly_financials, recs)
    or raises the last exception if all retries fail.
    """
    import time
    last_err = None
    for attempt in range(max_retries):
        try:
            tk      = yf.Ticker(ticker)
            yf_info = tk.info or {}
            hist    = tk.history(period="max")
            divs    = tk.dividends
            fins    = pd.DataFrame()
            qfins   = pd.DataFrame()
            recs    = pd.DataFrame()
            try:
                fins  = tk.financials
            except Exception:
                pass
            try:
                qfins = tk.quarterly_financials
            except Exception:
                pass
            try:
                recs  = tk.recommendations
            except Exception:
                pass
            return yf_info, hist, divs, fins, qfins, recs
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "too many requests" in err_str or "rate limit" in err_str or "429" in err_str:
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))  # back off: 2s, 4s
                    continue
            break  # non-rate-limit error, don't retry
    raise last_err


@st.cache_data(ttl=900, show_spinner=False)
def fetch_stock_data(ticker):
    """
    Fetch comprehensive stock data.
    Info/fundamentals: Supabase first, yfinance fallback.
    History/financials/recs: yfinance with retry, graceful degradation if unavailable.
    """
    # 1. Get info/fundamentals from Supabase
    info = _sb_get_ticker(ticker)

    # 2. Get history/dividends/financials from Supabase
    hist                 = _sb_get_price_history(ticker)
    div_hist             = _sb_get_dividend_history(ticker)
    financials, quarterly_financials = _sb_get_financials(ticker)
    recs                 = pd.DataFrame()
    yf_warning           = None

    # 3. Fall back to yfinance for anything missing from Supabase
    sb_has_hist = not hist.empty
    sb_has_fins = not financials.empty

    try:
        yf_info, yf_hist, yf_divs, yf_fins, yf_qfins, recs = \
            _fetch_yfinance_with_retry(ticker)

        # Merge info — prefer yfinance for richer fields
        if yf_info.get("longName") or yf_info.get("shortName"):
            info = {**info, **yf_info}
        # Only use yfinance history/fins if Supabase was empty
        if not sb_has_hist and not yf_hist.empty:
            hist = yf_hist
        if div_hist.empty and not yf_divs.empty:
            div_hist = yf_divs
        if not sb_has_fins and not yf_fins.empty:
            financials = yf_fins
            quarterly_financials = yf_qfins

    except Exception as e:
        err_str = str(e).lower()
        if "too many requests" in err_str or "rate limit" in err_str or "429" in err_str:
            if not sb_has_hist:
                yf_warning = "yfinance rate limited — price chart unavailable until next prefetch."
        else:
            if not sb_has_hist:
                yf_warning = f"yfinance unavailable ({e}) — showing cached data where available."

        # If Supabase also has nothing, we truly have no data
        if not info:
            raise Exception(f"No data available for '{ticker}'. Check the ticker symbol and try again.")

    return {
        "info":                  info,
        "history":               hist,
        "dividends":             div_hist,
        "financials":            financials,
        "quarterly_financials":  quarterly_financials,
        "recommendations":       recs,
        "yf_warning":            yf_warning,
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
yf_warning = data.get("yf_warning")

if not info.get("longName") and not info.get("shortName"):
    st.error(f"No data found for '{ticker_input}'. Check the ticker symbol.")
    st.stop()

if yf_warning:
    st.warning(f"⚠️ {yf_warning}")

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
# 2. COMPANY DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════
desc = g("longBusinessSummary", "")
if desc:
    st.markdown("---")
    with st.expander("📄 Company Description", expanded=True):
        st.markdown(f"<div style='font-size:13px;color:rgba(255,255,255,0.6);line-height:1.7;'>{desc}</div>",
                    unsafe_allow_html=True)
        ed1, ed2, ed3 = st.columns(3)
        employees = g("fullTimeEmployees", 0)
        ed1.metric("Employees", f"{employees:,}" if employees else "—")
        ed2.metric("Country", g("country", "—"))
        ed3.metric("Website", g("website", "—"))

# ══════════════════════════════════════════════════════════════════════════
# 3. PRICE CHART WITH MOVING AVERAGES
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 📈 Price Chart")

if not hist.empty:
    period_options = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "2Y": 504, "3Y": 756, "5Y": 1260, "Max": 0}
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
    elif selected_period == "Max" or period_options[selected_period] == 0:
        pass  # show full history
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
    st.plotly_chart(fig_price, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("No price history available.")


# ══════════════════════════════════════════════════════════════════════════
# 3. DIVIDEND HISTORY
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("#### 💰 Dividend History")

# ── Try Fish CCC data first (authoritative, up to 27 years) ──────────────
fish_data = {}
fish_hist = {}
fish_metrics = {}
if _FISH_AVAILABLE:
    fish_data = get_all_fish_data(ticker_input)
    fish_hist = fish_data.get("history", {})
    fish_metrics = fish_data.get("metrics", {})

# Build annual_divs from Fish or Supabase/yfinance
annual_divs = None
data_source = ""

if fish_hist and len(fish_hist) >= 2:
    # Use Fish Historical data (sorted by year)
    years_sorted = sorted(fish_hist.keys())
    annual_divs = pd.DataFrame({
        "Year": years_sorted,
        "Annual Dividend": [fish_hist[y] for y in years_sorted],
    })
    data_source = "Fish/IREIT CCC"

elif not divs.empty and len(divs) >= 2:
    # Fallback to Supabase/yfinance dividend data
    div_df = divs.reset_index()
    div_df.columns = ["date", "amount"]
    div_df["year"] = pd.to_datetime(div_df["date"]).dt.year
    annual_divs = div_df.groupby("year")["amount"].sum().reset_index()
    annual_divs.columns = ["Year", "Annual Dividend"]
    data_source = "Supabase/yfinance"

if annual_divs is not None and len(annual_divs) >= 2:
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
        st.plotly_chart(fig_div, use_container_width=True, config=PLOTLY_CONFIG)

    with col_div_stats:
        # Use Fish metrics if available (more reliable than computing from history)
        if fish_metrics:
            div_amt = fish_metrics.get("div_amount", 0)
            if div_amt:
                st.metric("Latest Annual Div", f"${div_amt:.2f}")

            dgr_1y = fish_metrics.get("dgr_1y", 0)
            if dgr_1y:
                st.metric("YoY Growth", f"{dgr_1y:+.1f}%")

            dgr_3y = fish_metrics.get("dgr_3y", 0)
            if dgr_3y:
                st.metric("3Y CAGR", f"{dgr_3y:+.1f}%")

            dgr_5y = fish_metrics.get("dgr_5y", 0)
            if dgr_5y:
                st.metric("5Y CAGR", f"{dgr_5y:+.1f}%")

            consec = fish_data.get("years", 0)
            if consec > 0:
                st.metric("Consec. Increases", f"{consec} yrs")

            streak_began = fish_metrics.get("streak_began", None)
            if streak_began:
                try:
                    st.metric("Streak Began", str(int(float(str(streak_began)))))
                except (ValueError, TypeError):
                    pass

            recessions = fish_metrics.get("recessions", 0)
            if recessions > 0:
                st.metric("Recessions Survived", str(recessions))

        else:
            # Fallback: compute stats from annual_divs
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

            if len(completed) >= 2:
                consec = 0
                for i in range(len(completed) - 1, 0, -1):
                    if completed.iloc[i]["Annual Dividend"] > completed.iloc[i-1]["Annual Dividend"] * 0.99:
                        consec += 1
                    else:
                        break
                st.metric("Consec. Increases", f"{consec} yrs")

        # Ex-date (always from Supabase/yfinance info)
        ex_str = ""
        ex_div = info.get("exDividendDate")
        if ex_div and isinstance(ex_div, (int, float)):
            try:
                ex_str = datetime.fromtimestamp(ex_div).strftime("%b %d, %Y")
            except Exception:
                pass
        elif ex_div and isinstance(ex_div, str) and ex_div:
            try:
                ex_str = datetime.strptime(ex_div, "%Y-%m-%d").strftime("%b %d, %Y")
            except Exception:
                ex_str = ex_div
        if ex_str:
            st.metric("Next Ex-Date", ex_str)

    # ── Year-over-Year Growth Table (newest to oldest) ────────────────────
    if len(annual_divs) >= 3:
        st.markdown(f"**Year-over-Year Dividend Growth**")
        amounts = annual_divs["Annual Dividend"].tolist()
        years_list = annual_divs["Year"].tolist()
        growth_data = []
        for i in range(len(amounts) - 1, 0, -1):
            if amounts[i-1] > 0:
                pct = ((amounts[i] - amounts[i-1]) / amounts[i-1]) * 100
            else:
                pct = 0
            growth_data.append({
                "Year": f"{years_list[i-1]}-{years_list[i]}",
                "From": f"${amounts[i-1]:.2f}",
                "To": f"${amounts[i]:.2f}",
                "Growth": f"{pct:+.1f}%",
            })
        st.dataframe(
            pd.DataFrame(growth_data),
            use_container_width=True, hide_index=True,
            height=(42 + len(growth_data) * 36),
        )

    if data_source:
        st.caption(f"Dividend data source: {data_source}")

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
                st.plotly_chart(fig_fin, use_container_width=True, config=PLOTLY_CONFIG)

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