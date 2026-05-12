"""
Martin Capital Partners — Kalshi Fed Rate Decision Probabilities
data/kalshi_fed.py

Pulls market-implied probabilities of Fed rate cuts from Kalshi's public
prediction-market API. Used by the Macro tab to replace the formerly
hardcoded Fed Meeting Calendar.

Approach
========
For each upcoming FOMC meeting, Kalshi runs ~11-18 binary markets at
different rate-strikes ("Will the upper bound be above X% following the
meeting?"). To get "probability of at least one cut by meeting X":
  1. Look up the current Fed Funds upper bound from FRED (series DFEDTARU).
  2. For each meeting, find the Kalshi market whose strike is exactly 25bp
     below the current upper bound.
  3. P(cut by then) = 1 - YES price at that strike.
  4. Render that as the headline probability for the meeting.

If the exact 25bp-below strike isn't available for a given meeting (rare,
but happens for further-out meetings), fall back to the nearest available
strike that's below the current rate and note the actual strike used so
the caption stays honest.

Edge cases handled
==================
- Kalshi unreachable: returns empty list, widget falls back to placeholder.
- FRED unreachable: returns empty list (we need the current rate for math).
- Rate-limited (HTTP 429): caught per-event, that event is skipped, the
  rest of the calendar still renders.
- All upcoming events have zero volume: still returned, widget can show
  them with a "low liquidity" flag.
"""

import time
import json
from datetime import datetime, timezone
from urllib import request, parse, error

import streamlit as st

# ── Endpoints ──────────────────────────────────────────────────────────────
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = "984881b404269d00afe946250729a01a"

# Series DFEDTARU — Federal Funds Target Range, Upper Limit. Updates whenever
# the FOMC announces a decision, so it's the right baseline for our math.
FRED_UPPER_BOUND_SERIES = "DFEDTARU"


# ── Low-level HTTP helper ──────────────────────────────────────────────────
def _http_get_json(url, timeout=15):
    """GET → JSON. Returns (status_code, body_dict_or_None, error_str_or_None)."""
    req = request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "MartinCapital-Dashboard/1.0",
    })
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body), None
    except error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, None, f"HTTP {e.code}: {body[:200]}"
    except (error.URLError, json.JSONDecodeError, Exception) as e:
        return None, None, f"{type(e).__name__}: {e}"


# ── FRED: current upper bound of the target range ─────────────────────────
def _get_current_upper_bound():
    """
    Returns the current Fed Funds Target Range upper bound as a float
    (e.g. 4.00 means 4.00%). Returns None if FRED is unreachable.
    """
    qs = parse.urlencode({
        "series_id": FRED_UPPER_BOUND_SERIES,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,
    })
    status, body, err = _http_get_json(f"{FRED_BASE}?{qs}")
    if status != 200 or not body:
        return None
    obs = body.get("observations", [])
    for o in obs:
        v = o.get("value", ".")
        if v != ".":
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


# ── Kalshi: discover FED events ────────────────────────────────────────────
def _list_fed_events():
    """
    List all upcoming Kalshi events under the KXFED series, sorted by
    closest-to-today first. Returns list of dicts with event_ticker,
    title, close-date string.
    """
    qs = parse.urlencode({
        "series_ticker": "KXFED",
        "status": "open",
        "limit": 200,
    })
    status, body, err = _http_get_json(f"{KALSHI_BASE}/events?{qs}")
    if status != 200 or not body:
        return []

    events = body.get("events", []) if isinstance(body, dict) else []
    # Each event ticker is KXFED-YYMMM (e.g. KXFED-26JUN). Parse the date
    # for sorting. If parsing fails, drop the event (better than crashing).
    parsed = []
    for ev in events:
        et = ev.get("event_ticker", "")
        if not et.startswith("KXFED-"):
            continue
        month_tag = et.split("-", 1)[1] if "-" in et else ""
        try:
            # YYMMM → e.g. "26JUN" → year 2026, month June
            year = 2000 + int(month_tag[:2])
            month_str = month_tag[2:]
            month_num = {
                "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
                "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
                "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
            }.get(month_str.upper())
            if month_num is None:
                continue
            sort_key = (year, month_num)
        except (ValueError, IndexError):
            continue

        parsed.append({
            "event_ticker": et,
            "title": ev.get("title", ""),
            "year": year,
            "month_num": month_num,
            "sort_key": sort_key,
        })

    parsed.sort(key=lambda x: x["sort_key"])

    # Drop events in the past (a meeting that's already happened — Kalshi
    # sometimes leaves them in "open" status briefly after settlement).
    today = datetime.now(timezone.utc).date()
    today_tuple = (today.year, today.month)
    return [e for e in parsed if e["sort_key"] >= today_tuple]


# ── Kalshi: markets under a single event ───────────────────────────────────
def _list_markets_for_event(event_ticker):
    """Fetch all markets under a single event. Returns list of dicts."""
    qs = parse.urlencode({"event_ticker": event_ticker, "limit": 100})
    status, body, err = _http_get_json(f"{KALSHI_BASE}/markets?{qs}")
    if status != 200 or not body:
        return []
    return body.get("markets", []) if isinstance(body, dict) else []


# ── Price parsing ──────────────────────────────────────────────────────────
def _parse_dollar_price(val):
    """
    Kalshi's modern API returns prices as string-formatted dollars
    ("0.4200" = $0.42 = 42% YES probability). Returns float in 0-1 range,
    or None if the value can't be parsed.
    """
    if val is None or val == "":
        return None
    try:
        f = float(val)
        if 0 <= f <= 1.0:
            return f
        # Legacy integer-cents format (0-100). Convert if it looks like one.
        if 0 < f <= 100:
            return f / 100
    except (ValueError, TypeError):
        pass
    return None


