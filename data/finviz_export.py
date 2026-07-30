"""
Martin Capital Partners — Finviz Elite Export API Client
data/finviz_export.py

Single-call batch snapshot for the entire ticker universe via Finviz Elite's
export endpoint (https://elite.finviz.com/export.ashx). One authenticated
HTTP request returns every screener column for every ticker — replacing the
~60 sequential yfinance calls (and their throttling, Yahoo-endpoint breakage,
and bad previous_close values) that used to power the price/fundamentals path.

This module is shared by BOTH the Streamlit app and prefetch_cloud.py
(GitHub Actions), so it has NO hard streamlit dependency.

Auth resolution (never hardcode the token in source):
    1. FINVIZ_AUTH environment variable            (GitHub Actions secret)
    2. st.secrets["FINVIZ_AUTH"]                   (Streamlit Cloud / local)
    3. st.secrets["finviz"]["auth"]                (nested form)
If no token is found, every call returns {} and callers fall through to
their existing Supabase / yfinance paths — nothing breaks, it just isn't live.

Rate limiting: Finviz's guidance is ~1 export request per 60 seconds
(exceeding it risks an account ban). This module enforces a minimum interval
between HTTP calls (_MIN_INTERVAL_S) and keeps a module-global merged store
of the latest row per ticker. Repeat calls inside the interval are served
from the store; tickers not yet in the store simply come back missing and
the caller's fallback chain handles them. Every HTTP call requests the
union of all tickers seen this session, so after the first call per process
one request per interval covers every tab.

Column IDs: the export's c= parameter takes integer column IDs that Finviz
does not document. The mapping below was discovered and verified empirically
on 2026-07-29 by requesting IDs in scrambled order and matching CSV headers.
If Finviz ever renames a header, _parse_row keys off OUR requested order,
not the header names, so renames are harmless; only ID reassignment would
matter (no known precedent).
"""

import os
import csv
import io
import time
import threading
from datetime import datetime

# ── Column catalog (verified 2026-07-29) ───────────────────────────────────
# id: internal_name — order here defines CSV column order in the response.
_COLUMNS = [
    (1,   "ticker"),
    (2,   "name"),
    (3,   "sector"),
    (4,   "industry"),
    (5,   "country"),
    (6,   "market_cap_m"),        # in millions of USD
    (7,   "pe"),
    (8,   "forward_pe"),
    (9,   "peg"),
    (10,  "ps"),
    (11,  "pb"),
    (13,  "p_fcf"),
    (14,  "dividend_yield"),      # e.g. "2.12%"
    (15,  "payout_ratio"),
    (16,  "eps_ttm"),
    (26,  "insider_own"),
    (27,  "insider_trans"),
    (28,  "inst_own"),
    (29,  "inst_trans"),
    (30,  "short_float"),
    (32,  "roa"),
    (33,  "roe"),
    (34,  "roic"),
    (35,  "current_ratio"),
    (36,  "quick_ratio"),
    (37,  "lt_debt_eq"),
    (38,  "debt_eq"),
    (39,  "gross_margin"),
    (40,  "oper_margin"),
    (41,  "profit_margin"),
    (42,  "perf_week"),
    (43,  "perf_month"),
    (44,  "perf_quarter"),
    (45,  "perf_half"),
    (46,  "perf_year"),
    (47,  "perf_ytd"),
    (48,  "beta"),
    (49,  "atr"),
    (50,  "vol_weekly"),
    (51,  "vol_monthly"),
    (52,  "sma20_dist"),
    (53,  "sma50_dist"),
    (54,  "sma200_dist"),
    (57,  "from_52w_high"),
    (58,  "from_52w_low"),
    (59,  "rsi_14"),
    (62,  "recommendation_raw"),
    (63,  "avg_volume_k"),        # in thousands
    (64,  "rel_volume"),
    (65,  "price"),
    (66,  "change_pct"),
    (67,  "volume"),
    (68,  "earnings_datetime"),   # "7/22/2026 4:30:00 PM"
    (69,  "target_price"),
    (71,  "after_hours_close"),
    (72,  "after_hours_change"),
    (73,  "book_sh"),
    (74,  "cash_sh"),
    (75,  "dividend_est"),        # forward annual rate estimate
    (77,  "eps_next_q"),
    (81,  "prev_close"),          # official prior-session close
    (130, "dividend_ttm"),
    (131, "ex_dividend_date"),    # "7/31/2026"
    (134, "range_52w"),           # "152.73 - 334.03"
    (147, "div_growth_1y"),
    (148, "div_growth_3y"),
    (149, "div_growth_5y"),
]
_COL_IDS = ",".join(str(i) for i, _ in _COLUMNS)
_COL_NAMES = [n for _, n in _COLUMNS]

