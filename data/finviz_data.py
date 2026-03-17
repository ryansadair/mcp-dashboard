"""
Martin Capital Partners — Finviz Data Module
data/finviz_data.py

Fetches analyst ratings, price targets, insider activity, and technical
signals from Finviz via the finvizfinance library.

Key fields per ticker:
  - Analyst recommendation (1-5 scale: 1=Buy, 5=Sell)
  - Target price (consensus)
  - Price vs target (% upside/downside)
  - Insider ownership %
  - Insider transactions (recent buys/sells)
  - RSI (14-day)
  - SMA20, SMA50, SMA200 distance
  - Short float %
  - Volatility (weekly/monthly)

Caching: 1 hour TTL (analyst data doesn't change intraday).
"""

import streamlit as st
from datetime import datetime


# ── Field mapping from finvizfinance fundament dict ────────────────────────
# finvizfinance returns a dict with human-readable keys like "Target Price",
# "Recom", "RSI (14)", etc. We map to our internal names.

_FIELD_MAP = {
    "Recom":            "recommendation",
    "Target Price":     "target_price",
    "Price":            "price",
    "RSI (14)":         "rsi_14",
    "SMA20":            "sma20_dist",
    "SMA50":            "sma50_dist",
    "SMA200":           "sma200_dist",
    "Short Float":      "short_float",
    "Insider Own":      "insider_own",
    "Insider Trans":    "insider_trans",
    "Inst Own":         "inst_own",
    "Inst Trans":       "inst_trans",
    "Volatility":       "volatility",
    "Perf Week":        "perf_week",
    "Perf Month":       "perf_month",
    "Perf Quarter":     "perf_quarter",
    "Perf Half Y":      "perf_half",
    "Perf Year":        "perf_year",
    "Perf YTD":         "perf_ytd",
    "Avg Volume":       "avg_volume",
    "Rel Volume":       "rel_volume",
    "Earnings":         "earnings_date",
    "Beta":             "beta",
    "ATR":              "atr",
    "52W High":         "from_52w_high",
    "52W Low":          "from_52w_low",
    "P/E":              "pe",
    "Forward P/E":      "forward_pe",
    "PEG":              "peg",
    "P/S":              "ps",
    "P/B":              "pb",
    "P/FCF":            "p_fcf",
    "EPS (ttm)":        "eps_ttm",
    "EPS next Y":       "eps_next_y",
    "EPS next Q":       "eps_next_q",
    "Dividend %":       "div_yield_finviz",
    "ROE":              "roe",
    "ROA":              "roa",
    "ROI":              "roi",
    "Gross Margin":     "gross_margin",
    "Oper. Margin":     "oper_margin",
    "Profit Margin":    "profit_margin",
}


def _parse_pct(val):
    """Parse a percentage string like '5.23%' or '-1.20%' to float."""
    if val is None or val == "" or val == "-":
        return None
    try:
        s = str(val).replace("%", "").strip()
        return round(float(s), 2)
    except (ValueError, TypeError):
        return None


def _parse_float(val):
    """Parse a numeric string, handling commas and special chars."""
    if val is None or val == "" or val == "-":
        return None
    try:
        s = str(val).replace(",", "").replace("$", "").strip()
        return round(float(s), 2)
    except (ValueError, TypeError):
        return None


