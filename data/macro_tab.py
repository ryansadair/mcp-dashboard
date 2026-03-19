"""
Macro Environment tab for the Dashboard.
Pulls rates, economic indicators, valuation & sentiment data from FRED + yfinance.
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# ── FRED API ───────────────────────────────────────────────────────────────

FRED_API_KEY = "984881b404269d00afe946250729a01a"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


@st.cache_data(ttl=3600)
def _fred(series_id, limit=10):
    """Fetch the latest observations from FRED."""
    try:
        resp = requests.get(FRED_BASE, params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }, timeout=10)
        if resp.status_code == 200:
            obs = resp.json().get("observations", [])
            # Filter out missing values
            return [o for o in obs if o.get("value", ".") != "."]
        return []
    except Exception:
        return []


def _fred_latest(series_id):
    """Get the latest value and previous value from a FRED series."""
    obs = _fred(series_id, limit=5)
    if not obs:
        return None, None, None
    latest = float(obs[0]["value"])
    prev = float(obs[1]["value"]) if len(obs) > 1 else None
    date_str = obs[0].get("date", "")
    return latest, prev, date_str


def _fred_history(series_id, months=12):
    """Get historical observations for charting."""
    try:
        start = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m-%d")
        resp = requests.get(FRED_BASE, params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "asc",
        }, timeout=10)
        if resp.status_code == 200:
            obs = resp.json().get("observations", [])
            return [(o["date"], float(o["value"])) for o in obs if o.get("value", ".") != "."]
        return []
    except Exception:
        return []


# ── yfinance helpers ───────────────────────────────────────────────────────

@st.cache_data(ttl=900)
def _yf_quote(ticker):
    """Fetch basic quote info via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        return {
            "price": getattr(info, "last_price", None),
            "prev_close": getattr(info, "previous_close", None),
        }
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def _yf_sp500_metrics():
    """Get S&P 500 forward P/E and related metrics via yfinance."""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        info = spy.info or {}
        fi = spy.fast_info

        fwd_pe = info.get("forwardPE")
        trailing_pe = info.get("trailingPE")
        div_yield = info.get("dividendYield")
        price = getattr(fi, "last_price", None)

        # Fallback P/E: compute from trailingEps if available
        if fwd_pe is None and trailing_pe is None:
            eps = info.get("trailingEps")
            if eps and eps > 0 and price and price > 0:
                trailing_pe = round(price / eps, 1)

        # Fallback div yield: compute from dividendRate / price
        if div_yield is None:
            div_rate = info.get("dividendRate")
            if div_rate and price and price > 0:
                div_yield = div_rate / price

        return {
            "fwd_pe": fwd_pe,
            "trailing_pe": trailing_pe,
            "div_yield": div_yield,
            "price": price,
        }
    except Exception:
        return {}


# ── FRED Series IDs ────────────────────────────────────────────────────────

RATES_SERIES = {
    "Fed Funds Rate": "DFEDTARU",       # Fed Funds upper target
    "2-Year Treasury": "DGS2",
    "10-Year Treasury": "DGS10",
    "30-Year Treasury": "DGS30",
}

ECON_SERIES = {
    "CPI (YoY)": {"id": "CPIAUCSL", "transform": "yoy", "freq": "monthly"},
    "Core CPI (YoY)": {"id": "CPILFESL", "transform": "yoy", "freq": "monthly"},
    "Unemployment Rate": {"id": "UNRATE", "transform": "level", "freq": "monthly"},
    "GDP Growth (QoQ Ann.)": {"id": "A191RL1Q225SBEA", "transform": "level", "freq": "quarterly"},
    "ISM Manufacturing": {"id": "MANEMP", "transform": "level", "freq": "monthly"},
    "Consumer Confidence": {"id": "UMCSENT", "transform": "level", "freq": "monthly"},
    "PCE (YoY)": {"id": "PCEPI", "transform": "yoy", "freq": "monthly"},
    "Initial Jobless Claims": {"id": "ICSA", "transform": "level", "freq": "weekly"},
}

MORTGAGE_SERIES = {
    "15Y Mortgage": "MORTGAGE15US",
    "30Y Mortgage": "MORTGAGE30US",
}


# ── Formatting helpers ─────────────────────────────────────────────────────

def _fmt_rate(val, suffix="%"):
    if val is None:
        return "—"
    return f"{val:.2f}{suffix}"


