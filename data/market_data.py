"""
Live market data: index quotes, ticker prices, basic fundamentals.
Sources: yfinance (free), with Finviz Elite as fallback/supplement.

Sprint 1: get_market_bar, get_ticker_data, get_price_history
Sprint 2: fetch_batch_prices (with SQLite cache), fetch_price_history,
          fetch_dividend_history, fetch_index_data
"""

import yfinance as yf
import pandas as pd
import sqlite3
import os
from datetime import datetime, date, timedelta
import streamlit as st


# ═══════════════════════════════════════════════════════════════════════════
# Sprint 1 — Market Bar & Ticker Data (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

MARKET_INDICES = [
    {"label": "S&P 500",      "ticker": "^GSPC"},
    {"label": "DJIA",         "ticker": "^DJI"},
    {"label": "Nasdaq",       "ticker": "^IXIC"},
    {"label": "10Y Treasury", "ticker": "^TNX"},
    {"label": "VIX",          "ticker": "^VIX"},
    {"label": "USD Index",    "ticker": "DX-Y.NYB"},
    {"label": "Crude Oil",    "ticker": "CL=F"},
    {"label": "Gold",         "ticker": "GC=F"},
]


@st.cache_data(ttl=300)  # 5-min cache for live data
def get_market_bar() -> list[dict]:
    """Return market bar data for display."""
    results = []
    tickers = [m["ticker"] for m in MARKET_INDICES]
    try:
        data = yf.download(tickers, period="2d", progress=False, auto_adjust=True)
        closes = data["Close"]

        for m in MARKET_INDICES:
            t = m["ticker"]
            if t not in closes.columns:
                continue
            series = closes[t].dropna()
            if len(series) < 2:
                continue
            today_val = series.iloc[-1]
            prev_val = series.iloc[-2]
            chg_pct = ((today_val - prev_val) / prev_val) * 100

            # Format display value
            if t == "^TNX":
                display = f"{today_val:.2f}%"
                chg_str = f"{chg_pct:+.1f}bp"
            elif t in ("^GSPC", "^DJI", "^IXIC"):
                display = f"{today_val:,.2f}"
                chg_str = f"{chg_pct:+.2f}%"
            elif t in ("CL=F", "GC=F"):
                display = f"${today_val:,.2f}"
                chg_str = f"{chg_pct:+.1f}%"
            else:
                display = f"{today_val:.2f}"
                chg_str = f"{chg_pct:+.2f}%"

            results.append({
                "name": m["label"],
                "value": display,
                "chg": chg_str,
                "up": chg_pct >= 0,
                "chg_pct": chg_pct,
            })
    except Exception as e:
        st.warning(f"Market data unavailable: {e}")

    return results


@st.cache_data(ttl=900)  # 15-min cache
def get_ticker_data(tickers: list[str]) -> pd.DataFrame:
    """Fetch price + basic fundamentals for a list of tickers."""
    rows = []
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            rows.append({
                "ticker": t,
                "name": info.get("longName", info.get("shortName", t)),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "chg1d": info.get("regularMarketChangePercent", 0),
                "ytd": _calc_ytd(t),
                "div_yield": (info.get("dividendYield") or 0) * 100,
                "div_amount": info.get("dividendRate") or 0,
                "payout_ratio": (info.get("payoutRatio") or 0) * 100,
                "sector": info.get("sector", ""),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "beta": info.get("beta"),
            })
        except Exception:
            rows.append({"ticker": t})
    return pd.DataFrame(rows)


def _calc_ytd(ticker: str) -> float:
    """Calculate YTD return for a ticker."""
    try:
        start = date(date.today().year, 1, 1)
        hist = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if len(hist) < 2:
            return 0.0
        first = hist["Close"].iloc[0]
        last = hist["Close"].iloc[-1]
        return round(((last - first) / first) * 100, 2)
    except Exception:
        return 0.0