# ── Pick the best market for "P(cut by this meeting)" ──────────────────────
def _pick_strike_market(markets, current_upper_bound):
    """
    From the markets under an event, find the one whose strike is exactly
    25bp below the current upper bound. If unavailable, fall back to the
    nearest-lower strike. Returns (market_dict, strike_used_float) or
    (None, None) if no usable market exists.
    """
    # Each market has a floor_strike or strike_type field — but the most
    # reliable cross-version field is the ticker suffix "T<rate>". Parse it.
    candidates = []
    for m in markets:
        if m.get("strike_type") != "greater":
            # Some markets are "less"-type or "between"-type. Skip non-"greater"
            # to keep the YES = "above strike" math consistent.
            continue
        ticker = m.get("ticker", "")
        # Ticker pattern: KXFED-YYMMM-T<strike> e.g. "KXFED-26JUN-T3.75"
        if "-T" not in ticker:
            continue
        try:
            strike_str = ticker.rsplit("-T", 1)[1]
            strike = float(strike_str)
        except (ValueError, IndexError):
            # Fall back to floor_strike if ticker parse fails
            fs = m.get("floor_strike")
            try:
                strike = float(fs) if fs is not None else None
            except (ValueError, TypeError):
                strike = None
            if strike is None:
                continue
        candidates.append((strike, m))

    if not candidates:
        return None, None

    # Target strike = 25bp below current upper bound
    target = round(current_upper_bound - 0.25, 4)

    # First try exact match
    for strike, m in candidates:
        if abs(strike - target) < 1e-6:
            return m, strike

    # Fall back: nearest strike below the current rate (i.e. a strike at or
    # below current_upper_bound - 0.25 means "rate was at most 25bp lower").
    # Among strikes that are <= target, pick the highest (closest to target).
    below = [(s, m) for s, m in candidates if s <= target + 1e-6]
    if below:
        below.sort(key=lambda x: -x[0])  # highest strike at-or-below target
        return below[0][1], below[0][0]

    return None, None


# ── Public API: get the calendar ──────────────────────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def get_fed_cut_probabilities(max_events: int = 6, _v: int = 1):
    """
    Returns a list of dicts ready for rendering, sorted by meeting date:
      {
        "meeting_label":      "Jun 17, 2026",
        "year":               2026,
        "month_num":          6,
        "prob_cut_pct":       42.0,   # probability of at least one cut by then, %
        "strike_used":        3.75,   # the Kalshi strike we read
        "exact_strike":       True,   # False if we used a fallback
        "current_upper_bound": 4.00,  # what we compared against
        "ticker":             "KXFED-26JUN-T3.75",
        "volume_24h":         97.0,   # informational
        "source_url":         "https://kalshi.com/markets/kxfed/...",
      }

    Empty list means data unavailable — caller should render a fallback.
    Cached 15 minutes.
    """
    upper = _get_current_upper_bound()
    if upper is None:
        return []

    events = _list_fed_events()
    if not events:
        return []

    results = []
    for ev in events[:max_events]:
        # Polite spacing between event calls to avoid Kalshi's rate limiter
        # (we got 429s on the diagnostic when running back-to-back).
        time.sleep(0.25)

        markets = _list_markets_for_event(ev["event_ticker"])
        if not markets:
            continue

        market, strike_used = _pick_strike_market(markets, upper)
        if market is None or strike_used is None:
            continue

        yes_price = _parse_dollar_price(market.get("last_price_dollars"))
        if yes_price is None:
            # Fall back to mid of bid/ask
            bid = _parse_dollar_price(market.get("yes_bid_dollars"))
            ask = _parse_dollar_price(market.get("yes_ask_dollars"))
            if bid is not None and ask is not None:
                yes_price = (bid + ask) / 2

        if yes_price is None:
            continue

        # P(above strike) = yes_price. P(at-or-below strike) = 1 - yes_price.
        # If strike = upper - 0.25, "at-or-below" means "rate cut by at least
        # 25bp by this meeting" — i.e., probability of a cut by then.
        prob_cut = max(0.0, min(1.0, 1.0 - yes_price))

        # Volume parsing — Kalshi uses both `volume_fp` (string) and `volume`
        try:
            v24 = float(market.get("volume_24h_fp", 0) or 0)
        except (ValueError, TypeError):
            v24 = 0.0

        # Build a human-readable meeting label. We don't know the exact
        # meeting day-of-month from event_ticker alone, but the market's
        # close_time gives it (close = meeting day for FOMC events).
        close_iso = market.get("close_time", "") or ""
        meeting_label = ""
        if close_iso:
            try:
                close_dt = datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
                meeting_label = close_dt.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                meeting_label = f"{ev['year']}-{ev['month_num']:02d}"
        else:
            meeting_label = f"{ev['year']}-{ev['month_num']:02d}"

        results.append({
            "meeting_label":       meeting_label,
            "year":                ev["year"],
            "month_num":           ev["month_num"],
            "prob_cut_pct":        round(prob_cut * 100, 1),
            "strike_used":         strike_used,
            "exact_strike":        abs(strike_used - (upper - 0.25)) < 1e-6,
            "current_upper_bound": upper,
            "ticker":              market.get("ticker", ""),
            "volume_24h":          v24,
            "source_url":          f"https://kalshi.com/markets/kxfed/fed-funds-target-rate?selection={market.get('ticker', '')}",
        })

    return results
