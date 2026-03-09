"""
Martin Capital Partners — Dividend Streak Auto-Updater
data/update_dividend_streaks.py

Scrapes dividendstocks.com Champions, Contenders, and Challengers lists
to get authoritative "Years of Dividend Growth" data for all MCP holdings.

Writes results to data/dividend_streaks.py as a Python dict — the same file
that dividends_tab.py reads from. Also writes a CSV backup.

Run: python data/update_dividend_streaks.py
Schedule: Windows Task Scheduler, weekly (Sunday night) or daily
Typical runtime: ~10 seconds (3 HTTP requests)

Falls back to existing data/dividend_streaks.py if scraping fails,
so the dashboard always has streak data available.
"""

import re
import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
THIS_DIR = Path(__file__).parent
STREAKS_PY = THIS_DIR / "dividend_streaks.py"
STREAKS_CSV = THIS_DIR / "cache" / "dividend_streaks.csv"

# dividendstocks.com CCC list URLs
CCC_URLS = {
    "champions":   "https://www.dividendstocks.com/tools/dividend-champions-list/",
    "contenders":  "https://www.dividendstocks.com/tools/dividend-contenders-list/",
    "challengers": "https://www.dividendstocks.com/tools/dividend-challengers-list/",
}

# Request headers to avoid bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# MCP tickers to look up (all holdings across all strategies)
# ETFs and non-US ADRs won't be in the CCC lists
MCP_TICKERS = {
    "ALSN", "AMGN", "ASML", "BKH", "CEF", "CFR", "CGGR", "CLX", "CME",
    "CNP", "COR", "CSCO", "CVX", "DGX", "DVN", "EMN", "ETR", "EWZ",
    "GD", "HD", "HII", "HRL", "INGR", "JKHY", "JNJ", "JPM", "KOF",
    "LECO", "MDT", "MKC", "MSFT", "MSM", "NKE", "NVO", "O", "PAYX",
    "PEP", "PFE", "PFG", "PG", "POR", "PRFZ", "PSX", "PXF", "PXH",
    "RGA", "RSP", "SNA", "SWK", "TROW", "TTE", "TXN", "UL", "UNP",
    "UPS", "VZ", "XOM", "XOP",
}

# ETFs and non-US tickers that won't appear in CCC lists
NON_CCC_TICKERS = {
    "ASML": "Netherlands — not on US CCC lists",
    "NVO":  "Denmark — not on US CCC lists",
    "UL":   "UK — not on US CCC lists",
    "TTE":  "France — not on US CCC lists",
    "KOF":  "Mexico ADR — not on US CCC lists",
    "EWZ":  "ETF — iShares Brazil",
    "CEF":  "ETF — Sprott Physical Gold & Silver",
    "CGGR": "ETF — Capital Group Growth",
    "PRFZ": "ETF — Invesco FTSE RAFI US 1500",
    "PXF":  "ETF — Invesco FTSE RAFI Developed Markets",
    "PXH":  "ETF — Invesco FTSE RAFI Emerging Markets",
    "RSP":  "ETF — Invesco S&P 500 Equal Weight",
    "XOP":  "ETF — SPDR S&P Oil & Gas Exploration",
    "HII":  "Huntington Ingalls — check if paying dividends",
}


def _classify_tier(years, list_name=""):
    """Classify a streak into CCC tier."""
    if years >= 50:
        return "King"
    elif years >= 25:
        return "Champion"
    elif years >= 10:
        return "Contender"
    elif years >= 5:
        return "Challenger"
    else:
        return "—"


