"""
Strategy definitions, brand colors, and global config.
Single source of truth — edit here to update the whole dashboard.
"""

# ── Brand ──────────────────────────────────────────────────────────────────
BRAND = {
    "green":  "#569542",
    "blue":   "#07415A",
    "gold":   "#C9A84C",
    "black":  "#0c1117",
    "red":    "#c45454",
}

# ── Strategy Definitions ──────────────────────────────────────────────────
STRATEGIES = {
    "QDVD": {
        "name": "Quality Dividend",
        "full_name": "Quality Dividend Strategy",
        "bench": "S&P 500",
        "bench_ticker": "^GSPC",
        "color": "#569542",
        "target_yield": 2.5,
        "description": "High-quality dividend payers with durable competitive advantages.",
    },
    "DAC": {
        "name": "Quality All-Cap Dividend",
        "full_name": "Quality All-Cap Dividend Strategy",
        "bench": "S&P Div Aristocrats",
        "bench_ticker": "^SP500DVS",
        "color": "#07415A",
        "target_yield": 2.8,
        "description": "S&P 500 Dividend Aristocrats with quality overlay.",
    },
    "SMID": {
        "name": "Quality SMID Dividend",
        "full_name": "Quality SMID Dividend Strategy",
        "bench": "Russell 2500",
        "bench_ticker": "^RUT",
        "color": "#C9A84C",
        "target_yield": 2.2,
        "description": "Small and mid-cap dividend growers with quality screens.",
    },
    "OR": {
        "name": "Oregon Dividend",
        "full_name": "Oregon Dividend Strategy",
        "bench": "S&P 500",
        "bench_ticker": "^GSPC",
        "color": "#569542",
        "target_yield": 2.0,
        "description": "Opportunistic dividend recovery and special situations.",
    },
    "DCP": {
        "name": "Dividend Core Plus",
        "full_name": "Dividend Core Plus",
        "bench": "S&P 500 Growth",
        "bench_ticker": "^SP500GR",
        "color": "#07415A",
        "target_yield": 1.8,
        "description": "Dividend compounders with above-average earnings growth.",
    },
}

# ── Composite Returns Benchmarks (Sprint 10) ─────────────────────────────
# Maps each strategy to its authoritative benchmark(s) from
# Composite_Returns.xls (inline with the composite data — no yfinance needed)
COMPOSITE_BENCHMARKS = {
    "QDVD": {"primary": "S&P 500", "secondary": "S&P 500 High Dividend"},
    "SMID": {"primary": "S&P Mid Cap 400", "secondary": "S&P 400 Aristocrats"},
    "DAC":  {"primary": "Russell 3000", "secondary": "Dow Jones Select Dividend"},
    "OR":   {"primary": "S&P 500", "secondary": None},
}

# ── Sector Colors ─────────────────────────────────────────────────────────
# Keys match normalized labels from normalize_sector() below.
SECTOR_COLORS = {
    "Healthcare":               "#569542",
    "Consumer Staples":         "#07415A",
    "Technology":               "#C9A84C",
    "Industrials":              "#3a7a5c",
    "Financials":               "#0a5a7a",
    "Energy":                   "#8a6a2c",
    "Utilities":                "#5a4a8a",
    "Real Estate":              "#8a3a5c",
    "Materials":                "#4a7a4a",
    "Communication Services":   "#2a5a8a",
    "Consumer Discretionary":   "#b87333",
    "Cash":                     "#444",
}

# ── Sector Name Normalization (Sprint 20) ─────────────────────────────────
# Map yfinance's GICS-ish labels to MCP's preferred labels. Single source
# of truth — apply via normalize_sector() wherever a sector string enters
# our dataframes (Overview heatmap, sector allocation, Holdings tab filter
# and pie chart).
SECTOR_RENAME = {
    "Consumer Defensive":  "Consumer Staples",
    "Consumer Cyclical":   "Consumer Discretionary",
    "Financial Services":  "Financials",
    "Basic Materials":     "Materials",
    # Communication Services kept as-is per Sprint 20 spec.
}

def normalize_sector(sector: str) -> str:
    """Return MCP's preferred sector label, falling back to the input."""
    if not sector:
        return "Other"
    return SECTOR_RENAME.get(sector, sector)

# ── Data Refresh ──────────────────────────────────────────────────────────
REFRESH_INTERVAL_MINUTES = 15
MARKET_OPEN_HOUR = 9    # ET
MARKET_CLOSE_HOUR = 16  # ET

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH = "data/martin_capital.db"

# ── Tamarac ───────────────────────────────────────────────────────────────
TAMARAC_WATCH_FOLDER = r"C:\Users\RyanAdair\Martin Capital Partners LLC\Eugene - Documents\Operations\Scripts\Portfolio Dashboard\data\tamarac_imports"