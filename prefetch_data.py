"""
Martin Capital Partners — Local Data Pre-Fetcher
prefetch_data.py

Runs on Ryan's office Windows machine via Task Scheduler.
Fetches all market + dividend data from yfinance locally (no IP blocking),
then upserts results to Supabase (cloud PostgreSQL) so Streamlit Cloud
can read fresh data without ever calling yfinance directly.

Schedule: Every 15 minutes during market hours (9:30 AM – 4:15 PM ET)
          Plus one EOD run at 4:30 PM ET for final prices.

Usage:
    python prefetch_data.py          # fetch all data + push to Supabase
    python prefetch_data.py --dry    # fetch only, skip Supabase push (testing)

Setup in Task Scheduler:
    Program:   C:\\path\\to\\venv\\Scripts\\python.exe
    Arguments: prefetch_data.py
    Start in:  C:\\Users\\RyanAdair\\Martin Capital Partners LLC\\Eugene - Documents\\Operations\\Scripts\\Portfolio Dashboard
    Trigger:   Every 15 min, 9:30 AM – 4:30 PM ET, weekdays only
"""

import os
import sys
import time
from datetime import datetime

# ── Path setup ─────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(SCRIPT_DIR, "data")
sys.path.insert(0, SCRIPT_DIR)

# ── Supabase config ────────────────────────────────────────────────────────
# Paste your Supabase project URL and service role key here after setup.
# Get these from: supabase.com → your project → Settings → API
SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
SUPABASE_KEY = "sb_secret_P1XNpklX_g_gcMamZb0qqw_udXSu8T7"   # use service role key, not anon key

# ══════════════════════════════════════════════════════════════════════════
# TICKER COLLECTION
# ══════════════════════════════════════════════════════════════════════════

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

    # Filter out empties and cash-like entries
    tickers = {t for t in tickers if t and len(t) <= 6 and t.isalpha()}
    print(f"  Found {len(tickers)} unique tickers")
    return sorted(tickers)


# ══════════════════════════════════════════════════════════════════════════
# PRICE FETCHING  (5-day history for accurate daily change)
# ══════════════════════════════════════════════════════════════════════════

def fetch_all_prices(tickers):
    """Fetch price + fundamentals for all tickers. Returns dict."""
    import yfinance as yf

    results = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        try:
            tk = yf.Ticker(ticker)

            # ── Daily price & change via 5-day history ─────────────────────
            # tk.info["previousClose"] is unreliable — often returns stale
            # values causing 200%+ daily change readings. History is accurate.
            hist5 = tk.history(period="5d", auto_adjust=True)
            price, prev_close, chg_1d = 0.0, 0.0, 0.0
            if hist5 is not None and len(hist5) >= 2:
                price      = round(float(hist5["Close"].iloc[-1]), 2)
                prev_close = round(float(hist5["Close"].iloc[-2]), 2)
                if prev_close > 0:
                    chg_1d = round((price - prev_close) / prev_close * 100, 2)
                    if abs(chg_1d) > 25:   # sanity cap
                        chg_1d = 0.0
            elif hist5 is not None and len(hist5) == 1:
                price = round(float(hist5["Close"].iloc[-1]), 2)

            # ── Lightweight fundamentals via fast_info ─────────────────────
            fi          = tk.fast_info
            market_cap  = getattr(fi, "market_cap", 0) or 0
            week52_high = round(float(getattr(fi, "year_high", 0) or 0), 2)
            week52_low  = round(float(getattr(fi, "year_low",  0) or 0), 2)

            # ── Deeper fundamentals via info (sector, PE, div) ────────────
            info = {}
            try:
                info = tk.info or {}
            except Exception:
                pass

            def g(key, default=0):
                val = info.get(key, default)
                return val if val is not None else default

            # Dividend yield — safe calculation
            div_yield = 0.0
            div_rate  = g("dividendRate") or 0
            if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                div_yield = round((div_rate / price) * 100, 2)
            else:
                raw = g("dividendYield") or 0
                if isinstance(raw, (int, float)) and raw > 0:
                    div_yield = round(raw * 100, 2) if raw < 1 else round(raw, 2)
            if div_yield > 15:
                div_yield = 0.0

            results[ticker] = {
                "ticker":         ticker,
                "price":          price,
                "previous_close": prev_close,
                "change_1d_pct":  chg_1d,
                "dividend_yield": div_yield,
                "sector":         g("sector", ""),
                "industry":       g("industry", ""),
                "pe_ratio":       round(float(g("trailingPE")   or 0), 2),
                "forward_pe":     round(float(g("forwardPE")    or 0), 2),
                "market_cap":     market_cap,
                "week52_high":    week52_high,
                "week52_low":     week52_low,
                "beta":           round(float(g("beta")         or 0), 2),
                "name":           g("longName", "") or g("shortName", ticker),
                "price_to_book":  round(float(g("priceToBook")  or 0), 2),
                "fetched_at":     datetime.now().isoformat(),
            }

            if i % 10 == 0 or i == total:
                print(f"  Prices: {i}/{total} ({ticker})")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
            results[ticker] = {
                "ticker": ticker, "price": 0, "change_1d_pct": 0,
                "dividend_yield": 0, "sector": "", "fetched_at": datetime.now().isoformat(),
            }

        time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════════════════
