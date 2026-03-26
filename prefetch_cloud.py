"""
Martin Capital Partners — Cloud Data Pre-Fetcher
prefetch_cloud.py

Cloud-native version of prefetch_data.py designed to run in GitHub Actions.
Reads credentials from environment variables (GitHub Secrets), fetches data
from yfinance, and upserts to Supabase.

Run modes:
    --mode quick   Prices + indices only (~2 min, runs every 15 min)
    --mode full    Everything: prices, dividends, indices, benchmarks,
                   price history, dividend history, financials (~15 min)
    --mode eod     Prices + indices + benchmarks (final EOD snapshot, ~3 min)

Environment variables (set via GitHub Secrets):
    SUPABASE_URL = "https://idtytpyehfbqldnvwenb.supabase.co"
    SUPABASE_KEY = "sb_secret_P1XNpklX_g_gcMamZb0qqw_udXSu8T7"   # paste your service role key here

Local testing:
    export SUPABASE_URL="https://..."
    export SUPABASE_KEY="sb_..."
    python prefetch_cloud.py --mode quick
    python prefetch_cloud.py --mode quick --dry    # skip Supabase push
"""

import os
import sys
import time
import math
import argparse
import requests
from datetime import datetime, date, timedelta

# ── Configuration ─────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[FATAL] SUPABASE_URL and SUPABASE_KEY must be set as environment variables.")
    print("  For GitHub Actions: set them as repository secrets.")
    print("  For local testing:  export SUPABASE_URL=... SUPABASE_KEY=...")
    sys.exit(1)

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

SB_UPSERT_HEADERS = {
    **SB_HEADERS,
    "Prefer": "resolution=merge-duplicates",
}


# ══════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════

def sb_upsert(table, rows, chunk_size=200, timeout=30):
    """Upsert rows to a Supabase table in chunks. Returns True on success."""
    if not rows:
        return True
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        try:
            resp = requests.post(url, headers=SB_UPSERT_HEADERS, json=chunk, timeout=timeout)
            if resp.status_code not in (200, 201):
                print(f"  [ERROR] {table} chunk {i // chunk_size + 1} "
                      f"({resp.status_code}): {resp.text[:200]}")
                return False
        except Exception as e:
            print(f"  [ERROR] {table} chunk {i // chunk_size + 1}: {e}")
            return False
    return True


def sb_get_column(table, column, filters=None):
    """Fetch a single column from Supabase. Returns list of values."""
    try:
        params = {"select": column}
        if filters:
            params.update(filters)
        # Paginate: Supabase default limit is 1000
        all_vals = []
        offset = 0
        while True:
            params["limit"] = 1000
            params["offset"] = offset
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/{table}",
                headers=SB_HEADERS, params=params, timeout=10,
            )
            if resp.status_code != 200:
                break
            rows = resp.json()
            if not rows:
                break
            all_vals.extend(r.get(column, "") for r in rows)
            if len(rows) < 1000:
                break
            offset += 1000
        return all_vals
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════
# TICKER COLLECTION — reads from Supabase (no Tamarac file needed)
# ══════════════════════════════════════════════════════════════════════════

def get_all_tickers():
    """
    Get the list of tickers to fetch from the existing Supabase prices table.
    This table was initially populated by the local prefetch_data.py, and now
    self-sustains: we always re-fetch whatever tickers are already tracked.

    To add a new ticker: manually insert a row in the prices table, or run
    the local prefetch_data.py once after updating Tamarac_Holdings.xlsx.
    """
    print("  Reading ticker list from Supabase prices table...")
    tickers = sb_get_column("prices", "ticker")
    tickers = sorted(set(t for t in tickers if t and len(t) <= 6 and t.replace(".", "").isalpha()))
    print(f"  Found {len(tickers)} tickers")

    if not tickers:
        print("  [WARN] No tickers in Supabase! Falling back to Tamarac parser...")
        tickers = _get_tickers_from_tamarac()

    return tickers


