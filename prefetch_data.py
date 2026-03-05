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

                annual_all = divs_df.groupby("year")["amount"].sum()
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
        "GC=F":     "Gold",
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





def fetch_price_history(tickers):
    """Fetch full OHLCV history. Skips tickers already stored today."""
    import yfinance as yf
    import requests as req
    import math as _math

    sb_headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        resp = req.get(f"{SUPABASE_URL}/rest/v1/price_history", headers=sb_headers,
                       params={"select": "ticker", "date": f"eq.{today_str}"}, timeout=10)
        already = {r["ticker"] for r in (resp.json() if resp.status_code == 200 else [])}
    except Exception:
        already = set()

    def _sf(v):
        try:
            f = float(v or 0)
            return 0.0 if (_math.isnan(f) or _math.isinf(f)) else f
        except Exception:
            return 0.0

    all_rows = []
    total = len(tickers)
    skipped = 0
    for i, ticker in enumerate(tickers, 1):
        if ticker in already:
            skipped += 1
            continue
        try:
            hist = yf.Ticker(ticker).history(period="max", auto_adjust=True)
            if hist is None or hist.empty:
                continue
            hist = hist.reset_index()
            for _, row in hist.iterrows():
                ds = str(row["Date"])[:10]
                all_rows.append({
                    "id": f"{ticker}_{ds}", "ticker": ticker, "date": ds,
                    "open":  round(_sf(row.get("Open",  0)), 4),
                    "high":  round(_sf(row.get("High",  0)), 4),
                    "low":   round(_sf(row.get("Low",   0)), 4),
                    "close": round(_sf(row.get("Close", 0)), 4),
                    "volume": int(_sf(row.get("Volume", 0))),
                    "fetched_at": datetime.now().isoformat(),
                })
            if i % 10 == 0 or i == total:
                print(f"  Price history: {i}/{total} ({ticker}, {len(hist)} rows)")
        except Exception as e:
            print(f"  [ERROR] Price history {ticker}: {e}")
        time.sleep(0.4)

    if skipped:
        print(f"  Price history: skipped {skipped} tickers already updated today")
    print(f"  Price history: {len(all_rows)} total rows to upsert")
    return all_rows


def fetch_dividend_history(tickers):
    """Fetch annual dividend totals per ticker."""
    import yfinance as yf
    import pandas as pd

    all_rows = []
    current_year = datetime.now().year
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        try:
            divs = yf.Ticker(ticker).dividends
            if divs is None or divs.empty:
                continue
            df = divs.reset_index()
            df.columns = ["date", "amount"]
            df["year"] = pd.to_datetime(df["date"]).dt.year
            annual = df[df["year"] < current_year].groupby("year")["amount"].sum()
            for year, amt in annual.items():
                all_rows.append({
                    "id": f"{ticker}_{year}", "ticker": ticker,
                    "year": int(year), "amount": round(float(amt), 4),
                    "fetched_at": datetime.now().isoformat(),
                })
            if i % 10 == 0 or i == total:
                print(f"  Div history: {i}/{total} ({ticker})")
        except Exception as e:
            print(f"  [ERROR] Div history {ticker}: {e}")
        time.sleep(0.3)
    print(f"  Div history: {len(all_rows)} total rows to upsert")
    return all_rows


def fetch_financials(tickers):
    """Fetch quarterly financials. Skips tickers updated within 7 days."""
    import yfinance as yf
    import requests as req
    import math as _math
    from datetime import timedelta

    sb_headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        resp = req.get(f"{SUPABASE_URL}/rest/v1/financials", headers=sb_headers,
                       params={"select": "ticker", "fetched_at": f"gte.{week_ago}"}, timeout=10)
        recent = {r["ticker"] for r in (resp.json() if resp.status_code == 200 else [])}
    except Exception:
        recent = set()

    def _sf(v):
        try:
            f = float(v)
            return 0.0 if (_math.isnan(f) or _math.isinf(f)) else f
        except Exception:
            return 0.0

    def _si(v):
        try:
            f = _sf(v)
            return int(f) if f else 0
        except Exception:
            return 0

    all_rows = []
    total = len(tickers)
    skipped = 0
    for i, ticker in enumerate(tickers, 1):
        if ticker in recent:
            skipped += 1
            continue
        try:
            qfins = yf.Ticker(ticker).quarterly_financials
            if qfins is None or qfins.empty:
                continue
            for period_idx, row in qfins.T.sort_index().iterrows():
                ps  = str(period_idx)[:10]
                rev = _sf(row.get("Total Revenue"))
                gp  = _sf(row.get("Gross Profit"))
                ni  = _sf(row.get("Net Income"))
                oi  = _sf(row.get("Operating Income"))
                eb  = _sf(row.get("EBITDA"))
                all_rows.append({
                    "id": f"{ticker}_{ps}", "ticker": ticker, "period": ps,
                    "revenue": _si(rev), "gross_profit": _si(gp),
                    "net_income": _si(ni), "operating_income": _si(oi), "ebitda": _si(eb),
                    "gross_margin":  round(gp / rev * 100, 2) if rev else 0.0,
                    "net_margin":    round(ni / rev * 100, 2) if rev else 0.0,
                    "op_margin":     round(oi / rev * 100, 2) if rev else 0.0,
                    "fetched_at": datetime.now().isoformat(),
                })
            if i % 10 == 0 or i == total:
                print(f"  Financials: {i}/{total} ({ticker})")
        except Exception as e:
            print(f"  [ERROR] Financials {ticker}: {e}")
        time.sleep(0.4)

    if skipped:
        print(f"  Financials: skipped {skipped} tickers updated within 7 days")
    print(f"  Financials: {len(all_rows)} total rows to upsert")
    return all_rows