_EXPORT_URL = "https://elite.finviz.com/export.ashx"
_TIMEOUT_S = 25
_MIN_INTERVAL_S = 30      # min seconds between HTTP calls (Finviz guidance ~60s;
                          # 30s worst-case burst only during first page loads)
_MAX_AGE_S = 90           # store entries older than this count as stale
_CHUNK = 400              # tickers per request (URL-length safety; we have ~80)

# ── Module-global merged store (shared across Streamlit reruns) ────────────
_STORE = {}               # ticker -> (normalized_row_dict, fetched_epoch)
_KNOWN = set()            # every ticker ever requested this session
_LAST_HTTP = 0.0
_LAST_SUCCESS = 0.0       # epoch of last fetch that returned data
_LOCK = threading.Lock()


def get_auth_token():
    """Resolve the Elite auth token. Returns None if unset (module disabled)."""
    tok = os.environ.get("FINVIZ_AUTH")
    if tok:
        return tok.strip()
    try:
        import streamlit as st
        if "FINVIZ_AUTH" in st.secrets:
            return str(st.secrets["FINVIZ_AUTH"]).strip()
        if "finviz" in st.secrets and "auth" in st.secrets["finviz"]:
            return str(st.secrets["finviz"]["auth"]).strip()
    except Exception:
        pass
    return None


def finviz_available():
    """True if an auth token is configured."""
    return get_auth_token() is not None


# ── Parsers ─────────────────────────────────────────────────────────────────