def _get_tickers_from_tamarac():
    """Fallback: parse Tamarac Excel if it exists in the repo."""
    try:
        # Look for Tamarac file in common locations
        for path in ["data/Tamarac_Holdings.xlsx", "Tamarac_Holdings.xlsx"]:
            if os.path.exists(path):
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from data.tamarac_parser import parse_tamarac_excel, get_holdings_for_strategy
                parsed = parse_tamarac_excel(path)
                tickers = set()
                for strat_key in parsed:
                    df = get_holdings_for_strategy(parsed, strat_key)
                    if not df.empty:
                        tickers.update(df["symbol"].tolist())
                tickers = {t for t in tickers if t and len(t) <= 6 and t.isalpha()}
                print(f"  Tamarac fallback: found {len(tickers)} tickers")
                return sorted(tickers)
    except Exception as e:
        print(f"  [WARN] Tamarac fallback failed: {e}")
    return []


# ══════════════════════════════════════════════════════════════════════════
# PRICE FETCHING
# ══════════════════════════════════════════════════════════════════════════

def fetch_all_prices(tickers):
    """Fetch price + fundamentals for all tickers."""
    import yfinance as yf

    results = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        try:
            tk = yf.Ticker(ticker)

            # 5-day history for accurate daily change
            hist5 = tk.history(period="5d", auto_adjust=True)
            price, prev_close, chg_1d = 0.0, 0.0, 0.0
            if hist5 is not None and len(hist5) >= 2:
                price      = round(float(hist5["Close"].iloc[-1]), 2)
                prev_close = round(float(hist5["Close"].iloc[-2]), 2)
                if prev_close > 0:
                    chg_1d = round((price - prev_close) / prev_close * 100, 2)
                    if abs(chg_1d) > 25:
                        chg_1d = 0.0
            elif hist5 is not None and len(hist5) == 1:
                price = round(float(hist5["Close"].iloc[-1]), 2)

            # fast_info for market cap & 52w range
            fi          = tk.fast_info
            market_cap  = getattr(fi, "market_cap", 0) or 0
            week52_high = round(float(getattr(fi, "year_high", 0) or 0), 2)
            week52_low  = round(float(getattr(fi, "year_low",  0) or 0), 2)

            # Deeper fundamentals
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
                "fetched_at":     datetime.utcnow().isoformat(),
            }

            if i % 10 == 0 or i == total:
                print(f"  Prices: {i}/{total} ({ticker}: ${price} {chg_1d:+.2f}%)")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
            results[ticker] = {
                "ticker": ticker, "price": 0, "change_1d_pct": 0,
                "dividend_yield": 0, "sector": "",
                "fetched_at": datetime.utcnow().isoformat(),
            }

        time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════════════════
# DIVIDEND FETCHING
# ══════════════════════════════════════════════════════════════════════════

def fetch_all_dividends(tickers):
    """Fetch dividend details for all tickers."""
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
                "fetched_at":          datetime.utcnow().isoformat(),
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
                "fetched_at": datetime.utcnow().isoformat(),
            }

        time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════════════════
# INDEX FETCHING
# ══════════════════════════════════════════════════════════════════════════

INDICES = {
    "^GSPC":    "S&P 500",
    "^DJI":     "DJIA",
    "^IXIC":    "Nasdaq",
    "^TNX":     "10Y Treasury",
    "^VIX":     "VIX",
    "DX-Y.NYB": "US Dollar",
    "CL=F":     "Crude Oil",
    "GC=F":     "Gold",
    "BTC-USD":  "Bitcoin",
}


