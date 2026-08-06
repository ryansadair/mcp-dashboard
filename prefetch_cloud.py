"""
Martin Capital Partners — Cloud Data Pre-Fetcher
prefetch_cloud.py

Cloud-native version of prefetch_data.py designed to run in GitHub Actions.
Reads credentials from environment variables (GitHub Secrets), fetches data
from yfinance, and upserts to Supabase.

Run modes:
    --mode quick   Prices + indices only (~2 min, runs every 15 min)
    --mode full    Everything: prices, dividends, indices, benchmarks,
                   price history, financials (~12 min)
                   NOTE: dividend_history removed — Fish CCC file in data/
                   is the authoritative source for historical dividends.
    --mode eod     Prices + indices + benchmarks (final EOD snapshot, ~3 min)
    --mode slow    Warbook metrics only — ROE, FCF yield, debt ratios, sub-
                   industry, etc. Runs once a day off-hours via prefetch-slow.yml
                   (Sprint 23E). ~8-12 min for ~60 tickers because of yfinance
                   financial-statement throttling.

Environment variables (set via GitHub Secrets / local env — NEVER commit real values):
    SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
    SUPABASE_KEY = "sb_secret_..."   # service role key — keep this out of source control

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
from datetime import datetime, date, timedelta, timezone


def _utc_now():
    """Timezone-aware UTC now — always includes +00:00 in .isoformat()."""
    return datetime.now(timezone.utc)

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

def _json_safe(obj):
    """Recursively replace NaN/Inf floats with None so the payload is valid JSON.
    PostgREST rejects 'NaN'/'Infinity' (not JSON-compliant); a single NaN in one
    field of one row would otherwise raise during serialization and silently drop
    the ENTIRE chunk it was in — which is exactly what froze the prices table."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def sb_upsert(table, rows, chunk_size=200, timeout=30):
    """
    Upsert rows to a Supabase table in chunks. Returns True on success.

    Rows are grouped by their key SIGNATURE before pushing: PostgREST
    rejects a bulk upsert whose rows carry different key sets (PGRST102
    "All object keys must match") — one stub row from a failed ticker
    took down the whole prices push on 2026-08-04. Grouping, rather than
    null-padding to a common schema, is deliberate: an explicit null
    OVERWRITES the existing column value on upsert, which would destroy
    the preserved-fields behavior for rate-limited tickers; an omitted
    key leaves the stored value untouched.
    """
    if not rows:
        return True
    rows = _json_safe(rows)   # NaN/Inf -> None so a single bad float can't kill a chunk
    grouped = {}
    for r in rows:
        grouped.setdefault(tuple(sorted(r.keys())), []).append(r)
    if len(grouped) > 1:
        print(f"  [INFO] {table}: {len(grouped)} distinct row shapes — "
              f"pushing each separately "
              f"({', '.join(str(len(g)) for g in grouped.values())} rows)")
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    n_chunk = 0
    for group in grouped.values():
        # chunk WITHIN each shape-group — a chunk must never mix shapes
        for i in range(0, len(group), chunk_size):
            chunk = group[i:i + chunk_size]
            n_chunk += 1
            try:
                resp = requests.post(url, headers=SB_UPSERT_HEADERS, json=chunk, timeout=timeout)
                if resp.status_code not in (200, 201):
                    print(f"  [ERROR] {table} chunk {n_chunk} "
                          f"({resp.status_code}): {resp.text[:200]}")
                    return False
            except Exception as e:
                print(f"  [ERROR] {table} chunk {n_chunk}: {e}")
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

    # ── Watchlist auto-enroll (Sprint 26) ──────────────────────────────────
    # Research names in data/Watchlists.xlsx become first-class citizens:
    # unioned into the universe here, they get 15-min Finviz prices, and the
    # full/slow modes populate dividends, price history, financials, and
    # warbook metrics — so the Stock Detail page loads them instantly from
    # Supabase instead of a cold yfinance pull. Adding a ticker to any
    # watchlist sheet is now all it takes; the row self-perpetuates via the
    # prices-table read above once the first run upserts it.
    try:
        wl_path = "data/Watchlists.xlsx"
        if os.path.exists(wl_path):
            import openpyxl
            wb = openpyxl.load_workbook(wl_path, read_only=True, data_only=True)
            wl = set()
            # Header/junk guard (2026-08-04): sheet header cells like
            # "TICKER" pass a naive length/alpha filter — one got enrolled
            # as a stock, produced a malformed stub row, and failed the
            # whole prices push (PGRST102). Reject known header words and
            # non-symbol entries.
            _not_symbols = {"TICKER", "TICKERS", "SYMBOL", "SYMBOLS",
                            "SYM", "NAME", "CASH", "TOTAL", "NOTES"}
            for ws in wb.worksheets:
                for row in ws.iter_rows(min_col=1, max_col=1, values_only=True):
                    v = row[0]
                    if isinstance(v, str):
                        v = v.strip().upper()
                        if (v and len(v) <= 6 and v.replace(".", "").isalpha()
                                and v not in _not_symbols):
                            wl.add(v)
            new_names = wl - set(tickers)
            if new_names:
                print(f"  Watchlists.xlsx: enrolling {len(new_names)} research "
                      f"tickers: {', '.join(sorted(new_names)[:12])}"
                      f"{' ...' if len(new_names) > 12 else ''}")
            tickers = sorted(set(tickers) | wl)
    except Exception as e:
        print(f"  [WARN] watchlist enroll skipped: {e}")

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

# ── Finviz Elite export (primary bulk source, 2026-07) ─────────────────────
# One authenticated call returns every needed field for every ticker —
# replacing the sequential yfinance loop as the primary source. yfinance
# remains the per-ticker fallback for anything Finviz misses and the sole
# source for what Finviz doesn't carry (indices/futures/crypto, dividend
# payment history, financial statements). Reads FINVIZ_AUTH from the
# environment (GitHub Actions secret); if unset, fetches return {} and
# every caller falls through to the yfinance path unchanged.

_FV_MEMO = {}


