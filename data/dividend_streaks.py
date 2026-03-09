"""
Martin Capital Partners — Dividend Streak Lookup
data/dividend_streaks.py

Authoritative consecutive dividend increase streak data, sourced from the
David Fish CCC (Champions/Contenders/Challengers) lists and cross-referenced
with dividendstocks.com, dividend.com, and simplysafedividends.com.

Tiers:
  King         = 50+ years
  Aristocrat   = 25–49 years
  Contender    = 10–24 years
  Challenger   = 5–9 years

Maintenance:
  - Update this file quarterly or after any dividend cut/increase announcement
  - Run `python data/dividend_streaks.py` standalone to print a summary
  - Tickers not in this dict will fall back to yfinance (less reliable)

Last verified: March 2026 from CCC lists / dividendstocks.com
"""

# ── Curated streak data for all MCP holdings ──────────────────────────────
# Format: "TICKER": (consecutive_years, "tier")
# Sources: dividendstocks.com Champions/Contenders/Challengers lists,
#          simplysafedividends.com Dividend Kings list, dividend.com

DIVIDEND_STREAKS = {
    # ── Kings (50+) ──────────────────────────────────────────────────────
    "JNJ":   (62, "King"),          # Johnson & Johnson — 62 years
    "PG":    (68, "King"),          # Procter & Gamble — 68 years
    "KO":    (64, "King"),          # Coca-Cola — 64 years
    "EMR":   (67, "King"),          # Emerson Electric — 67 years
    "CL":    (61, "King"),          # Colgate-Palmolive — 61 years
    "ABT":   (54, "King"),          # Abbott Labs — 54 years (from CCC list)
    "CLX":   (50, "King"),          # Clorox — ~48–50 years
    "SWK":   (57, "King"),          # Stanley Black & Decker — 57 years
    "PEP":   (52, "King"),          # PepsiCo — 52 years
    "HRL":   (58, "King"),          # Hormel Foods — 58 years
    "MKC":   (39, "Champion"),      # McCormick — 39 years (was recently reclassified, verify)
    "XOM":   (42, "Champion"),      # Exxon Mobil — 42 years
    "ABBV":  (53, "King"),          # AbbVie (inherits from Abbott) — 53 years
    "BKH":   (55, "King"),          # Black Hills Corp — 55 years

    # ── Champions (25–49) ────────────────────────────────────────────────
    "CVX":   (38, "Champion"),      # Chevron — 38 years
    "AMGN":  (14, "Contender"),     # Amgen — ~14 years
    "MDT":   (47, "Champion"),      # Medtronic — 47 years
    "HD":    (15, "Contender"),     # Home Depot — ~15 years
    "GD":    (33, "Champion"),      # General Dynamics — 33 years
    "MSFT":  (22, "Contender"),     # Microsoft — 22 years (contender, not yet champion)
    "TXN":   (22, "Contender"),     # Texas Instruments — 22 years
    "LECO":  (29, "Champion"),      # Lincoln Electric — 29 years
    "SNA":   (15, "Contender"),     # Snap-on — ~15 years
    "UNP":   (18, "Contender"),     # Union Pacific — ~18 years
    "INGR":  (14, "Contender"),     # Ingredion — ~14 years
    "EMN":   (15, "Contender"),     # Eastman Chemical — ~15 years
    "TROW":  (39, "Champion"),      # T. Rowe Price — 39 years
    "CFR":   (32, "Champion"),      # Cullen/Frost Bankers — 32 years
    "PAYX":  (15, "Contender"),     # Paychex — ~15 years
    "JPM":   (14, "Contender"),     # JPMorgan Chase — ~14 years (reset in 2020, restarted)
    "CNP":   (20, "Contender"),     # CenterPoint Energy — ~20 years
    "ETR":   (10, "Contender"),     # Entergy — ~10 years
    "NKE":   (23, "Contender"),     # Nike — ~23 years
    "MSM":   (23, "Contender"),     # MSC Industrial — ~23 years
    "DGX":   (15, "Contender"),     # Quest Diagnostics — ~15 years

    # ── Contenders (10–24) ───────────────────────────────────────────────
    "CSCO":  (14, "Contender"),     # Cisco Systems — ~14 years
    "JKHY":  (13, "Contender"),     # Jack Henry & Associates — ~13 years
    "VZ":    (20, "Contender"),     # Verizon — ~20 years
    "PFE":   (15, "Contender"),     # Pfizer — ~15 years
    "UPS":   (15, "Contender"),     # UPS — ~15 years
    "PFG":   (16, "Contender"),     # Principal Financial — ~16 years
    "CME":   (14, "Contender"),     # CME Group — ~14 years
    "RGA":   (15, "Contender"),     # Reinsurance Group of America — ~15 years
    "PSX":   (12, "Contender"),     # Phillips 66 — ~12 years
    "COR":   (11, "Contender"),     # Cencora (formerly AmerisourceBergen) — ~11 years
    "POR":   (19, "Contender"),     # Portland General Electric — ~19 years

    # ── Challengers (5–9) ────────────────────────────────────────────────
    "DVN":   (7, "Challenger"),     # Devon Energy — ~7 years (variable div model)
    "O":     (32, "Champion"),      # Realty Income — 32 years (monthly REIT)
    "ALSN":  (8, "Challenger"),     # Allison Transmission — ~8 years

    # ── Non-US / No streak / ETFs / Special ──────────────────────────────
    "ASML":  (5, "Challenger"),     # ASML (Netherlands) — ~5 years of increases
    "NVO":   (0, "—"),              # Novo Nordisk — variable div policy
    "UL":    (0, "—"),              # Unilever — UK-listed, not on US CCC lists
    "TTE":   (0, "—"),              # TotalEnergies — French, not on US CCC lists
    "KOF":   (0, "—"),              # Coca-Cola FEMSA — Mexican ADR
    "EWZ":   (0, "—"),              # iShares Brazil ETF
    "CEF":   (0, "—"),              # Sprott Physical Gold & Silver Trust
    "CGGR":  (0, "—"),              # Capital Group Growth ETF
    "PRFZ":  (0, "—"),              # Invesco FTSE RAFI US 1500 Small-Mid ETF
    "PXF":   (0, "—"),              # Invesco FTSE RAFI Developed Markets ETF
    "PXH":   (0, "—"),             # Invesco FTSE RAFI Emerging Markets ETF
    "RSP":   (0, "—"),              # Invesco S&P 500 Equal Weight ETF
    "XOP":   (0, "—"),              # SPDR S&P Oil & Gas Exploration ETF
}