def _scrape_ccc_list(url, list_name):
    """
    Scrape a dividendstocks.com CCC list page.
    Returns dict: {ticker: years_of_growth}
    """
    print(f"  Fetching {list_name}... ", end="", flush=True)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"FAILED ({e})")
        return {}

    # Parse the HTML table rows
    # Each row has: ticker symbol, company name, price, yield, payout, payout ratio,
    # 5Y growth, Years of Dividend Growth, ex-date
    # The ticker appears in links like: /stocks/NASDAQ/AMGN/ or /stocks/NYSE/JNJ/
    results = {}

    # Pattern: find ticker symbols from marketbeat links
    # Format in HTML: <a href="https://www.marketbeat.com/stocks/NYSE/JNJ/" ...>
    # followed later by the years value in a table cell
    ticker_pattern = re.compile(
        r'marketbeat\.com/stocks/(?:NYSE|NASDAQ)/([A-Z.]+)/'
    )

    # Find all table rows - split by row markers
    # The HTML has rows like: SRCE  1st Source | $67.33 | 2.38% | $1.60 | 24.96% | 34.51% | 38 | N/A
    # We need to extract ticker and "Years of Dividend Growth" (7th data column)

    # Simpler approach: find all tickers and their associated years
    # Each entry block contains the ticker link and then columns of data
    # Years of Dividend Growth is typically the 2nd-to-last or last numeric column

    # Split by table rows to process each entry
    rows = html.split('</tr>')

    for row in rows:
        # Find ticker
        ticker_match = ticker_pattern.search(row)
        if not ticker_match:
            continue
        ticker = ticker_match.group(1).replace(".", "-")  # BF.A -> BF-A if needed

        # Find "Years of Dividend Growth" — it's a standalone integer in a cell
        # Look for the pattern of cells with the years value
        # The years column contains just a number (no %, no $)
        cells = re.findall(r'<td[^>]*>\s*(\d+)\s*</td>', row)
        if cells:
            # The years value is typically the last pure integer cell
            # (other integers might be in other columns but years is the last one)
            years = int(cells[-1])
            if 1 <= years <= 100:  # sanity check
                results[ticker] = years

    print(f"found {len(results)} tickers")
    return results


def scrape_all_streaks():
    """Scrape all three CCC lists and merge results."""
    all_streaks = {}

    for list_name, url in CCC_URLS.items():
        streaks = _scrape_ccc_list(url, list_name)
        for ticker, years in streaks.items():
            # Keep the highest value if a ticker appears in multiple lists
            if ticker not in all_streaks or years > all_streaks[ticker]:
                all_streaks[ticker] = years

    return all_streaks