def fetch_index_data():
    """
    Fetch major market indices for the ticker bar.
    Uses batch yf.download with 5-day history to compute change_pct
    from the last two actual closes. fast_info.previous_close is
    unreliable for futures tickers (GC=F, CL=F, etc.).
    """
    import yfinance as yf

    results = {}
    tickers_str = " ".join(INDICES.keys())

    try:
        data = yf.download(
            tickers_str,
            period="5d",
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"  [ERROR] Batch index download failed: {e}")
        for symbol, name in INDICES.items():
            results[symbol] = {
                "symbol": symbol, "name": name, "price": 0,
                "change_pct": 0, "fetched_at": datetime.utcnow().isoformat(),
            }
        return results

    for symbol, name in INDICES.items():
        try:
            if len(INDICES) == 1:
                df = data
            else:
                df = data[symbol] if symbol in data.columns.get_level_values(0) else None

            if df is None or df.empty:
                results[symbol] = {
                    "symbol": symbol, "name": name, "price": 0,
                    "change_pct": 0, "fetched_at": datetime.utcnow().isoformat(),
                }
                continue

            df = df.dropna(subset=["Close"])
            if len(df) < 1:
                results[symbol] = {
                    "symbol": symbol, "name": name, "price": 0,
                    "change_pct": 0, "fetched_at": datetime.utcnow().isoformat(),
                }
                continue

            price = round(float(df["Close"].iloc[-1]), 2)
            prev  = round(float(df["Close"].iloc[-2]), 2) if len(df) >= 2 else price
            chg   = round((price - prev) / prev * 100, 2) if prev > 0 else 0

            results[symbol] = {
                "symbol":     symbol,
                "name":       name,
                "price":      price,
                "change_pct": chg,
                "fetched_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"  [ERROR] Index {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "name": name, "price": 0,
                "change_pct": 0, "fetched_at": datetime.utcnow().isoformat(),
            }

    return results


# ══════════════════════════════════════════════════════════════════════════
# BENCHMARK FETCHING
# ══════════════════════════════════════════════════════════════════════════

BENCHMARK_TICKERS = {
    "^GSPC": "S&P 500",
    "^DJI":  "DJIA",
    "^RUT":  "Russell 2000",
    "NOBL":  "S&P Dividend Aristocrats",
    "IVW":   "S&P 500 Growth",
}


def fetch_benchmark_data():
    """Fetch YTD price history for benchmark tickers."""
    import yfinance as yf
    import pandas as pd

    results = {}
    start = date(date.today().year, 1, 1).strftime("%Y-%m-%d")

    for symbol, name in BENCHMARK_TICKERS.items():
        try:
            hist = yf.download(symbol, start=start, progress=False, auto_adjust=True)
            if hist is None or len(hist) < 2:
                raise ValueError("Not enough data")

            if isinstance(hist.columns, pd.MultiIndex):
                closes = hist["Close"][symbol]
            else:
                closes = hist["Close"]

            closes = closes.dropna()
            if len(closes) < 2:
                raise ValueError("Not enough data after dropna")

            first = float(closes.iloc[0])
            last  = float(closes.iloc[-1])
            ytd   = round(((last - first) / first) * 100, 2)

            history_rows = []
            for dt, close in closes.items():
                date_str = str(dt)[:10]
                history_rows.append({
                    "id":         f"{symbol}_{date_str}",
                    "symbol":     symbol,
                    "date":       date_str,
                    "close":      round(float(close), 4),
                    "fetched_at": datetime.utcnow().isoformat(),
                })

            results[symbol] = {
                "symbol":     symbol,
                "ytd_return": ytd,
                "history":    history_rows,
                "fetched_at": datetime.utcnow().isoformat(),
            }
            print(f"  Benchmark {symbol}: YTD {ytd:+.2f}%")
            time.sleep(0.3)

        except Exception as e:
            print(f"  [ERROR] Benchmark {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "ytd_return": 0, "history": [],
                "fetched_at": datetime.utcnow().isoformat(),
            }

    return results


# ══════════════════════════════════════════════════════════════════════════
# PRICE HISTORY (full mode only — heavy)
# ══════════════════════════════════════════════════════════════════════════

def fetch_price_history(tickers):
    """Fetch full OHLCV history. Skips tickers already stored today."""
    import yfinance as yf

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/price_history",
            headers=SB_HEADERS,
            params={"select": "ticker", "date": f"eq.{today_str}"},
            timeout=10,
        )
        already = {r["ticker"] for r in (resp.json() if resp.status_code == 200 else [])}
    except Exception:
        already = set()

    def _sf(v):
        try:
            f = float(v or 0)
            return 0.0 if (math.isnan(f) or math.isinf(f)) else f
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
                    "open":   round(_sf(row.get("Open",   0)), 4),
                    "high":   round(_sf(row.get("High",   0)), 4),
                    "low":    round(_sf(row.get("Low",    0)), 4),
                    "close":  round(_sf(row.get("Close",  0)), 4),
                    "volume": int(_sf(row.get("Volume", 0))),
                    "fetched_at": datetime.utcnow().isoformat(),
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