def _parse_recommendation(val):
    """Parse Finviz recommendation (1-5 float) to human label + numeric."""
    num = _parse_float(val)
    if num is None:
        return None, "—"

    if num <= 1.5:
        label = "Strong Buy"
    elif num <= 2.0:
        label = "Buy"
    elif num <= 2.5:
        label = "Outperform"
    elif num <= 3.0:
        label = "Hold"
    elif num <= 3.5:
        label = "Underperform"
    elif num <= 4.0:
        label = "Sell"
    else:
        label = "Strong Sell"

    return round(num, 1), label


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_finviz_batch(tickers_tuple):
    """
    Fetch Finviz fundamental snapshot for a batch of tickers.

    Returns dict: {
        "TICK": {
            "recommendation": 2.1,
            "rec_label": "Buy",
            "target_price": 185.00,
            "upside_pct": 12.3,
            "rsi_14": 55.2,
            "sma20_dist": 1.5,
            "sma50_dist": 3.2,
            "sma200_dist": 8.1,
            "short_float": 1.2,
            "insider_own": 5.3,
            "insider_trans": -0.5,
            "inst_own": 78.2,
            ...
        }
    }
    """
    results = {}

    try:
        from finvizfinance.quote import finvizfinance
        import time as _time

        for ticker in tickers_tuple:
            try:
                stock = finvizfinance(ticker)
                raw = stock.ticker_fundament()

                if not raw:
                    results[ticker] = {}
                    continue

                parsed = {}
                for finviz_key, our_key in _FIELD_MAP.items():
                    val = raw.get(finviz_key)
                    if our_key == "recommendation":
                        num, label = _parse_recommendation(val)
                        parsed["recommendation"] = num
                        parsed["rec_label"] = label
                    elif our_key in (
                        "sma20_dist", "sma50_dist", "sma200_dist",
                        "short_float", "insider_own", "insider_trans",
                        "inst_own", "inst_trans",
                        "perf_week", "perf_month", "perf_quarter",
                        "perf_half", "perf_year", "perf_ytd",
                        "from_52w_high", "from_52w_low",
                        "div_yield_finviz",
                        "roe", "roa", "roi",
                        "gross_margin", "oper_margin", "profit_margin",
                    ):
                        parsed[our_key] = _parse_pct(val)
                    elif our_key == "volatility":
                        # Finviz returns "3.50% 2.10%" (weekly monthly)
                        parts = str(val).split() if val else []
                        parsed["vol_weekly"] = _parse_pct(parts[0]) if len(parts) >= 1 else None
                        parsed["vol_monthly"] = _parse_pct(parts[1]) if len(parts) >= 2 else None
                    elif our_key == "earnings_date":
                        parsed[our_key] = str(val).strip() if val and val != "-" else None
                    else:
                        parsed[our_key] = _parse_float(val)

                # Compute upside/downside to target
                if parsed.get("target_price") and parsed.get("price"):
                    tp = parsed["target_price"]
                    px = parsed["price"]
                    parsed["upside_pct"] = round((tp - px) / px * 100, 1) if px > 0 else None
                else:
                    parsed["upside_pct"] = None

                results[ticker] = parsed
                _time.sleep(0.5)  # rate limit: ~2 req/sec to avoid Finviz throttle

            except Exception:
                results[ticker] = {}

    except ImportError:
        # finvizfinance not installed
        for ticker in tickers_tuple:
            results[ticker] = {}

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_finviz_insider_activity(ticker):
    """
    Fetch recent insider transactions for a single ticker.
    Returns list of dicts: [{date, owner, transaction, value, shares_total}, ...]
    Limited to 10 most recent for display.
    """
    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(ticker)
        df = stock.ticker_inside_trader()
        if df is None or df.empty:
            return []

        rows = []
        for _, row in df.head(10).iterrows():
            rows.append({
                "date": str(row.get("Date", "")),
                "owner": str(row.get("Insider Trading", row.get("Insider", ""))),
                "relationship": str(row.get("Relationship", "")),
                "transaction": str(row.get("Transaction", "")),
                "value": str(row.get("Value ($)", row.get("Value", ""))),
                "shares_total": str(row.get("#Shares Total", "")),
            })
        return rows
    except Exception:
        return []


# ── Rendering helpers (used by Holdings tab and Alerts tab) ────────────────

def recommendation_badge(rec_val, rec_label):
    """Return HTML for a colored recommendation badge."""
    if rec_val is None:
        return '<span style="font-size:11px;color:rgba(255,255,255,0.3);">—</span>'

    if rec_val <= 2.0:
        bg = "rgba(86,149,66,0.15)"
        color = "#569542"
    elif rec_val <= 3.0:
        bg = "rgba(201,168,76,0.12)"
        color = "#C9A84C"
    else:
        bg = "rgba(196,84,84,0.12)"
        color = "#c45454"

    return (
        f'<span style="padding:2px 8px;border-radius:4px;font-size:11px;'
        f'font-weight:600;background:{bg};color:{color};">'
        f'{rec_label} ({rec_val})</span>'
    )


def upside_badge(upside_pct):
    """Return HTML for an upside/downside badge."""
    if upside_pct is None:
        return '<span style="font-size:11px;color:rgba(255,255,255,0.3);">—</span>'

    if upside_pct >= 10:
        color = "#569542"
    elif upside_pct >= 0:
        color = "rgba(255,255,255,0.6)"
    elif upside_pct >= -10:
        color = "#C9A84C"
    else:
        color = "#c45454"

    arrow = "▲" if upside_pct >= 0 else "▼"
    return (
        f'<span style="font-size:12px;font-weight:500;color:{color};">'
        f'{arrow} {upside_pct:+.1f}%</span>'
    )


def rsi_indicator(rsi):
    """Return HTML for an RSI indicator with color coding."""
    if rsi is None:
        return '<span style="font-size:11px;color:rgba(255,255,255,0.3);">—</span>'

    if rsi >= 70:
        color = "#c45454"
        label = "Overbought"
    elif rsi >= 60:
        color = "#C9A84C"
        label = ""
    elif rsi >= 40:
        color = "rgba(255,255,255,0.6)"
        label = ""
    elif rsi >= 30:
        color = "#C9A84C"
        label = ""
    else:
        color = "#569542"
        label = "Oversold"

    suffix = f' <span style="font-size:9px;opacity:0.5;">{label}</span>' if label else ""
    return f'<span style="font-size:12px;color:{color};">{rsi:.0f}{suffix}</span>'