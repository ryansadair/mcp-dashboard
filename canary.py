"""
Martin Capital Partners — Daily Data Canary
canary.py

Answers one question every market morning: "is the data on the dashboard
trustworthy right now?" — without a human cross-checking Finviz.

Every check below corresponds to a failure mode this system has ACTUALLY
exhibited:

  1. SUPABASE FRESHNESS   — cron-job.org / workflow stops, prices go stale
  2. FINVIZ COVERAGE      — token revoked/banned, export format change
                            (Finviz is the load-bearing price source)
  3. FROZEN VENDOR FEEDS  — Yahoo ^RLG froze at a 2-day-old close and the
                            Markets tab showed a stale -1.78% as "today"
  4. QUOTE SANITY         — corrupted bars / bad prev_close (the fake -75%
                            IWF bar; the fast_info prev_close bug)
  5. EARNINGS PARSE       — the alerts earnings calendar died silently for
                            months when yfinance changed .calendar's shape
  6. NOTION REACHABLE     — warbook ADR fields, CLD commentary, ratings all
                            ride the Notion API + token
  7. TAMARAC FRESHNESS    — Task Scheduler on the office machine can stop
                            committing holdings without anyone noticing

Behavior:
  - Any FAIL   → exit 1 → red workflow run → GitHub emails the repo owner
  - Warnings   → recorded, run stays green
  - Either way → one row upserted to Supabase `canary_status`, which the
                 dashboard header reads to show a systems indicator, so a
                 failed (or missing!) canary is visible in-app too.

Run: python canary.py            (needs SUPABASE_URL/KEY, FINVIZ_AUTH env;
                                  NOTION_TOKEN optional but recommended)
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
FINVIZ_AUTH = os.environ.get("FINVIZ_AUTH", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

failures = []   # red run + email
warnings = []   # recorded, still green
metrics = {}    # numbers worth trending


def _sb_get(table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=SB_HEADERS,
                     params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ══════════════════════════════════════════════════════════════════════════
# 1. Supabase prices freshness — is the prefetch pipeline alive?
# ══════════════════════════════════════════════════════════════════════════
def check_supabase_freshness():
    try:
        rows = _sb_get("prices", {"select": "fetched_at",
                                  "order": "fetched_at.desc", "limit": "1"})
        if not rows:
            failures.append("Supabase: prices table is EMPTY")
            return
        ts = rows[0]["fetched_at"].replace("Z", "+00:00")
        age_min = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(ts)).total_seconds() / 60
        metrics["prices_age_min"] = round(age_min, 1)
        # Prefetch runs every 15 min during market hours; the canary runs
        # 20 min after the open, so anything > 45 min means the pipeline
        # (cron-job.org trigger, workflow, or upsert) has stopped.
        if age_min > 45:
            failures.append(
                f"Supabase: newest prices row is {age_min:.0f} min old "
                f"(prefetch pipeline appears stopped)")
    except Exception as e:
        failures.append(f"Supabase freshness check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# 2. Finviz export coverage — is the load-bearing price source healthy?
# ══════════════════════════════════════════════════════════════════════════
def check_finviz_coverage():
    if not FINVIZ_AUTH:
        failures.append("Finviz: FINVIZ_AUTH secret not provided to canary")
        return
    try:
        tick_rows = _sb_get("prices", {"select": "ticker"})
        universe = sorted({r["ticker"] for r in tick_rows
                           if r.get("ticker") and "=" not in r["ticker"]
                           and not r["ticker"].startswith("^")
                           and "-USD" not in r["ticker"]})
        metrics["universe_size"] = len(universe)

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from data.finviz_export import fetch_once
        snap = fetch_once(universe)
        cov = len(snap)
        priced = sum(1 for d in snap.values()
                     if d.get("price") and d.get("prev_close"))
        metrics["finviz_coverage"] = cov
        metrics["finviz_priced"] = priced

        # Known permanent yfinance-fallback names (OTC ADRs) mean coverage
        # never hits 100%. Healthy baseline is ~125/128.
        floor_fail = int(len(universe) * 0.85)
        floor_warn = int(len(universe) * 0.93)
        if cov < floor_fail:
            failures.append(
                f"Finviz: export covered only {cov}/{len(universe)} tickers "
                f"(token dead? format change? ban?)")
        elif cov < floor_warn:
            warnings.append(
                f"Finviz: coverage {cov}/{len(universe)} below normal")
        if cov and priced < cov * 0.95:
            failures.append(
                f"Finviz: only {priced}/{cov} covered tickers carry "
                f"price+prev_close (column mapping may have shifted)")
    except Exception as e:
        failures.append(f"Finviz coverage check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# 3. Frozen vendor feeds — the ^RLG failure mode, checked at the source
# ══════════════════════════════════════════════════════════════════════════
# Critical Markets-tab symbols. If Yahoo freezes or kills any of these, the
# staleness guard blanks the row in-app; this check makes sure a human hears
# about it the same morning instead of wondering why a row went blank.
CRITICAL_MARKET_SYMBOLS = [
    "^GSPC", "^NDX", "^DJI", "^RUT", "^SP400", "^RUA", "^TNX",
    "SPYD", "SDY", "IWF", "IWD", "AGG",
    "GC=F", "CL=F", "JPY=X", "EURUSD=X", "DX-Y.NYB",
]


def check_frozen_feeds():
    try:
        import numpy as np
        import yfinance as yf
        data = yf.download(" ".join(CRITICAL_MARKET_SYMBOLS), period="10d",
                           interval="1d", group_by="ticker", progress=False,
                           threads=True)
        last_dates, missing = {}, []
        for t in CRITICAL_MARKET_SYMBOLS:
            try:
                df = data[t].dropna(subset=["Close"])
                if df.empty:
                    missing.append(t)
                else:
                    last_dates[t] = df.index[-1].date()
            except Exception:
                missing.append(t)
        if not last_dates:
            failures.append("Frozen-feed check: yfinance returned nothing "
                            "for the entire critical symbol set")
            return
        batch_max = max(last_dates.values())
        frozen = [f"{t} (last bar {d})" for t, d in last_dates.items()
                  if np.busday_count(d, batch_max) > 1]
        metrics["frozen_symbols"] = len(frozen)
        metrics["missing_symbols"] = len(missing)
        if frozen:
            failures.append("Frozen vendor feed(s): " + ", ".join(frozen))
        if missing:
            # Missing entirely (the ^RLG end-state). One symbol can be a
            # Yahoo hiccup; two or more is systemic.
            msg = "No data returned for: " + ", ".join(missing)
            (failures if len(missing) >= 2 else warnings).append(msg)
    except Exception as e:
        failures.append(f"Frozen-feed check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# 4. Quote sanity — corrupted bars / bad prev_close in the prices table
# ══════════════════════════════════════════════════════════════════════════
def check_quote_sanity():
    try:
        rows = _sb_get("prices",
                       {"select": "ticker,price,previous_close,change_1d_pct"})
        equities = [r for r in rows if r.get("ticker")
                    and "=" not in r["ticker"]
                    and not r["ticker"].startswith("^")]
        if not equities:
            failures.append("Quote sanity: no equity rows in prices table")
            return
        bad = []
        for r in equities:
            p, pc = r.get("price") or 0, r.get("previous_close") or 0
            if p <= 0 or pc <= 0:
                bad.append(f"{r['ticker']} (p={p}, pc={pc})")
            elif abs(p / pc - 1) > 0.35:
                bad.append(f"{r['ticker']} (move {((p/pc)-1)*100:+.0f}%)")
        metrics["quote_rows"] = len(equities)
        metrics["quote_bad"] = len(bad)
        if len(bad) > max(2, len(equities) * 0.03):
            failures.append(f"Quote sanity: {len(bad)} bad rows — "
                            + ", ".join(bad[:6]))
        elif bad:
            warnings.append("Quote sanity: " + ", ".join(bad[:6]))
    except Exception as e:
        failures.append(f"Quote sanity check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# 5. Earnings parse — the alerts-tab silent-death class
# ══════════════════════════════════════════════════════════════════════════
def check_earnings_parse():
    try:
        import yfinance as yf
        test = ["MSFT", "JNJ", "CVX", "TXN"]
        parsed = 0
        for t in test:
            try:
                cal = yf.Ticker(t).calendar
                if isinstance(cal, dict) and cal.get("Earnings Date"):
                    parsed += 1
                elif cal is not None and hasattr(cal, "empty") and not cal.empty:
                    parsed += 1
            except Exception:
                pass
        metrics["earnings_parsed"] = parsed
        if parsed == 0:
            failures.append(
                "Earnings: 0/4 test tickers parsed — yfinance .calendar "
                "shape likely changed again (alerts tab affected)")
        elif parsed < 2:
            warnings.append(f"Earnings: only {parsed}/4 test tickers parsed")
    except Exception as e:
        warnings.append(f"Earnings parse check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# 6. Notion reachable — warbook ADR fields, ratings, CLD commentary
# ══════════════════════════════════════════════════════════════════════════
NOTION_DB_ID = "29cff1792e3c461d978af87ca1bea797"


def check_notion():
    if not NOTION_TOKEN:
        warnings.append("Notion: NOTION_TOKEN not configured in canary "
                        "(add it as a GitHub secret to enable this check)")
        return
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                     "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            json={"page_size": 100}, timeout=20)
        r.raise_for_status()
        n = len(r.json().get("results", []))
        metrics["notion_rows"] = n
        if n < 40:
            failures.append(f"Notion: Master Holdings query returned only "
                            f"{n} rows (expected ~53)")
    except Exception as e:
        failures.append(f"Notion check errored: {e} "
                        "(token expired? integration removed?)")


# ══════════════════════════════════════════════════════════════════════════
# 7. Tamarac freshness — is the office machine still committing holdings?
# ══════════════════════════════════════════════════════════════════════════
def check_tamarac_freshness():
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--",
             "data/Tamarac_Holdings.xlsx"],
            capture_output=True, text=True, timeout=15,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
        ts = out.stdout.strip()
        if not ts:
            warnings.append("Tamarac: could not read last commit time "
                            "(shallow checkout? file moved?)")
            return
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromtimestamp(int(ts), tz=timezone.utc)
                 ).total_seconds() / 3600
        metrics["tamarac_age_hours"] = round(age_h, 1)
        # The Task Scheduler job commits each market morning. Monday
        # mornings the newest commit is Friday's (~72h). Beyond ~76h the
        # office-machine pipeline has missed at least one market day.
        if age_h > 76:
            failures.append(f"Tamarac: holdings file last committed "
                            f"{age_h/24:.1f} days ago — office-machine "
                            f"pipeline appears stopped")
        elif age_h > 30:
            warnings.append(f"Tamarac: holdings file {age_h:.0f}h old "
                            f"(no commit yet today?)")
    except Exception as e:
        warnings.append(f"Tamarac freshness check errored: {e}")


# ══════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════
def write_status(status):
    """Upsert today's row so the dashboard header can display it."""
    try:
        payload = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "failures": "\n".join(failures) or None,
            "warnings": "\n".join(warnings) or None,
            "metrics": metrics,
        }
        r = requests.post(f"{SUPABASE_URL}/rest/v1/canary_status",
                          headers=SB_HEADERS, json=payload, timeout=20)
        r.raise_for_status()
        print(f"  status row written: {status}")
    except Exception as e:
        print(f"  [WARN] could not write canary_status row: {e}")


def main():
    print(f"MCP Data Canary — {datetime.now(timezone.utc).isoformat()}")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("FATAL: SUPABASE_URL / SUPABASE_KEY not set")
        sys.exit(1)

    for name, fn in [
        ("Supabase freshness", check_supabase_freshness),
        ("Finviz coverage", check_finviz_coverage),
        ("Frozen vendor feeds", check_frozen_feeds),
        ("Quote sanity", check_quote_sanity),
        ("Earnings parse", check_earnings_parse),
        ("Notion", check_notion),
        ("Tamarac freshness", check_tamarac_freshness),
    ]:
        print(f"• {name} ...")
        fn()

    print()
    print(f"metrics:  {json.dumps(metrics)}")
    for w in warnings:
        print(f"WARN: {w}")
    for f in failures:
        print(f"FAIL: {f}")

    status = "fail" if failures else ("warn" if warnings else "pass")
    write_status(status)

    if failures:
        print(f"\nCANARY RED — {len(failures)} failure(s). "
              "This run will show red in Actions and email the repo owner.")
        sys.exit(1)
    print(f"\nCANARY GREEN{' (with warnings)' if warnings else ''}.")


if __name__ == "__main__":
    main()