# ══════════════════════════════════════════════════════════════════════════
# DIVIDEND HISTORY (full mode only)
# ══════════════════════════════════════════════════════════════════════════

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
                    "fetched_at": datetime.utcnow().isoformat(),
                })
            if i % 10 == 0 or i == total:
                print(f"  Div history: {i}/{total} ({ticker})")
        except Exception as e:
            print(f"  [ERROR] Div history {ticker}: {e}")
        time.sleep(0.3)
    print(f"  Div history: {len(all_rows)} total rows to upsert")
    return all_rows


# ══════════════════════════════════════════════════════════════════════════
# FINANCIALS (full mode only)
# ══════════════════════════════════════════════════════════════════════════

def fetch_financials(tickers):
    """Fetch quarterly financials. Skips tickers updated within 7 days."""
    import yfinance as yf

    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/financials",
            headers=SB_HEADERS,
            params={"select": "ticker", "fetched_at": f"gte.{week_ago}"},
            timeout=10,
        )
        recent = {r["ticker"] for r in (resp.json() if resp.status_code == 200 else [])}
    except Exception:
        recent = set()

    def _sf(v):
        try:
            f = float(v)
            return 0.0 if (math.isnan(f) or math.isinf(f)) else f
        except Exception:
            return 0.0

    def _si(v):
        try:
            return int(_sf(v)) if _sf(v) else 0
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
                    "fetched_at": datetime.utcnow().isoformat(),
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


# ══════════════════════════════════════════════════════════════════════════
# PUSH TO SUPABASE
# ══════════════════════════════════════════════════════════════════════════