def _write_streaks_py(mcp_streaks, all_streaks):
    """Write the dividend_streaks.py file with updated data."""
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines = []
    lines.append('"""')
    lines.append("Martin Capital Partners — Dividend Streak Lookup")
    lines.append("data/dividend_streaks.py")
    lines.append("")
    lines.append("AUTO-GENERATED — do not edit manually unless correcting data.")
    lines.append(f"Last updated: {now}")
    lines.append(f"Source: dividendstocks.com CCC lists (Champions/Contenders/Challengers)")
    lines.append(f"Total CCC tickers scraped: {len(all_streaks)}")
    lines.append('"""')
    lines.append("")
    lines.append("# ── Curated streak data for all MCP holdings ──────────────────────────────")
    lines.append('# Format: "TICKER": (consecutive_years, "tier")')
    lines.append("")
    lines.append("DIVIDEND_STREAKS = {")

    # Sort: Kings first, then Champions, Contenders, Challengers, then no-data
    tier_order = {"King": 0, "Champion": 1, "Contender": 2, "Challenger": 3, "—": 4}
    sorted_tickers = sorted(
        mcp_streaks.items(),
        key=lambda x: (tier_order.get(x[1][1], 99), -x[1][0], x[0])
    )

    current_tier = None
    for ticker, (years, tier) in sorted_tickers:
        if tier != current_tier:
            current_tier = tier
            tier_label = {
                "King": "Kings (50+)", "Champion": "Champions (25-49)",
                "Contender": "Contenders (10-24)", "Challenger": "Challengers (5-9)",
                "—": "Non-US / ETFs / No CCC Data",
            }.get(tier, tier)
            lines.append(f"    # ── {tier_label} {'─' * (60 - len(tier_label))}")

        note = NON_CCC_TICKERS.get(ticker, "")
        note_str = f"  # {note}" if note else ""
        lines.append(f'    "{ticker}": ({years}, "{tier}"),{note_str}')

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def get_streak(ticker):")
    lines.append('    """Get (years, tier) for a ticker."""')
    lines.append('    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))')
    lines.append("")
    lines.append("")
    lines.append("def get_streak_years(ticker):")
    lines.append('    """Get just the number of consecutive years."""')
    lines.append('    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[0]')
    lines.append("")
    lines.append("")
    lines.append("def get_streak_tier(ticker):")
    lines.append('    """Get just the tier label."""')
    lines.append('    return DIVIDEND_STREAKS.get(ticker.upper(), (0, "—"))[1]')
    lines.append("")
    lines.append("")
    lines.append("def get_all_streaks_for_tickers(tickers):")
    lines.append('    """Get streak data for a list of tickers."""')
    lines.append("    return {t: {'years': get_streak_years(t), 'tier': get_streak_tier(t)} for t in tickers}")
    lines.append("")

    with open(STREAKS_PY, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ Wrote {STREAKS_PY} with {len(mcp_streaks)} tickers")


def _write_csv_backup(mcp_streaks):
    """Write a CSV backup of streak data."""
    os.makedirs(STREAKS_CSV.parent, exist_ok=True)
    with open(STREAKS_CSV, "w", encoding="utf-8") as f:
        f.write("ticker,consecutive_years,tier,updated\n")
        now = datetime.now().strftime("%Y-%m-%d")
        for ticker, (years, tier) in sorted(mcp_streaks.items()):
            f.write(f"{ticker},{years},{tier},{now}\n")
    print(f"✅ Wrote CSV backup: {STREAKS_CSV}")


def main():
    print("=" * 60)
    print("Martin Capital Partners — Dividend Streak Auto-Updater")
    print("=" * 60)
    print(f"Scraping dividendstocks.com CCC lists...")
    print()

    # Scrape all CCC lists
    all_streaks = scrape_all_streaks()

    if not all_streaks:
        print("\n⚠️  Scraping returned no data — keeping existing dividend_streaks.py")
        return

    print(f"\nTotal CCC tickers found: {len(all_streaks)}")

    # Build MCP-specific lookup
    mcp_streaks = {}

    # First: populate from scraped data
    for ticker in MCP_TICKERS:
        if ticker in all_streaks:
            years = all_streaks[ticker]
            tier = _classify_tier(years)
            mcp_streaks[ticker] = (years, tier)
        elif ticker in NON_CCC_TICKERS:
            mcp_streaks[ticker] = (0, "—")
        else:
            # Not found in any list and not a known non-CCC ticker
            mcp_streaks[ticker] = (0, "—")

    # Summary
    found = sum(1 for y, _ in mcp_streaks.values() if y > 0)
    print(f"MCP tickers matched: {found} / {len(MCP_TICKERS)}")
    print(f"Non-CCC (ETFs/non-US): {len(NON_CCC_TICKERS)}")

    # Show what we found
    print("\nMatched MCP holdings:")
    for ticker in sorted(mcp_streaks.keys()):
        years, tier = mcp_streaks[ticker]
        if years > 0:
            print(f"  {ticker:<8} {years:>3}y  {tier}")

    not_found = [t for t in MCP_TICKERS if t not in all_streaks and t not in NON_CCC_TICKERS]
    if not_found:
        print(f"\n⚠️  Not found in CCC lists (may need manual entry):")
        for t in sorted(not_found):
            print(f"  {t}")

    # Write files
    print()
    _write_streaks_py(mcp_streaks, all_streaks)
    _write_csv_backup(mcp_streaks)

    print("\nDone! The dashboard will use the updated data on next load.")


if __name__ == "__main__":
    main()