# DIVIDEND FETCHING
# ══════════════════════════════════════════════════════════════════════════

def fetch_all_dividends(tickers):
    """Fetch dividend details for all tickers. Returns dict."""
    import yfinance as yf
    import pandas as pd

    results = {}
    total        = len(tickers)
    current_year = datetime.now().year

    for i, ticker in enumerate(tickers, 1):
        try:
            tk   = yf.Ticker(ticker)
            info = {}
            try:
                info = tk.info or {}
            except Exception:
                pass
            divs = tk.dividends

            def g(key, default=0):
                val = info.get(key, default)
                return val if val is not None else default

            price    = g("currentPrice") or g("regularMarketPrice") or 0
            div_rate = g("dividendRate") or 0

            # Yield
            yld = 0.0
            if isinstance(div_rate, (int, float)) and div_rate > 0 and price > 0:
                yld = round((div_rate / price) * 100, 2)
                if yld > 15:
                    yld = 0.0
            else:
                raw = g("dividendYield") or 0
                if isinstance(raw, (int, float)) and raw > 0:
                    yld = round(raw * 100, 2) if raw < 1 else round(raw, 2)
                    if yld > 15:
                        yld = 0.0

            # Payout ratio
            pr = g("payoutRatio") or 0
            payout = 0.0
            if isinstance(pr, (int, float)) and 0 < pr < 5:
                payout = round(pr * 100, 1)
                if payout > 150:
                    payout = 0.0

            result = {
                "ticker":              ticker,
                "dividend_yield":      yld,
                "dividend_rate":       round(float(div_rate), 4) if div_rate else 0,
                "payout_ratio":        min(payout, 100),
                "ex_dividend_date":    "",
                "five_year_avg_yield": round(float(g("fiveYearAvgDividendYield") or 0), 2),
                "div_growth_1y":       0,
                "div_growth_3y":       0,
                "div_growth_5y":       0,
                "div_growth_years":    0,
                "consecutive_years":   0,
                "fetched_at":          datetime.now().isoformat(),
            }

            # Ex-dividend date
            ex_div = info.get("exDividendDate")
            if ex_div:
                try:
                    if isinstance(ex_div, (int, float)):
                        result["ex_dividend_date"] = datetime.fromtimestamp(ex_div).strftime("%Y-%m-%d")
                    else:
                        result["ex_dividend_date"] = str(ex_div)
                except Exception:
                    pass

            # Dividend growth from history
            if divs is not None and not divs.empty and len(divs) >= 4:
                divs_df = divs.reset_index()
                divs_df.columns = ["date", "amount"]
                divs_df["year"] = pd.to_datetime(divs_df["date"]).dt.year
                annual = divs_df[divs_df["year"] < current_year].groupby("year")["amount"].sum()

                if len(annual) >= 2:
                    recent = annual.iloc[-1]
                    for label, years_back in [("div_growth_1y", 1), ("div_growth_3y", 3), ("div_growth_5y", 5)]:
                        yb = min(years_back, len(annual) - 1)
                        if yb >= 1:
                            older = annual.iloc[-(yb + 1)]
                            if older > 0 and recent > 0:
                                cagr = ((recent / older) ** (1 / yb) - 1) * 100
                                if -50 < cagr < 100:
                                    result[label] = round(cagr, 1)
                                    if label == "div_growth_5y":
                                        result["div_growth_years"] = yb

                # Exclude current partial year so incomplete data doesn't break streak
                annual_all = divs_df[divs_df["year"] < current_year].groupby("year")["amount"].sum()
                if len(annual_all) >= 3:
                    consec = 0
                    for j in range(len(annual_all) - 1, 0, -1):
                        if annual_all.iloc[j] > annual_all.iloc[j - 1] * 0.99:
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
                "ticker": ticker, "dividend_yield": 0, "dividend_rate": 0,
                "payout_ratio": 0, "ex_dividend_date": "", "five_year_avg_yield": 0,
                "div_growth_1y": 0, "div_growth_3y": 0, "div_growth_5y": 0,
                "div_growth_years": 0, "consecutive_years": 0,
                "fetched_at": datetime.now().isoformat(),
            }

        time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════════════════
