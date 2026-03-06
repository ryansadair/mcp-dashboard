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
        return {
            "fwd_pe": info.get("forwardPE"),
            "trailing_pe": info.get("trailingPE"),
            "div_yield": info.get("dividendYield"),
            "price": getattr(spy.fast_info, "last_price", None),
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

SPREAD_SERIES = {
    "IG Credit Spread": "BAMLC0A0CM",        # ICE BofA US Corp Index OAS
    "HY Credit Spread": "BAMLH0A0HYM2",      # ICE BofA US HY Index OAS
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
        '📊 Rates & Yields</div>',
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

        # Credit spreads
        for name, series_id in SPREAD_SERIES.items():
            latest, prev, date_str = _fred_latest(series_id)
            if latest is not None:
                chg_str, direction = _fmt_chg(latest, prev, is_bp=True)
                rates_display.append({
                    "name": name,
                    "value": f"{latest:.0f}bp",
                    "chg": chg_str,
                    "direction": direction,
                })

    # Render rate cards as HTML
    cards_html = ['<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px">']
    for r in rates_display:
        arrow_color = "#c45454" if r["direction"] == "up" else "#569542" if r["direction"] == "down" else "rgba(255,255,255,0.3)"
        arrow = "▲" if r["direction"] == "up" else "▼" if r["direction"] == "down" else "◆"
        cards_html.append(f'''
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
        ''')
    cards_html.append('</div>')
    st.markdown("".join(cards_html), unsafe_allow_html=True)

    # ── Yield Curve Chart + Fed Calendar ───────────────────────────────────
    col_chart, col_fed = st.columns([3, 1])

    with col_chart:
        st.markdown("**2s10s Yield Curve Spread — 12 Month**")
        st.caption("Positive = normal curve · Negative = inverted (recession signal)")

        # Fetch 2Y and 10Y history
        hist_2y = _fred_history("DGS2", months=13)
        hist_10y = _fred_history("DGS10", months=13)

        if hist_2y and hist_10y:
            df_2y = pd.DataFrame(hist_2y, columns=["date", "val_2y"])
            df_10y = pd.DataFrame(hist_10y, columns=["date", "val_10y"])
            df_curve = pd.merge(df_2y, df_10y, on="date", how="inner")
            df_curve["spread"] = (df_curve["val_10y"] - df_curve["val_2y"]) * 100
            df_curve["date"] = pd.to_datetime(df_curve["date"])

            # Resample to weekly to smooth
            df_curve = df_curve.set_index("date").resample("W").last().dropna().reset_index()

            if len(df_curve) > 0:
                import plotly.graph_objects as go

                fig = go.Figure()

                # Positive fill
                pos_spread = df_curve["spread"].clip(lower=0)
                fig.add_trace(go.Scatter(
                    x=df_curve["date"], y=pos_spread,
                    fill="tozeroy", fillcolor="rgba(86,149,66,0.08)",
                    line=dict(width=0), showlegend=False, hoverinfo="skip",
                ))

                # Negative fill
                neg_spread = df_curve["spread"].clip(upper=0)
                fig.add_trace(go.Scatter(
                    x=df_curve["date"], y=neg_spread,
                    fill="tozeroy", fillcolor="rgba(196,84,84,0.08)",
                    line=dict(width=0), showlegend=False, hoverinfo="skip",
                ))

                # Main line
                fig.add_trace(go.Scatter(
                    x=df_curve["date"], y=df_curve["spread"],
                    mode="lines",
                    line=dict(color="#C9A84C", width=2.5),
                    name="2s10s Spread",
                    hovertemplate="%{x|%b %d, %Y}<br>Spread: %{y:+.0f}bp<extra></extra>",
                ))

                # Zero line
                fig.add_hline(y=0, line_dash="solid", line_color="rgba(255,255,255,0.15)", line_width=1)

                _layout = {
                    "paper_bgcolor": "rgba(255,255,255,0.02)",
                    "plot_bgcolor": "rgba(0,0,0,0)",
                    "font": dict(family="DM Sans", color="rgba(255,255,255,0.6)"),
                    "margin": dict(l=50, r=10, t=10, b=30),
                    "height": 220,
                    "showlegend": False,
                    "xaxis": dict(
                        gridcolor="rgba(255,255,255,0.04)", showline=False,
                        tickfont=dict(size=10),
                    ),
                    "yaxis": dict(
                        gridcolor="rgba(255,255,255,0.04)", showline=False,
                        tickfont=dict(size=10), ticksuffix="bp",
                    ),
                    "hovermode": "x unified",
                }
                fig.update_layout(**_layout)
                st.plotly_chart(fig, use_container_width=True, config={
                    "displayModeBar": False, "scrollZoom": False,
                    "doubleClick": False, "staticPlot": False,
                })
            else:
                st.info("Insufficient yield curve data from FRED.")
        else:
            st.info("Could not fetch yield curve data from FRED.")

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
        '📈 Economic Indicators</div>',
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

    # Render as HTML table
    econ_html = ['''
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
    <thead><tr>
        <th style="text-align:left;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Indicator</th>
        <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Latest</th>
        <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Previous</th>
        <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Trend</th>
        <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Release</th>
        <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
            color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
            border-bottom:1px solid rgba(255,255,255,0.06)">Signal</th>
    </tr></thead><tbody>
    ''']

    for name, val, prev, trend, date_label, signal in econ_rows:
        arrow = _trend_arrow(trend)
        badge = _signal_badge(signal)
        econ_html.append(f'''
        <tr style="border-bottom:1px solid rgba(255,255,255,0.03)">
            <td style="text-align:left;padding:10px 10px;font-size:13px;font-weight:600;
                color:rgba(255,255,255,0.8)">{name}</td>
            <td style="text-align:right;padding:10px 10px;font-size:15px;font-weight:700;
                font-family:'DM Serif Display',serif;color:rgba(255,255,255,0.9)">{val}</td>
            <td style="text-align:right;padding:10px 10px;font-size:13px;
                color:rgba(255,255,255,0.35)">{prev}</td>
            <td style="text-align:right;padding:10px 10px">{arrow}</td>
            <td style="text-align:right;padding:10px 10px;font-size:11px;
                color:rgba(255,255,255,0.3)">{date_label}</td>
            <td style="text-align:right;padding:10px 10px">{badge}</td>
        </tr>
        ''')

    econ_html.append('</tbody></table>')
    st.markdown("".join(econ_html), unsafe_allow_html=True)

    # ── Valuation & Sentiment ──────────────────────────────────────────────
    col_val, col_sent = st.columns([3, 1])

    with col_val:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
            'text-transform:uppercase;letter-spacing:0.06em;padding:12px 0 8px;'
            'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
            '🎯 Market Valuation</div>',
            unsafe_allow_html=True,
        )

        # Build valuation data
        spy_data = _yf_sp500_metrics()
        ten_y = next((r["raw"] for r in rates_display if "10-Year" in r["name"]), None) if rates_display else None

        val_rows = []

        fwd_pe = spy_data.get("fwd_pe")
        if fwd_pe:
            status = "elevated" if fwd_pe > 20 else "neutral" if fwd_pe > 16 else "low"
            val_rows.append(("S&P 500 Fwd P/E", f"{fwd_pe:.1f}x", "Hist avg ~18.5x", status))

        # Earnings yield
        if fwd_pe and fwd_pe > 0:
            ey = (1 / fwd_pe) * 100
            note = f"vs {ten_y:.2f}% 10Y" if ten_y else ""
            status = "tight" if ten_y and ey - ten_y < 1 else "neutral"
            val_rows.append(("S&P 500 Earnings Yield", f"{ey:.2f}%", note, status))

            # Equity risk premium
            if ten_y:
                erp = ey - ten_y
                erp_bp = round(erp * 100)
                status = "alert" if erp < 0.5 else "watch" if erp < 1.5 else "neutral"
                val_rows.append(("Equity Risk Premium", f"{erp_bp:+d}bp", "Earnings yield − 10Y", status))

        # S&P dividend yield
        sp_div = spy_data.get("div_yield")
        if sp_div:
            sp_div_pct = sp_div * 100 if sp_div < 1 else sp_div
            status = "low" if sp_div_pct < 1.5 else "neutral"
            val_rows.append(("S&P 500 Div Yield", f"{sp_div_pct:.2f}%", "Hist avg ~1.83%", status))

        # Credit spreads as valuation context
        for name, series_id in SPREAD_SERIES.items():
            latest, prev, _ = _fred_latest(series_id)
            if latest:
                status = "tight" if latest < 150 and "HY" in name else "tight" if latest < 100 and "IG" in name else "neutral"
                avg_label = "Hist avg ~450bp" if "HY" in name else "Hist avg ~130bp"
                val_rows.append((name, f"{latest:.0f}bp", avg_label, status))

        # Render valuation table
        val_html = ['''
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
        <thead><tr>
            <th style="text-align:left;padding:8px 10px;font-size:10px;font-weight:600;
                color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
                border-bottom:1px solid rgba(255,255,255,0.06)">Metric</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
                color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
                border-bottom:1px solid rgba(255,255,255,0.06)">Current</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
                color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
                border-bottom:1px solid rgba(255,255,255,0.06)">Context</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;font-weight:600;
                color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.06em;
                border-bottom:1px solid rgba(255,255,255,0.06)">Signal</th>
        </tr></thead><tbody>
        ''']

        for name, val, note, status in val_rows:
            badge = _signal_badge(status)
            val_html.append(f'''
            <tr style="border-bottom:1px solid rgba(255,255,255,0.03)">
                <td style="text-align:left;padding:10px 10px;font-size:13px;font-weight:500;
                    color:rgba(255,255,255,0.7)">{name}</td>
                <td style="text-align:right;padding:10px 10px;font-size:15px;font-weight:700;
                    font-family:'DM Serif Display',serif;color:rgba(255,255,255,0.9)">{val}</td>
                <td style="text-align:right;padding:10px 10px;font-size:12px;
                    color:rgba(255,255,255,0.35)">{note}</td>
                <td style="text-align:right;padding:10px 10px">{badge}</td>
            </tr>
            ''')

        val_html.append('</tbody></table>')
        st.markdown("".join(val_html), unsafe_allow_html=True)

    with col_sent:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
            'text-transform:uppercase;letter-spacing:0.06em;padding:12px 0 8px;'
            'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
            '🧭 Sentiment</div>',
            unsafe_allow_html=True,
        )

        # VIX from yfinance
        vix_data = _yf_quote("^VIX")
        vix_price = vix_data.get("price")
        vix_prev = vix_data.get("prev_close")

        sentiment_items = []
        if vix_price:
            vix_color = "#569542" if vix_price < 16 else "#C9A84C" if vix_price < 25 else "#c45454"
            sentiment_items.append(("VIX", f"{vix_price:.2f}", vix_color))

        # UMCSENT for consumer sentiment (already fetched above but get latest)
        um_latest, um_prev, _ = _fred_latest("UMCSENT")
        if um_latest:
            um_color = "#569542" if um_latest > 80 else "#C9A84C" if um_latest > 60 else "#c45454"
            sentiment_items.append(("UMich Sentiment", f"{um_latest:.1f}", um_color))

        # Yield curve signal
        if spread_bp is not None:
            curve_label = "Normal" if spread_bp > 0 else "Inverted"
            curve_color = "#569542" if spread_bp > 0 else "#c45454"
            sentiment_items.append(("Yield Curve", f"{curve_label} ({spread_bp:+d}bp)", curve_color))

        sent_html = ['<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:12px;padding:16px 20px">']
        for name, val, color in sentiment_items:
            sent_html.append(f'''
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.04)">
                <span style="font-size:13px;color:rgba(255,255,255,0.6)">{name}</span>
                <span style="font-size:16px;font-weight:700;font-family:'DM Serif Display',serif;
                             color:{color}">{val}</span>
            </div>
            ''')
        sent_html.append('</div>')
        st.markdown("".join(sent_html), unsafe_allow_html=True)

    # ── Dividend Strategy Context ──────────────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:12px">'
        '💡 Dividend Strategy Context</div>',
        unsafe_allow_html=True,
    )

    # Build context values
    ten_y_str = f"{ten_y:.2f}%" if ten_y else "—"
    sp_yield_str = f"{sp_div_pct:.2f}%" if sp_div else "—"
    qdvd_str = f"{qdvd_yield:.2f}%" if qdvd_yield else "—"

    erp_val = ""
    erp_color = "rgba(255,255,255,0.95)"
    if fwd_pe and ten_y:
        ey = (1 / fwd_pe) * 100
        erp = ey - ten_y
        erp_bp = round(erp * 100)
        erp_val = f"{erp_bp:+d}bp"
        erp_color = "#c45454" if erp < 0.5 else "#C9A84C" if erp < 1.5 else "#569542"

    context_html = f'''
    <div style="background:linear-gradient(135deg, rgba(7,65,90,0.12) 0%, rgba(86,149,66,0.06) 100%);
                border:1px solid rgba(201,168,76,0.15);border-radius:12px;padding:18px 22px;margin-bottom:16px">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px">
            <div>
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:4px">10Y vs S&P Div Yield vs QDVD</div>
                <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:rgba(255,255,255,0.95);margin-bottom:4px">
                    {ten_y_str} <span style="color:rgba(255,255,255,0.3)">vs</span> {sp_yield_str}
                    <span style="color:rgba(255,255,255,0.3)">vs</span>
                    <span style="color:#C9A84C">{qdvd_str}</span>
                </div>
                <div style="font-size:11px;color:rgba(255,255,255,0.35);line-height:1.5">
                    QDVD yield premium over S&P 500 supports quality dividend strategy positioning</div>
            </div>
            <div>
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:4px">Equity Risk Premium</div>
                <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:{erp_color};margin-bottom:4px">{erp_val if erp_val else "—"}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.35);line-height:1.5">
                    Near historic lows — stock valuations offer minimal premium over bonds</div>
            </div>
            <div>
                <div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;
                            letter-spacing:0.06em;margin-bottom:4px">Yield Curve</div>
                <div style="font-size:20px;font-weight:700;font-family:'DM Serif Display',serif;
                            color:{"#569542" if spread_bp and spread_bp > 0 else "#c45454" if spread_bp else "rgba(255,255,255,0.95)"};
                            margin-bottom:4px">{f"{spread_bp:+d}bp" if spread_bp is not None else "—"}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.35);line-height:1.5">
                    {"Normal curve — positive for economic outlook and bank earnings" if spread_bp and spread_bp > 0 else "Inverted — historically signals recession risk" if spread_bp and spread_bp <= 0 else ""}</div>
            </div>
        </div>
    </div>
    '''
    st.markdown(context_html, unsafe_allow_html=True)

    st.caption(f"Data: FRED API · yfinance · {datetime.now().strftime('%I:%M %p')}")