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

# ── Sector Colors ─────────────────────────────────────────────────────────
SECTOR_COLORS = {
    "Healthcare":        "#569542",
    "Consumer Staples":  "#07415A",
    "Technology":        "#C9A84C",
    "Industrials":       "#3a7a5c",
    "Financials":        "#0a5a7a",
    "Energy":            "#8a6a2c",
    "Utilities":         "#5a4a8a",
    "Real Estate":       "#8a3a5c",
    "Materials":         "#4a7a4a",
    "Communication":     "#2a5a8a",
    "Cash":              "#444",
}

# ── Data Refresh ──────────────────────────────────────────────────────────
REFRESH_INTERVAL_MINUTES = 15
MARKET_OPEN_HOUR = 9    # ET
MARKET_CLOSE_HOUR = 16  # ET

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH = "data/martin_capital.db"

# ── Tamarac ───────────────────────────────────────────────────────────────
TAMARAC_WATCH_FOLDER = r"C:\Users\RyanAdair\Martin Capital Partners LLC\Eugene - Documents\Operations\Scripts\Portfolio Dashboard\data\tamarac_imports"