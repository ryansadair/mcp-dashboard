"""
Martin Capital Partners — Watchlist Module
data/watchlist.py

Reads watchlist tickers from a single Excel file with 5 sheets:
  - QDVD Watchlist A
  - QDVD Watchlist B
  - SMID Watchlist A
  - SMID Watchlist B
  - C Watch

Each sheet has one column: "Ticker" (column A).
yfinance enriches with price, valuation, and dividend data.

Place the file at: data/Watchlists.xlsx
"""

import os
import pandas as pd

# ── File location ───────────────────────────────────────────────────────────
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

WATCHLIST_PATHS = [
    os.path.join(DATA_DIR, "Watchlists.xlsx"),
    "data/Watchlists.xlsx",
    "Watchlists.xlsx",
]

# The 5 expected sheet names (used for validation / display order)
WATCHLIST_NAMES = [
    "QDVD Watchlist A",
    "QDVD Watchlist B",
    "SMID Watchlist A",
    "SMID Watchlist B",
    "C Watch",
]


def _find_watchlist_file():
    """Locate the Watchlists.xlsx file."""
    for p in WATCHLIST_PATHS:
        if os.path.exists(p):
            return p
    return None


def parse_watchlist_excel(path=None):
    """
    Parse the watchlist Excel file.
    Returns dict: { "Sheet Name": ["TICK1", "TICK2", ...], ... }
    Only returns sheets that exist in the file.
    """
    if path is None:
        path = _find_watchlist_file()
    if path is None:
        return {}

    try:
        xls = pd.ExcelFile(path)
    except Exception as e:
        print(f"[watchlist] Failed to open {path}: {e}")
        return {}

    result = {}
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet)

            # Find the ticker column — look for "Ticker", "Symbol", or just use first column
            ticker_col = None
            for col in df.columns:
                if str(col).strip().lower() in ("ticker", "symbol", "tickers", "symbols"):
                    ticker_col = col
                    break
            if ticker_col is None:
                # Fall back to first column
                ticker_col = df.columns[0]

            # Extract tickers, clean up
            tickers = (
                df[ticker_col]
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
                .tolist()
            )

            # Filter out header-like values and empties
            tickers = [t for t in tickers if t and t not in ("TICKER", "SYMBOL", "TICKERS", "")]

            if tickers:
                result[sheet] = tickers

        except Exception as e:
            print(f"[watchlist] Error reading sheet '{sheet}': {e}")
            continue

    return result


def get_watchlist_names(parsed):
    """Return list of available watchlist names in display order."""
    if not parsed:
        return []
    # Return in our preferred order, then any extras
    ordered = [n for n in WATCHLIST_NAMES if n in parsed]
    extras = [n for n in parsed if n not in WATCHLIST_NAMES]
    return ordered + extras


def enrich_from_yfinance(ticker):
    """
    Fetch company name, sector, market cap, valuation from yfinance.
    Returns dict on success, empty dict on failure.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}

        def g(key, default=""):
            val = info.get(key, default)
            return val if val is not None else default

        # Market cap formatting
        mc_raw = g("marketCap", 0)
        if mc_raw >= 1e12:
            mc_str = f"${mc_raw/1e12:.1f}T"
        elif mc_raw >= 1e9:
            mc_str = f"${mc_raw/1e9:.1f}B"
        elif mc_raw >= 1e6:
            mc_str = f"${mc_raw/1e6:.0f}M"
        else:
            mc_str = ""

        # Dividend yield — prefer dividendRate / price (most reliable)
        # yfinance's dividendYield field is inconsistent: sometimes decimal,
        # sometimes percentage, sometimes garbage. Calculate it ourselves.
        div_rate = g("dividendRate", 0) or 0
        price_val = g("currentPrice", 0) or g("regularMarketPrice", 0) or 0
        if isinstance(div_rate, (int, float)) and div_rate > 0 and price_val > 0:
            div_yield = round((div_rate / price_val) * 100, 2)
        else:
            # Fallback to dividendYield field
            raw_yield = g("dividendYield", 0)
            if isinstance(raw_yield, (int, float)) and raw_yield > 0:
                if raw_yield < 1:
                    div_yield = round(raw_yield * 100, 2)
                else:
                    div_yield = round(raw_yield, 2)
            else:
                div_yield = 0.0
        # Sanity cap — no legitimate equity yields above 15%
        if div_yield > 15:
            div_yield = 0.0

        return {
            "company_name": g("longName") or g("shortName", ticker),
            "sector": g("sector"),
            "market_cap": mc_str,
            "current_price": g("currentPrice", 0) or g("regularMarketPrice", 0),
            "dividend_yield": div_yield,
            "pe_ratio": round(g("trailingPE", 0) or 0, 1),
            "forward_pe": round(g("forwardPE", 0) or 0, 1),
            "price_to_book": round(g("priceToBook", 0) or 0, 2),
            "52w_high": round(g("fiftyTwoWeekHigh", 0) or 0, 2),
            "52w_low": round(g("fiftyTwoWeekLow", 0) or 0, 2),
            "beta": round(g("beta", 0) or 0, 2),
            "payout_ratio": round((g("payoutRatio", 0) or 0) * 100, 1)
                if isinstance(g("payoutRatio", 0), (int, float)) and g("payoutRatio", 0) < 5
                else 0.0,
        }
    except Exception as e:
        print(f"[watchlist] yfinance enrich failed for {ticker}: {e}")
        return {}


def enrich_batch(tickers):
    """Enrich a list of tickers. Returns dict: { "TICK": {info}, ... }"""
    results = {}
    for t in tickers:
        info = enrich_from_yfinance(t)
        if info:
            results[t] = info
    return results