def push_to_supabase(prices=None, dividends=None, indices=None,
                     benchmarks=None, price_history=None,
                     div_history=None, financials=None):
    """Upsert all fetched data to Supabase."""

    if prices:
        # Preserve existing dividend_yield and sector when yfinance returns 0/empty
        # (prevents rate-limited fetches from wiping good data)
        _preserve_fields = ["dividend_yield", "sector", "industry", "pe_ratio", "forward_pe", "beta", "name", "price_to_book"]
        try:
            tickers_filter = f"in.({','.join(prices.keys())})"
            existing_url = f"{SUPABASE_URL}/rest/v1/prices"
            existing_params = {
                "select": "ticker," + ",".join(_preserve_fields),
                "ticker": tickers_filter,
                "limit": 1000,
            }
            resp = requests.get(existing_url, headers=SB_HEADERS, params=existing_params, timeout=10)
            if resp.status_code == 200:
                existing = {row["ticker"]: row for row in resp.json()}
                for ticker, data in prices.items():
                    old = existing.get(ticker, {})
                    for field in _preserve_fields:
                        new_val = data.get(field)
                        old_val = old.get(field)
                        # Keep old value if new is empty/zero but old was populated
                        if field in ("sector", "industry", "name"):
                            if not new_val and old_val:
                                data[field] = old_val
                        else:
                            if (new_val == 0 or new_val is None) and old_val and old_val != 0:
                                data[field] = old_val
                print(f"    ✓ preserved existing data for rate-limited fields")
        except Exception as e:
            print(f"    [WARN] Could not read existing prices for preservation: {e}")

        print(f"  Pushing: prices ({len(prices)} rows)...")
        if sb_upsert("prices", list(prices.values())):
            print(f"    ✓ prices OK")

    if dividends:
        print(f"  Pushing: dividends ({len(dividends)} rows)...")
        if sb_upsert("dividends", list(dividends.values())):
            print(f"    ✓ dividends OK")

    if indices:
        print(f"  Pushing: indices ({len(indices)} rows)...")
        if sb_upsert("indices", list(indices.values())):
            print(f"    ✓ indices OK")

    if benchmarks:
        ytd_rows = [{"symbol": s, "ytd_return": d["ytd_return"], "fetched_at": d["fetched_at"]}
                    for s, d in benchmarks.items()]
        print(f"  Pushing: benchmark_ytd ({len(ytd_rows)} rows)...")
        if sb_upsert("benchmark_ytd", ytd_rows):
            print(f"    ✓ benchmark_ytd OK")

        all_history = []
        for d in benchmarks.values():
            all_history.extend(d.get("history", []))
        if all_history:
            print(f"  Pushing: benchmark_history ({len(all_history)} rows)...")
            if sb_upsert("benchmark_history", all_history):
                print(f"    ✓ benchmark_history OK")

    if div_history:
        print(f"  Pushing: dividend_history ({len(div_history)} rows)...")
        if sb_upsert("dividend_history", div_history):
            print(f"    ✓ dividend_history OK")

    if financials:
        print(f"  Pushing: financials ({len(financials)} rows)...")
        if sb_upsert("financials", financials):
            print(f"    ✓ financials OK")

    if price_history:
        # Push ticker by ticker to avoid memory issues
        by_ticker = {}
        for row in price_history:
            by_ticker.setdefault(row["ticker"], []).append(row)
        total_tickers = len(by_ticker)
        pushed = 0
        failed = 0
        print(f"  Pushing: price_history ({len(price_history)} rows, {total_tickers} tickers)...")
        for t, rows in by_ticker.items():
            if sb_upsert("price_history", rows, chunk_size=100, timeout=30):
                pushed += 1
            else:
                failed += 1
        print(f"    ✓ price_history: {pushed} OK, {failed} failed")

    print("  Push complete.")


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def _is_market_hours():
    """
    Check if current UTC time falls within US equity market hours.
    Market: Mon-Fri, 9:30 AM - 4:00 PM ET.
    We add a 30-min buffer on each side for pre/post processing.
    Returns (is_open, et_hour, et_min, weekday).

    ET offset: UTC-4 during EDT (Mar-Nov), UTC-5 during EST (Nov-Mar).
    We detect DST by checking if we're between 2nd Sunday of March
    and 1st Sunday of November.
    """
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    year = now_utc.year
    weekday = now_utc.weekday()  # 0=Mon, 6=Sun

    # Find 2nd Sunday of March and 1st Sunday of November for DST
    mar1 = date(year, 3, 1)
    mar_first_sun = 7 - mar1.weekday() if mar1.weekday() != 6 else 0
    dst_start = date(year, 3, mar_first_sun + 7 + 1)  # 2nd Sunday

    nov1 = date(year, 11, 1)
    nov_first_sun = 7 - nov1.weekday() if nov1.weekday() != 6 else 0
    dst_end = date(year, 11, nov_first_sun + 1)  # 1st Sunday

    today = now_utc.date()
    is_edt = dst_start <= today < dst_end
    et_offset = 4 if is_edt else 5

    et_hour = (now_utc.hour - et_offset) % 24
    et_min = now_utc.minute

    # Market hours with buffer: 9:00 AM - 4:30 PM ET, Mon-Fri
    is_weekday = weekday < 5
    is_in_window = (et_hour > 9 or (et_hour == 9 and et_min >= 0)) and \
                   (et_hour < 16 or (et_hour == 16 and et_min <= 30))

    return is_weekday and is_in_window, et_hour, et_min, weekday