@st.cache_data(ttl=3600)  # 1-hr cache for historical
def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Pull historical price data for charts."""
    try:
        hist = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        hist = hist[["Close", "Volume"]].copy()
        hist.index = pd.to_datetime(hist.index)
        return hist
    except Exception:
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# Sprint 2 — Batch Fetching with SQLite Cache
# ═══════════════════════════════════════════════════════════════════════════

CACHE_DB = "data/market_cache.db"
CACHE_TTL_MINUTES = 15


def _safe_dividend_yield(info, price=None):
    """
    Return dividend yield as a sensible percentage (e.g. 3.01 for 3.01%).
    yfinance is inconsistent — sometimes returns 0.0301, sometimes 3.01,
    sometimes garbage. We sanity-check and fall back to rate/price if needed.
    """
    raw = info.get("dividendYield")
    rate = info.get("dividendRate") or 0
    px = price or info.get("currentPrice") or info.get("regularMarketPrice") or 0

    # Try the reported yield first
    if raw is not None and raw > 0:
        # If it looks like a decimal (e.g. 0.0301), convert to percent
        if raw < 1:
            pct = round(raw * 100, 2)
        else:
            # Already a percentage (e.g. 3.01)
            pct = round(raw, 2)

        # Sanity check: no equity yields above 20% realistically
        if pct <= 20:
            return pct

    # Fallback: calculate from rate and price
    if rate > 0 and px > 0:
        return round((rate / px) * 100, 2)

    return 0.0


def _init_cache_db():
    """Initialize the market data cache database."""
    os.makedirs(os.path.dirname(CACHE_DB) if os.path.dirname(CACHE_DB) else ".", exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            symbol TEXT PRIMARY KEY,
            price REAL,
            prev_close REAL,
            change_1d REAL,
            change_1d_pct REAL,
            market_cap REAL,
            pe_ratio REAL,
            forward_pe REAL,
            sector TEXT,
            industry TEXT,
            dividend_yield REAL,
            dividend_rate REAL,
            payout_ratio REAL,
            beta REAL,
            fifty_two_week_high REAL,
            fifty_two_week_low REAL,
            avg_volume REAL,
            ex_dividend_date TEXT,
            last_updated TEXT
        )
    """)
    conn.commit()
    conn.close()