def _fmt_chg(latest, prev, suffix="", is_bp=False):
    if latest is None or prev is None:
        return "—", "neutral"
    diff = latest - prev
    if is_bp:
        diff_display = f"{diff:+.0f}bp" if abs(diff) >= 0.5 else "unch"
    elif suffix == "%":
        diff_display = f"{diff:+.1f}%"
    else:
        diff_display = f"{diff:+.2f}{suffix}"

    if abs(diff) < 0.005:
        return "unch", "neutral"

    direction = "up" if diff > 0 else "down"
    return diff_display, direction


def _fmt_econ_val(name, val):
    """Format economic indicator values."""
    if val is None:
        return "—"
    if "Claims" in name:
        return f"{val / 1000:.0f}K" if val > 100 else f"{val:.0f}K"
    if "Unemployment" in name or "CPI" in name or "PCE" in name or "GDP" in name:
        return f"{val:.1f}%"
    if "ISM" in name or "Confidence" in name:
        return f"{val:.1f}"
    return f"{val:.2f}"


def _signal_for_econ(name, val, prev):
    """Determine signal based on indicator direction and level."""
    if val is None or prev is None:
        return "neutral"
    if "CPI" in name or "PCE" in name:
        return "positive" if val < prev else "watch" if val > prev else "neutral"
    if "Unemployment" in name:
        return "positive" if val <= prev else "watch"
    if "GDP" in name:
        return "positive" if val >= 2.0 else "watch" if val >= 0 else "alert"
    if "ISM" in name:
        return "positive" if val >= 50 else "watch"
    if "Claims" in name:
        return "positive" if val < prev else "watch"
    if "Confidence" in name:
        return "positive" if val > prev else "neutral"
    return "neutral"


# ── HTML rendering helpers ─────────────────────────────────────────────────

SIGNAL_COLORS = {
    "positive": ("#569542", "rgba(86,149,66,0.10)", "rgba(86,149,66,0.3)"),
    "neutral": ("rgba(255,255,255,0.5)", "rgba(255,255,255,0.03)", "rgba(255,255,255,0.06)"),
    "watch": ("#C9A84C", "rgba(201,168,76,0.08)", "rgba(201,168,76,0.2)"),
    "alert": ("#c45454", "rgba(196,84,84,0.08)", "rgba(196,84,84,0.2)"),
    "elevated": ("#C9A84C", "rgba(201,168,76,0.08)", "rgba(201,168,76,0.2)"),
    "tight": ("#c45454", "rgba(196,84,84,0.08)", "rgba(196,84,84,0.2)"),
    "low": ("#569542", "rgba(86,149,66,0.10)", "rgba(86,149,66,0.3)"),
}


def _signal_badge(status):
    color, bg, border = SIGNAL_COLORS.get(status, SIGNAL_COLORS["neutral"])
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            f'background:{bg};border:1px solid {border};color:{color};'
            f'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em">'
            f'{status}</span>')


def _trend_arrow(direction):
    if direction == "up":
        return '<span style="color:#569542;font-size:13px">▲</span>'
    if direction == "down":
        return '<span style="color:#c45454;font-size:13px">▼</span>'
    return '<span style="color:rgba(255,255,255,0.25);font-size:11px">◆</span>'


# ══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════

