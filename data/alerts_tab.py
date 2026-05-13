"""
Martin Capital Partners — News & Alerts Tab
data/alerts_tab.py

Section order (top to bottom):
  Row 1 (side-by-side on desktop, stacked on mobile):
    Left:  Price Movers      — holdings with ±2% daily change
    Left:  Dividend Events   — upcoming ex-dates within 14 days
    Right: Earnings Calendar — holdings reporting in next 30 days,
                               grouped by week, with BMO/AMC flag
  Row 2 (full width):
    Market Headlines — markets-focused RSS feeds
    Holdings News    — filtered ticker-specific news (quality-sourced)

News filtering:
  - Holdings news requires ticker symbol or company name in the title.
  - Listicle/clickbait patterns are blocklisted ("3 stocks to buy", etc.).
  - Junk publishers (Zacks, MarketBeat, Motley Fool, InvestorPlace, etc.) are
    suppressed unless they are the only available source for a holding.

Data sources:
  - RSS feeds via feedparser (cached 15 min) — CNBC/MarketWatch/Reuters/WSJ Markets
  - Supabase prices table (change_1d_pct, price)
  - Supabase dividends table (ex_dividend_date, dividend_rate)
  - Finviz earnings_date field (cached 1 hr via finviz_data) — primary source,
    includes BMO/AMC timing flag
  - yfinance earnings dates (cached 1 hr) — fallback when Finviz misses
  - yfinance ticker news (cached 15 min)

Sprint 25-6: replaced standalone "Upcoming Earnings" alert section with a
dedicated 30-day Earnings Calendar grouped by week. Side-by-side layout for
desktop, native mobile stacking.
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

# Finviz earnings date is the primary source for the Earnings Calendar — it
# returns "May 12 BMO" / "May 15 AMC" style strings with timing flags. yfinance
# is the fallback for any ticker Finviz didn't return.
try:
    from data.finviz_data import fetch_finviz_batch
    _FINVIZ_AVAILABLE = True
except ImportError:
    _FINVIZ_AVAILABLE = False

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
            chg_color = "#569542" if chg > 0 else "#c45454"
            alerts.append({
                "type": "price",
                "severity": severity,
                "ticker": ticker,
                "title": f"{ticker} {'▲' if chg > 0 else '▼'} <span style='color:{chg_color}'>{chg:+.2f}%</span>",
                "detail": f"{name} — ${price:.2f}",
                "value": chg,
                "sort_key": abs(chg),
            })

    # Sort by change value: best (most positive) on top, worst (most negative) on bottom
    alerts.sort(key=lambda a: a["value"], reverse=True)
    return alerts


def _dividend_alerts(tickers, price_data, div_data):
    """
    Flag upcoming ex-dividend dates (within 14 days).
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


# ──────────────────────────────────────────────────────────────────────────
# EARNINGS CALENDAR — 30-day view, BMO/AMC flag, grouped by week
# ──────────────────────────────────────────────────────────────────────────

# Map of common Finviz earnings_date formats to a parsed (date, timing) tuple.
# Finviz returns strings like:
#   "May 12 BMO"   — Before Market Open
#   "May 15/AMC"   — After Market Close
#   "Apr 25"       — no timing flag
#   "May 12 BMO"   — sometimes with year if far out: "Dec 18 2026 BMO"
# This function is forgiving: it returns (None, None) on anything it can't parse.