# INDEX FETCHING
# ══════════════════════════════════════════════════════════════════════════

def fetch_index_data():
    """Fetch major market indices for the top ticker bar."""
    import yfinance as yf

    indices = {
        "^GSPC":    "S&P 500",
        "^DJI":     "DJIA",
        "^IXIC":    "Nasdaq",
        "^TNX":     "10Y Treasury",
        "^VIX":     "VIX",
        "DX-Y.NYB": "US Dollar",
        "CL=F":     "Crude Oil",
    }

    results = {}
    for symbol, name in indices.items():
        try:
            tk   = yf.Ticker(symbol)
            # Use fast_info for indices — more reliable than .info
            fi    = tk.fast_info
            price = round(float(getattr(fi, "last_price",      0) or 0), 2)
            prev  = round(float(getattr(fi, "previous_close",  0) or 0), 2)
            chg   = round((price - prev) / prev * 100, 2) if prev else 0

            results[symbol] = {
                "symbol":     symbol,
                "name":       name,
                "price":      price,
                "change_pct": chg,
                "fetched_at": datetime.now().isoformat(),
            }
            time.sleep(0.2)
        except Exception as e:
            print(f"  [ERROR] Index {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "name": name, "price": 0,
                "change_pct": 0, "fetched_at": datetime.now().isoformat(),
            }

    return results


# ── Benchmark tickers to track ─────────────────────────────────────────────
BENCHMARK_TICKERS = {
    "^GSPC":  "S&P 500",
    "^DJI":   "DJIA",
    "^RUT":   "Russell 2000",
    "NOBL":   "S&P Dividend Aristocrats",
    "IVW":    "S&P 500 Growth",
}


def fetch_benchmark_data():
    """
    Fetch YTD price history for all benchmark tickers.
    Returns dict: { "^GSPC": { "ytd_return": 7.15, "history": [...] }, ... }
    """
    import yfinance as yf
    import pandas as pd
    from datetime import date

    results = {}
    start = date(date.today().year, 1, 1).strftime("%Y-%m-%d")

    for symbol, name in BENCHMARK_TICKERS.items():
        try:
            hist = yf.download(symbol, start=start, progress=False, auto_adjust=True)
            if hist is None or len(hist) < 2:
                raise ValueError("Not enough data")

            # Handle multi-level columns from yf.download
            if isinstance(hist.columns, pd.MultiIndex):
                closes = hist["Close"][symbol]
            else:
                closes = hist["Close"]

            # Convert to simple float series
            closes = closes.dropna()
            if len(closes) < 2:
                raise ValueError("Not enough data after dropna")

            first = float(closes.iloc[0])
            last  = float(closes.iloc[-1])
            ytd   = round(((last - first) / first) * 100, 2)

            # Build history rows for Supabase
            history_rows = []
            for dt, close in closes.items():
                date_str = str(dt)[:10]
                history_rows.append({
                    "id":         f"{symbol}_{date_str}",
                    "symbol":     symbol,
                    "date":       date_str,
                    "close":      round(float(close), 4),
                    "fetched_at": datetime.now().isoformat(),
                })

            results[symbol] = {
                "symbol":     symbol,
                "ytd_return": ytd,
                "history":    history_rows,
                "fetched_at": datetime.now().isoformat(),
            }
            print(f"  Benchmark {symbol}: YTD {ytd:+.2f}%")
            time.sleep(0.3)

        except Exception as e:
            print(f"  [ERROR] Benchmark {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "ytd_return": 0, "history": [], "fetched_at": datetime.now().isoformat()
            }

    return results




