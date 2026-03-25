"""
Martin Capital Partners — Stock Detail Page
pages/2_Stock_Detail.py

Dedicated detail page for individual holdings.
Accessed via ticker selector or linked from Holdings tab.

Sections:
  1. Company Profile header
  2. Price chart with 50/200 day moving averages
  3. Analyst targets & recommendations
  4. Valuation metrics
  5. Revenue / earnings / margins
  6. Sector peer comparison
  7. Dividend history (annual payments + growth)
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

# Finviz data (analyst ratings, technicals, ownership)
try:
    from data.finviz_data import (
        fetch_finviz_batch,
        recommendation_badge,
        upside_badge,
        rsi_indicator,
    )
    _FINVIZ_AVAILABLE = True
except ImportError:
    _FINVIZ_AVAILABLE = False

# Market data for peer comparison
try:
    from data.market_data import fetch_batch_prices
    _MARKET_DATA_AVAILABLE = True
except ImportError:
    _MARKET_DATA_AVAILABLE = False

# Notion proprietary metrics (MCP Target) + Dividend Commentary + Thesis
try:
    from data.notion_metrics import fetch_notion_metrics, fetch_dividend_commentary, fetch_mcp_thesis
    _NOTION_AVAILABLE = True
except ImportError:
    _NOTION_AVAILABLE = False

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

# Mobile responsiveness
try:
    from utils.mobile_css import inject_mobile_css
    inject_mobile_css()
except ImportError:
    pass

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
    "staticPlot": False,
}

# Crosshair spike settings — reusable across all charts
_SPIKE = dict(showspikes=True, spikecolor="rgba(255,255,255,0.15)", spikethickness=1, spikemode="across", spikedash="solid")

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
            # Remove non-equity entries (e.g. CASH from Tamarac)
            available_tickers = [t for t in available_tickers if t not in ("CASH",)]
            break
except Exception:
    pass

# ── Build ticker lookup with company names ────────────────────────────────
# Fetches names from market_data cache so the selectbox shows "MSFT — Microsoft Corp"
_ticker_labels = {}
if available_tickers and _MARKET_DATA_AVAILABLE:
    try:
        _name_data = fetch_batch_prices(tuple(available_tickers))
        for t in available_tickers:
            name = _name_data.get(t, {}).get("name", "")
            _ticker_labels[t] = f"{t}  —  {name}" if name else t
    except Exception:
        _ticker_labels = {t: t for t in available_tickers}
else:
    _ticker_labels = {t: t for t in available_tickers}

# Sorted display list: holdings with company names + manual entry option at the end
_display_options = [_ticker_labels.get(t, t) for t in available_tickers]
_OTHER_OPTION = "Other — Enter any ticker..."
_display_options.append(_OTHER_OPTION)

# ── Ticker Selector ───────────────────────────────────────────────────────
# Check if coming from Holdings tab with a pre-selected ticker
default_ticker = (
    st.query_params.get("ticker")
    or st.session_state.get("detail_ticker")
    or ""
).upper()

# Find default index: match holding, or default to "Other" if ticker isn't in holdings
_default_idx = len(_display_options) - 1  # default to "Other"
if default_ticker:
    for i, opt in enumerate(_display_options[:-1]):  # skip "Other" entry
        if opt.startswith(default_ticker + " ") or opt == default_ticker:
            _default_idx = i
            break

# Truncate long option text in the selectbox on narrow screens
st.markdown("""<style>
[data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
</style>""", unsafe_allow_html=True)

# Back button as a right-aligned link above the selectbox
if st.button("← Back to Dashboard", key="back_btn"):
    st.switch_page("pages/1_Dashboard.py")

selected_option = st.selectbox(
    "Select or Search Ticker",
    options=_display_options,
    index=_default_idx,
    placeholder="Type ticker or company name...",
    key="detail_ticker_select",
)

# If "Other" is selected, show a text input for manual ticker entry
if selected_option == _OTHER_OPTION:
    manual_ticker = st.text_input(
        "Enter any ticker symbol",
        value=default_ticker if _default_idx == len(_display_options) - 1 and default_ticker else "",
        placeholder="e.g. NVDA, META, CMCSA...",
        key="detail_ticker_manual",
    ).strip().upper()
    ticker_input = manual_ticker
else:
    ticker_input = selected_option.split("  —  ")[0].strip().upper() if selected_option else ""

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
def fetch_stock_data(ticker, _v=2):
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
            yf_warning = "yfinance rate limited — showing available data from other sources."
        else:
            yf_warning = f"yfinance unavailable — showing available data from other sources."

    # Never crash — return whatever we have, even if info is empty
    return {
        "info":                  info if info else {},
        "history":               hist,
        "dividends":             div_hist,
        "financials":            financials,
        "quarterly_financials":  quarterly_financials,
        "recommendations":       recs,
        "yf_warning":            yf_warning,
    }



with st.spinner(f"Loading {ticker_input}..."):
    _fetch_error = None
    try:
        data = fetch_stock_data(ticker_input)
    except Exception as e:
        _fetch_error = str(e)
        data = {
            "info": {},
            "history": pd.DataFrame(),
            "dividends": pd.Series(dtype=float),
            "financials": pd.DataFrame(),
            "quarterly_financials": pd.DataFrame(),
            "recommendations": pd.DataFrame(),
            "yf_warning": f"yfinance unavailable — showing Finviz data where possible.",
        }

info = data["info"]
hist = data["history"]
divs = data["dividends"]
yf_warning = data.get("yf_warning")

# If info is empty (yfinance rate-limited, ticker not in Supabase), try Finviz for basics
if not info.get("longName") and not info.get("shortName"):
    _fv_fallback_status = "Starting Finviz fallback..."
    if _FINVIZ_AVAILABLE:
        try:
            _fallback_fv = fetch_finviz_batch((ticker_input,))
            _fb = _fallback_fv.get(ticker_input, {})
            _fv_fallback_status = f"Finviz returned {len(_fb)} keys. Keys: {sorted(_fb.keys())[:10]}"
            # Try multiple possible field names for company name
            _fv_name = _fb.get("company_name") or _fb.get("name") or _fb.get("Company") or ""
            if _fv_name:
                info = {
                    "longName": _fv_name,
                    "shortName": ticker_input,
                    "sector": _fb.get("sector", "") or _fb.get("Sector", ""),
                    "industry": _fb.get("industry", "") or _fb.get("Industry", ""),
                    "currentPrice": _fb.get("price", 0) or _fb.get("Price", 0),
                    "marketCap": _fb.get("market_cap_raw", 0),
                    "trailingPE": _fb.get("pe", 0),
                    "forwardPE": _fb.get("forward_pe", 0),
                    "beta": _fb.get("beta", 0),
                    "dividendYield": (_fb.get("dividend_yield", 0) or 0) / 100 if _fb.get("dividend_yield") else 0,
                    "_from_finviz_fallback": True,
                }
                data["info"] = info
                if not yf_warning:
                    yf_warning = "yfinance unavailable — showing Finviz data. Some sections may be limited."
                _fv_fallback_status += f" → SUCCESS: name={_fv_name}"
            else:
                _fv_fallback_status += f" → No company name found in keys"
        except Exception as fv_err:
            _fv_fallback_status = f"Finviz fallback EXCEPTION: {fv_err}"
    else:
        _fv_fallback_status = "Finviz not available (_FINVIZ_AVAILABLE=False)"

    # DEBUG — always show what happened
    st.caption(
        f"DEBUG: fetch_error={_fetch_error} | info_keys={len(info)} | "
        f"has_longName={info.get('longName', 'NONE')} | {_fv_fallback_status}"
    )

if not info.get("longName") and not info.get("shortName"):
    st.error(f"No data found for '{ticker_input}'. Check the ticker symbol.")
    st.stop()

if yf_warning:
    st.warning(f"{yf_warning}")

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

# Quick stats row — responsive flex grid
def _qs_card(label, value):
    return (
        f'<div style="flex:1 1 130px;min-width:100px;padding:8px 0;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:18px;font-weight:700;color:rgba(255,255,255,0.9);">{value}</div>'
        f'</div>'
    )

_qs_divyield = f"{div_yield:.2f}%" if div_yield > 0 else "—"
_qs_divrate = f"${div_rate:.2f}" if div_rate > 0 else "—"
_qs_pe = f"{g('trailingPE', 0):.1f}" if g("trailingPE", 0) else "—"
_qs_52hi = f"${g('fiftyTwoWeekHigh', 0):.2f}" if g("fiftyTwoWeekHigh", 0) else "—"
_qs_52lo = f"${g('fiftyTwoWeekLow', 0):.2f}" if g("fiftyTwoWeekLow", 0) else "—"

st.markdown(
    f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">'
    f'{_qs_card("Mkt Cap", mc_str)}'
    f'{_qs_card("Div Yield", _qs_divyield)}'
    f'{_qs_card("Div Rate", _qs_divrate)}'
    f'{_qs_card("P/E", _qs_pe)}'
    f'{_qs_card("52W High", _qs_52hi)}'
    f'{_qs_card("52W Low", _qs_52lo)}'
    f'</div>',
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════════════════
# 2. COMPANY DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════
desc = g("longBusinessSummary", "")
if desc:
    st.markdown("---")
    with st.expander("Company Description", expanded=True):
        st.markdown(f"<div style='font-size:13px;color:rgba(255,255,255,0.6);line-height:1.7;'>{desc}</div>",
                    unsafe_allow_html=True)
        ed1, ed2, ed3 = st.columns(3)
        employees = g("fullTimeEmployees", 0)
        ed1.metric("Employees", f"{employees:,}" if employees else "—")
        ed2.metric("Country", g("country", "—"))
        ed3.metric("Website", g("website", "—"))

# ══════════════════════════════════════════════════════════════════════════
# 2b. MCP INVESTMENT THESIS (from Notion Wiki)
# ══════════════════════════════════════════════════════════════════════════
if _NOTION_AVAILABLE:
    try:
        _thesis_html = fetch_mcp_thesis(ticker_input)
        if _thesis_html:
            st.markdown(
                f'<div style="background:rgba(201,168,76,0.04); border:1px solid rgba(201,168,76,0.12); '
                f'border-radius:10px; padding:16px 20px; margin:12px 0 4px;">'
                f'<div style="font-size:11px; font-weight:700; color:{GOLD}; text-transform:uppercase; '
                f'letter-spacing:0.06em; margin-bottom:8px;">MCP Investment Thesis</div>'
                f'<div style="font-size:13px; color:rgba(255,255,255,0.65); line-height:1.7;">'
                f'{_thesis_html}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════
# 3. PRICE CHART WITH MOVING AVERAGES
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown('<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">Price Chart</div>', unsafe_allow_html=True)

if not hist.empty:
    period_options = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "2Y": 504, "3Y": 756, "5Y": 1260, "Max": 0}
    if "chart_period" not in st.session_state:
        st.session_state["chart_period"] = "1Y"

    period_cols = st.columns(len(period_options))
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
        dragmode=False,
    )
    fig_price.update_xaxes(fixedrange=True, **_SPIKE)
    fig_price.update_yaxes(fixedrange=True, **_SPIKE)
    st.plotly_chart(fig_price, use_container_width=True, config=PLOTLY_CONFIG)
else:
    st.info("No price history available.")


# ══════════════════════════════════════════════════════════════════════════
# 4. VALUATION METRICS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown('<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">Valuation</div>', unsafe_allow_html=True)

v_pe = f"{g('trailingPE', 0):.1f}" if g("trailingPE", 0) else "—"
v_fpe = f"{g('forwardPE', 0):.1f}" if g("forwardPE", 0) else "—"
v_peg = f"{g('pegRatio', 0):.2f}" if g("pegRatio", 0) else "—"
v_pb = f"{g('priceToBook', 0):.2f}" if g("priceToBook", 0) else "—"
v_ps = f"{g('priceToSalesTrailing12Months', 0):.2f}" if g("priceToSalesTrailing12Months", 0) else "—"
v_ev = f"{g('enterpriseToEbitda', 0):.1f}" if g("enterpriseToEbitda", 0) else "—"

def _val_card(label, value):
    return (
        f'<div style="flex:1 1 130px;min-width:100px;padding:8px 0;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:18px;font-weight:700;color:rgba(255,255,255,0.9);">{value}</div>'
        f'</div>'
    )

st.markdown(
    f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">'
    f'{_val_card("P/E (TTM)", v_pe)}{_val_card("Fwd P/E", v_fpe)}{_val_card("PEG Ratio", v_peg)}'
    f'{_val_card("P/B", v_pb)}{_val_card("P/S (TTM)", v_ps)}{_val_card("EV/EBITDA", v_ev)}'
    f'</div>',
    unsafe_allow_html=True,
)

# Second row
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

v_beta = f"{g('beta', 0):.2f}" if g("beta", 0) else "—"

payout_raw = g("payoutRatio", 0)
payout_pct = round(payout_raw * 100, 1) if isinstance(payout_raw, (int, float)) and 0 < payout_raw < 5 else 0
v_payout = f"{payout_pct:.1f}%" if payout_pct > 0 else "—"

ev_raw = g("enterpriseValue", 0)
if ev_raw >= 1e12:
    ev_str = f"${ev_raw/1e12:.2f}T"
elif ev_raw >= 1e9:
    ev_str = f"${ev_raw/1e9:.1f}B"
else:
    ev_str = "—"

v_roe = f"{g('returnOnEquity', 0)*100:.1f}%" if isinstance(g("returnOnEquity", 0), (int, float)) and g("returnOnEquity", 0) else "—"
v_de = f"{g('debtToEquity', 0):.0f}%" if g("debtToEquity", 0) else "—"
v_cr = f"{g('currentRatio', 0):.2f}" if g("currentRatio", 0) else "—"

st.markdown(
    f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">'
    f'{_val_card("Beta", v_beta)}{_val_card("Payout Ratio", v_payout)}{_val_card("Enterprise Value", ev_str)}'
    f'{_val_card("ROE", v_roe)}{_val_card("Debt/Equity", v_de)}{_val_card("Current Ratio", v_cr)}'
    f'</div>',
    unsafe_allow_html=True,
)



# ══════════════════════════════════════════════════════════════════════════
# FINVIZ: ANALYST, TECHNICALS & OWNERSHIP
# ══════════════════════════════════════════════════════════════════════════
if _FINVIZ_AVAILABLE:
    fv_data = fetch_finviz_batch((ticker_input,))
    fv = fv_data.get(ticker_input, {})

    if fv:
        st.markdown("---")
        st.markdown('<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">Analyst & Technical Signals</div>', unsafe_allow_html=True)

        # ── Row 1: Analyst Consensus ──────────────────────────────────────
        rec_val = fv.get("recommendation")
        rec_label = fv.get("rec_label", "—")
        rsi = fv.get("rsi_14")
        earnings = fv.get("earnings_date")

        # MCP Target from Notion (replaces Finviz consensus target)
        _notion_data = fetch_notion_metrics() if _NOTION_AVAILABLE else {}
        _nm = _notion_data.get(ticker_input.upper(), {})
        mcp_target = _nm.get("mcp_target")
        if mcp_target and price and price > 0:
            upside = round((mcp_target - price) / price * 100, 1)
        else:
            upside = None

        # ── Row 1: Analyst Consensus (responsive HTML grid) ────────────
        # Custom HTML grid: 6 cols on desktop, wraps to 3×2 on mobile
        def _card(label, value_html):
            return (
                f'<div style="flex:1 1 130px;min-width:100px;padding:8px 0;">'
                f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:4px;">{label}</div>'
                f'{value_html}</div>'
            )

        # Analyst Rating
        if rec_val is not None:
            _rec_color = GREEN if rec_val <= 2.0 else GOLD if rec_val <= 3.0 else "#c45454"
            card_rating = _card("Analyst Rating",
                f'<div style="font-size:20px;font-weight:700;color:{_rec_color};">{rec_val:.1f}</div>'
                f'<div style="font-size:11px;color:{_rec_color};font-weight:600;">{rec_label}</div>')
        else:
            card_rating = _card("Analyst Rating", '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        # MCP Target
        target_str = f"${mcp_target:,.0f}" if mcp_target else "—"
        card_target = _card("MCP Target",
            f'<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.9);">{target_str}</div>')

        # Upside
        if upside is not None:
            _up_color = GREEN if upside >= 0 else "#c45454"
            _arrow = "▲" if upside >= 0 else "▼"
            card_upside = _card("Upside to MCP Target",
                f'<div style="font-size:20px;font-weight:700;color:{_up_color};">{_arrow} {upside:+.1f}%</div>')
        else:
            card_upside = _card("Upside to MCP Target", '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        # RSI
        if rsi is not None:
            _rsi_color = "#c45454" if rsi >= 70 else GREEN if rsi <= 30 else "rgba(255,255,255,0.8)"
            _rsi_label = "Overbought" if rsi >= 70 else "Oversold" if rsi <= 30 else "Neutral"
            card_rsi = _card("RSI (14)",
                f'<div style="font-size:20px;font-weight:700;color:{_rsi_color};">{rsi:.0f}</div>'
                f'<div style="font-size:11px;color:{_rsi_color};">{_rsi_label}</div>')
        else:
            card_rsi = _card("RSI (14)", '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        # Short Float
        short_fl = fv.get("short_float")
        if short_fl is not None:
            _sf_color = "#c45454" if short_fl >= 5 else GOLD if short_fl >= 3 else "rgba(255,255,255,0.8)"
            card_short = _card("Short Float",
                f'<div style="font-size:20px;font-weight:700;color:{_sf_color};">{short_fl:.1f}%</div>')
        else:
            card_short = _card("Short Float", '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        # Earnings
        earnings_str = earnings if earnings else "—"
        card_earnings = _card("Earnings Date",
            f'<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.9);">{earnings_str}</div>')

        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">'
            f'{card_rating}{card_target}{card_upside}{card_rsi}{card_short}{card_earnings}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Row 2: SMA Distances ──────────────────────────────────────────
        sma20 = fv.get("sma20_dist")
        sma50 = fv.get("sma50_dist")
        sma200 = fv.get("sma200_dist")
        insider_own = fv.get("insider_own")
        inst_own = fv.get("inst_own")
        insider_trans = fv.get("insider_trans")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # SMA cards
        def _sma_card(label, val):
            if val is not None:
                _color = GREEN if val > 0 else "#c45454" if val < -5 else GOLD
                return _card(label, f'<div style="font-size:20px;font-weight:700;color:{_color};">{val:+.1f}%</div>')
            return _card(label, '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        card_sma20 = _sma_card("vs 20-SMA", sma20)
        card_sma50 = _sma_card("vs 50-SMA", sma50)
        card_sma200 = _sma_card("vs 200-SMA", sma200)

        insider_str = f"{insider_own:.1f}%" if insider_own is not None else "—"
        card_insider = _card("Insider Own",
            f'<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.9);">{insider_str}</div>')

        inst_str = f"{inst_own:.1f}%" if inst_own is not None else "—"
        card_inst = _card("Inst Own",
            f'<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.9);">{inst_str}</div>')

        if insider_trans is not None:
            _it_color = GREEN if insider_trans > 0 else "#c45454" if insider_trans < 0 else "rgba(255,255,255,0.6)"
            card_ins_trans = _card("Insider Trans",
                f'<div style="font-size:20px;font-weight:700;color:{_it_color};">{insider_trans:+.1f}%</div>')
        else:
            card_ins_trans = _card("Insider Trans", '<div style="font-size:20px;font-weight:700;color:rgba(255,255,255,0.5);">—</div>')

        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">'
            f'{card_sma20}{card_sma50}{card_sma200}{card_insider}{card_inst}{card_ins_trans}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Performance row ───────────────────────────────────────────────
        perf_ytd = fv.get("perf_ytd")
        perf_week = fv.get("perf_week")
        perf_month = fv.get("perf_month")
        perf_quarter = fv.get("perf_quarter")
        perf_half = fv.get("perf_half")
        perf_year = fv.get("perf_year")

        has_perf = any(v is not None for v in [perf_week, perf_month, perf_quarter, perf_half, perf_year, perf_ytd])
        if has_perf:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            def _perf_card(label, val):
                if val is not None:
                    _color = GREEN if val >= 0 else "#c45454"
                    return _card(label, f'<div style="font-size:16px;font-weight:600;color:{_color};">{val:+.1f}%</div>')
                return _card(label, '<div style="font-size:16px;font-weight:600;color:rgba(255,255,255,0.5);">—</div>')

            perf_cards = (
                _perf_card("Week", perf_week)
                + _perf_card("Month", perf_month)
                + _perf_card("Quarter", perf_quarter)
                + _perf_card("Half Year", perf_half)
                + _perf_card("Year", perf_year)
                + _perf_card("YTD", perf_ytd)
            )

            st.markdown(
                f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;">{perf_cards}</div>',
                unsafe_allow_html=True,
            )

        st.caption(f"Source: Finviz · Cached 1 hour · Analyst ratings are consensus of Wall Street coverage")



# ══════════════════════════════════════════════════════════════════════════
# 5. REVENUE / EARNINGS / MARGINS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown('<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">Financials</div>', unsafe_allow_html=True)

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

            # Build aligned data — use revenue index as the master timeline
            chart_index = rev_data.index
            years = [d.strftime("%Y") for d in chart_index]
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
                    # Reindex net income to match revenue's dates exactly
                    ni_aligned = ni_data.reindex(chart_index)
                    ni_vals = (ni_aligned / 1e9).round(2)
                    fig_fin.add_trace(go.Bar(
                        x=years, y=ni_vals,
                        name="Net Income",
                        marker_color=GREEN,
                        text=[f"${v:.1f}B" if pd.notna(v) else "" for v in ni_vals],
                        textposition="outside",
                        textfont=dict(size=10, color="rgba(255,255,255,0.5)"),
                    ))
                fig_fin.update_layout(
                    **PLOTLY_DARK,
                    height=300,
                    title="Revenue & Net Income ($B)",
                    barmode="group",
                    showlegend=True,
                    hovermode="x unified",
                    dragmode=False,
                )
                fig_fin.update_xaxes(fixedrange=True, **_SPIKE)
                fig_fin.update_yaxes(fixedrange=True)
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


# ══════════════════════════════════════════════════════════════════════════
# 6. PEER COMPARISON
# ══════════════════════════════════════════════════════════════════════════
# Find sector peers from the same Tamarac holdings universe
_current_sector = g("sector", "")
if _current_sector and _MARKET_DATA_AVAILABLE and available_tickers:
    # Gather all unique tickers from Tamarac (excluding current ticker)
    peer_candidates = [t for t in available_tickers if t != ticker_input]

    if peer_candidates:
        # Fetch price data for all candidates to find same-sector peers
        with st.spinner("Finding sector peers..."):
            peer_prices = fetch_batch_prices(tuple(peer_candidates))

        # Filter to same sector
        same_sector = []
        for t in peer_candidates:
            p = peer_prices.get(t, {})
            if p.get("sector", "") == _current_sector:
                same_sector.append(t)

        if same_sector:
            st.markdown("---")
            st.markdown(
                f'<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);'
                f'text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">'
                f'Sector Peers — {_current_sector}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
                f"Holdings in the same sector across all MCP strategies"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Limit to 8 peers max
            same_sector = same_sector[:8]

            # Include current ticker in the comparison
            all_compare = [ticker_input] + same_sector
            compare_prices = fetch_batch_prices(tuple(all_compare))

            # Fetch Finviz data for all compare tickers
            compare_fv = {}
            if _FINVIZ_AVAILABLE:
                compare_fv = fetch_finviz_batch(tuple(all_compare))

            # Fetch Fish CCC data for dividend metrics
            compare_fish = {}
            if _FISH_AVAILABLE:
                for t in all_compare:
                    try:
                        fd = get_all_fish_data(t)
                        compare_fish[t] = fd.get("metrics", {})
                    except Exception:
                        compare_fish[t] = {}

            # Build comparison table — single table, single st.markdown call.
            # Max 9 rows (current ticker + 8 peers) keeps HTML well under
            # Streamlit Cloud's silent-fail size limit.
            _tw = "width:100%;border-collapse:collapse;min-width:720px"
            _th_base = ("font-size:10px;font-weight:600;"
                        "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
                        "border-bottom:1px solid rgba(255,255,255,0.06);white-space:nowrap;"
                        "padding:6px 8px")

            # Build all rows first
            rows_html = ""
            for t in all_compare:
                p = compare_prices.get(t, {})
                fv = compare_fv.get(t, {})
                fish = compare_fish.get(t, {})

                _price = p.get("price", 0)
                _yield = p.get("dividend_yield", 0) or 0
                _pe = p.get("pe_ratio", 0) or fv.get("pe", 0) or 0
                _name = p.get("name", t)
                _ytd = fv.get("perf_ytd")
                _dgr5 = fish.get("dgr_5y", 0) or 0
                _payout = fish.get("payout_ratio", 0) or 0
                _rec = fv.get("recommendation")
                _rec_label = fv.get("rec_label", "—")

                # Highlight current ticker row
                is_current = t == ticker_input
                bg = "background:rgba(201,168,76,0.06);" if is_current else ""
                sym_color = "#C9A84C" if is_current else "rgba(255,255,255,0.7)"
                sym_weight = "700" if is_current else "600"

                # Format values
                price_str = f"${_price:.2f}" if _price else "—"
                yield_str = f"{_yield:.2f}%" if _yield > 0 else "—"
                yield_color = GOLD if _yield > 0 else "rgba(255,255,255,0.4)"
                dgr5_str = f"{_dgr5:+.1f}%" if _dgr5 else "—"
                dgr5_color = GREEN if _dgr5 > 0 else "#c45454" if _dgr5 < 0 else "rgba(255,255,255,0.4)"
                payout_str = f"{_payout:.0f}%" if _payout > 0 else "—"
                payout_color = GREEN if 0 < _payout < 50 else GOLD if _payout < 70 else "#c45454" if _payout > 0 else "rgba(255,255,255,0.4)"
                pe_str = f"{_pe:.1f}" if _pe > 0 else "—"
                ytd_str = f"{_ytd:+.1f}%" if _ytd is not None else "—"
                ytd_color = GREEN if _ytd and _ytd >= 0 else "#c45454" if _ytd else "rgba(255,255,255,0.4)"

                # Analyst badge
                if _rec is not None:
                    rec_html = recommendation_badge(_rec, _rec_label) if _FINVIZ_AVAILABLE else f"{_rec_label}"
                else:
                    rec_html = '<span style="font-size:11px;color:rgba(255,255,255,0.3);">—</span>'

                _td = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"

                rows_html += (
                    f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03);{bg}">'
                    f'<td style="text-align:left;padding:8px;font-size:12px;font-weight:{sym_weight};color:{sym_color};{_td}">{t}</td>'
                    f'<td style="text-align:left;padding:8px;font-size:11px;color:rgba(255,255,255,0.5);{_td}">{_name}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.8);{_td}">{price_str}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:{yield_color};{_td}">{yield_str}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:{dgr5_color};{_td}">{dgr5_str}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:{payout_color};{_td}">{payout_str}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:rgba(255,255,255,0.7);{_td}">{pe_str}</td>'
                    f'<td style="text-align:right;padding:8px;font-size:12px;color:{ytd_color};{_td}">{ytd_str}</td>'
                    f'<td style="text-align:center;padding:8px;{_td}">{rec_html}</td>'
                    f'</tr>'
                )

            # Single table: header + all rows in one st.markdown call
            st.markdown(
                f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
                f'<table style="{_tw}"><thead><tr>'
                f'<th style="text-align:left;{_th_base}">Sym</th>'
                f'<th style="text-align:left;{_th_base}">Company</th>'
                f'<th style="text-align:right;{_th_base}">Price</th>'
                f'<th style="text-align:right;{_th_base}">Yield</th>'
                f'<th style="text-align:right;{_th_base}">5Y DGR</th>'
                f'<th style="text-align:right;{_th_base}">Payout</th>'
                f'<th style="text-align:right;{_th_base}">P/E</th>'
                f'<th style="text-align:right;{_th_base}">YTD</th>'
                f'<th style="text-align:center;{_th_base}">Analyst</th>'
                f'</tr></thead><tbody>{rows_html}</tbody></table>'
                f'</div>',
                unsafe_allow_html=True,
            )

            st.caption(f"Peers: MCP holdings in {_current_sector} · Finviz + Fish CCC · {datetime.now().strftime('%I:%M %p')}")



# ══════════════════════════════════════════════════════════════════════════
# 7. DIVIDEND HISTORY
# ══════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown(
    f'<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);'
    f'text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">'
    f'Dividend History — {ticker_input}</div>',
    unsafe_allow_html=True,
)

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
    years_sorted = sorted(fish_hist.keys())
    annual_divs = pd.DataFrame({
        "Year": years_sorted,
        "Annual Dividend": [fish_hist[y] for y in years_sorted],
    })
    data_source = "Fish/IREIT CCC"

elif not divs.empty and len(divs) >= 2:
    div_df = divs.reset_index()
    div_df.columns = ["date", "amount"]
    div_df["year"] = pd.to_datetime(div_df["date"]).dt.year
    annual_divs = div_df.groupby("year")["amount"].sum().reset_index()
    annual_divs.columns = ["Year", "Annual Dividend"]
    data_source = "Supabase/yfinance"

if annual_divs is not None and len(annual_divs) >= 2:

    # ── KPI Cards — two horizontal rows of 4 ─────────────────────────────
    if fish_metrics:
        div_amt = fish_metrics.get("div_amount", 0)
        dgr_1y = fish_metrics.get("dgr_1y", 0)
        dgr_3y = fish_metrics.get("dgr_3y", 0)
        dgr_5y = fish_metrics.get("dgr_5y", 0)
        dgr_10y = fish_metrics.get("dgr_10y", 0)
        consec = fish_data.get("years", 0)
        streak_began = fish_metrics.get("streak_began", None)
        recessions = fish_metrics.get("recessions", 0)

        # Row 1
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.metric("Latest Annual Div", f"${div_amt:.2f}" if div_amt else "—")
        with k2: st.metric("1Y Growth", f"{dgr_1y:+.1f}%" if dgr_1y else "—")
        with k3: st.metric("3Y CAGR", f"{dgr_3y:+.1f}%" if dgr_3y else "—")
        with k4: st.metric("5Y CAGR", f"{dgr_5y:+.1f}%" if dgr_5y else "—")

        # Row 2
        k5, k6, k7, k8 = st.columns(4)
        with k5: st.metric("10Y CAGR", f"{dgr_10y:+.1f}%" if dgr_10y else "—")
        with k6: st.metric("Consec. Increases", f"{consec} yrs" if consec > 0 else "—")
        with k7:
            try:
                began_str = str(int(float(str(streak_began)))) if streak_began and str(streak_began).strip() not in ("", "0", "None", "nan") else "—"
            except (ValueError, TypeError):
                began_str = "—"
            st.metric("Streak Began", began_str)
        with k8: st.metric("Recessions Survived", str(recessions) if recessions > 0 else "—")

    else:
        # Fallback: compute what we can from annual_divs
        current_year = datetime.now().year
        completed = annual_divs[annual_divs["Year"] < current_year]

        latest_val = completed.iloc[-1]["Annual Dividend"] if len(completed) >= 1 else 0
        yoy_val = ((completed.iloc[-1]["Annual Dividend"] / completed.iloc[-2]["Annual Dividend"]) - 1) * 100 if len(completed) >= 2 and completed.iloc[-2]["Annual Dividend"] > 0 else 0
        cagr3_val = ((completed.iloc[-1]["Annual Dividend"] / completed.iloc[-4]["Annual Dividend"]) ** (1/3) - 1) * 100 if len(completed) >= 4 and completed.iloc[-4]["Annual Dividend"] > 0 else 0
        cagr5_val = ((completed.iloc[-1]["Annual Dividend"] / completed.iloc[-6]["Annual Dividend"]) ** (1/5) - 1) * 100 if len(completed) >= 6 and completed.iloc[-6]["Annual Dividend"] > 0 else 0

        consec = 0
        if len(completed) >= 2:
            for i in range(len(completed) - 1, 0, -1):
                if completed.iloc[i]["Annual Dividend"] > completed.iloc[i-1]["Annual Dividend"] * 0.99:
                    consec += 1
                else:
                    break

        k1, k2, k3, k4 = st.columns(4)
        with k1: st.metric("Latest Annual Div", f"${latest_val:.2f}" if latest_val else "—")
        with k2: st.metric("1Y Growth", f"{yoy_val:+.1f}%" if yoy_val else "—")
        with k3: st.metric("3Y CAGR", f"{cagr3_val:+.1f}%" if cagr3_val else "—")
        with k4: st.metric("5Y CAGR", f"{cagr5_val:+.1f}%" if cagr5_val else "—")

        k5, k6, k7, k8 = st.columns(4)
        with k5: st.metric("10Y CAGR", "—")
        with k6: st.metric("Consec. Increases", f"{consec} yrs" if consec > 0 else "—")
        with k7: st.metric("Streak Began", "—")
        with k8: st.metric("Recessions Survived", "—")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Annual Dividend Bar Chart ─────────────────────────────────────────
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
        height=320,
        title="Annual Dividends Per Share",
        yaxis_title="$/Share",
        showlegend=False,
        hovermode="x unified",
        dragmode=False,
    )
    fig_div.update_xaxes(fixedrange=True, **_SPIKE)
    fig_div.update_yaxes(fixedrange=True)
    st.plotly_chart(fig_div, use_container_width=True, config=PLOTLY_CONFIG)

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
# 8. DIVIDEND COMMENTARY (from Notion Wiki)
# ══════════════════════════════════════════════════════════════════════════
if _NOTION_AVAILABLE:
    try:
        commentary_blocks = fetch_dividend_commentary(ticker_input)
        if commentary_blocks:
            st.markdown("---")
            st.markdown(
                f'<div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.8);'
                f'text-transform:uppercase;letter-spacing:0.08em;padding:4px 0 8px;">'
                f'Dividend Commentary — {ticker_input}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:12px;'>"
                "Source: MCP internal research notes (Notion)"
                "</div>",
                unsafe_allow_html=True,
            )

            # Render each block as its own st.markdown call
            # (avoids Streamlit Cloud HTML size limit on large commentaries)
            for block_html in commentary_blocks:
                st.markdown(block_html, unsafe_allow_html=True)
    except Exception:
        pass  # Silently skip if commentary fetch fails

# ── Footer ────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='display:flex;gap:12px;justify-content:center;padding:16px 28px;margin-top:20px;"
    "border-top:1px solid rgba(255,255,255,0.04);font-size:11px;color:rgba(255,255,255,0.2);'>"
    "<span>© 2026 Martin Capital Partners LLC</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Data: yfinance · Finviz · Fish CCC · Notion</span>"
    "<span style='opacity:0.3;'>|</span>"
    "<span>Internal use only</span>"
    "</div>",
    unsafe_allow_html=True,
)