def render_macro_tab(qdvd_yield=None):
    """
    Render the full Macro Environment tab.

    Parameters
    ----------
    qdvd_yield : float or None
        QDVD weighted avg dividend yield (passed from main dashboard).
    """

    # Initialize variables used across sections
    ten_y = None
    spread_bp = None
    fwd_pe = None
    sp_div_pct = None
    sp_div = None

    st.markdown(
        '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:16px">'
        'Rates, economic indicators & market context for dividend strategies'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Rates & Yields ─────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:12px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
        'Rates & Yields</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Fetching rates from FRED..."):
        rates_display = []

        # Fetch core rates
        for name, series_id in RATES_SERIES.items():
            latest, prev, date_str = _fred_latest(series_id)
            chg_str, direction = _fmt_chg(latest, prev, is_bp=True)
            rates_display.append({
                "name": name,
                "value": _fmt_rate(latest) if latest else "—",
                "chg": chg_str,
                "direction": direction,
                "raw": latest,
            })

        # 2s10s spread (computed)
        r2y = next((r["raw"] for r in rates_display if "2-Year" in r["name"]), None)
        r10y = next((r["raw"] for r in rates_display if "10-Year" in r["name"]), None)
        if r2y is not None and r10y is not None:
            spread_bp = round((r10y - r2y) * 100)
            # Get previous spread
            obs_2y = _fred("DGS2", limit=5)
            obs_10y = _fred("DGS10", limit=5)
            prev_spread = None
            if len(obs_2y) > 1 and len(obs_10y) > 1:
                prev_spread = round((float(obs_10y[1]["value"]) - float(obs_2y[1]["value"])) * 100)
            spread_chg = f"{spread_bp - prev_spread:+d}bp" if prev_spread is not None else "—"
            spread_dir = "up" if prev_spread and spread_bp > prev_spread else "down" if prev_spread and spread_bp < prev_spread else "neutral"
            rates_display.append({
                "name": "2s10s Spread",
                "value": f"{spread_bp:+d}bp",
                "chg": spread_chg,
                "direction": spread_dir,
            })
        else:
            spread_bp = None

        # Mortgage rates
        for name, series_id in MORTGAGE_SERIES.items():
            latest, prev, date_str = _fred_latest(series_id)
            if latest is not None:
                chg_str, direction = _fmt_chg(latest, prev, is_bp=True)
                rates_display.append({
                    "name": name,
                    "value": _fmt_rate(latest) if latest else "—",
                    "chg": chg_str,
                    "direction": direction,
                    "raw": latest,
                })

    # Extract key rates for use in later sections — fall back to 30Y if 10Y unavailable
    ten_y = next((r["raw"] for r in rates_display if "10-Year" in r["name"]), None)
    ten_y_label = "10Y"
    if ten_y is None:
        ten_y = next((r["raw"] for r in rates_display if "30-Year" in r["name"]), None)
        ten_y_label = "30Y"

    # Render rate cards — one st.markdown per card to avoid HTML size limits
    cols = st.columns(len(rates_display))
    for i, r in enumerate(rates_display):
        arrow_color = "#c45454" if r["direction"] == "up" else "#569542" if r["direction"] == "down" else "rgba(255,255,255,0.3)"
        arrow = "▲" if r["direction"] == "up" else "▼" if r["direction"] == "down" else "◆"
        with cols[i]:
            st.markdown(f'''
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
                        border-radius:10px;padding:14px 14px 10px">
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:6px">{r["name"]}</div>
                <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:rgba(255,255,255,0.95);line-height:1.1">{r["value"]}</div>
                <div style="display:flex;align-items:center;margin-top:8px;gap:4px">
                    <span style="color:{arrow_color};font-size:12px">{arrow}</span>
                    <span style="color:{arrow_color};font-size:11px">{r["chg"]}</span>
                </div>
            </div>
            ''', unsafe_allow_html=True)

    # ── Dividend Context + Sentiment + Fed Calendar ─────────────────────────
    col_ctx, col_sent_top, col_fed = st.columns([2, 1, 1])

    # Pre-fetch valuation data needed for context box
    spy_data = _yf_sp500_metrics()
    fwd_pe = spy_data.get("fwd_pe") or spy_data.get("trailing_pe")
    sp_div = spy_data.get("div_yield")
    sp_div_pct = (sp_div * 100 if sp_div and sp_div < 1 else sp_div) if sp_div else None

    with col_ctx:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
            'text-transform:uppercase;letter-spacing:0.06em;padding:12px 0 8px;'
            'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
            'Dividend Strategy Context</div>',
            unsafe_allow_html=True,
        )

        ten_y_str = f"{ten_y:.2f}%" if ten_y else "—"
        sp_yield_str = f"{sp_div_pct:.2f}%" if sp_div_pct else "—"
        qdvd_str = f"{qdvd_yield:.2f}%" if qdvd_yield else "—"

        erp_val = ""
        erp_color = "rgba(255,255,255,0.95)"
        if fwd_pe and fwd_pe > 0 and ten_y:
            ey = (1 / fwd_pe) * 100
            erp = ey - ten_y
            erp_bp = round(erp * 100)
            erp_val = f"{erp_bp:+d}bp"
            erp_color = "#c45454" if erp < 0.5 else "#C9A84C" if erp < 1.5 else "#569542"

        # Yield comparison
        st.markdown(f'''
        <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
                    border-radius:8px;padding:14px 16px;margin-bottom:8px">
            <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                        letter-spacing:0.06em;margin-bottom:6px">{ten_y_label} vs S&P Div Yield vs QDVD</div>
            <div style="font-size:18px;font-weight:700;font-family:'DM Serif Display',serif;
                        color:rgba(255,255,255,0.95)">
                {ten_y_str} <span style="color:rgba(255,255,255,0.3)">vs</span> {sp_yield_str}
                <span style="color:rgba(255,255,255,0.3)">vs</span>
                <span style="color:#C9A84C">{qdvd_str}</span>
            </div>
            <div style="font-size:11px;color:rgba(255,255,255,0.30);margin-top:4px">
                QDVD yield premium supports quality dividend positioning</div>
        </div>
        ''', unsafe_allow_html=True)

        # ERP + Yield Curve side by side
        curve_color = "#569542" if spread_bp and spread_bp > 0 else "#c45454" if spread_bp else "rgba(255,255,255,0.95)"
        curve_label = f"{spread_bp:+d}bp" if spread_bp is not None else "—"
        curve_note = "Normal curve" if spread_bp and spread_bp > 0 else "Inverted" if spread_bp and spread_bp <= 0 else ""

        st.markdown(f'''
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
                        border-radius:8px;padding:14px 16px">
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:6px">Equity Risk Premium</div>
                <div style="font-size:18px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:{erp_color}">{erp_val if erp_val else "—"}</div>
                <div style="font-size:10px;color:rgba(255,255,255,0.25);margin-top:4px">
                    Earnings yield − {ten_y_label}</div>
            </div>
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
                        border-radius:8px;padding:14px 16px">
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:6px">Yield Curve</div>
                <div style="font-size:18px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:{curve_color}">{curve_label}</div>
                <div style="font-size:10px;color:rgba(255,255,255,0.25);margin-top:4px">
                    {curve_note}</div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    with col_sent_top:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
            'text-transform:uppercase;letter-spacing:0.06em;padding:12px 0 8px;'
            'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
            'Sentiment</div>',
            unsafe_allow_html=True,
        )

        # VIX
        vix_data = _yf_quote("^VIX")
        vix_price = vix_data.get("price")
        sentiment_items = []
        if vix_price:
            vix_color = "#569542" if vix_price < 16 else "#C9A84C" if vix_price < 25 else "#c45454"
            sentiment_items.append(("VIX", f"{vix_price:.2f}", vix_color))

        # UMich Sentiment
        um_latest, um_prev, _ = _fred_latest("UMCSENT")
        if um_latest:
            um_color = "#569542" if um_latest > 80 else "#C9A84C" if um_latest > 60 else "#c45454"
            sentiment_items.append(("UMich Sentiment", f"{um_latest:.1f}", um_color))

        # Yield curve signal
        if spread_bp is not None:
            curve_label_s = "Normal" if spread_bp > 0 else "Inverted"
            curve_color_s = "#569542" if spread_bp > 0 else "#c45454"
            sentiment_items.append(("Yield Curve", f"{curve_label_s} ({spread_bp:+d}bp)", curve_color_s))

        for name, val, color in sentiment_items:
            st.markdown(f'''
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);
                        border-radius:8px;padding:12px 16px;margin-bottom:6px;
                        display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:13px;color:rgba(255,255,255,0.6)">{name}</span>
                <span style="font-size:16px;font-weight:700;font-family:'DM Serif Display',serif;
                             color:{color}">{val}</span>
            </div>
            ''', unsafe_allow_html=True)

    with col_fed:
        st.markdown("**Fed Meeting Calendar**")
        st.caption("CME FedWatch probabilities")

        # Fed meeting dates — manually maintained (these change infrequently)
        fed_meetings = [
            {"date": "Mar 18-19", "expectation": "Hold", "prob": "92%"},
            {"date": "May 6-7", "expectation": "Hold", "prob": "68%"},
            {"date": "Jun 17-18", "expectation": "Cut 25bp", "prob": "54%"},
            {"date": "Jul 29-30", "expectation": "Cut 25bp", "prob": "61%"},
            {"date": "Sep 16-17", "expectation": "Cut 25bp", "prob": "58%"},
            {"date": "Dec 16-17", "expectation": "Cut 25bp", "prob": "52%"},
        ]

        fed_html = []
        for m in fed_meetings:
            is_cut = "Cut" in m["expectation"]
            exp_color = "#569542" if is_cut else "rgba(255,255,255,0.4)"
            prob_color = "#569542" if is_cut else "rgba(255,255,255,0.5)"
            fed_html.append(f'''
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
                <div>
                    <div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.8)">{m["date"]}</div>
                    <div style="font-size:11px;color:{exp_color};margin-top:2px">{m["expectation"]}</div>
                </div>
                <div style="font-size:14px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:{prob_color}">{m["prob"]}</div>
            </div>
            ''')
        st.markdown("".join(fed_html), unsafe_allow_html=True)

    # ── Economic Indicators ────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
        'Economic Indicators</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Fetching economic data from FRED..."):
        econ_rows = []
        for name, cfg in ECON_SERIES.items():
            obs = _fred(cfg["id"], limit=15)
            if not obs:
                econ_rows.append((name, "—", "—", "neutral", "—", "neutral"))
                continue

            if cfg["transform"] == "yoy" and len(obs) >= 13:
                # Year-over-year percentage change
                latest_val = float(obs[0]["value"])
                year_ago_val = float(obs[12]["value"]) if len(obs) > 12 else None
                prev_month_val = float(obs[1]["value"])
                prev_year_ago = float(obs[13]["value"]) if len(obs) > 13 else None

                if year_ago_val and year_ago_val != 0:
                    yoy = ((latest_val / year_ago_val) - 1) * 100
                else:
                    yoy = None

                if prev_month_val and prev_year_ago and prev_year_ago != 0:
                    prev_yoy = ((prev_month_val / prev_year_ago) - 1) * 100
                else:
                    prev_yoy = None

                display_val = f"{yoy:.1f}%" if yoy is not None else "—"
                display_prev = f"{prev_yoy:.1f}%" if prev_yoy is not None else "—"
                trend = "down" if yoy and prev_yoy and yoy < prev_yoy else "up" if yoy and prev_yoy and yoy > prev_yoy else "neutral"
                signal = _signal_for_econ(name, yoy, prev_yoy)
                date_label = obs[0].get("date", "")[:7]

            else:
                latest_val = float(obs[0]["value"])
                prev_val = float(obs[1]["value"]) if len(obs) > 1 else None
                display_val = _fmt_econ_val(name, latest_val)
                display_prev = _fmt_econ_val(name, prev_val) if prev_val else "—"
                trend = "down" if prev_val and latest_val < prev_val else "up" if prev_val and latest_val > prev_val else "neutral"
                signal = _signal_for_econ(name, latest_val, prev_val)
                date_label = obs[0].get("date", "")[:10]

            econ_rows.append((name, display_val, display_prev, trend, date_label, signal))

    # Render as one single table inside a scroll container for alignment
    _tw = "width:100%;border-collapse:collapse;table-layout:fixed;min-width:580px"
    _th = ("padding:8px 10px;font-size:10px;font-weight:600;"
           "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
           "border-bottom:1px solid rgba(255,255,255,0.06);white-space:nowrap")
    _td_nw = "white-space:nowrap;"
    _coldef = ('<col style="width:25%"><col style="width:15%"><col style="width:15%">'
               '<col style="width:10%"><col style="width:18%"><col style="width:17%">')

    econ_html = (
        f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
        f'<table style="{_tw}"><colgroup>{_coldef}</colgroup>'
        f'<thead><tr>'
        f'<th style="text-align:left;{_th}">Indicator</th>'
        f'<th style="text-align:right;{_th}">Latest</th>'
        f'<th style="text-align:right;{_th}">Previous</th>'
        f'<th style="text-align:right;{_th}">Trend</th>'
        f'<th style="text-align:right;{_th}">Release</th>'
        f'<th style="text-align:right;{_th}">Signal</th>'
        f'</tr></thead><tbody>'
    )

    for name, val, prev, trend, date_label, signal in econ_rows:
        arrow = _trend_arrow(trend)
        badge = _signal_badge(signal)
        econ_html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03)">'
            f'<td style="text-align:left;padding:10px 10px;font-size:13px;font-weight:600;'
            f'color:rgba(255,255,255,0.8);{_td_nw}">{name}</td>'
            f'<td style="text-align:right;padding:10px 10px;font-size:15px;font-weight:700;'
            f'font-family:\'DM Serif Display\',serif;color:rgba(255,255,255,0.9);{_td_nw}">{val}</td>'
            f'<td style="text-align:right;padding:10px 10px;font-size:13px;'
            f'color:rgba(255,255,255,0.35);{_td_nw}">{prev}</td>'
            f'<td style="text-align:right;padding:10px 10px;{_td_nw}">{arrow}</td>'
            f'<td style="text-align:right;padding:10px 10px;font-size:11px;'
            f'color:rgba(255,255,255,0.3);{_td_nw}">{date_label}</td>'
            f'<td style="text-align:right;padding:10px 10px;{_td_nw}">{badge}</td>'
            f'</tr>'
        )

    econ_html += '</tbody></table></div>'
    st.markdown(econ_html, unsafe_allow_html=True)

    # ── Market Valuation — full width ────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
        'Market Valuation</div>',
        unsafe_allow_html=True,
    )

    val_rows = []

    if fwd_pe:
        status = "elevated" if fwd_pe > 20 else "neutral" if fwd_pe > 16 else "low"
        val_rows.append(("S&P 500 Fwd P/E", f"{fwd_pe:.1f}x", "Hist avg ~18.5x", status))

    # Earnings yield
    if fwd_pe and fwd_pe > 0:
        ey = (1 / fwd_pe) * 100
        note = f"vs {ten_y:.2f}% {ten_y_label}" if ten_y else ""
        status = "tight" if ten_y and ey - ten_y < 1 else "neutral"
        val_rows.append(("S&P 500 Earnings Yield", f"{ey:.2f}%", note, status))

        # Equity risk premium
        if ten_y:
            erp = ey - ten_y
            erp_bp = round(erp * 100)
            status = "alert" if erp < 0.5 else "watch" if erp < 1.5 else "neutral"
            val_rows.append(("Equity Risk Premium", f"{erp_bp:+d}bp", f"Earnings yield − {ten_y_label}", status))

    # S&P dividend yield
    if sp_div_pct:
        status = "low" if sp_div_pct < 1.5 else "neutral"
        val_rows.append(("S&P 500 Div Yield", f"{sp_div_pct:.2f}%", "Hist avg ~1.83%", status))

    # QDVD yield comparison
    if qdvd_yield and sp_div_pct:
        premium = qdvd_yield - sp_div_pct
        status = "positive" if premium > 0.5 else "neutral"
        val_rows.append(("QDVD Yield Premium", f"+{premium:.2f}%", f"QDVD {qdvd_yield:.2f}% vs S&P {sp_div_pct:.2f}%", status))

    # Mortgage rates as context
    for name, series_id in MORTGAGE_SERIES.items():
        latest, prev, _ = _fred_latest(series_id)
        if latest:
            status = "positive" if latest < 5.5 else "neutral" if latest < 7.0 else "elevated"
            val_rows.append((name, f"{latest:.2f}%", "Weekly avg from Freddie Mac", status))

    # Render as one single table inside a scroll container
    _vtw = "width:100%;border-collapse:collapse;table-layout:fixed;min-width:480px"
    _vth = ("padding:8px 10px;font-size:10px;font-weight:600;"
            "color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;"
            "border-bottom:1px solid rgba(255,255,255,0.06);white-space:nowrap")
    _vcoldef = '<col style="width:30%"><col style="width:18%"><col style="width:35%"><col style="width:17%">'
    _vtd_nw = "white-space:nowrap;"

    val_html = (
        f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
        f'<table style="{_vtw}"><colgroup>{_vcoldef}</colgroup>'
        f'<thead><tr>'
        f'<th style="text-align:left;{_vth}">Metric</th>'
        f'<th style="text-align:right;{_vth}">Current</th>'
        f'<th style="text-align:right;{_vth}">Context</th>'
        f'<th style="text-align:right;{_vth}">Signal</th>'
        f'</tr></thead><tbody>'
    )

    for name, val, note, status in val_rows:
        badge = _signal_badge(status)
        val_html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.03)">'
            f'<td style="text-align:left;padding:10px 10px;font-size:13px;font-weight:500;'
            f'color:rgba(255,255,255,0.7);{_vtd_nw}">{name}</td>'
            f'<td style="text-align:right;padding:10px 10px;font-size:15px;font-weight:700;'
            f'font-family:\'DM Serif Display\',serif;color:rgba(255,255,255,0.9);{_vtd_nw}">{val}</td>'
            f'<td style="text-align:right;padding:10px 10px;font-size:12px;'
            f'color:rgba(255,255,255,0.35);{_vtd_nw}">{note}</td>'
            f'<td style="text-align:right;padding:10px 10px;{_vtd_nw}">{badge}</td>'
            f'</tr>'
        )

    val_html += '</tbody></table></div>'
    st.markdown(val_html, unsafe_allow_html=True)

    st.caption(f"Data: FRED API · yfinance · {datetime.now().strftime('%I:%M %p')}")