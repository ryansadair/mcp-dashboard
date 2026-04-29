"""
Martin Capital Partners — Dividend Distress Scorecard Loader
data/scorecard_loader.py

Loads the JSON payload produced by the standalone Dividend Distress
Scorecard pipeline (run_scorecard.py in the Dividend Monitoring System
project) and surfaces it to the Streamlit Safety & Growth sub-tab.

Source of truth: data/dividend_scorecard_latest.json — written by
run_scorecard.py each time the scorecard is generated, then committed
to git so Streamlit Cloud picks it up.

The loader is deliberately defensive: if the file is missing, malformed,
or stale, the tab degrades gracefully rather than blowing up.
"""

import json
from datetime import datetime, date
from pathlib import Path

import streamlit as st


# Path resolution: walk up from this file to find the project root, then
# the data/ folder. Works whether Streamlit launches from pages/ or root.
_THIS_DIR = Path(__file__).parent
_DATA_DIR = _THIS_DIR if _THIS_DIR.name == "data" else _THIS_DIR / "data"
SCORECARD_PATH = _DATA_DIR / "dividend_scorecard_latest.json"

# Staleness threshold — warn the user if the scorecard hasn't been
# refreshed in this many days. Ryan runs scorecard ~monthly so 60 days
# leaves comfortable headroom before the warning fires.
STALE_DAYS = 60


@st.cache_data(ttl=3600, show_spinner=False)
def load_scorecard():
    """
    Load the latest scorecard payload from disk.

    Returns:
        dict — full payload (as written by run_scorecard.py / build_payload)
        None — file missing or malformed (caller should render an empty
               state and prompt the user to run scorecard)

    Cached 1 hour. Scorecard updates infrequently (~monthly) so a long
    cache is fine; on Streamlit Cloud this avoids re-reading the JSON
    on every interaction.
    """
    if not SCORECARD_PATH.exists():
        return None

    try:
        with open(SCORECARD_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Sanity check: required top-level keys
    required = ["as_of_date", "summary", "mcp_rows"]
    if not all(k in data for k in required):
        return None

    return data


def days_since(as_of_str):
    """
    Compute days since the scorecard was generated. Returns None if the
    date string can't be parsed.
    """
    if not as_of_str:
        return None
    try:
        as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
        return (date.today() - as_of).days
    except (ValueError, TypeError):
        return None


def is_stale(as_of_str):
    """True if scorecard is older than STALE_DAYS, or date can't be parsed."""
    d = days_since(as_of_str)
    return d is None or d > STALE_DAYS


def format_as_of(as_of_str):
    """Format the as_of date for display (e.g., 'April 24, 2026')."""
    if not as_of_str:
        return "Unknown"
    try:
        d = datetime.strptime(as_of_str, "%Y-%m-%d").date()
        return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else as_of_str
    except (ValueError, TypeError):
        return as_of_str


def get_mcp_detail_map(scorecard):
    """
    Build a lookup: {ticker: detail_dict} from scorecard['mcp_detail'].
    Tickers are normalized via _normalize_ticker so 'NYS:KOF' and 'KOF'
    both resolve. Returns empty dict if scorecard is None.
    """
    if not scorecard:
        return {}
    out = {}
    for d in scorecard.get("mcp_detail", []):
        t = _normalize_ticker(d.get("Ticker", ""))
        if t:
            out[t] = d
    return out


def _normalize_ticker(t):
    """
    Strip exchange prefix from scorecard ticker. The scorecard uses
    PitchBook-style 'NYS:KOF' notation while Tamarac uses bare 'KOF'.
    This converges them so cross-references work.
    """
    if not t:
        return ""
    return str(t).split(":")[-1].strip().upper()


# ── Bucket constants ──────────────────────────────────────────────────────
# Match the scorecard's risk bucket vocabulary exactly. Order = severity
# (worst to best); used for sorting and for the colored counter cards at
# the top of the Safety & Growth tab.
BUCKET_ORDER = ["Critical", "Red", "Yellow", "Green", "Strong"]

BUCKET_COLORS = {
    "Critical": "#7a1f1f",   # deep red — multiple severe pillars, urgent
    "Red":      "#c45454",   # red — significant stress
    "Yellow":   "#C9A84C",   # MCP gold — emerging stress / watchlist
    "Green":    "#8cc47a",   # light green — neutral to mildly healthy
    "Strong":   "#569542",   # MCP green — well-covered, healthy
}

# Insufficient Data is a fifth state from scoring.py for tickers with
# fewer than 3 pillars scored. Falls outside the 5-bucket spectrum.
BUCKET_COLORS["Insufficient Data"] = "rgba(255,255,255,0.25)"