def push_to_supabase(prices, dividends, indices, benchmarks=None):
    """
    Upsert all fetched data to Supabase via direct REST API calls.
    Uses only the `requests` library — no supabase-py needed.
    """
    import requests

    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates",
    }

    def upsert(table, rows):
        if not rows:
            return True
        chunk_size = 200
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            url  = f"{SUPABASE_URL}/rest/v1/{table}"
            resp = requests.post(url, headers=headers, json=chunk, timeout=30)
            if resp.status_code not in (200, 201):
                print(f"  [ERROR] {table} upsert failed ({resp.status_code}): {resp.text[:200]}")
                return False
        return True

    try:
        # ── Prices ────────────────────────────────────────────────────────
        price_rows = list(prices.values())
        if upsert("prices", price_rows):
            print(f"  Supabase: upserted {len(price_rows)} price rows")

        # ── Dividends ─────────────────────────────────────────────────────
        div_rows = list(dividends.values())
        if upsert("dividends", div_rows):
            print(f"  Supabase: upserted {len(div_rows)} dividend rows")

        # ── Indices ───────────────────────────────────────────────────────
        index_rows = list(indices.values())
        if upsert("indices", index_rows):
            print(f"  Supabase: upserted {len(index_rows)} index rows")

        # ── Benchmarks ────────────────────────────────────────────────────
        if benchmarks:
            # YTD summary
            ytd_rows = [{"symbol": s, "ytd_return": d["ytd_return"], "fetched_at": d["fetched_at"]}
                        for s, d in benchmarks.items()]
            if upsert("benchmark_ytd", ytd_rows):
                print(f"  Supabase: upserted {len(ytd_rows)} benchmark YTD rows")

            # Full history (only push once per day — expensive otherwise)
            all_history = []
            for d in benchmarks.values():
                all_history.extend(d.get("history", []))
            if all_history and upsert("benchmark_history", all_history):
                print(f"  Supabase: upserted {len(all_history)} benchmark history rows")

        return True

    except Exception as e:
        print(f"  [ERROR] Supabase push failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    dry_run = "--dry" in sys.argv
    start   = time.time()

    print(f"\n{'='*60}")
    print(f"  Martin Capital — Data Pre-Fetch {'(DRY RUN)' if dry_run else ''}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 1. Gather tickers
    print("[1/5] Gathering tickers...")
    tickers = get_all_tickers()
    if not tickers:
        print("  No tickers found! Check Tamarac_Holdings.xlsx exists.")
        return

    # 2. Fetch prices
    print(f"\n[2/5] Fetching prices for {len(tickers)} tickers...")
    prices = fetch_all_prices(tickers)

    # 3. Fetch dividends
    print(f"\n[3/5] Fetching dividend data for {len(tickers)} tickers...")
    dividends = fetch_all_dividends(tickers)

    # 4. Fetch indices
    print("\n[4/5] Fetching market indices...")
    indices = fetch_index_data()

    # 5. Fetch benchmark history
    print("\n[5/5] Fetching benchmark history...")
    benchmarks = fetch_benchmark_data()

    elapsed = round(time.time() - start, 1)
    print(f"\n  Fetch complete in {elapsed}s")

    # 6. Push to Supabase
    success = False
    if not dry_run:
        print("\n[6/6] Pushing to Supabase...")
        success = push_to_supabase(prices, dividends, indices, benchmarks)
        if success:
            print(f"  Done at {datetime.now().strftime('%H:%M:%S')}")
    else:
        print("\n  DRY RUN — skipping Supabase push")
        print(f"  Sample price: {list(prices.items())[0]}")

    # 6. Write to log file
    log_path = os.path.join(SCRIPT_DIR, "prefetch_log.txt")
    try:
        status = "DRY RUN" if dry_run else ("SUCCESS" if success else "FAILED")
        with open(log_path, "a") as log:
            log.write(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — "
                f"{status} — "
                f"{len(prices)} tickers — "
                f"{elapsed}s\n"
            )
    except Exception as e:
        print(f"  [WARN] Could not write log: {e}")

    print()


if __name__ == "__main__":
    main()