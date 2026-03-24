"""
Martin Capital Partners — News & Alerts Tab
data/alerts_tab.py

Top section: Market news headlines from RSS feeds (CNBC, MarketWatch).
Bottom section: Portfolio alerts computed live from Supabase data.

News sources (RSS, no API keys needed):
  - MarketWatch Top Stories
  - CNBC Top News
  - CNBC Economy

Alert types:
  1. Price Movers     — holdings with ±2% daily change
  2. Dividend Events  — upcoming ex-dates, recent increases/cuts
  3. Earnings Dates   — holdings reporting within the next 14 days
  4. 52-Week Extremes — holdings within 5% of 52-week high or low

Data sources:
  - RSS feeds via feedparser (cached 15 min)
  - Supabase prices table (change_1d_pct, week52_high, week52_low, price)
  - Supabase dividends table (ex_dividend_date, div_growth_1y, dividend_rate)
  - yfinance earnings dates (fetched live, cached 1hr)
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from utils.config import BRAND, STRATEGIES
from data.market_data import fetch_batch_prices
from data.tamarac_parser import (
    get_holdings_for_strategy,
    get_all_unique_tickers,
    STRATEGY_NAMES,
)

# Dividend data
try:
    from data.dividends import get_batch_dividend_details
    _DIV_AVAILABLE = True
except ImportError:
    _DIV_AVAILABLE = False

# Fish CCC data for authoritative streak/growth info
try:
    from data.dividend_streaks import get_fish_metrics, get_streak
    _FISH_AVAILABLE = True
except ImportError:
    _FISH_AVAILABLE = False

# ── Colors ─────────────────────────────────────────────────────────────────
GREEN = BRAND["green"]
BLUE  = BRAND["blue"]
GOLD  = BRAND["gold"]
RED   = BRAND["red"]

# ── Alert severity config ──────────────────────────────────────────────────
SEVERITY_STYLES = {
    "critical": {"dot": RED,   "bg": "rgba(196,84,84,0.08)",  "border": "rgba(196,84,84,0.25)",  "icon": "🔴"},
    "warning":  {"dot": GOLD,  "bg": "rgba(201,168,76,0.06)", "border": "rgba(201,168,76,0.20)", "icon": "🟡"},
    "positive": {"dot": GREEN, "bg": "rgba(86,149,66,0.06)",  "border": "rgba(86,149,66,0.20)",  "icon": "🟢"},
    "info":     {"dot": BLUE,  "bg": "rgba(7,65,90,0.08)",    "border": "rgba(7,65,90,0.25)",    "icon": "🔵"},
}


# ══════════════════════════════════════════════════════════════════════════
# ALERT GENERATORS
# ══════════════════════════════════════════════════════════════════════════

def _price_mover_alerts(tickers, price_data, threshold=2.0):
    """
    Flag holdings with daily moves exceeding ±threshold%.
    Returns list of alert dicts.
    """
    alerts = []
    for ticker in tickers:
        mkt = price_data.get(ticker, {})
        chg = mkt.get("change_1d_pct", 0) or 0
        price = mkt.get("price", 0) or 0
        name = mkt.get("name", ticker)

        if abs(chg) >= threshold:
            direction = "up" if chg > 0 else "down"
            severity = "positive" if chg > 0 else "warning" if chg > -5 else "critical"
            alerts.append({
                "type": "price",
                "severity": severity,
                "ticker": ticker,
                "title": f"{ticker} {'▲' if chg > 0 else '▼'} {chg:+.2f}%",
                "detail": f"{name} — ${price:.2f}",
                "value": chg,
                "sort_key": abs(chg),
            })

    # Sort by change value: best (most positive) on top, worst (most negative) on bottom
    alerts.sort(key=lambda a: a["value"], reverse=True)
    return alerts


def _dividend_alerts(tickers, price_data, div_data):
    """
    Flag upcoming ex-dividend dates and notable dividend changes.
    Returns list of alert dicts.
    """
    alerts = []
    today = datetime.now().date()

    for ticker in tickers:
        dd = div_data.get(ticker, {})
        mkt = price_data.get(ticker, {})
        name = mkt.get("name", ticker)

        # Upcoming ex-dividend date (within 14 days)
        ex_date_str = dd.get("ex_dividend_date", "")
        if ex_date_str:
            try:
                ex_date = datetime.strptime(ex_date_str[:10], "%Y-%m-%d").date()
                days_until = (ex_date - today).days
                if 0 <= days_until <= 14:
                    div_rate = dd.get("dividend_rate", 0) or 0
                    amt_str = f" — ${div_rate / 4:.2f}/share" if div_rate > 0 else ""
                    severity = "info" if days_until > 3 else "warning"
                    alerts.append({
                        "type": "dividend",
                        "severity": severity,
                        "ticker": ticker,
                        "title": f"{ticker} ex-dividend {ex_date.strftime('%b %d')}",
                        "detail": f"{name}{amt_str} · {days_until}d away" if days_until > 0 else f"{name}{amt_str} · TODAY",
                        "value": days_until,
                        "sort_key": days_until,
                    })
            except (ValueError, TypeError):
                pass

        # Dividend growth alerts — Fish CCC data tracks regular dividends only,
        # but ADRs (KOF, TTE) can appear in Fish with FX-distorted growth rates.
        # Only trust Fish growth as "real" if growth is positive OR the ticker has
        # a meaningful streak (5+ years). Otherwise treat as unreliable.
        growth_1y = 0
        _source = "yfinance"
        _fish_reliable = False

        if _FISH_AVAILABLE:
            fish = get_fish_metrics(ticker)
            ccc_years, _ = get_streak(ticker)
            fish_growth = fish.get("dgr_1y", 0) or 0

            if fish_growth != 0 or ccc_years > 0:
                growth_1y = fish_growth
                _source = "CCC"
                # Only mark as reliable if positive growth or long streak
                if fish_growth >= 0 or ccc_years >= 5:
                    _fish_reliable = True
                # else: negative growth + short streak → likely ADR/special noise

        if _source == "yfinance":
            growth_1y = dd.get("div_growth_1y", 0) or 0

        if growth_1y >= 10:
            alerts.append({
                "type": "dividend",
                "severity": "positive",
                "ticker": ticker,
                "title": f"{ticker} dividend grew {growth_1y:+.1f}% (1Y)",
                "detail": f"{name} — strong dividend growth ({_source})",
                "value": growth_1y,
                "sort_key": 100 - growth_1y,
            })
        elif _fish_reliable and growth_1y < -5:
            # Reliable Fish data with negative growth — real cut concern
            alerts.append({
                "type": "dividend",
                "severity": "critical",
                "ticker": ticker,
                "title": f"{ticker} dividend declined {growth_1y:+.1f}% (1Y)",
                "detail": f"{name} — potential dividend cut ({_source})",
                "value": growth_1y,
                "sort_key": 0,
            })
        elif not _fish_reliable and growth_1y < -15:
            # Unreliable source (ADR in Fish or yfinance) — strict threshold + caveat
            alerts.append({
                "type": "dividend",
                "severity": "warning",
                "ticker": ticker,
                "title": f"{ticker} dividend may have declined {growth_1y:+.1f}% (1Y)",
                "detail": f"{name} — verify manually (may be ADR FX effect or special div drop)",
                "value": growth_1y,
                "sort_key": 1,
            })

    alerts.sort(key=lambda a: a["sort_key"])
    return alerts


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_earnings_dates(tickers_tuple):
    """
    Fetch upcoming earnings dates from yfinance.
    Cached 1 hour since earnings calendars don't change often.
    Returns dict: {ticker: earnings_date_str}
    """
    result = {}
    try:
        import yfinance as yf
        import time as _time

        for ticker in tickers_tuple:
            try:
                tk = yf.Ticker(ticker)
                cal = tk.calendar
                if cal is not None and not cal.empty:
                    # calendar can be a DataFrame with "Earnings Date" row
                    if "Earnings Date" in cal.index:
                        dates = cal.loc["Earnings Date"]
                        if len(dates) > 0:
                            ed = dates.iloc[0]
                            if hasattr(ed, "strftime"):
                                result[ticker] = ed.strftime("%Y-%m-%d")
                            elif isinstance(ed, str):
                                result[ticker] = ed[:10]
                elif isinstance(cal, dict) and "Earnings Date" in cal:
                    dates = cal["Earnings Date"]
                    if dates:
                        ed = dates[0] if isinstance(dates, list) else dates
                        if hasattr(ed, "strftime"):
                            result[ticker] = ed.strftime("%Y-%m-%d")
                _time.sleep(0.15)
            except Exception:
                pass
    except ImportError:
        pass
    return result


def _earnings_alerts(tickers, price_data, days_ahead=14):
    """
    Flag holdings with earnings dates within the next N days.
    Returns list of alert dicts.
    """
    alerts = []
    today = datetime.now().date()

    earnings_dates = _fetch_earnings_dates(tuple(tickers))

    for ticker, date_str in earnings_dates.items():
        try:
            earn_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            days_until = (earn_date - today).days
            if 0 <= days_until <= days_ahead:
                mkt = price_data.get(ticker, {})
                name = mkt.get("name", ticker)
                severity = "warning" if days_until <= 3 else "info"
                alerts.append({
                    "type": "earnings",
                    "severity": severity,
                    "ticker": ticker,
                    "title": f"{ticker} earnings {earn_date.strftime('%b %d')}",
                    "detail": f"{name} · {days_until}d away" if days_until > 0 else f"{name} · TODAY",
                    "value": days_until,
                    "sort_key": days_until,
                })
        except (ValueError, TypeError):
            pass

    alerts.sort(key=lambda a: a["sort_key"])
    return alerts


def _proximity_alerts(tickers, price_data, threshold_pct=5.0):
    """
    Flag holdings near their 52-week high or low.
    Returns list of alert dicts.
    """
    alerts = []
    for ticker in tickers:
        mkt = price_data.get(ticker, {})
        price = mkt.get("price", 0) or 0
        hi = mkt.get("52w_high", 0) or 0
        lo = mkt.get("52w_low", 0) or 0
        name = mkt.get("name", ticker)

        if price <= 0 or hi <= 0:
            continue

        pct_from_hi = ((price - hi) / hi) * 100
        pct_from_lo = ((price - lo) / lo) * 100 if lo > 0 else 999

        if abs(pct_from_hi) <= threshold_pct:
            alerts.append({
                "type": "52w",
                "severity": "positive",
                "ticker": ticker,
                "title": f"{ticker} near 52-week high ({pct_from_hi:+.1f}%)",
                "detail": f"{name} — ${price:.2f} vs high ${hi:.2f}",
                "value": pct_from_hi,
                "sort_key": abs(pct_from_hi),
            })
        elif pct_from_lo <= threshold_pct:
            alerts.append({
                "type": "52w",
                "severity": "warning",
                "ticker": ticker,
                "title": f"{ticker} near 52-week low (+{pct_from_lo:.1f}% from low)",
                "detail": f"{name} — ${price:.2f} vs low ${lo:.2f}",
                "value": pct_from_lo,
                "sort_key": pct_from_lo,
            })

    alerts.sort(key=lambda a: a["sort_key"])
    return alerts


# ══════════════════════════════════════════════════════════════════════════
# RENDERING
# ══════════════════════════════════════════════════════════════════════════

def _render_alert_card(alert):
    """Render a single alert as a styled HTML card."""
    sev = SEVERITY_STYLES.get(alert["severity"], SEVERITY_STYLES["info"])
    return (
        f'<div style="padding:12px 14px;margin-bottom:8px;border-radius:8px;'
        f'background:{sev["bg"]};border-left:3px solid {sev["dot"]};">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
        f'<div>'
        f'<div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.85);">'
        f'{sev["icon"]} {alert["title"]}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.45);margin-top:3px;">'
        f'{alert["detail"]}</div>'
        f'</div>'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.25);text-transform:uppercase;'
        f'letter-spacing:0.06em;white-space:nowrap;margin-left:12px;">'
        f'{alert["type"]}</div>'
        f'</div>'
        f'</div>'
    )


def _render_alert_section(title, alerts):
    """Render a section header + list of alerts."""
    if not alerts:
        return

    st.markdown(
        f'<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        f'text-transform:uppercase;letter-spacing:0.06em;padding:16px 0 8px;'
        f'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        f'{title}'
        f'<span style="font-size:11px;font-weight:400;color:rgba(255,255,255,0.3);'
        f'margin-left:8px;">{len(alerts)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Render each alert individually to avoid HTML size limits
    for alert in alerts:
        st.markdown(_render_alert_card(alert), unsafe_allow_html=True)


def _render_summary_bar(all_alerts):
    """Render a summary bar with alert counts by severity."""
    counts = {"critical": 0, "warning": 0, "positive": 0, "info": 0}
    for a in all_alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1

    parts = []
    for sev, count in counts.items():
        if count > 0:
            s = SEVERITY_STYLES[sev]
            parts.append(
                f'<div style="display:flex;align-items:center;gap:6px;'
                f'padding:8px 14px;border-radius:6px;background:{s["bg"]};'
                f'border:1px solid {s["border"]};">'
                f'<span style="font-size:16px;">{s["icon"]}</span>'
                f'<span style="font-size:18px;font-weight:700;font-family:\'DM Serif Display\',serif;'
                f'color:rgba(255,255,255,0.9);">{count}</span>'
                f'<span style="font-size:10px;color:rgba(255,255,255,0.4);text-transform:uppercase;'
                f'letter-spacing:0.06em;">{sev}</span>'
                f'</div>'
            )

    if parts:
        st.markdown(
            f'<div style="display:flex;gap:12px;margin-bottom:16px;">{"".join(parts)}</div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════
# NEWS HEADLINES (RSS)
# ══════════════════════════════════════════════════════════════════════════

# RSS feed sources — free, no API keys, reliable
_NEWS_FEEDS = [
    {
        "name": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "color": GREEN,
    },
    {
        "name": "CNBC",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "color": BLUE,
    },
    {
        "name": "CNBC Economy",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        "color": GOLD,
    },
]


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_news_headlines(max_per_feed=5, max_total=12):
    """
    Fetch headlines from RSS feeds. Cached 15 min.
    Returns list of dicts: [{title, link, source, published, source_color}]
    """
    try:
        import feedparser
    except ImportError:
        return []

    headlines = []

    for feed_cfg in _NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            for entry in feed.entries[:max_per_feed]:
                # Parse published date
                pub_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        from time import mktime
                        pub_dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                        # Relative time
                        delta = datetime.now() - pub_dt
                        if delta.total_seconds() < 3600:
                            pub_str = f"{int(delta.total_seconds() / 60)}m ago"
                        elif delta.total_seconds() < 86400:
                            pub_str = f"{int(delta.total_seconds() / 3600)}h ago"
                        else:
                            pub_str = pub_dt.strftime("%b %d")
                    except Exception:
                        pub_str = entry.get("published", "")[:16]

                headlines.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "source": feed_cfg["name"],
                    "source_color": feed_cfg["color"],
                    "published": pub_str,
                    "sort_ts": getattr(entry, "published_parsed", None),
                })
        except Exception:
            continue

    # Sort by publish time (newest first), then cap total
    headlines.sort(
        key=lambda h: h.get("sort_ts") or (0, 0, 0, 0, 0, 0, 0, 0, 0),
        reverse=True,
    )
    return headlines[:max_total]


def _render_news_section():
    """Render the news headlines section."""
    headlines = _fetch_news_headlines()

    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:0 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        'Market Headlines'
        '</div>',
        unsafe_allow_html=True,
    )

    if not headlines:
        st.markdown(
            '<div style="font-size:12px;color:rgba(255,255,255,0.35);padding:12px 0;">'
            'Unable to load news feeds. Check that <code>feedparser</code> is in requirements.txt.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Render headlines as compact cards
    for h in headlines:
        src_color = h.get("source_color", "rgba(255,255,255,0.3)")
        html = (
            f'<div style="padding:10px 14px;margin-bottom:6px;border-radius:6px;'
            f'background:rgba(255,255,255,0.02);border-left:3px solid {src_color};'
            f'display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">'
            f'<div style="flex:1;min-width:0;">'
            f'<a href="{h["link"]}" target="_blank" rel="noopener" style="'
            f'font-size:13px;font-weight:500;color:rgba(255,255,255,0.82);'
            f'text-decoration:none;line-height:1.4;display:block;'
            f'overflow:hidden;text-overflow:ellipsis;">{h["title"]}</a>'
            f'</div>'
            f'<div style="display:flex;flex-direction:column;align-items:flex-end;'
            f'flex-shrink:0;gap:2px;">'
            f'<span style="font-size:10px;font-weight:600;color:{src_color};'
            f'text-transform:uppercase;letter-spacing:0.04em;">{h["source"]}</span>'
            f'<span style="font-size:10px;color:rgba(255,255,255,0.25);">'
            f'{h["published"]}</span>'
            f'</div>'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)

    st.markdown(
        '<div style="height:12px;border-bottom:1px solid rgba(255,255,255,0.04);'
        'margin-bottom:12px;"></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════

def render_alerts_tab(tamarac_parsed, active_strategy):
    """
    Render the full Alerts & Activity tab.

    Args:
        tamarac_parsed: dict from parse_tamarac_excel()
        active_strategy: str, e.g. "QDVD"
    """

    st.markdown(
        '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px">'
        'Market news · portfolio alerts · computed from RSS feeds + Supabase data'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── News Headlines (top section) ─────────────────────────────────────
    _render_news_section()

    # ── Portfolio Alerts (bottom section) ─────────────────────────────────
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:rgba(255,255,255,0.6);'
        'text-transform:uppercase;letter-spacing:0.06em;padding:0 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px">'
        'Portfolio Alerts'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Scope selector ────────────────────────────────────────────────────
    scope = st.radio(
        "Alert scope",
        ["Current strategy", "All strategies"],
        horizontal=True,
        key="alerts_scope",
        label_visibility="collapsed",
    )

    # ── Gather tickers ────────────────────────────────────────────────────
    if scope == "All strategies":
        tickers = sorted(get_all_unique_tickers(tamarac_parsed))
        scope_label = "all strategies"
    else:
        tam_df = get_holdings_for_strategy(tamarac_parsed, active_strategy)
        if tam_df.empty:
            st.info("No holdings for this strategy in Tamarac file.")
            return
        tickers = tam_df["symbol"].tolist()
        scope_label = STRATEGY_NAMES.get(active_strategy, active_strategy)

    # ── Fetch data ────────────────────────────────────────────────────────
    with st.spinner(f"Scanning {len(tickers)} holdings for alerts..."):
        price_data = fetch_batch_prices(tuple(tickers))

        div_data = {}
        if _DIV_AVAILABLE:
            div_data = get_batch_dividend_details(tuple(tickers))

    # ── Generate alerts ───────────────────────────────────────────────────
    price_alerts = _price_mover_alerts(tickers, price_data)
    div_alerts = _dividend_alerts(tickers, price_data, div_data) if div_data else []
    earnings_alerts = _earnings_alerts(tickers, price_data)
    proximity_alerts = _proximity_alerts(tickers, price_data)

    all_alerts = price_alerts + div_alerts + earnings_alerts + proximity_alerts

    # ── Summary bar ───────────────────────────────────────────────────────
    st.markdown(
        f"**{len(all_alerts)} alerts** across {len(tickers)} holdings in {scope_label}",
    )
    _render_summary_bar(all_alerts)

    if not all_alerts:
        st.success("✅ No alerts — all holdings within normal ranges.")
        st.caption(f"Checked: ±2% price moves, ex-dividend dates, earnings dates, 52-week proximity")
        return

    # ── Render sections ───────────────────────────────────────────────────
    if price_alerts:
        _render_alert_section("Price Movers (±2%+ Today)", price_alerts)

    if div_alerts:
        _render_alert_section("Dividend Events", div_alerts)

    if earnings_alerts:
        _render_alert_section("Upcoming Earnings", earnings_alerts)

    if proximity_alerts:
        _render_alert_section("52-Week Proximity", proximity_alerts)

    # ── Footer ────────────────────────────────────────────────────────────
    st.caption(
        f"Alerts computed live from Supabase · {len(tickers)} tickers · "
        f"{datetime.now().strftime('%I:%M %p')}"
    )