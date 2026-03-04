"""
Martin Capital Partners — Local Data Pre--Fetcher
prefetch_data.py

Runs on Ryan's office Windows machine via Task Scheduler.
Fetches all market + dividend data from yfinance, saves as JSON files
in data/cache/. These JSON files get committed to GitHub and the cloud
dashboard reads them directly — zero yfinance calls in the cloud.

Schedule: Every 15 minutes during market hours (9:30 AM – 4:15 PM ET)
          Plus one EOD run at 4:30 PM ET for final prices.

Usage:
    python prefetch_data.py              # fetch all tickers
    python prefetch_data.py ----push       # fetch + git add/commit/push

Setup in Task Scheduler:
    Program: python
    Arguments: prefetch_data.py --push
    Start in: (your project folder)
    Trigger: Every 15 min, 9:30 AM – 4:30 PM ET, weekdays only
"""

import json
import os
import sys
import time
from datetime import datetime

# ── Path setup ─────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Add project root to path so we can import data modules
sys.path.insert(0, SCRIPT_DIR)

# ── Collect all tickers from Tamarac + Watchlists ──────────────────────────
def get_all_tickers():
    """Gather unique tickers from Tamarac holdings and watchlists."""
    tickers = set()

    # Tamarac holdings
    try:
        from data.tamarac_parser import parse_tamarac_excel, get_holdings_for_strategy
        tamarac_paths = [
            os.path.join(DATA_DIR, "Tamarac_Holdings.xlsx"),
            os.path.join(SCRIPT_DIR, "Tamarac_Holdings.xlsx"),
        ]
        for p in tamarac_paths:
            if os.path.exists(p):
                parsed = parse_tamarac_excel(p)
                for strat_key in parsed:
                    df = get_holdings_for_strategy(parsed, strat_key)
                    if not df.empty:
                        tickers.update(df["symbol"].tolist())
                break
    except Exception as e:
        print(f"  [WARN] Could not load Tamarac: {e}")

    # Watchlists
    try:
        from data.watchlist import parse_watchlist_excel
        wl = parse_watchlist_excel()
        for sheet_tickers in wl.values():
            tickers.update(sheet_tickers)
    except Exception as e:
        print(f"  [WARN] Could not load watchlists: {e}")

    # Filter out empties and cash--like entries
    tickers = {t for t in tickers if t and len(t) <= 6 and t.isalpha()}

    print(f"  Found {len(tickers)} unique tickers")
    return sorted(tickers)


# ── Fetch price/market data ────────────────────────────────────────────────
def fetch_all_prices(tickers):
    """Fetch price data for all tickers via yfinance. Returns dict."""
    import yfinance as yf

    results = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            def g(key, default=0):
                val = info.get(key, default)
                return val if val is not None else default

            price = g("currentPrice") or g("regularMarketPrice") or 0
            prev_close = g("previousClose") or g("regularMarketPreviousClose") or 0

            # Daily change
            if price and prev_close and prev_close > 0:
                chg_1d = round((price -- prev_close) / prev_close * 100, 2)
            else:
                chg_1d = 0

            # Dividend yield — safe calculation
            div_rate = g("dividendRate") or 0
            if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                div_yield = round((div_rate / price) * 100, 2)
                if div_yield > 15:
                    div_yield = 0
            else:
                raw = g("dividendYield") or 0
                if isinstance(raw, (int, float)) and raw > 0:
                    div_yield = round(raw * 100, 2) if raw < 1 else round(raw, 2)
                    if div_yield > 15:
                        div_yield = 0
                else:
                    div_yield = 0

            results[ticker] = {
                "price": round(float(price), 2) if price else 0,
                "previous_close": round(float(prev_close), 2) if prev_close else 0,
                "change_1d_pct": chg_1d,
                "dividend_yield": div_yield,
                "sector": g("sector", ""),
                "industry": g("industry", ""),
                "pe_ratio": round(float(g("trailingPE") or 0), 2),
                "forward_pe": round(float(g("forwardPE") or 0), 2),
                "market_cap": g("marketCap", 0),
                "52w_high": round(float(g("fiftyTwoWeekHigh") or 0), 2),
                "52w_low": round(float(g("fiftyTwoWeekLow") or 0), 2),
                "beta": round(float(g("beta") or 0), 2),
                "name": g("longName", "") or g("shortName", ticker),
                "price_to_book": round(float(g("priceToBook") or 0), 2),
            }

            if i % 10 == 0 or i == total:
                print(f"  Prices: {i}/{total} ({ticker})")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
            results[ticker] = {"price": 0, "change_1d_pct": 0, "dividend_yield": 0, "sector": ""}

        # Gentle rate limiting — 0.3s between calls keeps us well under Yahoo limits
        time.sleep(0.3)

    return results