def _auto_detect_mode(et_hour, et_min):
    """
    Auto-detect run mode based on Eastern Time:
      - 9:00 AM ET (first run of day): full
      - 4:00-4:30 PM ET (after close): eod
      - Everything else: quick
    """
    if et_hour == 9 and et_min <= 15:
        return "full"
    elif et_hour == 16:
        return "eod"
    return "quick"


def main():
    parser = argparse.ArgumentParser(description="Martin Capital — Cloud Data Pre-Fetcher")
    parser.add_argument("--mode", choices=["quick", "full", "eod", "auto"], default="auto",
                        help="quick=prices+indices, full=everything, eod=prices+indices+benchmarks, auto=detect from time")
    parser.add_argument("--dry", action="store_true", help="Skip Supabase push (testing)")
    parser.add_argument("--force", action="store_true", help="Run even outside market hours")
    args = parser.parse_args()

    start = time.time()

    # ── Market hours gate ─────────────────────────────────────────────────
    is_open, et_hour, et_min, weekday = _is_market_hours()
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    if not is_open and not args.force and args.mode == "auto":
        print(f"\n  Martin Capital — Cloud Pre-Fetch")
        print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} "
              f"({day_names[weekday]} {et_hour}:{et_min:02d} ET)")
        print(f"  Outside market hours — skipping. Use --force to override.")
        sys.exit(0)

    # ── Mode detection ────────────────────────────────────────────────────
    if args.mode == "auto":
        mode = _auto_detect_mode(et_hour, et_min)
    else:
        mode = args.mode

    print(f"\n{'=' * 60}")
    print(f"  Martin Capital — Cloud Pre-Fetch")
    print(f"  Mode: {mode.upper()}{'  (DRY RUN)' if args.dry else ''}")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} "
          f"({day_names[weekday]} {et_hour}:{et_min:02d} ET)")
    print(f"{'=' * 60}\n")

    # 1. Gather tickers
    print("[1] Gathering tickers...")
    tickers = get_all_tickers()
    if not tickers:
        print("  [FATAL] No tickers found! Check Supabase prices table.")
        sys.exit(1)

    # 2. Always fetch prices + indices
    print(f"\n[2] Fetching prices for {len(tickers)} tickers...")
    prices = fetch_all_prices(tickers)

    print(f"\n[3] Fetching market indices...")
    indices = fetch_index_data()

    # 3. Mode-dependent fetches
    dividends = None
    benchmarks = None
    price_hist = None
    div_hist = None
    financials_data = None

    if mode in ("full", "eod"):
        print(f"\n[4] Fetching benchmark data...")
        benchmarks = fetch_benchmark_data()

    if mode == "full":
        print(f"\n[5] Fetching dividends for {len(tickers)} tickers...")
        dividends = fetch_all_dividends(tickers)

        print(f"\n[6] Fetching price history...")
        price_hist = fetch_price_history(tickers)

        print(f"\n[7] Fetching dividend history...")
        div_hist = fetch_dividend_history(tickers)

        print(f"\n[8] Fetching financials...")
        financials_data = fetch_financials(tickers)

    elapsed = round(time.time() - start, 1)
    print(f"\n  Fetch complete in {elapsed}s")

    # 4. Push to Supabase
    if not args.dry:
        print(f"\n[Push] Pushing to Supabase...")
        push_to_supabase(
            prices=prices,
            dividends=dividends,
            indices=indices,
            benchmarks=benchmarks,
            price_history=price_hist,
            div_history=div_hist,
            financials=financials_data,
        )
    else:
        print(f"\n  DRY RUN — skipping Supabase push")
        if prices:
            sample = list(prices.items())[0]
            print(f"  Sample: {sample[0]} = ${sample[1].get('price', 0)}")

    total_elapsed = round(time.time() - start, 1)
    print(f"\n  Done in {total_elapsed}s at {datetime.utcnow().strftime('%H:%M:%S UTC')}")


if __name__ == "__main__":
    main()