def _fv_snapshot(tickers):
    """Fetch the Finviz export once per run for a given ticker set."""
    key = frozenset(tickers)
    if key not in _FV_MEMO:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from data.finviz_export import fetch_once
            _FV_MEMO[key] = fetch_once(list(tickers))
        except Exception as e:
            print(f"  [WARN] Finviz export unavailable: {e}")
            _FV_MEMO[key] = {}
    return _FV_MEMO[key]


def _ny_today():
    """Current calendar date in US market time."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()


def _bday_gap(d1, d2):
    """Approximate business days between d1 (older) and d2 (newer), exclusive
    of d1, inclusive of d2. Weekends only — market holidays are handled by the
    tolerance in _resolve_price_prev, not here."""
    if d1 >= d2:
        return 0
    n, d = 0, d1
    while d < d2:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _resolve_price_prev(closes, fi_last, fi_prev, today=None):
    """
    Resolve (price, previous_close) from a daily-close series + live quote.

    Daily HISTORY is the source of truth for previous_close (the official
    close of the last completed session). The live quote (fast_info) supplies
    the intraday price, and is used for previous_close ONLY when the history
    is gapped by 2+ sessions.

    Why: yfinance's fast_info.previous_close frequently returns extended-hours
    or stale quote-meta values that do not match the official prior close
    (verified 2026-07-29: wrong for 24 of 37 QDVD holdings, off by up to
    2.8%, which systematically distorted the dashboard's daily returns vs
    Finviz/Tamarac). History intermittently drops a recent session (the
    "missing Monday" problem), which is why fast_info was preferred before —
    the date validation below catches that gap explicitly instead.

    Args:
        closes:  pandas Series of daily closes (DatetimeIndex), raw
                 (auto_adjust=False) so prev close matches the official
                 unadjusted close, same convention as Finviz/Tamarac.
        fi_last: fast_info.last_price (float or 0)
        fi_prev: fast_info.previous_close (float or 0) — fallback only
        today:   date override for testing
    Returns (price, previous_close); either may be 0.0 if unresolvable.
    """
    today = today or _ny_today()
    price, prev = 0.0, 0.0

    if closes is not None and len(closes) > 0:
        closes = closes.dropna()
    if closes is not None and len(closes) > 0:
        last_bar_date = closes.index[-1]
        last_bar_date = last_bar_date.date() if hasattr(last_bar_date, "date") else last_bar_date
        last_close = float(closes.iloc[-1])
        price = last_close

        if last_bar_date >= today:
            # History includes today's (live/just-closed) bar → previous
            # close is the bar before it.
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
        else:
            gap = _bday_gap(last_bar_date, today)
            if gap <= 1:
                # Normal pre-market / overnight shape: the most recent
                # completed close IS the previous close.
                prev = last_close
            else:
                # History is gapped (missing recent session). Prefer the
                # quote's previous_close, but only if it is plausibly a
                # close (within 15% of the last known close) — otherwise a
                # market holiday just made the gap look bigger and the last
                # close is still correct.
                if fi_prev and fi_prev > 0 and last_close > 0 \
                        and abs(fi_prev - last_close) / last_close <= 0.15:
                    prev = float(fi_prev)
                else:
                    prev = last_close

    # Live intraday price from the quote always wins when present.
    if fi_last and float(fi_last) > 0:
        price = round(float(fi_last), 2)
    # Last-resort fallback if history gave us nothing.
    if prev <= 0 and fi_prev and float(fi_prev) > 0:
        prev = float(fi_prev)

    return round(price, 2), round(prev, 2)


def fetch_all_prices(tickers):
    """
    Fetch price + fundamentals for all tickers.

    Primary: ONE Finviz Elite export call for the entire list — real-time
    price, official Prev Close, and all fundamentals in ~2 seconds.
    Fallback: the original per-ticker yfinance path (history-authoritative
    previous close via _resolve_price_prev) for any ticker the export
    missed, or for the whole list when FINVIZ_AUTH is not configured.
    """
    import yfinance as yf

    results = {}

    # ── Finviz Elite bulk pass ─────────────────────────────────────────────
    fv = _fv_snapshot(tickers)
    for ticker in tickers:
        d = fv.get(ticker.upper())
        if not d or not (d.get("price") or 0) > 0:
            continue
        chg = d.get("change_pct")
        if chg is None or abs(chg) > 25:
            chg = 0.0
        results[ticker] = {
            "ticker":         ticker,
            "price":          d.get("price") or 0,
            "previous_close": d.get("prev_close") or 0,
            "change_1d_pct":  chg,
            "dividend_yield": d.get("dividend_yield") or 0,
            "sector":         d.get("sector", ""),
            "industry":       d.get("industry", ""),
            "pe_ratio":       round(d.get("pe") or 0, 2),
            "forward_pe":     round(d.get("forward_pe") or 0, 2),
            "market_cap":     d.get("market_cap") or 0,
            "week52_high":    d.get("week52_high") or 0,
            "week52_low":     d.get("week52_low") or 0,
            "beta":           round(d.get("beta") or 0, 2),
            "name":           d.get("name") or ticker,
            "price_to_book":  round(d.get("pb") or 0, 2),
            "fetched_at":     _utc_now().isoformat(),
        }
    # Yield ruling (2026-07): the headline dividend_yield is the INDICATED
    # REGULAR yield — the canonical rate computed by the dividends job
    # (last regular payment x frequency, specials filtered) divided by the
    # live price. Finviz's yield field is estimate-based and folds variable
    # dividends in (CME reads 4.4% there vs the 1.9% regular), so it serves
    # only as the fallback when no canonical rate exists yet.
    try:
        rate_rows = requests.get(
            f"{SUPABASE_URL}/rest/v1/dividends",
            headers=SB_HEADERS,
            params={"select": "ticker,dividend_rate",
                    "ticker": f"in.({','.join(tickers)})"},
            timeout=10,
        ).json()
        rates = {r["ticker"]: r.get("dividend_rate") for r in rate_rows
                 if isinstance(r, dict)}
        for t, row in results.items():
            rt = rates.get(t)
            if rt and row.get("price"):
                y = round(float(rt) / row["price"] * 100, 2)
                if 0 < y <= 15:
                    row["dividend_yield"] = y
    except Exception as e:
        print(f"  [WARN] indicated-yield overlay skipped: {e}")

    yf_list = [t for t in tickers if t not in results]
    print(f"  Prices: Finviz export covered {len(results)}/{len(tickers)}"
          f"{' — yfinance fallback for ' + str(len(yf_list)) if yf_list else ''}")

    # ── yfinance fallback pass ─────────────────────────────────────────────
    total = len(yf_list)

    for i, ticker in enumerate(yf_list, 1):
        try:
            tk = yf.Ticker(ticker)

            # 5-day RAW history (auto_adjust=False so the prior close matches
            # the official unadjusted close — the same convention Finviz and
            # Tamarac use — instead of a dividend-adjusted close on ex-div days)
            hist5 = tk.history(period="5d", auto_adjust=False)

            # fast_info for live price, market cap & 52w range
            fi          = tk.fast_info
            market_cap  = getattr(fi, "market_cap", 0) or 0
            week52_high = round(float(getattr(fi, "year_high", 0) or 0), 2)
            week52_low  = round(float(getattr(fi, "year_low",  0) or 0), 2)
            fi_last     = getattr(fi, "last_price", None) or 0
            fi_prev     = getattr(fi, "previous_close", None) or 0

            # Resolve price + previous close. History is authoritative for the
            # previous close (fast_info.previous_close returns extended-hours /
            # stale values for many tickers); the quote supplies the live
            # intraday price. See _resolve_price_prev for the full rationale.
            closes = hist5["Close"] if hist5 is not None and not hist5.empty else None
            price, prev_close = _resolve_price_prev(closes, fi_last, fi_prev)

            chg_1d = 0.0
            if price > 0 and prev_close > 0:
                chg_1d = round((price - prev_close) / prev_close * 100, 2)
                if abs(chg_1d) > 25:
                    chg_1d = 0.0

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
                "fetched_at":     _utc_now().isoformat(),
            }

            if i % 10 == 0 or i == total:
                print(f"  Prices: {i}/{total} ({ticker}: ${price} {chg_1d:+.2f}%)")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
            results[ticker] = {
                "ticker": ticker, "price": 0, "change_1d_pct": 0,
                "dividend_yield": 0, "sector": "",
                "fetched_at": _utc_now().isoformat(),
            }

        time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════════════════
# DIVIDEND FETCHING
# ══════════════════════════════════════════════════════════════════════════

def _indicated_regular_dividend(divs):
    """
    Indicated REGULAR dividend rate (ruled 2026-07): the most recent regular
    payment x payment frequency, with special/variable payments filtered out.

    Why: neither vendor field is what MCP means by "yield". Finviz's forward
    estimate folds expected variable dividends in (CME showed 4.4% vs the
    2% regular), and TTM fields have opaque special-handling. Computing it
    from the payment record is deterministic and auditable.

    Filter: a payment is "special" when it exceeds 1.75x the median of the
    trailing regular payments (specials like CME's annual variable run 3-5x
    the quarterly regular; genuine raises run 1.03-1.15x, far below the
    threshold). Frequency = count of regular payments in the last 370 days
    (4 = quarterly, 2 = semiannual ADRs, 12 = monthly payers like O).

    Returns (rate, frequency) or (None, None) when history is insufficient.
    """
    try:
        import pandas as pd
        if divs is None or len(divs) < 2:
            return None, None
        tail = divs.tail(10)
        amounts = [float(v) for v in tail.values]
        med = sorted(amounts)[len(amounts) // 2]
        if med <= 0:
            return None, None
        regs = [(ts, amt) for ts, amt in zip(tail.index, amounts)
                if amt <= med * 1.75]
        if not regs:
            return None, None
        last_ts, last_amt = regs[-1]
        cutoff = last_ts - pd.Timedelta(days=370)
        n_year = sum(1 for ts, _ in regs if ts > cutoff)
        freq = 12 if n_year >= 10 else 4 if n_year >= 4 else 2 if n_year >= 2 else 1
        return round(last_amt * freq, 4), freq
    except Exception:
        return None, None


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
                "fetched_at":          _utc_now().isoformat(),
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

            # ── Indicated regular rate & yield (canonical, ruled 2026-07) ──
            # Computed from the payment record; overrides whatever the info
            # blob supplied above. See _indicated_regular_dividend.
            fvd = _fv_snapshot(tickers).get(ticker.upper())
            ind_rate, _freq = _indicated_regular_dividend(divs)
            ind_price = (fvd.get("price") if fvd else 0) or price
            if ind_rate and ind_price and ind_price > 0:
                ind_yld = round(ind_rate / ind_price * 100, 2)
                if 0 < ind_yld <= 15:
                    result["dividend_rate"] = ind_rate
                    result["dividend_yield"] = ind_yld

            # ── Finviz Elite overrides (facts only) ────────────────────────
            # Payout ratio and — most valuably — the actual upcoming
            # ex-dividend date, which yfinance's info blob often lags or
            # omits. Yield/rate are NOT taken from Finviz anymore: the
            # indicated-regular computation above is canonical (Finviz's
            # yield is estimate-based and folds variable dividends in).
            # yfinance history below still owns dividend growth and
            # consecutive-year streaks (and Fish CCC overrides both
            # downstream).
            if fvd:
                fv_payout = fvd.get("payout_ratio")
                if fv_payout is not None and 0 < fv_payout <= 150:
                    result["payout_ratio"] = min(round(fv_payout, 1), 100)
                if fvd.get("ex_dividend_date"):
                    result["ex_dividend_date"] = fvd["ex_dividend_date"]

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
                "fetched_at": _utc_now().isoformat(),
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


def _push_snapshot_bars(want, prices, indices):
    """
    Fallback intraday source (2026-08-06): when Yahoo refuses sub-daily
    data even to GitHub Actions, build one bar per ticker per quick-run
    from the Finviz/index prices fetched seconds earlier in this same
    run. The Overview chart then draws a 15-minute-resolution line (one
    point per prefetch cycle) with the live Finviz endpoint keeping the
    tip minute-fresh — coarser than 5-min bars, immune to Yahoo forever.
    Timestamps round down to the 5-min grid so re-runs in the same
    window upsert instead of duplicating.
    """
    if not prices and not indices:
        print("  [WARN] snapshot fallback has no price data to draw from")
        return
    now = _utc_now()
    ts = now.replace(minute=now.minute - now.minute % 5, second=0,
                     microsecond=0).isoformat()
    rows = []
    for t in want:
        px = None
        if prices and t in prices:
            px = prices[t].get("price")
        if not px and indices and t in indices:
            px = indices[t].get("price")
        if px:
            rows.append({"ticker": t, "ts": ts, "close": round(float(px), 4)})
    print(f"  Snapshot bars: {len(rows)}/{len(want)} tickers at {ts}")
    if rows:
        sb_upsert("intraday_bars", rows, chunk_size=500)


def fetch_and_push_intraday(tickers, prices=None, indices=None):
    """
    Fetch today's 5-minute bars and upsert to Supabase `intraday_bars`.

    Added 2026-08-06: Yahoo began returning EMPTY for all sub-daily
    interval requests from Streamlit Cloud's shared IPs (daily data still
    served; confirmed via the in-app ?debug=1 diag while the identical
    call succeeded from other networks). GitHub Actions' IPs are still
    served, so the every-15-min quick prefetch now owns intraday and the
    Overview chart reads Supabase instead of calling Yahoo app-side.

    Rolling window: prunes rows older than 3 days each run. Logs coverage
    so a future block of Actions IPs is visible in the run log (and would
    surface on the dashboard as the chart's "no bars" placeholder).
    """
    import pandas as pd
    import yfinance as yf

    want = sorted(set(list(tickers) + ["^GSPC", "SPYD"]))
    try:
        data = yf.download(
            tickers=" ".join(want), period="1d", interval="5m",
            group_by="ticker", progress=False, threads=True,
            auto_adjust=False,
        )
    except Exception as e:
        print(f"  [WARN] intraday fetch raised: {e}")
        return
    if data is None or (hasattr(data, "empty") and data.empty):
        print("  [WARN] Yahoo intraday returned EMPTY — falling back to "
              "Finviz snapshot bars (15-min resolution)")
        _push_snapshot_bars(want, prices, indices)
        return

    rows = []
    covered = 0
    for t in want:
        try:
            df = data[t] if t in data.columns.get_level_values(0) else data
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue
            covered += 1
            for ts, close in df["Close"].items():
                rows.append({
                    "ticker": t,
                    "ts": pd.Timestamp(ts).tz_convert("UTC").isoformat(),
                    "close": round(float(close), 4),
                })
        except Exception:
            continue
    print(f"  Intraday: {covered}/{len(want)} tickers, {len(rows)} bars")
    if not rows:
        return
    sb_upsert("intraday_bars", rows, chunk_size=500)

    # prune the rolling window
    try:
        cutoff = (_utc_now() - timedelta(days=3)).isoformat()
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/intraday_bars",
            headers=SB_HEADERS, params={"ts": f"lt.{cutoff}"}, timeout=20,
        )
    except Exception as e:
        print(f"  [WARN] intraday prune skipped: {e}")


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
                "change_pct": 0, "fetched_at": _utc_now().isoformat(),
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
                    "change_pct": 0, "fetched_at": _utc_now().isoformat(),
                }
                continue

            df = df.dropna(subset=["Close"])
            if len(df) < 1:
                results[symbol] = {
                    "symbol": symbol, "name": name, "price": 0,
                    "change_pct": 0, "fetched_at": _utc_now().isoformat(),
                }
                continue

            # Price + previous close.
            #
            # History is authoritative for the previous close; the live quote
            # supplies the intraday price. _resolve_price_prev date-validates
            # the history and only falls back to fast_info.previous_close when
            # the history is gapped by 2+ sessions (the "missing Monday" case)
            # — fast_info.previous_close otherwise returns extended-hours /
            # stale values that don't match the official close. Futures (=F)
            # skip the quote entirely: fast_info is not reliable for them at
            # all, so they stay purely history-based (unchanged behavior).
            fi_last, fi_prev = 0, 0
            if not symbol.endswith("=F"):
                try:
                    fi = yf.Ticker(symbol).fast_info
                    fi_last = getattr(fi, "last_price", None) or 0
                    fi_prev = getattr(fi, "previous_close", None) or 0
                except Exception:
                    pass

            price, prev = _resolve_price_prev(df["Close"], fi_last, fi_prev)
            if prev <= 0:
                prev = price

            chg = round((price - prev) / prev * 100, 2) if prev > 0 else 0

            results[symbol] = {
                "symbol":     symbol,
                "name":       name,
                "price":      price,
                "change_pct": chg,
                "fetched_at": _utc_now().isoformat(),
            }
        except Exception as e:
            print(f"  [ERROR] Index {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "name": name, "price": 0,
                "change_pct": 0, "fetched_at": _utc_now().isoformat(),
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
                    "fetched_at": _utc_now().isoformat(),
                })

            results[symbol] = {
                "symbol":     symbol,
                "ytd_return": ytd,
                "history":    history_rows,
                "fetched_at": _utc_now().isoformat(),
            }
            print(f"  Benchmark {symbol}: YTD {ytd:+.2f}%")
            time.sleep(0.3)

        except Exception as e:
            print(f"  [ERROR] Benchmark {symbol}: {e}")
            results[symbol] = {
                "symbol": symbol, "ytd_return": 0, "history": [],
                "fetched_at": _utc_now().isoformat(),
            }

    return results


# ══════════════════════════════════════════════════════════════════════════
# PRICE HISTORY (full mode only — heavy)
# ══════════════════════════════════════════════════════════════════════════

def fetch_price_history(tickers):
    """Fetch full OHLCV history. Skips tickers already stored today."""
    import yfinance as yf

    today_str = _utc_now().strftime("%Y-%m-%d")
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
                    "fetched_at": _utc_now().isoformat(),
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

def fetch_financials(tickers):
    """Fetch quarterly financials. Skips tickers updated within 7 days."""
    import yfinance as yf

    week_ago = (_utc_now() - timedelta(days=7)).strftime("%Y-%m-%d")
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
                    "fetched_at": _utc_now().isoformat(),
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
                     financials=None, warbook_metrics=None):
    """Upsert all fetched data to Supabase.

    Returns a list of table names that FAILED to push (empty == all good).
    Callers must treat a non-empty list as a hard failure and exit non-zero,
    so a dropped write surfaces as a RED run instead of a silently stale board.
    """
    failures = []

    if warbook_metrics:
        # Sprint 23E — slow-path yfinance fields. Upsert all rows even when
        # values are None; the warbook renderer treats None as em dash. We
        # do NOT preserve previous values like the prices table does, because
        # if yfinance throttled this run we'd rather show em dashes than
        # stale data that misleads (e.g. an ROE from 2 quarters ago).
        rows = list(warbook_metrics.values())
        print(f"  Pushing: warbook_metrics ({len(rows)} rows)...")
        if sb_upsert("warbook_metrics", rows):
            print(f"    ✓ warbook_metrics OK")
        else:
            failures.append("warbook_metrics")

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
        else:
            failures.append("prices")

    if dividends:
        print(f"  Pushing: dividends ({len(dividends)} rows)...")
        if sb_upsert("dividends", list(dividends.values())):
            print(f"    ✓ dividends OK")
        else:
            failures.append("dividends")

    if indices:
        print(f"  Pushing: indices ({len(indices)} rows)...")
        if sb_upsert("indices", list(indices.values())):
            print(f"    ✓ indices OK")
        else:
            failures.append("indices")

    if benchmarks:
        ytd_rows = [{"symbol": s, "ytd_return": d["ytd_return"], "fetched_at": d["fetched_at"]}
                    for s, d in benchmarks.items()]
        print(f"  Pushing: benchmark_ytd ({len(ytd_rows)} rows)...")
        if sb_upsert("benchmark_ytd", ytd_rows):
            print(f"    ✓ benchmark_ytd OK")
        else:
            failures.append("benchmark_ytd")

        all_history = []
        for d in benchmarks.values():
            all_history.extend(d.get("history", []))
        if all_history:
            print(f"  Pushing: benchmark_history ({len(all_history)} rows)...")
            if sb_upsert("benchmark_history", all_history):
                print(f"    ✓ benchmark_history OK")
            else:
                failures.append("benchmark_history")

    if financials:
        print(f"  Pushing: financials ({len(financials)} rows)...")
        if sb_upsert("financials", financials):
            print(f"    ✓ financials OK")
        else:
            failures.append("financials")

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
        if failed:
            failures.append(f"price_history ({failed}/{total_tickers} tickers)")

    if failures:
        print(f"  [FAILED] {len(failures)} table(s) did not push: {', '.join(failures)}")
    else:
        print("  Push complete.")

    return failures


# ══════════════════════════════════════════════════════════════════════════
# WARBOOK METRICS (Sprint 23E — slow mode)
# ══════════════════════════════════════════════════════════════════════════
#
# Slow-path yfinance fields the warbook tabs need but which throttle out on
# Streamlit Cloud's shared egress. Run once a day via prefetch-slow.yml and
# upserted to the warbook_metrics Supabase table.
#
# Compute logic is lifted from data/warbook_metrics.py — duplicated rather
# than imported because prefetch_cloud.py is a standalone GitHub Actions
# script that shouldn't pull in Streamlit / disk_cache dependencies.
# If the compute logic changes in data/warbook_metrics.py, mirror it here.

# Morningstar super-sector groupings. Mirror of _SUPER_SECTOR_MAP in
# data/warbook_metrics.py.
_WB_SUPER_SECTOR_MAP = {
    "Basic Materials":         "Cyclical",
    "Materials":               "Cyclical",
    "Consumer Cyclical":       "Cyclical",
    "Consumer Discretionary":  "Cyclical",
    "Financial Services":      "Cyclical",
    "Financials":              "Cyclical",
    "Real Estate":             "Cyclical",
    "Communication Services":  "Sensitive",
    "Energy":                  "Sensitive",
    "Industrials":             "Sensitive",
    "Technology":              "Sensitive",
    "Consumer Defensive":      "Defensive",
    "Consumer Staples":        "Defensive",
    "Healthcare":              "Defensive",
    "Utilities":               "Defensive",
}


def _wb_safe_float(v, default=None):
    """Coerce to float, returning default on any failure or NaN."""
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _wb_balance_sheet_metrics(tk):
    """LT D/Cap, Net D/Cap, debt coverage ratio from balance + income statements."""
    out = {
        "lt_debt_to_capital": None,
        "net_debt_to_capital": None,
        "debt_coverage_ratio": None,
        "roe_nm": False,
    }
    cur_ltd = None

    try:
        bs = tk.balance_sheet
        if bs is None or bs.empty:
            return out

        col = bs.columns[0]

        def _bs_get(*keys):
            for k in keys:
                if k in bs.index:
                    v = _wb_safe_float(bs.loc[k, col])
                    if v is not None:
                        return v
            return None

        lt_debt = _bs_get("Long Term Debt", "Long-Term Debt", "LongTermDebt")
        # Canonical capital definition (ruled 2026-07): total equity INCLUDING
        # minority interest, per the textbook LT Debt / (LT Debt + Total
        # Equity) formula. Gross-minority key is preferred; common-equity
        # keys are fallbacks for issuers where Yahoo omits it.
        equity = _bs_get(
            "Total Equity Gross Minority Interest",
            "Stockholders Equity",
            "Common Stock Equity",
            "Total Stockholder Equity",
        )
        total_assets = _bs_get("Total Assets")
        cur_ltd = _bs_get(
            "Current Debt And Capital Lease Obligation",
            "Current Debt",
            "Other Current Borrowings",
        )

        # ROE "NM" inputs (ruled 2026-07): equity-thinness signal for the
        # caller. Hard-flag only clearly degenerate bases here (equity <= 0
        # or under 5% of assets); the caller applies the full rule, including
        # a >200% display ceiling. e.g. CLX printed 4,163% and HD 1,466% in
        # the FactSet warbook off near-zero historical equity.
        if equity is not None:
            if equity <= 0 or (total_assets and equity / total_assets < 0.05):
                out["roe_nm"] = True
            if total_assets and total_assets > 0:
                out["_equity_pct_assets"] = round(equity / total_assets * 100, 1)

        # Statement-computed ROE (TTM NI / average equity): Yahoo's packaged
        # returnOnEquity is unreliable on thin-equity names (CLX comes back
        # 5.5% when the arithmetic says ~150%), so the caller substitutes
        # this when equity is under 15% of assets.
        try:
            if equity is not None and equity > 0:
                eq_prev = None
                if len(bs.columns) > 1:
                    for k in ("Total Equity Gross Minority Interest",
                              "Stockholders Equity", "Common Stock Equity"):
                        if k in bs.index:
                            v = _wb_safe_float(bs.loc[k, bs.columns[1]])
                            if v is not None:
                                eq_prev = v
                                break
                avg_eq = (equity + eq_prev) / 2 if eq_prev and eq_prev > 0 else equity
                is2 = tk.income_stmt
                if is2 is not None and not is2.empty:
                    ni = None
                    for k in ("Net Income", "Net Income Common Stockholders"):
                        if k in is2.index:
                            ni = _wb_safe_float(is2.loc[k, is2.columns[0]])
                            if ni is not None:
                                break
                    if ni is not None and avg_eq > 0:
                        out["_roe_stmt"] = round(ni / avg_eq * 100, 1)
        except Exception:
            pass
        cash = _bs_get(
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments",
            "Cash",
        )

        if lt_debt is not None and equity is not None:
            denom = lt_debt + equity
            if denom > 0:
                out["lt_debt_to_capital"] = round((lt_debt / denom) * 100, 1)

        if lt_debt is not None and equity is not None and cash is not None:
            net_debt = lt_debt - cash
            denom = lt_debt + equity
            if denom > 0:
                out["net_debt_to_capital"] = round((net_debt / denom) * 100, 1)
    except Exception:
        pass

    try:
        is_ = tk.income_stmt
        if is_ is not None and not is_.empty:
            col = is_.columns[0]

            def _is_get(*keys):
                for k in keys:
                    if k in is_.index:
                        v = _wb_safe_float(is_.loc[k, col])
                        if v is not None:
                            return v
                return None

            op_income = _is_get(
                "Operating Income",
                "Total Operating Income As Reported",
                "Operating Revenue",
            )
            interest_exp = _is_get("Interest Expense", "Interest Expense Non Operating")

            # Debt-Service Coverage (ruled 2026-07):
            #     EBIT / (interest expense + current LT debt maturities)
            # i.e. "can this year's operating earnings cover this year's
            # actual debt obligations." Replaces the old plain interest-
            # coverage calc (EBIT/interest), which read far higher than the
            # legacy FactSet warbook column and answered a weaker question.
            # Finance-lease current maturities are included when Yahoo folds
            # them into the current-debt line (its default presentation).
            # Financials and REITs are blanked by the caller — capital-
            # structure coverage is not meaningful for them.
            if op_income is not None:
                denom = abs(interest_exp or 0) + (cur_ltd or 0)
                if denom > 0:
                    out["debt_coverage_ratio"] = round(op_income / denom, 1)
    except Exception:
        pass

    return out


def _wb_cash_flow_metrics(tk, info):
    """FCF yield, dividend coverage ratios, CF/EV yield."""
    out = {
        "fcf_yield": None,
        "fcf_div_coverage": None,
        "cf_div_coverage": None,
        "eps_div_coverage": None,
        "cash_flow_ev_yield": None,
    }

    fcf = _wb_safe_float(info.get("freeCashflow"))
    op_cf = _wb_safe_float(info.get("operatingCashflow"))
    market_cap = _wb_safe_float(info.get("marketCap"))
    enterprise_value = _wb_safe_float(info.get("enterpriseValue"))
    eps = _wb_safe_float(info.get("trailingEps"))
    div_rate = _wb_safe_float(info.get("dividendRate"))
    shares_out = _wb_safe_float(info.get("sharesOutstanding"))

    if fcf is not None and market_cap is not None and market_cap > 0:
        out["fcf_yield"] = round((fcf / market_cap) * 100, 2)

    if op_cf is not None and enterprise_value is not None and enterprise_value > 0:
        out["cash_flow_ev_yield"] = round((op_cf / enterprise_value) * 100, 2)

    if div_rate is not None and div_rate > 0 and shares_out is not None and shares_out > 0:
        annual_divs_total = div_rate * shares_out
        if fcf is not None and annual_divs_total > 0:
            out["fcf_div_coverage"] = round(fcf / annual_divs_total, 1)
        if op_cf is not None and annual_divs_total > 0:
            out["cf_div_coverage"] = round(op_cf / annual_divs_total, 1)

    if eps is not None and div_rate is not None and div_rate > 0:
        out["eps_div_coverage"] = round(eps / div_rate, 1)

    return out


def _wb_5yr_roe_avg(tk):
    """5-year average ROE from income statement + balance sheet history."""
    try:
        is_ = tk.income_stmt
        bs = tk.balance_sheet
        if is_ is None or bs is None or is_.empty or bs.empty:
            return None

        roes = []
        max_periods = min(5, len(is_.columns), len(bs.columns))

        for i in range(max_periods):
            try:
                is_col = is_.columns[i]
                bs_col = bs.columns[i] if i < len(bs.columns) else None
                if bs_col is None:
                    continue

                ni = None
                for k in ("Net Income", "Net Income Common Stockholders",
                         "Net Income Continuous Operations"):
                    if k in is_.index:
                        ni = _wb_safe_float(is_.loc[k, is_col])
                        if ni is not None:
                            break

                eq = None
                for k in ("Stockholders Equity", "Common Stock Equity",
                         "Total Stockholder Equity"):
                    if k in bs.index:
                        eq = _wb_safe_float(bs.loc[k, bs_col])
                        if eq is not None:
                            break

                if ni is not None and eq is not None and eq > 0:
                    roes.append((ni / eq) * 100)
            except Exception:
                continue

        if len(roes) < 2:
            return None

        return round(sum(roes) / len(roes), 1)
    except Exception:
        return None


def _wb_dividend_metadata(tk):
    """Modal month of dividend increase + payment frequency (Q/M/SA/A)."""
    out = {"timing_of_raise": None, "dividend_frequency": None}
    try:
        divs = tk.dividends
        if divs is None or len(divs) == 0:
            return out

        cutoff = datetime.now().replace(tzinfo=None) - timedelta(days=365 * 5)
        recent = divs.copy()
        try:
            recent.index = recent.index.tz_localize(None) if recent.index.tz is not None else recent.index
        except Exception:
            pass
        recent = recent[recent.index >= cutoff] if len(recent) > 0 else recent

        if len(recent) == 0:
            return out

        from collections import Counter
        years = recent.index.year
        per_year = Counter(years)
        if per_year:
            counts = sorted(per_year.values())
            median_count = counts[len(counts) // 2]
            if median_count >= 11:
                out["dividend_frequency"] = "M"
            elif median_count >= 3:
                out["dividend_frequency"] = "Q"
            elif median_count == 2:
                out["dividend_frequency"] = "SA"
            elif median_count == 1:
                out["dividend_frequency"] = "A"

        months_with_increase = []
        prior = None
        for ts, amt in recent.items():
            try:
                amt_f = float(amt)
            except (TypeError, ValueError):
                continue
            if prior is not None and amt_f > prior * 1.001:
                months_with_increase.append(ts.month)
            prior = amt_f

        if months_with_increase:
            month_counts = Counter(months_with_increase)
            modal_month = month_counts.most_common(1)[0][0]
            month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            out["timing_of_raise"] = month_names[modal_month - 1]
    except Exception:
        pass

    return out


def fetch_warbook_metrics(tickers):
    """
    Fetch all warbook-specific metrics for the given tickers. Returns a dict
    keyed by ticker; each value is a row ready to upsert to warbook_metrics.

    Cold path is the slow one — financial statement queries throttle worse
    than price data, so we use a 0.5s inter-ticker delay (vs 0.3s for the
    price fetch). For ~60 tickers that's ~30s of throttle padding, but the
    actual compute time is dominated by yfinance's per-statement HTTP cost
    (~8-12 min total for the full universe is typical).
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  [FATAL] yfinance not installed")
        return {}

    results = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        row = {
            "ticker": ticker,
            "roe_ttm": None,
            "roe_5y_avg": None,
            "lt_debt_to_capital": None,
            "net_debt_to_capital": None,
            "debt_coverage_ratio": None,
            "roe_nm": False,
            "fcf_yield": None,
            "fcf_div_coverage": None,
            "cf_div_coverage": None,
            "eps_div_coverage": None,
            "cash_flow_ev_yield": None,
            "super_sector": None,
            "sub_industry": None,
            "country": None,
            "forward_pe": None,
            "timing_of_raise": None,
            "dividend_frequency": None,
            "fetched_at": _utc_now().isoformat(),
        }

        try:
            tk = yf.Ticker(ticker)

            try:
                info = tk.info or {}
            except Exception:
                info = {}

            # ROE TTM (heuristic: <5 means decimal fraction)
            roe = _wb_safe_float(info.get("returnOnEquity"))
            if roe is not None:
                row["roe_ttm"] = round(roe * 100, 1) if abs(roe) < 5 else round(roe, 1)

            # ROE 5Y avg (slow — financial statement query)
            row["roe_5y_avg"] = _wb_5yr_roe_avg(tk)

            # Balance sheet metrics
            row.update(_wb_balance_sheet_metrics(tk))

            # Cash flow metrics
            row.update(_wb_cash_flow_metrics(tk, info))

            # Dividend metadata (uses tk.dividends — generally reliable)
            row.update(_wb_dividend_metadata(tk))

            # Industry / geo classification
            sector_raw = info.get("sector", "") or ""
            row["super_sector"] = _WB_SUPER_SECTOR_MAP.get(sector_raw)
            row["sub_industry"] = info.get("industry", "") or None
            row["country"] = info.get("country", "") or None

            fwd_pe = _wb_safe_float(info.get("forwardPE"))
            if fwd_pe is not None:
                row["forward_pe"] = round(fwd_pe, 1)

            if i % 5 == 0 or i == total:
                # Cherry-pick a few fields for the progress line so we can
                # eyeball whether the compute is producing real values
                roe_v = row.get("roe_ttm")
                fcf_v = row.get("fcf_yield")
                sub = row.get("sub_industry") or "?"
                print(f"  Warbook: {i}/{total} ({ticker}: "
                      f"ROE={roe_v}, FCF Yld={fcf_v}, sub={sub[:24]})")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")

        # ── Finviz Elite gap-fill ──────────────────────────────────────────
        # Facts (industry, country, forward P/E) and simple ratios fill in
        # whenever yfinance came back empty. Statement-derived metrics keep
        # their existing yfinance methodology — Finviz only backstops them
        # so a yfinance outage no longer blanks the warbook.
        try:
            fvd = _fv_snapshot(tickers).get(ticker.upper())
            if fvd:
                if row["roe_ttm"] is None and not row.get("roe_nm") \
                        and fvd.get("roe") is not None:
                    row["roe_ttm"] = round(fvd["roe"], 1)
                if row["fcf_yield"] is None and fvd.get("fcf_yield") is not None:
                    row["fcf_yield"] = fvd["fcf_yield"]
                if not row["sub_industry"] and fvd.get("industry"):
                    row["sub_industry"] = fvd["industry"]
                if not row["country"] and fvd.get("country"):
                    row["country"] = fvd["country"]
                if row["forward_pe"] is None and fvd.get("forward_pe") is not None:
                    row["forward_pe"] = round(fvd["forward_pe"], 1)
                if row["super_sector"] is None and fvd.get("sector"):
                    row["super_sector"] = _WB_SUPER_SECTOR_MAP.get(fvd["sector"])
        except Exception:
            pass

        # ── Canonical-definition rulings (2026-07) ─────────────────────────
        # 1. ROE: on thin equity (<15% of assets) trust the statement
        #    arithmetic over Yahoo's packaged figure; flag NM when the base
        #    is degenerate (equity <= 0 / <5% of assets) or the resulting
        #    figure exceeds 200% — past that point the number is a
        #    capital-structure artifact, not a profitability signal.
        _epa = row.pop("_equity_pct_assets", None)
        _roe_stmt = row.pop("_roe_stmt", None)
        if _epa is not None and _epa < 15 and _roe_stmt is not None:
            row["roe_ttm"] = _roe_stmt
        if row.get("roe_ttm") is not None and row["roe_ttm"] > 200:
            row["roe_nm"] = True
        if row.get("roe_nm"):
            row["roe_ttm"] = None
        # 2. Debt-Service Coverage is not meaningful for financials (funding
        #    IS the business) or REITs; blank it, matching the legacy
        #    warbook convention of showing 0/— for banks.
        _sec = (row.get("sub_industry") or "").lower()
        if any(k in _sec for k in ("bank", "insurance", "reinsurance",
                                   "asset manag", "capital markets",
                                   "financial data", "exchange", "reit")):
            row["debt_coverage_ratio"] = None

        results[ticker] = row

        # Throttle — financial-statement queries are heavier than price queries
        time.sleep(0.5)

    return results


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
    parser.add_argument("--mode", choices=["quick", "full", "eod", "slow", "auto"], default="auto",
                        help="quick=prices+indices, full=everything, eod=prices+indices+benchmarks, "
                             "slow=warbook_metrics only (Sprint 23E daily cron), auto=detect from time")
    parser.add_argument("--dry", action="store_true", help="Skip Supabase push (testing)")
    parser.add_argument("--force", action="store_true", help="Run even outside market hours")
    args = parser.parse_args()

    start = time.time()

    # ── Market hours gate ─────────────────────────────────────────────────
    is_open, et_hour, et_min, weekday = _is_market_hours()
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    if not is_open and not args.force and args.mode == "auto":
        print(f"\n  Martin Capital — Cloud Pre-Fetch")
        print(f"  {_utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')} "
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
    print(f"  {_utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')} "
          f"({day_names[weekday]} {et_hour}:{et_min:02d} ET)")
    print(f"{'=' * 60}\n")

    # 1. Gather tickers
    print("[1] Gathering tickers...")
    tickers = get_all_tickers()
    if not tickers:
        print("  [FATAL] No tickers found! Check Supabase prices table.")
        sys.exit(1)

    # ── slow mode: warbook_metrics only (Sprint 23E) ──────────────────────
    # No prices/indices/benchmarks — the fast prefetch handles those. This
    # mode runs once a day to populate the slow-changing fundamentals that
    # Streamlit Cloud can't fetch reliably from yfinance (ROE, FCF yield,
    # debt ratios, sub-industry, etc.).
    if mode == "slow":
        print(f"\n[2] Fetching warbook metrics for {len(tickers)} tickers...")
        warbook = fetch_warbook_metrics(tickers)

        elapsed = round(time.time() - start, 1)
        print(f"\n  Fetch complete in {elapsed}s")

        push_failures = []
        if not args.dry:
            print(f"\n[Push] Pushing to Supabase...")
            push_failures = push_to_supabase(warbook_metrics=warbook)
        else:
            print(f"\n  DRY RUN — skipping Supabase push")
            if warbook:
                sample = list(warbook.items())[0]
                print(f"  Sample: {sample[0]} = {sample[1]}")

        total_elapsed = round(time.time() - start, 1)
        print(f"\n  Done in {total_elapsed}s at {_utc_now().strftime('%H:%M:%S UTC')}")
        if push_failures:
            print(f"\n[FATAL] Supabase push failed for: {', '.join(push_failures)}")
            sys.exit(1)
        return

    # 2. Always fetch prices + indices (quick/full/eod modes)
    print(f"\n[2] Fetching prices for {len(tickers)} tickers...")
    prices = fetch_all_prices(tickers)

    print(f"\n[3] Fetching market indices...")
    indices = fetch_index_data()

    print(f"\n[3b] Fetching intraday bars (5m) for the Overview chart...")
    fetch_and_push_intraday(tickers, prices=prices, indices=indices)

    # 3. Mode-dependent fetches
    dividends = None
    benchmarks = None
    price_hist = None
    financials_data = None

    if mode in ("full", "eod"):
        print(f"\n[4] Fetching benchmark data...")
        benchmarks = fetch_benchmark_data()

    if mode == "full":
        print(f"\n[5] Fetching dividends for {len(tickers)} tickers...")
        dividends = fetch_all_dividends(tickers)

        print(f"\n[6] Fetching price history...")
        price_hist = fetch_price_history(tickers)

        # Dividend history previously fetched here — removed in favor of
        # the Fish CCC spreadsheet (data/Fish_*.xlsx), which is the
        # authoritative source for historical dividends and streak data.

        print(f"\n[7] Fetching financials...")
        financials_data = fetch_financials(tickers)

    elapsed = round(time.time() - start, 1)
    print(f"\n  Fetch complete in {elapsed}s")

    # 4. Push to Supabase
    push_failures = []
    if not args.dry:
        print(f"\n[Push] Pushing to Supabase...")
        push_failures = push_to_supabase(
            prices=prices,
            dividends=dividends,
            indices=indices,
            benchmarks=benchmarks,
            price_history=price_hist,
            financials=financials_data,
        )
    else:
        print(f"\n  DRY RUN — skipping Supabase push")
        if prices:
            sample = list(prices.items())[0]
            print(f"  Sample: {sample[0]} = ${sample[1].get('price', 0)}")

    total_elapsed = round(time.time() - start, 1)
    print(f"\n  Done in {total_elapsed}s at {_utc_now().strftime('%H:%M:%S UTC')}")
    if push_failures:
        print(f"\n[FATAL] Supabase push failed for: {', '.join(push_failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()