def _f(val):
    """Parse a float, stripping %, $ and commas. None on blank/dash/error."""
    if val is None:
        return None
    s = str(val).replace("%", "").replace("$", "").replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date_iso(val):
    """Parse Finviz m/d/Y (optionally with time) -> 'YYYY-MM-DD' or ''."""
    s = str(val or "").strip()
    if not s:
        return ""
    try:
        return datetime.strptime(s.split(" ")[0], "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _earnings_fields(val):
    """
    Parse "7/22/2026 4:30:00 PM" ->
      (iso_date, timing, legacy_str)
    timing: 'BMO' (before noon), 'AMC' (noon or later), None (no time given).
    legacy_str: "Jul 22 2026 AMC" — the string format the existing
    alerts-tab parser (_parse_finviz_earnings_date) already understands.
    """
    s = str(val or "").strip()
    if not s:
        return "", None, None
    parts = s.split(" ", 1)
    iso = _date_iso(parts[0])
    if not iso:
        return "", None, None
    timing = None
    if len(parts) > 1 and parts[1].strip():
        try:
            t = datetime.strptime(s, "%m/%d/%Y %I:%M:%S %p")
            if not (t.hour == 0 and t.minute == 0):
                timing = "BMO" if t.hour < 12 else "AMC"
        except ValueError:
            pass
    d = datetime.strptime(iso, "%Y-%m-%d")
    legacy = d.strftime("%b %d %Y") + (f" {timing}" if timing else "")
    return iso, timing, legacy


# Finviz sector taxonomy differs from yfinance's in one label; the rest of
# the app (SECTOR_RENAME in utils/config.py, warbook super-sector map) is
# keyed to yfinance names, so translate at the source.
_SECTOR_TRANSLATE = {"Financial": "Financial Services"}


def _normalize(raw):
    """Convert a raw CSV row dict (internal_name -> str) into typed fields."""
    row = {}
    row["ticker"]   = raw.get("ticker", "").strip()
    row["name"]     = raw.get("name", "").strip()
    sector          = raw.get("sector", "").strip()
    row["sector"]   = _SECTOR_TRANSLATE.get(sector, sector)
    row["industry"] = raw.get("industry", "").strip()
    row["country"]  = raw.get("country", "").strip()

    mc = _f(raw.get("market_cap_m"))
    row["market_cap"] = round(mc * 1_000_000) if mc else 0

    for k in ("pe", "forward_pe", "peg", "ps", "pb", "p_fcf", "eps_ttm",
              "eps_next_q", "beta", "atr", "rel_volume", "current_ratio",
              "quick_ratio", "lt_debt_eq", "debt_eq", "book_sh", "cash_sh",
              "rsi_14", "target_price", "price", "prev_close",
              "after_hours_close", "dividend_est", "dividend_ttm"):
        row[k] = _f(raw.get(k))

    for k in ("dividend_yield", "payout_ratio", "insider_own", "insider_trans",
              "inst_own", "inst_trans", "short_float", "roa", "roe", "roic",
              "gross_margin", "oper_margin", "profit_margin",
              "perf_week", "perf_month", "perf_quarter", "perf_half",
              "perf_year", "perf_ytd", "vol_weekly", "vol_monthly",
              "sma20_dist", "sma50_dist", "sma200_dist",
              "from_52w_high", "from_52w_low", "change_pct",
              "after_hours_change", "div_growth_1y", "div_growth_3y",
              "div_growth_5y"):
        v = _f(raw.get(k))
        row[k] = round(v, 2) if v is not None else None

    av = _f(raw.get("avg_volume_k"))
    row["avg_volume"] = round(av * 1000) if av else None
    row["volume"] = _f(raw.get("volume"))

    # 52-week range -> explicit levels
    row["week52_low"], row["week52_high"] = None, None
    rng = raw.get("range_52w", "")
    if "-" in rng:
        lo, _, hi = rng.partition("-")
        row["week52_low"], row["week52_high"] = _f(lo), _f(hi)

    row["ex_dividend_date"] = _date_iso(raw.get("ex_dividend_date"))
    (row["earnings_date_iso"],
     row["earnings_timing"],
     row["earnings_date_finviz"]) = _earnings_fields(raw.get("earnings_datetime"))

    row["recommendation_raw"] = _f(raw.get("recommendation_raw"))

    # Derived: FCF yield from P/FCF (FCF/price = 1 / (P/FCF))
    row["fcf_yield"] = round(100.0 / row["p_fcf"], 1) if row.get("p_fcf") else None

    row["fetched_at"] = datetime.utcnow().isoformat()
    return row


# ── HTTP layer ──────────────────────────────────────────────────────────────

def _http_fetch(tickers, auth):
    """One export call for a ticker list. Returns {ticker: normalized_row}.
    Raises nothing — returns {} on any failure so callers fall through."""
    import requests

    out = {}
    try:
        for i in range(0, len(tickers), _CHUNK):
            chunk = tickers[i:i + _CHUNK]
            resp = requests.get(
                _EXPORT_URL,
                params={"v": "152", "t": ",".join(chunk),
                        "c": _COL_IDS, "auth": auth},
                timeout=_TIMEOUT_S,
            )
            if resp.status_code != 200 or not resp.text.startswith('"Ticker"'):
                # Auth failure / HTML error page / ban page — treat as outage.
                # (With an explicit c= list that starts at id 1, the CSV
                # begins with the "Ticker" header; the "No." counter only
                # appears if id 0 is requested.)
                print(f"  [WARN] Finviz export HTTP {resp.status_code} "
                      f"(body starts: {resp.text[:40]!r})")
                return out
            reader = csv.reader(io.StringIO(resp.text))
            headers = next(reader, None)
            if not headers or len(headers) != len(_COL_NAMES):
                print(f"  [WARN] Finviz export returned {len(headers or [])} "
                      f"columns, expected {len(_COL_NAMES)} — schema drift?")
                return out
            # Columns arrive in the exact order of _COLUMNS.
            for row in reader:
                raw = dict(zip(_COL_NAMES, row))
                norm = _normalize(raw)
                if norm["ticker"]:
                    out[norm["ticker"].upper()] = norm
    except Exception as e:
        print(f"  [WARN] Finviz export failed: {e}")
    return out


def get_snapshot(tickers, max_age_s=_MAX_AGE_S):
    """
    Return {ticker: row} for as many of the requested tickers as possible.

    Serves from the module store when fresh; makes at most one HTTP call per
    _MIN_INTERVAL_S window (requesting the union of every ticker seen this
    session, so one call warms every tab). Tickers it can't serve are simply
    absent from the result — callers MUST treat missing tickers via their
    existing fallback chain (Supabase / yfinance).
    """
    global _LAST_HTTP, _LAST_SUCCESS
    auth = get_auth_token()
    if not auth:
        return {}

    req = [t.upper() for t in tickers if t]
    now = time.time()

    with _LOCK:
        _KNOWN.update(req)
        missing = [t for t in req
                   if t not in _STORE or now - _STORE[t][1] > max_age_s]
        if missing and (now - _LAST_HTTP) >= _MIN_INTERVAL_S:
            fetched = _http_fetch(sorted(_KNOWN), auth)
            _LAST_HTTP = time.time()
            if fetched:
                _LAST_SUCCESS = _LAST_HTTP
            for t, rowdata in fetched.items():
                _STORE[t] = (rowdata, _LAST_HTTP)
        return {t: _STORE[t][0] for t in req
                if t in _STORE and time.time() - _STORE[t][1] <= max_age_s * 4}


def fetch_once(tickers):
    """
    Unconditional single fetch for batch jobs (prefetch_cloud). Bypasses the
    interval throttle (a batch job makes exactly one call anyway) but still
    returns {} on any failure. Does not touch the module store.
    """
    auth = get_auth_token()
    if not auth:
        print("  [INFO] FINVIZ_AUTH not set — skipping Finviz export "
              "(falling back to yfinance)")
        return {}
    return _http_fetch([t.upper() for t in tickers if t], auth)


def last_fetch_time():
    """
    Epoch seconds of the most recent SUCCESSFUL export fetch in this
    process, or None if no fetch has succeeded yet. Used by the dashboard
    freshness stamp to show live-quote freshness instead of the (older)
    Supabase prefetch timestamp.
    """
    return _LAST_SUCCESS or None