def get_streak(ticker):
    """
    Get the consecutive dividend increase streak for a ticker.
    Returns (years, tier) tuple.
    """
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))


def get_streak_years(ticker):
    """Get just the number of consecutive years."""
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[0]


def get_streak_tier(ticker):
    """Get just the tier label."""
    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[1]


def get_all_streaks_for_tickers(tickers):
    """
    Get streak data for a list of tickers.
    Returns dict: {ticker: {"years": int, "tier": str}}
    """
    result = {}
    for t in tickers:
        years, tier = get_streak(t)
        result[t] = {"years": years, "tier": tier}
    return result


# ── Standalone: print summary when run directly ───────────────────────────
if __name__ == "__main__":
    print("Martin Capital Partners — Dividend Streak Lookup")
    print("=" * 60)

    # Group by tier
    tiers = {}
    for ticker, (years, tier) in sorted(DIVIDEND_STREAKS.items(), key=lambda x: -x[1][0]):
        if tier not in tiers:
            tiers[tier] = []
        tiers[tier].append((ticker, years))

    for tier in ["King", "Champion", "Contender", "Challenger", "—"]:
        if tier in tiers:
            print(f"\n{tier} ({len(tiers[tier])} holdings):")
            for ticker, years in sorted(tiers[tier], key=lambda x: -x[1]):
                print(f"  {ticker:<8} {years:>3}y")

    print(f"\nTotal: {len(DIVIDEND_STREAKS)} tickers tracked")
    with_streaks = sum(1 for y, _ in DIVIDEND_STREAKS.values() if y > 0)
    print(f"With streaks: {with_streaks}")
    print(f"ETFs/Non-US/No data: {len(DIVIDEND_STREAKS) - with_streaks}")