def _parse_finviz_earnings_date(s):
    """Parse a Finviz earnings_date string. Returns (date, timing_flag).
    timing_flag is one of {'BMO', 'AMC', None}."""
    if not s:
        return None, None
    s = str(s).strip().replace("/", " ")

    # Pull off timing flag if present
    timing = None
    if " BMO" in s.upper():
        timing = "BMO"
        s = s.upper().replace(" BMO", "").strip()
    elif " AMC" in s.upper():
        timing = "AMC"
        s = s.upper().replace(" AMC", "").strip()

    # Try several date formats. Finviz dates have no year by default so
    # we assume the current year and roll forward if the parsed date is
    # in the past by more than 60 days (i.e. December → next January).
    today = datetime.now().date()
    parsed = None
    for fmt in ("%b %d %Y", "%b %d", "%B %d %Y", "%B %d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.title() if "-" not in s else s, fmt).date()
            if "%Y" not in fmt:
                # Year was missing — assume current year, roll forward if needed
                dt = dt.replace(year=today.year)
                if (dt - today).days < -60:
                    dt = dt.replace(year=today.year + 1)
            parsed = dt
            break
        except (ValueError, TypeError):
            continue
    return parsed, timing


def _build_earnings_calendar(tickers, price_data, finviz_data, days_ahead=30):
    """
    Build the earnings calendar from Finviz (primary) + yfinance (fallback).
    Returns list of dicts: {ticker, name, date, timing, days_until, week_key, week_label}.
    Sorted by date ascending.
    """
    today = datetime.now().date()
    horizon = today + timedelta(days=days_ahead)
    results = {}

    # 1) Finviz pass — primary source
    if finviz_data:
        for ticker in tickers:
            fv = finviz_data.get(ticker, {})
            ed_str = fv.get("earnings_date")
            if not ed_str:
                continue
            dt, timing = _parse_finviz_earnings_date(ed_str)
            if dt and today <= dt <= horizon:
                results[ticker] = (dt, timing)

    # 2) yfinance fallback — only for tickers Finviz didn't return
    missing = [t for t in tickers if t not in results]
    if missing:
        yf_dates = _fetch_earnings_dates(tuple(missing))
        for ticker, date_str in yf_dates.items():
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                if today <= dt <= horizon:
                    results[ticker] = (dt, None)  # yfinance doesn't expose BMO/AMC
            except (ValueError, TypeError):
                pass

    # 3) Build display rows with week grouping
    rows = []
    for ticker, (dt, timing) in results.items():
        mkt = price_data.get(ticker, {})
        name = mkt.get("name", ticker)
        days_until = (dt - today).days

        # Week key: Monday of that week. Label is e.g. "This week" / "Next week" / "May 26 – Jun 1"
        monday = dt - timedelta(days=dt.weekday())
        this_monday = today - timedelta(days=today.weekday())
        weeks_out = (monday - this_monday).days // 7
        if weeks_out == 0:
            week_label = "This week"
        elif weeks_out == 1:
            week_label = "Next week"
        else:
            sunday = monday + timedelta(days=6)
            week_label = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d')}"

        rows.append({
            "ticker": ticker,
            "name": name,
            "date": dt,
            "timing": timing,
            "days_until": days_until,
            "week_key": monday,
            "week_label": week_label,
        })

    rows.sort(key=lambda r: (r["date"], r["timing"] or "ZZZ", r["ticker"]))
    return rows


def _render_earnings_calendar(rows):
    """Render the earnings calendar as a compact grouped-by-week list."""
    st.markdown(
        '<div style="font-size:12px;font-weight:700;color:rgba(255,255,255,0.45);'
        'text-transform:uppercase;letter-spacing:0.08em;padding:0 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0">'
        'Earnings Calendar'
        f'<span style="font-size:11px;font-weight:400;color:rgba(255,255,255,0.2);'
        f'margin-left:8px;">{len(rows)}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        st.markdown(
            '<div style="padding:16px 0;font-size:13px;color:rgba(255,255,255,0.35);">'
            'No earnings in the next 30 days.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Group by week_key
    current_week = None
    html_parts = []
    for r in rows:
        if r["week_key"] != current_week:
            # Close previous table if any
            if current_week is not None:
                html_parts.append("</tbody></table>")
            # Open new week heading + table
            html_parts.append(
                f'<div style="font-size:10px;font-weight:600;color:rgba(255,255,255,0.4);'
                f'text-transform:uppercase;letter-spacing:0.06em;padding:14px 0 6px;">'
                f'{r["week_label"]}</div>'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<tbody>'
            )
            current_week = r["week_key"]

        # Timing badge
        if r["timing"] == "BMO":
            timing_html = (
                '<span style="font-size:9px;font-weight:600;color:rgba(201,168,76,0.85);'
                'background:rgba(201,168,76,0.10);padding:2px 6px;border-radius:3px;'
                'letter-spacing:0.04em;">BMO</span>'
            )
        elif r["timing"] == "AMC":
            timing_html = (
                '<span style="font-size:9px;font-weight:600;color:rgba(7,140,200,0.9);'
                'background:rgba(7,65,90,0.20);padding:2px 6px;border-radius:3px;'
                'letter-spacing:0.04em;">AMC</span>'
            )
        else:
            timing_html = (
                '<span style="font-size:9px;color:rgba(255,255,255,0.25);'
                'letter-spacing:0.04em;">—</span>'
            )

        # Date display: "Mon May 12"
        date_str = r["date"].strftime("%a %b %d")

        # Highlight TODAY in gold; "in 1d" / "in 2d" hint below name
        if r["days_until"] == 0:
            days_hint = '<span style="color:#C9A84C;font-weight:600;">TODAY</span>'
        elif r["days_until"] == 1:
            days_hint = '<span style="color:rgba(201,168,76,0.7);">in 1 day</span>'
        else:
            days_hint = f'<span style="color:rgba(255,255,255,0.3);">in {r["days_until"]} days</span>'

        html_parts.append(
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
            f'<td style="padding:8px 8px;font-size:12px;font-weight:600;color:#C9A84C;'
            f'white-space:nowrap;vertical-align:top;width:50px;">{r["ticker"]}</td>'
            f'<td style="padding:8px 6px;vertical-align:top;">'
            f'<div style="font-size:12px;color:rgba(255,255,255,0.8);line-height:1.3;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:0;width:100%;">'
            f'{r["name"]}</div>'
            f'<div style="font-size:10px;margin-top:2px;">{days_hint}</div>'
            f'</td>'
            f'<td style="padding:8px 6px;font-size:11px;color:rgba(255,255,255,0.55);'
            f'white-space:nowrap;vertical-align:top;text-align:right;">{date_str}</td>'
            f'<td style="padding:8px 6px;vertical-align:top;text-align:right;'
            f'width:48px;">{timing_html}</td>'
            f'</tr>'
        )

    # Close the final table
    html_parts.append("</tbody></table>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def _build_ticker_name_map(tickers, price_data):
    """Map each ticker to a set of strings (ticker + name tokens) used for
    relevance matching in holdings-news filtering."""
    out = {}
    for ticker in tickers:
        mkt = price_data.get(ticker, {})
        name = (mkt.get("name") or "").strip()
        tokens = {ticker.upper()}
        if name:
            # First word of the company name, stripped of common suffixes
            cleaned = name.replace(",", "").replace(".", "")
            for suffix in (" Inc", " Corp", " Corporation", " Company", " Co",
                           " Ltd", " LLC", " Holdings", " Group", " Plc",
                           " The", "The "):
                cleaned = cleaned.replace(suffix, "")
            first = cleaned.strip().split(" ")[0]
            if len(first) >= 3:
                tokens.add(first.lower())
        out[ticker] = tokens
    return out


# ══════════════════════════════════════════════════════════════════════════
# RENDERING
# ══════════════════════════════════════════════════════════════════════════

def _render_alert_row(alert):
    """Render a single alert as a clean table-style row."""
    # Ticker color: subtle gold for recognition, not severity-based
    ticker = alert.get("ticker", "")
    title = alert["title"]
    detail = alert["detail"]
    atype = alert.get("type", "")

    # Type label styling — all muted
    type_labels = {
        "price": "PRICE",
        "dividend": "DIVIDEND",
        "earnings": "EARNINGS",
    }
    type_str = type_labels.get(atype, atype.upper())

    return (
        f'<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
        f'<td style="padding:9px 10px;font-size:12px;font-weight:600;color:#C9A84C;'
        f'white-space:nowrap;vertical-align:top;width:60px;">{ticker}</td>'
        f'<td style="padding:9px 10px;vertical-align:top;">'
        f'<div style="font-size:13px;color:rgba(255,255,255,0.8);line-height:1.4;">{title}</div>'
        f'<div style="font-size:11px;color:rgba(255,255,255,0.35);margin-top:2px;">{detail}</div>'
        f'</td>'
        f'<td style="padding:9px 10px;font-size:10px;color:rgba(255,255,255,0.2);'
        f'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
        f'vertical-align:top;text-align:right;width:70px;">{type_str}</td>'
        f'</tr>'
    )


def _render_alert_section(title, alerts):
    """Render a section header + table of alerts."""
    if not alerts:
        return

    st.markdown(
        f'<div style="font-size:12px;font-weight:700;color:rgba(255,255,255,0.45);'
        f'text-transform:uppercase;letter-spacing:0.08em;padding:18px 0 8px;'
        f'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0">'
        f'{title}'
        f'<span style="font-size:11px;font-weight:400;color:rgba(255,255,255,0.2);'
        f'margin-left:8px;">{len(alerts)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Render as a clean table
    rows = "".join(_render_alert_row(a) for a in alerts)
    html = (
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<tbody>{rows}</tbody>'
        f'</table>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# NEWS HEADLINES (RSS + Holdings)
# ══════════════════════════════════════════════════════════════════════════

# RSS feed sources — markets-focused, free, no API keys
_NEWS_FEEDS = [
    {
        "name": "CNBC Markets",
        "url": "https://www.cnbc.com/id/15839069/device/rss/rss.html",
        "color": BLUE,
    },
    {
        "name": "MarketWatch Markets",
        "url": "https://feeds.marketwatch.com/marketwatch/marketpulse/",
        "color": GREEN,
    },
    {
        "name": "Reuters Business",
        "url": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
        "color": GOLD,
    },
    {
        "name": "WSJ Markets",
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "color": "#a06868",
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


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_holdings_news(tickers_tuple, ticker_tokens_tuple=(), max_total=15):
    """
    Fetch news for portfolio holdings via yfinance .news property.
    Filters applied in order:
      1. Title must mention the ticker symbol or company name token.
      2. Listicle/clickbait patterns are dropped.
      3. Junk publishers are dropped unless they are the only source for that ticker.

    Args:
        tickers_tuple: tuple of ticker symbols.
        ticker_tokens_tuple: tuple of (ticker, frozenset(tokens)) for relevance matching.
        max_total: max headlines to return.
    """
    import time as _time
    import re

    # Token map (ticker → set of strings the title must mention)
    token_map = {t: set(toks) for t, toks in ticker_tokens_tuple} if ticker_tokens_tuple else {}

    # Clickbait / listicle patterns — case-insensitive
    listicle_patterns = [
        r"\b\d+\s+(top|best|great|hot|cheap|safe|reliable|favorite|smart)\b",
        r"\btop\s+\d+\b",
        r"\bbest\s+(stocks?|dividend|growth|value|reits?)\b",
        r"\bstocks?\s+to\s+buy\b",
        r"\bstocks?\s+to\s+watch\b",
        r"\bstocks?\s+to\s+own\b",
        r"\bshould\s+you\s+buy\b",
        r"\bwhy\s+(i'?m|i\s+am)\s+buying\b",
        r"\bretirement\s+income\b",
        r"\bdividend\s+(stocks?|picks?|champions?|kings?|aristocrats?)\s+(to|for)\b",
        r"\bmaximize\s+(your\s+)?(retirement|income|wealth)\b",
        r"\bpassive\s+income\b",
        r"\b(buy|sell)\s+the\s+dip\b",
        r"\bmillionaire(s|aire)?\b",
        r"\b(could|will|can)\s+make\s+you\s+(rich|wealthy)\b",
        r"\bunder\s+\$?\d+\s+(to\s+buy|right\s+now)\b",
    ]
    listicle_re = re.compile("|".join(listicle_patterns), re.IGNORECASE)

    # Junk publishers — kept only if they're a holding's sole source
    junk_publishers = {
        "zacks", "zacks investment research", "marketbeat",
        "the motley fool", "motley fool", "fool.com",
        "investorplace", "benzinga", "gurufocus", "insider monkey",
        "simply wall st", "simply wall street", "247 wall st",
        "24/7 wall st", "smartasset", "investopedia",
        "valuewalk", "talkmarkets", "tipranks",
    }

    # Quality publishers — always preferred when available
    quality_publishers = {
        "reuters", "bloomberg", "wall street journal", "wsj",
        "financial times", "ft", "barron's", "barrons",
        "seeking alpha", "cnbc", "marketwatch", "the new york times",
        "new york times", "nyt", "associated press", "ap",
        "bbc", "axios", "fortune", "forbes",
    }

    headlines = []
    seen_titles = set()

    try:
        import yfinance as yf
    except ImportError:
        return []

    for ticker in tickers_tuple:
        tokens = token_map.get(ticker, {ticker.upper()})
        # Lowercase variants for matching
        tokens_lower = {t.lower() for t in tokens}

        # Per-ticker pool so we can apply quality filter at the end
        ticker_pool = []

        try:
            tk = yf.Ticker(ticker)
            news = tk.news
            if not news:
                continue
            for item in news[:5]:  # pull a few extra, we'll filter down
                content = item.get("content", {})
                title = content.get("title", "").strip()
                if not title or title in seen_titles:
                    continue

                # ── Filter 1: Title-relevance ──────────────────────────────
                title_lower = title.lower()
                if not any(tok in title_lower for tok in tokens_lower):
                    continue

                # ── Filter 2: Listicle / clickbait blocklist ───────────────
                if listicle_re.search(title):
                    continue

                # Parse publish time
                pub_str = ""
                pub_ts = content.get("pubDate")
                sort_ts = None
                if pub_ts:
                    try:
                        pub_dt = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
                        pub_dt_naive = pub_dt.replace(tzinfo=None)
                        delta = datetime.utcnow() - pub_dt_naive
                        if delta.total_seconds() < 3600:
                            pub_str = f"{max(1, int(delta.total_seconds() / 60))}m ago"
                        elif delta.total_seconds() < 86400:
                            pub_str = f"{int(delta.total_seconds() / 3600)}h ago"
                        else:
                            pub_str = pub_dt_naive.strftime("%b %d")
                        sort_ts = pub_dt_naive
                    except Exception:
                        pass

                provider = content.get("provider", {}).get("displayName", "")
                provider_lower = provider.lower().strip()
                link = content.get("canonicalUrl", {}).get("url", "")

                # Classify publisher
                is_quality = any(qp in provider_lower for qp in quality_publishers)
                is_junk = any(jp == provider_lower or jp in provider_lower for jp in junk_publishers)

                ticker_pool.append({
                    "title": title,
                    "link": link,
                    "source": provider or "yfinance",
                    "source_color": GOLD,
                    "published": pub_str,
                    "sort_ts": sort_ts,
                    "ticker": ticker,
                    "is_quality": is_quality,
                    "is_junk": is_junk,
                })

            # ── Filter 3: Prefer quality; only fall back to junk if it's all we have
            if ticker_pool:
                quality_items = [x for x in ticker_pool if x["is_quality"]]
                neutral_items = [x for x in ticker_pool if not x["is_quality"] and not x["is_junk"]]
                junk_items = [x for x in ticker_pool if x["is_junk"]]

                # Keep quality + neutral. Only use junk if there are no quality/neutral results.
                kept = quality_items + neutral_items
                if not kept and junk_items:
                    kept = junk_items[:1]  # one junk item max as fallback

                for item in kept:
                    if item["title"] not in seen_titles:
                        seen_titles.add(item["title"])
                        headlines.append(item)

            _time.sleep(0.1)
        except Exception:
            continue

        if len(headlines) >= max_total * 2:
            break

    # Sort newest first, cap total
    headlines.sort(key=lambda h: h.get("sort_ts") or datetime.min, reverse=True)
    return headlines[:max_total]


def _render_news_section(tickers=None, ticker_tokens_tuple=()):
    """Render the news headlines section: market news + holdings news."""
    headlines = _fetch_news_headlines()

    st.markdown(
        '<div style="font-size:12px;font-weight:700;color:rgba(255,255,255,0.45);'
        'text-transform:uppercase;letter-spacing:0.08em;padding:0 0 8px;'
        'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0">'
        'Market Headlines'
        '</div>',
        unsafe_allow_html=True,
    )

    if not headlines:
        st.markdown(
            '<div style="font-size:12px;color:rgba(255,255,255,0.3);padding:12px 0;">'
            'Unable to load news feeds. Ensure <code>feedparser</code> is in requirements.txt.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        # Render as a clean table — same structure as alerts
        rows = ""
        for h in headlines:
            rows += (
                f'<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
                f'<td style="padding:9px 10px;vertical-align:top;">'
                f'<a href="{h["link"]}" target="_blank" rel="noopener" style="'
                f'font-size:13px;color:rgba(255,255,255,0.8);text-decoration:none;'
                f'line-height:1.4;">{h["title"]}</a>'
                f'</td>'
                f'<td style="padding:9px 10px;text-align:right;vertical-align:top;'
                f'white-space:nowrap;width:110px;">'
                f'<div style="font-size:10px;color:rgba(255,255,255,0.25);'
                f'text-transform:uppercase;letter-spacing:0.04em;">{h["source"]}</div>'
                f'<div style="font-size:10px;color:rgba(255,255,255,0.15);margin-top:1px;">'
                f'{h["published"]}</div>'
                f'</td>'
                f'</tr>'
            )

        html = (
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<tbody>{rows}</tbody>'
            f'</table>'
        )
        st.markdown(html, unsafe_allow_html=True)

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # ── Holdings News ─────────────────────────────────────────────────────
    if tickers:
        with st.spinner("Fetching holdings news..."):
            holdings_news = _fetch_holdings_news(tuple(tickers), ticker_tokens_tuple)

        st.markdown(
            f'<div style="font-size:12px;font-weight:700;color:rgba(255,255,255,0.45);'
            f'text-transform:uppercase;letter-spacing:0.08em;padding:0 0 8px;'
            f'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0">'
            f'Holdings News'
            f'<span style="font-size:11px;font-weight:400;color:rgba(255,255,255,0.2);'
            f'margin-left:8px;">{len(holdings_news)} stories</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if holdings_news:
            rows = ""
            for h in holdings_news:
                ticker_badge = (
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;'
                    f'background:rgba(201,168,76,0.12);color:#C9A84C;font-size:10px;'
                    f'font-weight:600;letter-spacing:0.03em;margin-right:6px;">'
                    f'{h.get("ticker", "")}</span>'
                ) if h.get("ticker") else ""
                rows += (
                    f'<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
                    f'<td style="padding:9px 10px;vertical-align:top;">'
                    f'{ticker_badge}'
                    f'<a href="{h["link"]}" target="_blank" rel="noopener" style="'
                    f'font-size:13px;color:rgba(255,255,255,0.8);text-decoration:none;'
                    f'line-height:1.4;">{h["title"]}</a>'
                    f'</td>'
                    f'<td style="padding:9px 10px;text-align:right;vertical-align:top;'
                    f'white-space:nowrap;width:110px;">'
                    f'<div style="font-size:10px;color:rgba(255,255,255,0.25);'
                    f'text-transform:uppercase;letter-spacing:0.04em;">{h["source"]}</div>'
                    f'<div style="font-size:10px;color:rgba(255,255,255,0.15);margin-top:1px;">'
                    f'{h["published"]}</div>'
                    f'</td>'
                    f'</tr>'
                )
            html = (
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<tbody>{rows}</tbody>'
                f'</table>'
            )
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-size:12px;color:rgba(255,255,255,0.3);padding:12px 0;">'
                'No recent holdings news available.'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════════════════

def render_alerts_tab(tamarac_parsed, active_strategy):
    """
    Render the full News & Alerts tab.

    Args:
        tamarac_parsed: dict from parse_tamarac_excel()
        active_strategy: str, e.g. "QDVD"

    Sprint 25-6 layout:
      Row 1 (st.columns([1, 1])):
        Left  — Price Movers + Dividend Events stacked
        Right — Earnings Calendar (30 days, grouped by week)
      Row 2 (full width): Market Headlines + Holdings News

    On mobile, Streamlit auto-stacks columns vertically:
      Price Movers → Dividend Events → Earnings Calendar → News
    """

    tickers = sorted(get_all_unique_tickers(tamarac_parsed))

    # ── Fetch data ────────────────────────────────────────────────────────
    with st.spinner(f"Scanning {len(tickers)} holdings..."):
        price_data = fetch_batch_prices(tuple(tickers))

        div_data = {}
        if _DIV_AVAILABLE:
            div_data = get_batch_dividend_details(tuple(tickers))

        # Finviz batch — already cached 1hr by fetch_finviz_batch itself.
        # We use this for the earnings_date field; yfinance is the fallback
        # for any ticker Finviz didn't return.
        finviz_data = {}
        if _FINVIZ_AVAILABLE:
            try:
                finviz_data = fetch_finviz_batch(tuple(tickers))
            except Exception:
                finviz_data = {}

    # ── Generate alerts ───────────────────────────────────────────────────
    price_alerts = _price_mover_alerts(tickers, price_data)
    div_alerts = _dividend_alerts(tickers, price_data, div_data) if div_data else []
    earnings_rows = _build_earnings_calendar(tickers, price_data, finviz_data, days_ahead=30)

    # ── Row 1: Side-by-side alerts + earnings calendar ────────────────────
    col_alerts, col_earnings = st.columns([1, 1])

    with col_alerts:
        # If both alert lists are empty, show the empty-state header once
        if not price_alerts and not div_alerts:
            st.markdown(
                '<div style="font-size:12px;font-weight:700;color:rgba(255,255,255,0.45);'
                'text-transform:uppercase;letter-spacing:0.08em;padding:0 0 8px;'
                'border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0">'
                'Portfolio Alerts'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="padding:16px 0;font-size:13px;color:rgba(255,255,255,0.35);">'
                'No alerts — all holdings within normal ranges.'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            if price_alerts:
                _render_alert_section("Price Movers", price_alerts)
            if div_alerts:
                _render_alert_section("Dividend Events", div_alerts)

    with col_earnings:
        _render_earnings_calendar(earnings_rows)

    # Spacer between top row and news
    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)

    # ── Row 2: News (Market Headlines + Holdings News) full-width ─────────
    # Build the ticker→tokens map for relevance filtering, then pass as a
    # hashable tuple so @st.cache_data on _fetch_holdings_news still works.
    token_map = _build_ticker_name_map(tickers, price_data)
    ticker_tokens_tuple = tuple(
        (t, frozenset(toks)) for t, toks in sorted(token_map.items())
    )
    _render_news_section(tickers=tickers, ticker_tokens_tuple=ticker_tokens_tuple)

    # ── Footer ────────────────────────────────────────────────────────────
    st.caption(
        f"Alerts: Supabase + yfinance · Earnings: Finviz + yfinance · "
        f"News: RSS feeds (15-min cache) · "
        f"{datetime.now().strftime('%I:%M %p')}"
    )