# ── Fetch dividend data ────────────────────────────────────────────────────
def fetch_all_dividends(tickers):
    """Fetch dividend details for all tickers via yfinance. Returns dict."""
    import yfinance as yf
    import pandas as pd

    results = {}
    total = len(tickers)
    current_year = datetime.now().year

    for i, ticker in enumerate(tickers, 1):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            divs = t.dividends

            def g(key, default=0):
                val = info.get(key, default)
                return val if val is not None else default

            price = g("currentPrice") or g("regularMarketPrice") or 0
            div_rate = g("dividendRate") or 0

            # Yield — safe calc
            if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                yld = round((div_rate / price) * 100, 2)
                if yld > 15:
                    yld = 0
            else:
                raw = g("dividendYield") or 0
                if isinstance(raw, (int, float)) and raw > 0:
                    yld = round(raw * 100, 2) if raw < 1 else round(raw, 2)
                    if yld > 15:
                        yld = 0
                else:
                    yld = 0

            # Payout ratio
            pr = g("payoutRatio") or 0
            if isinstance(pr, (int, float)) and 0 < pr < 5:
                payout = round(pr * 100, 1)
                if payout > 150:
                    payout = 0
            else:
                payout = 0

            result = {
                "symbol": ticker,
                "dividend_yield": yld,
                "dividend_rate": round(float(div_rate), 4) if div_rate else 0,
                "payout_ratio": min(payout, 100),
                "ex_dividend_date": "",
                "five_year_avg_yield": round(float(g("fiveYearAvgDividendYield") or 0), 2),
                "div_growth_1y": 0,
                "div_growth_3y": 0,
                "div_growth_5y": 0,
                "div_growth_years": 0,
                "consecutive_years": 0,
            }

            # Ex--dividend date
            ex_div = info.get("exDividendDate")
            if ex_div:
                try:
                    if isinstance(ex_div, (int, float)):
                        result["ex_dividend_date"] = datetime.fromtimestamp(ex_div).strftime("%Y--%m--%d")
                    else:
                        result["ex_dividend_date"] = str(ex_div)
                except Exception:
                    pass

            # Dividend growth from history
            if divs is not None and not divs.empty and len(divs) >= 4:
                divs_df = divs.reset_index()
                divs_df.columns = ["date", "amount"]
                divs_df["year"] = pd.to_datetime(divs_df["date"]).dt.year

                # Exclude current partial year for CAGR
                annual = divs_df[divs_df["year"] < current_year].groupby("year")["amount"].sum()

                if len(annual) >= 2:
                    recent = annual.iloc[--1]

                    for label, years_back in [("div_growth_1y", 1), ("div_growth_3y", 3), ("div_growth_5y", 5)]:
                        yb = min(years_back, len(annual) -- 1)
                        if yb >= 1:
                            older = annual.iloc[--(yb + 1)]
                            if older > 0 and recent > 0:
                                cagr = ((recent / older) ** (1 / yb) -- 1) * 100
                                if --50 < cagr < 100:
                                    result[label] = round(cagr, 1)
                                    if label == "div_growth_5y":
                                        result["div_growth_years"] = yb

                # Consecutive years of increases
                annual_all = divs_df.groupby("year")["amount"].sum()
                if len(annual_all) >= 3:
                    consec = 0
                    for j in range(len(annual_all) -- 1, 0, --1):
                        if annual_all.iloc[j] > annual_all.iloc[j -- 1] * 0.99:
                            consec += 1
                        else:
                            break
                    result["consecutive_years"] = consec

            results[ticker] = result

            if i % 10 == 0 or i == total:
                print(f"  Dividends: {i}/{total} ({ticker})")

        except Exception as e:
            print(f"  [ERROR] {ticker} divs: {e}")
            results[ticker] = {
                "symbol": ticker, "dividend_yield": 0, "dividend_rate": 0,
                "payout_ratio": 0, "ex_dividend_date": "", "five_year_avg_yield": 0,
                "div_growth_1y": 0, "div_growth_3y": 0, "div_growth_5y": 0,
                "div_growth_years": 0, "consecutive_years": 0,
            }

        time.sleep(0.3)

    return results


