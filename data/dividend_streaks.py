"""
Martin Capital Partners -- Dividend Streak Lookup
data/dividend_streaks.py

Reads consecutive dividend increase years from the David Fish / IREIT
CCC spreadsheet (Fish_*.xlsx or CCC_*.xlsx).

Ryan downloads this monthly from https://www.ireitinvestor.com/dividend-champions/
and drops it in the data/ folder. The parser finds the newest Fish*.xlsx file
and reads the "All CCC" sheet, matching tickers by column B (Symbol) and
extracting years from column E (Yrs).

ETFs and non-US tickers not in the CCC list get 0.
"""

import os
import glob
import streamlit as st
import pandas as pd

# -- Paths to search for the Fish CCC file --
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# Glob patterns to find the Fish file (newest wins)
FISH_PATTERNS = [
    os.path.join(_THIS_DIR, "Fish_*.xlsx"),
    os.path.join(_THIS_DIR, "CCC_*.xlsx"),
    os.path.join(_THIS_DIR, "fish_*.xlsx"),
    os.path.join(_PROJECT_ROOT, "data", "Fish_*.xlsx"),
    os.path.join(_PROJECT_ROOT, "data", "CCC_*.xlsx"),
    "data/Fish_*.xlsx",
    "data/CCC_*.xlsx",
]

# Also check for the manually-curated fallback
MANUAL_PATHS = [
    os.path.join(_THIS_DIR, "Dividend_Streaks.xlsx"),
    os.path.join(_PROJECT_ROOT, "data", "Dividend_Streaks.xlsx"),
    "data/Dividend_Streaks.xlsx",
]


def _find_newest_fish():
    """Find the newest Fish/CCC xlsx file by modification time."""
    candidates = []
    for pattern in FISH_PATTERNS:
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return None
    # Sort by modification time, newest first
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def _classify_tier(years):
    """Classify consecutive years into CCC tier."""
    if years >= 50:
        return "King"
    elif years >= 25:
        return "Champion"
    elif years >= 10:
        return "Contender"
    elif years >= 5:
        return "Challenger"
    return "--"


@st.cache_data(ttl=300, show_spinner=False)
def _load_streaks():
    """
    Load streak data. Priority:
    1. Fish/CCC spreadsheet (All CCC sheet, col B=Symbol, col E=Yrs)
    2. Manual Dividend_Streaks.xlsx fallback
    """
    result = {}

    # -- 1. Try Fish CCC file --
    fish_path = _find_newest_fish()
    if fish_path:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(fish_path, read_only=True, data_only=True)

            # Try "All CCC" sheet first, then Champions/Contenders/Challengers
            sheets_to_try = ["All CCC", "Champions", "Contenders", "Challengers"]
            for sheet_name in sheets_to_try:
                if sheet_name not in wb.sheetnames:
                    continue
                ws = wb[sheet_name]
                rows = list(ws.iter_rows(values_only=True))

                # Find the header row (look for "Symbol" in column B area)
                header_row = None
                for i, row in enumerate(rows[:10]):
                    if row and len(row) > 4:
                        # Check if this row has "Symbol" or "Yrs" as headers
                        row_strs = [str(v).strip().lower() if v else "" for v in row[:10]]
                        if "symbol" in row_strs or "yrs" in row_strs:
                            header_row = i
                            break

                if header_row is None:
                    # Default: row 5 (0-indexed) based on known Fish format
                    header_row = 5

                # Data starts after header row
                for row in rows[header_row + 1:]:
                    if row and len(row) > 4:
                        symbol = str(row[1]).strip() if row[1] else ""
                        yrs_raw = row[4]
                        if symbol and yrs_raw is not None:
                            try:
                                years = int(float(str(yrs_raw)))
                                if years > 0 and symbol not in result:
                                    result[symbol.upper()] = (years, _classify_tier(years))
                            except (ValueError, TypeError):
                                pass

                # If we got data from "All CCC", no need to check individual sheets
                if sheet_name == "All CCC" and result:
                    break

            wb.close()

            if result:
                return result
        except Exception:
            pass

    # -- 2. Fallback: Dividend_Streaks.xlsx (manual file) --
    for p in MANUAL_PATHS:
        if os.path.exists(p):
            try:
                df = pd.read_excel(p, sheet_name="Dividend Streaks")
                df.columns = [c.strip() for c in df.columns]
                for _, row in df.iterrows():
                    ticker = str(row.get("Ticker", "")).strip().upper()
                    years = int(row.get("Consecutive Years", 0) or 0)
                    tier = str(row.get("Tier", "--")).strip()
                    if ticker and ticker not in result:
                        result[ticker] = (years, tier)
                return result
            except Exception:
                pass

    return result


def get_streak(ticker):
    """Get (years, tier) for a ticker. Returns (0, "--") if not found."""
    streaks = _load_streaks()
    return streaks.get(ticker.upper(), (0, "--"))


def get_streak_years(ticker):
    """Get just the number of consecutive years."""
    years, _ = get_streak(ticker)
    return years


def get_streak_tier(ticker):
    """Get just the tier label."""
    _, tier = get_streak(ticker)
    return tier


def get_all_streaks_for_tickers(tickers):
    """Get streak data for a list of tickers."""
    streaks = _load_streaks()
    return {
        t: {
            "years": streaks.get(t.upper(), (0, "--"))[0],
            "tier": streaks.get(t.upper(), (0, "--"))[1],
        }
        for t in tickers
    }