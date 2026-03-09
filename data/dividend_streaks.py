"""
Martin Capital Partners — Dividend Streak Lookup
data/dividend_streaks.py

AUTO-GENERATED — do not edit manually unless correcting data.
Last updated: March 09, 2026 at 01:42 PM
Source: dividendstocks.com CCC lists (Champions/Contenders/Challengers)
Total CCC tickers scraped: 537
"""

# ── Curated streak data for all MCP holdings ──────────────────────────────
# Format: "TICKER": (consecutive_years, "tier")

DIVIDEND_STREAKS = {
    # ── Kings (50+) ─────────────────────────────────────────────────
    "PG": (70, "King"),
    "JNJ": (64, "King"),
    "HRL": (60, "King"),
    "SWK": (58, "King"),
    "BKH": (55, "King"),
    "PEP": (54, "King"),
    # ── Champions (25-49) ───────────────────────────────────────────
    "MDT": (49, "Champion"),
    "CLX": (47, "Champion"),
    "XOM": (42, "Champion"),
    "TROW": (39, "Champion"),
    "CVX": (38, "Champion"),
    "MKC": (38, "Champion"),
    "JKHY": (35, "Champion"),
    "GD": (34, "Champion"),
    "CFR": (32, "Champion"),
    "LECO": (30, "Champion"),
    # ── Contenders (10-24) ──────────────────────────────────────────
    "MSFT": (23, "Contender"),
    "NKE": (22, "Contender"),
    "TXN": (21, "Contender"),
    "HD": (16, "Contender"),
    "PFE": (16, "Contender"),
    "RGA": (16, "Contender"),
    "COR": (15, "Contender"),
    "EMN": (15, "Contender"),
    "JPM": (15, "Contender"),
    "SNA": (15, "Contender"),
    "AMGN": (14, "Contender"),
    "DGX": (14, "Contender"),
    "INGR": (14, "Contender"),
    "PSX": (14, "Contender"),
    "CSCO": (13, "Contender"),
    "HII": (13, "Contender"),  # Huntington Ingalls — check if paying dividends
    "ETR": (10, "Contender"),
    # ── Challengers (5-9) ───────────────────────────────────────────
    "CNP": (5, "Challenger"),
    # ── Non-US / ETFs / No CCC Data ─────────────────────────────────
    "ALSN": (0, "—"),
    "ASML": (0, "—"),  # Netherlands — not on US CCC lists
    "CEF": (0, "—"),  # ETF — Sprott Physical Gold & Silver
    "CGGR": (0, "—"),  # ETF — Capital Group Growth
    "CME": (0, "—"),
    "DVN": (0, "—"),
    "EWZ": (0, "—"),  # ETF — iShares Brazil
    "KOF": (0, "—"),  # Mexico ADR — not on US CCC lists
    "MSM": (0, "—"),
    "NVO": (0, "—"),  # Denmark — not on US CCC lists
    "O": (0, "—"),
    "PAYX": (0, "—"),
    "PFG": (0, "—"),
    "POR": (0, "—"),
    "PRFZ": (0, "—"),  # ETF — Invesco FTSE RAFI US 1500
    "PXF": (0, "—"),  # ETF — Invesco FTSE RAFI Developed Markets
    "PXH": (0, "—"),  # ETF — Invesco FTSE RAFI Emerging Markets
    "RSP": (0, "—"),  # ETF — Invesco S&P 500 Equal Weight
    "TTE": (0, "—"),  # France — not on US CCC lists
    "UL": (0, "—"),  # UK — not on US CCC lists
    "UNP": (0, "—"),
    "UPS": (0, "—"),
    "VZ": (0, "—"),
    "XOP": (0, "—"),  # ETF — SPDR S&P Oil & Gas Exploration
}


def get_streak(ticker):
    """Get (years, tier) for a ticker."""
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))


def get_streak_years(ticker):
    """Get just the number of consecutive years."""
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[0]


def get_streak_tier(ticker):
    """Get just the tier label."""
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[1]


def get_all_streaks_for_tickers(tickers):
    """Get streak data for a list of tickers."""
    return {t: {'years': get_streak_years(t), 'tier': get_streak_tier(t)} for t in tickers}