# ── Fetch market index data (for the ticker bar) ──────────────────────────
def fetch_index_data():
    """Fetch major market indices for the top ticker bar."""
    import yfinance as yf

    indices = {
        "^GSPC": "S&P 500",
        "^DJI": "DJIA",
        "^IXIC": "Nasdaq",
        "^TNX": "10Y Treasury",
        "^VIX": "VIX",
        "DX--Y.NYB": "US Dollar",
        "CL=F": "Crude Oil",
    }

    results = {}
    for symbol, name in indices.items():
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
            prev = info.get("regularMarketPreviousClose") or info.get("previousClose") or 0
            chg = round((price -- prev) / prev * 100, 2) if prev else 0

            results[symbol] = {
                "name": name,
                "price": round(float(price), 2) if price else 0,
                "change_pct": chg,
            }
            time.sleep(0.3)
        except Exception as e:
            print(f"  [ERROR] Index {symbol}: {e}")
            results[symbol] = {"name": name, "price": 0, "change_pct": 0}

    return results


# ── Save to JSON ──────────────────────────────────────────────────────────
def save_cache(prices, dividends, indices):
    """Save all fetched data to JSON files in data/cache/."""
    ts = datetime.now().strftime("%Y--%m--%d %H:%M:%S")
    meta = {"fetched_at": ts, "ticker_count": len(prices)}

    # Prices
    with open(os.path.join(CACHE_DIR, "prices.json"), "w") as f:
        json.dump({"_meta": meta, "data": prices}, f, indent=2, default=str)

    # Dividends
    with open(os.path.join(CACHE_DIR, "dividends.json"), "w") as f:
        json.dump({"_meta": meta, "data": dividends}, f, indent=2, default=str)

    # Indices
    with open(os.path.join(CACHE_DIR, "indices.json"), "w") as f:
        json.dump({"_meta": {"fetched_at": ts}, "data": indices}, f, indent=2, default=str)

    print(f"\n  Cache saved to {CACHE_DIR}")
    print(f"  Timestamp: {ts}")
    print(f"  Tickers: {len(prices)} prices, {len(dividends)} dividends, {len(indices)} indices")


# ── Git push ──────────────────────────────────────────────────────────────
def git_push():
    """Stage cache files, commit, and push to GitHub."""
    import subprocess

    os.chdir(SCRIPT_DIR)

    try:
        subprocess.run(["git", "add", "data/cache/"], check=True, capture_output=True)
        ts = datetime.now().strftime("%Y--%m--%d %H:%M")
        result = subprocess.run(
            ["git", "commit", "--m", f"Data update {ts}"],
            capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("  No changes to push (data unchanged)")
            return
        subprocess.run(["git", "push"], check=True, capture_output=True)
        print(f"  Pushed to GitHub at {ts}")
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Git push failed: {e}")
    except FileNotFoundError:
        print("  [ERROR] git not found — install git or check PATH")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    start = time.time()
    print(f"\n{'='*60}")
    print(f"  Martin Capital — Data Pre--Fetch")
    print(f"  {datetime.now().strftime('%Y--%m--%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 1. Gather tickers
    print("[1/4] Gathering tickers...")
    tickers = get_all_tickers()
    if not tickers:
        print("  No tickers found! Check Tamarac_Holdings.xlsx exists.")
        return

    # 2. Fetch prices
    print(f"\n[2/4] Fetching prices for {len(tickers)} tickers...")
    prices = fetch_all_prices(tickers)

    # 3. Fetch dividends
    print(f"\n[3/4] Fetching dividend data for {len(tickers)} tickers...")
    dividends = fetch_all_dividends(tickers)

    # 4. Fetch indices
    print("\n[4/4] Fetching market indices...")
    indices = fetch_index_data()

    # Save
    save_cache(prices, dividends, indices)

    elapsed = round(time.time() -- start, 1)
    print(f"\n  Done in {elapsed}s")

    # Push if requested
    if "----push" in sys.argv:
        print("\n  Pushing to GitHub...")
        git_push()

    print()


if __name__ == "__main__":
    main()