def push_to_supabase(prices, dividends, indices, benchmarks=None,
                     price_history=None, div_history=None, financials=None):
    """
    Upsert all fetched data to Supabase. Each table is fully independent.
    price_history is pushed ticker-by-ticker to avoid memory issues.
    """
    import requests
    import sys

    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates",
    }

    def upsert(table, rows, chunk_size=200, timeout=30):
        if not rows:
            return True
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            try:
                resp = requests.post(url, headers=headers, json=chunk, timeout=timeout)
                if resp.status_code not in (200, 201):
                    print(f"  [ERROR] {table} chunk {i//chunk_size+1} ({resp.status_code}): {resp.text[:150]}")
                    return False
            except Exception as e:
                print(f"  [ERROR] {table} chunk {i//chunk_size+1}: {e}")
                return False
        return True

    # ── Standard tables (always fast) ────────────────────────────────────
    print("  Pushing: prices...")
    if upsert("prices", list(prices.values())):
        print(f"  Supabase: upserted {len(prices)} price rows")

    print("  Pushing: dividends...")
    if upsert("dividends", list(dividends.values())):
        print(f"  Supabase: upserted {len(dividends)} dividend rows")

    print("  Pushing: indices...")
    if upsert("indices", list(indices.values())):
        print(f"  Supabase: upserted {len(indices)} index rows")

    if benchmarks:
        print("  Pushing: benchmark_ytd...")
        ytd_rows = [{"symbol": s, "ytd_return": d["ytd_return"], "fetched_at": d["fetched_at"]}
                    for s, d in benchmarks.items()]
        if upsert("benchmark_ytd", ytd_rows):
            print(f"  Supabase: upserted {len(ytd_rows)} benchmark YTD rows")

        print("  Pushing: benchmark_history...")
        all_history = []
        for d in benchmarks.values():
            all_history.extend(d.get("history", []))
        if all_history and upsert("benchmark_history", all_history):
            print(f"  Supabase: upserted {len(all_history)} benchmark history rows")

    # ── Dividend history ──────────────────────────────────────────────────
    if div_history:
        print(f"  Pushing: dividend_history ({len(div_history)} rows)...")
        if upsert("dividend_history", div_history):
            print(f"  Supabase: upserted {len(div_history)} dividend history rows")

    # ── Financials ────────────────────────────────────────────────────────
    if financials:
        print(f"  Pushing: financials ({len(financials)} rows)...")
        if upsert("financials", financials):
            print(f"  Supabase: upserted {len(financials)} financials rows")

    # ── Price history — push ticker by ticker to avoid memory issues ──────
    if price_history:
        # Group by ticker
        by_ticker = {}
        for row in price_history:
            by_ticker.setdefault(row["ticker"], []).append(row)
        total_tickers = len(by_ticker)
        pushed = 0
        failed = 0
        print(f"  Pushing: price_history ({len(price_history)} rows across {total_tickers} tickers)...")
        for t, rows in by_ticker.items():
            sys.stdout.write(f"\r  price_history: {pushed+failed+1}/{total_tickers} ({t})    ")
            sys.stdout.flush()
            if upsert("price_history", rows, chunk_size=100, timeout=30):
                pushed += 1
            else:
                failed += 1
        print(f"\n  Supabase: price_history done — {pushed} tickers OK, {failed} failed")

    print("  Push complete.")
    return True


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

    # 6. Fetch price history
    print(f"\n[6/8] Fetching price history for {len(tickers)} tickers...")
    price_hist_rows = fetch_price_history(tickers)

    # 7. Fetch dividend history
    print(f"\n[7/8] Fetching dividend history for {len(tickers)} tickers...")
    div_hist_rows = fetch_dividend_history(tickers)

    # 8. Fetch financials
    print(f"\n[8/8] Fetching financials for {len(tickers)} tickers...")
    financials_rows = fetch_financials(tickers)

    # Push to Supabase
    success = False
    if not dry_run:
        print("\n[Pushing] Pushing to Supabase...")
        success = push_to_supabase(prices, dividends, indices, benchmarks,
                                   price_history=price_hist_rows,
                                   div_history=div_hist_rows,
                                   financials=financials_rows)
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