def _is_cache_fresh(symbol):
    """Check if cached data for a symbol is within TTL."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        row = conn.execute(
            "SELECT last_updated FROM price_cache WHERE symbol = ?", (symbol,)
        ).fetchone()
        conn.close()
        if row is None:
            return False
        last = datetime.fromisoformat(row[0])
        return (datetime.now() - last).total_seconds() < CACHE_TTL_MINUTES * 60
    except Exception:
        return False


def _save_to_cache(record):
    """Save a single record to the price cache."""
    try:
        conn = sqlite3.connect(CACHE_DB)
        conn.execute("""
            INSERT OR REPLACE INTO price_cache
            (symbol, price, prev_close, change_1d, change_1d_pct, market_cap,
             pe_ratio, forward_pe, sector, industry, dividend_yield, dividend_rate,
             payout_ratio, beta, fifty_two_week_high, fifty_two_week_low,
             avg_volume, ex_dividend_date, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            record["symbol"], record["price"], record["prev_close"],
            record["change_1d"], record["change_1d_pct"], record["market_cap"],
            record["pe_ratio"], record["forward_pe"], record["sector"],
            record["industry"], record["dividend_yield"], record["dividend_rate"],
            record["payout_ratio"], record["beta"], record["fifty_two_week_high"],
            record["fifty_two_week_low"], record["avg_volume"],
            record["ex_dividend_date"], record["last_updated"],
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass


@st.cache_data(ttl=900, show_spinner=False)
def fetch_batch_prices(tickers_tuple):
    """
    Fetch live price data for a batch of tickers (used by Holdings page).
    Accepts a tuple (for Streamlit cache hashability).
    Returns dict: {symbol: {price, prev_close, change_1d, change_1d_pct, sector, ...}}
    """
    tickers = list(tickers_tuple)
    _init_cache_db()

    # Check cache first
    results = {}
    to_fetch = []
    conn = sqlite3.connect(CACHE_DB)

    for t in tickers:
        if _is_cache_fresh(t):
            row = conn.execute(
                "SELECT * FROM price_cache WHERE symbol = ?", (t,)
            ).fetchone()
            if row:
                cols = [d[0] for d in conn.execute(
                    "SELECT * FROM price_cache LIMIT 0"
                ).description]
                results[t] = dict(zip(cols, row))
                continue
        to_fetch.append(t)

    conn.close()

    if to_fetch:
        try:
            batch_str = " ".join(to_fetch)
            data = yf.download(
                batch_str, period="5d", group_by="ticker",
                progress=False, threads=True
            )

            for t in to_fetch:
                try:
                    if len(to_fetch) == 1:
                        ticker_data = data
                    else:
                        ticker_data = (
                            data[t]
                            if t in data.columns.get_level_values(0)
                            else None
                        )

                    if ticker_data is None or ticker_data.empty:
                        continue

                    recent = ticker_data.dropna(subset=["Close"])
                    if len(recent) < 1:
                        continue

                    current_price = float(recent["Close"].iloc[-1])
                    prev_close = (
                        float(recent["Close"].iloc[-2])
                        if len(recent) >= 2
                        else current_price
                    )

                    chg = current_price - prev_close
                    chg_pct = (chg / prev_close * 100) if prev_close != 0 else 0

                    # Get additional info from yfinance Ticker object
                    info = {}
                    try:
                        tk = yf.Ticker(t)
                        info = tk.info or {}
                    except Exception:
                        pass

                    record = {
                        "symbol": t,
                        "price": round(current_price, 2),
                        "prev_close": round(prev_close, 2),
                        "change_1d": round(chg, 2),
                        "change_1d_pct": round(chg_pct, 2),
                        "market_cap": info.get("marketCap", 0),
                        "pe_ratio": info.get("trailingPE", 0),
                        "forward_pe": info.get("forwardPE", 0),
                        "sector": info.get("sector", ""),
                        "industry": info.get("industry", ""),
                        "dividend_yield": _safe_dividend_yield(info, current_price),
                        "dividend_rate": info.get("dividendRate", 0) or 0,
                        "payout_ratio": round(
                            (info.get("payoutRatio", 0) or 0) * 100, 1
                        ),
                        "beta": round(info.get("beta", 0) or 0, 2),
                        "fifty_two_week_high": (
                            info.get("fiftyTwoWeekHigh", 0) or 0
                        ),
                        "fifty_two_week_low": (
                            info.get("fiftyTwoWeekLow", 0) or 0
                        ),
                        "avg_volume": info.get("averageVolume", 0) or 0,
                        "ex_dividend_date": "",
                        "last_updated": datetime.now().isoformat(),
                    }

                    # Parse ex-dividend date
                    ex_div = info.get("exDividendDate")
                    if ex_div:
                        try:
                            if isinstance(ex_div, (int, float)):
                                record["ex_dividend_date"] = (
                                    datetime.fromtimestamp(ex_div).strftime("%Y-%m-%d")
                                )
                            else:
                                record["ex_dividend_date"] = str(ex_div)
                        except Exception:
                            pass

                    results[t] = record
                    _save_to_cache(record)

                except Exception:
                    pass  # silently skip failed tickers

        except Exception:
            pass  # return whatever we have from cache

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_price_history(ticker, period="1y"):
    """
    Fetch historical price data for performance charts.
    Returns DataFrame with Date and Close columns.
    (Complements get_price_history which returns Close+Volume with DatetimeIndex.)
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period)
        if hist.empty:
            return pd.DataFrame()
        return hist[["Close"]].reset_index()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_dividend_history(ticker):
    """Fetch dividend payment history for a ticker."""
    try:
        tk = yf.Ticker(ticker)
        divs = tk.dividends
        if divs.empty:
            return pd.DataFrame()
        df = divs.reset_index()
        df.columns = ["date", "amount"]
        return df
    except Exception:
        return pd.DataFrame()


def fetch_index_data():
    """
    Fetch major market indices (alternative to get_market_bar).
    Returns list of dicts — used by Performance page for quick benchmark reference.
    """
    indices = {
        "S&P 500": "^GSPC",
        "DJIA": "^DJI",
        "NASDAQ": "^IXIC",
        "10Y Treasury": "^TNX",
        "VIX": "^VIX",
        "Russell 2000": "^RUT",
    }
    results = []
    try:
        batch = " ".join(indices.values())
        data = yf.download(
            batch, period="2d", group_by="ticker",
            progress=False, threads=True
        )

        for name, ticker in indices.items():
            try:
                if len(indices) == 1:
                    td = data
                else:
                    td = data[ticker]
                recent = td.dropna(subset=["Close"])
                if len(recent) < 1:
                    continue
                current = float(recent["Close"].iloc[-1])
                prev = (
                    float(recent["Close"].iloc[-2])
                    if len(recent) >= 2
                    else current
                )
                chg_pct = (
                    ((current - prev) / prev * 100) if prev != 0 else 0
                )

                if name == "10Y Treasury":
                    display_val = f"{current:.2f}%"
                    chg_display = f"{chg_pct:+.0f}bp"
                elif name == "VIX":
                    display_val = f"{current:.2f}"
                    chg_display = f"{chg_pct:+.1f}%"
                else:
                    display_val = f"{current:,.2f}"
                    chg_display = f"{chg_pct:+.2f}%"

                results.append({
                    "name": name,
                    "value": display_val,
                    "change": chg_display,
                    "change_pct": chg_pct,
                    "up": chg_pct >= 0,
                })
            except Exception:
                pass
    except Exception:
        pass

    return results