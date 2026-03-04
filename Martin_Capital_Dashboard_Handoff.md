# Martin Capital Partners — Portfolio Intelligence Dashboard
## Project Handoff Document (Post Sprint 2)
### Last Updated: March 3, 2026

---

## Project Overview

Internal Streamlit-based portfolio dashboard for Martin Capital Partners LLC, a 3-person dividend-focused equity boutique. The team is Ryan Adair (Operations/developer/IT lead), Cameron Martin (CIO), and Reid Weaver (Portfolio Manager).

The dashboard tracks 5 investment strategies across ~60 unique tickers, all dividend-focused equity portfolios.

---

## Strategies

| Code | Full Name | Tamarac Sheet | Holdings | Benchmark |
|------|-----------|---------------|----------|-----------|
| QDVD | Quality Dividend | QDVD | 36 + cash | S&P 500 |
| DAC | Quality All-Cap Dividend | DAC | 46 + cash | S&P 500 |
| SMID | Quality SMID Dividend | SMID | 24 + cash | Russell 2500 |
| OR | Oregon Dividend | OR | 36 + cash | S&P 500 |
| DCP | Dividend Core Plus | DCP | 44 + cash | S&P 500 |

60 unique tickers across all strategies. DCP is the most diversified and includes ETFs (PRFZ, RSP, CGGR, PXF, PXH, EWZ, XOP, CEF).

---

## Tech Stack

- **Framework:** Streamlit (Python)
- **Charts:** Plotly (dark theme)
- **Data Sources:** Tamarac Holdings Excel exports + yfinance (live prices/dividends) + FRED API (key: 984881b404269d00afe946250729a01a)
- **Database:** SQLite for caching (market_cache.db, portfolio.db — auto-created)
- **Auth:** Simple password gate (MartinCapital2026) via utils/auth.py
- **Deployment:** Local Windows machine, accessed via office WiFi by Cameron and Reid
- **Python:** 3.14, virtual environment in venv/

---

## Brand

| Element | Value |
|---------|-------|
| Green | #569542 |
| Blue | #07415A |
| Gold | #C9A84C |
| Black/BG | #0c1117 |
| Font | DM Sans (body), DM Serif Display (KPI values) |
| Logo | assets/M__Vector_.png |

---

## File Structure (Windows Path)

Root: `C:\Users\RyanAdair\Martin Capital Partners LLC\Eugene - Documents\Operations\Scripts\Portfolio Dashboard`

```
Portfolio Dashboard\
├── .streamlit\
│   └── config.toml
├── app.py                          ← Entry point: auth + redirect to Dashboard
├── assets\
│   └── M__Vector_.png              ← Logo
├── components\
│   ├── header.py                   ← Branded header with Pacific time
│   ├── market_ticker.py            ← Live index ticker bar
│   ├── kpi_cards.py                ← Strategy KPI card row (Daily Return, YTD, Alpha, Yield, Holdings)
│   ├── strategy_selector.py
│   └── charts.py
├── data\
│   ├── holdings.py                 ← Sprint 1 holdings module (fallback)
│   ├── performance.py              ← Sprint 1 performance module (fallback, has hardcoded mock YTD/AUM)
│   ├── monthly_returns.py          ← Ryan updates monthly with official Tamarac YTD numbers
│   ├── tamarac_parser.py           ← Sprint 2: multi-sheet Tamarac Excel parser
│   ├── market_data.py              ← Sprint 1+2 merged: market bar + batch price fetcher with SQLite cache
│   ├── dividends.py                ← Sprint 2: dividend analysis (yield, growth, consecutive years, income)
│   ├── Tamarac_Holdings.xlsx       ← Real holdings export (5 sheets, as-of 2026-02-27)
│   ├── market_cache.db             ← Auto-created SQLite cache for prices (15-min TTL)
│   └── portfolio.db                ← Auto-created SQLite cache for parsed holdings
├── pages\
│   └── 1_Dashboard.py              ← Main page: Overview + Holdings + Performance + Dividends tabs
├── utils\
│   ├── auth.py                     ← Password check (MartinCapital2026)
│   ├── styles.py                   ← Global CSS injection (dark theme, button/tab styling)
│   ├── cache.py
│   └── config.py                   ← STRATEGIES dict, SECTOR_COLORS, BRAND constants, FRED key
└── venv\                           ← Python 3.14 virtual environment
```

---

## Sprint Status

### Sprint 1 — COMPLETE
- Branded header with Pacific time display
- Live market ticker bar (S&P 500, DJIA, Nasdaq, 10Y, VIX, USD, Crude) via yfinance
- Password authentication
- Strategy selector buttons (QDVD, DAC, SMID, OR, DCP)
- KPI cards (AUM, YTD return, alpha, div yield, holdings count)
- Overview tab with cumulative YTD chart + sector allocation + top 6 holdings
- Holdings tab with search/sort and Tamarac drag-and-drop upload
- Performance tab with chart + return attribution + risk metrics (mock data)
- Dividends tab with upcoming ex-dates + yield chart (mock data)
- Dark-themed Plotly charts
- SQLite caching layer

### Sprint 2 — COMPLETE
**Data Layer:**
- Tamarac Excel parser (data/tamarac_parser.py) — handles multi-sheet format with ="value" quoting
- Merged market_data.py — Sprint 1 functions preserved + batch price fetcher with SQLite cache + Gold added to market ticker bar
- Dividend analysis module (data/dividends.py) — yield, 5Y CAGR, consecutive years, income projection
- Monthly returns file (data/monthly_returns.py) — Ryan updates monthly with official Tamarac YTD numbers

**Overview Tab:**
- Today's Returns bar chart — horizontal bars ranking all holdings by daily return, green/red colored
- Sector Allocation — real data from Tamarac + yfinance per strategy
- Top 5 Holdings — compact custom HTML display with ticker, name, weight, price, daily change (below sector allocation)
- Removed old cumulative performance chart (duplicated Performance tab)
- Removed old full-width top holdings table (replaced by compact top 5)

**Holdings Tab:**
- Full sortable holdings table with live yfinance prices merged with Tamarac weights
- 5 KPI metrics: Holdings count, Invested %, Cash %, Avg Yield, Top Weight
- Search by ticker/company + sector filter dropdown
- Sector breakdown aggregation table
- 1D Change column color-coded green/red via Pandas Styler
- Beta column removed
- Tamarac drag-and-drop uploader removed (no longer needed)

**Performance Tab:**
- Weighted portfolio returns vs benchmark using real Tamarac weights + yfinance price history
- Period selector (1mo, 3mo, 6mo, YTD, 1y)
- Real Sharpe, Sortino, Beta, Max Drawdown, Annualized Volatility
- Top Contributors table (symbol, weight, return, contribution)
- Drawdown chart (underwater plot)
- Monthly Returns Heatmap — full years + current partial year, green/red cells

**Dividends Tab:**
- Real ex-dividend dates from yfinance, sorted by upcoming
- 5 KPIs: weighted yield, est. annual income, avg 5Y growth, avg consecutive years, avg payout ratio
- Dividend yield horizontal bar chart (color-scaled)
- 5Y dividend growth CAGR chart (green/red bars)

**KPI Cards:**
- Replaced AUM with Daily Return (weighted avg of holdings' 1D changes, includes cash dilution)
- Holdings count pulled from real Tamarac data
- Dividend yield is weighted average from yfinance
- YTD Return pulled from data/monthly_returns.py with "as of [date]" in the label (grey, no arrow)
- All KPIs update per strategy

**Styling:**
- Active strategy button: green tint, glow, bright text
- Inactive strategy buttons: muted, subtle hover
- Tabs (Overview/Holdings/Performance/Dividends): matching green active state + hover effects
- Removed YTD % from strategy button labels (redundant with KPI cards)

**Bug Fixes:**
- yfinance dividend yield inconsistency — _safe_dividend_yield() helper caps at 20%, falls back to rate/price
- Daily return accuracy — includes cash weight (0% return) in denominator to match Finviz
- Plotly duplicate keyword error — heatmap layout uses explicit properties instead of **PLOTLY_DARK spread

### Sprint 3 — PLANNED (prioritized by Ryan)
1. **Alerts feed** — dividend events, price triggers (52W hi/lo), earnings date reminders, Morningstar changes
2. **Watchlist page** — research candidate pipeline, valuation screens, team notes
3. **Quality/dividend culture scoring** — integrate into holdings table
4. **Tamarac folder watcher** — auto-import new exports from a monitored directory

### Sprint 4 — PLANNED
- Mobile responsiveness / iPhone home screen optimization
- Custom domain setup
- Auto-refresh scheduling (Windows Task Scheduler → push to DB)
- Performance optimization
- Cameron and Reid user testing

---

## Architecture Notes

### Single-Page Tab Architecture
The dashboard is a single page (pages/1_Dashboard.py) with 4 tabs: Overview, Holdings, Performance, Dividends. app.py does auth then `st.switch_page()` to the Dashboard. The sidebar is hidden/collapsed. There are NO separate page files for Sprint 2 — everything is in-page tabs.

### How Data Flows
```
Tamarac_Holdings.xlsx (5 sheets, manually placed in data/)
        │
        ▼
tamarac_parser.py ── parses sheets, cleans ="..." quoting, separates cash
        │
        ├──► Overview tab ── fetch_batch_prices() for daily return bars + top 5
        ├──► Holdings tab ── merges with fetch_batch_prices() for full table
        ├──► Performance tab ── fetch_price_history() for weighted returns
        └──► Dividends tab ── get_batch_dividend_details() from dividends.py

monthly_returns.py ── official YTD numbers (Ryan updates monthly)
        │
        └──► KPI cards ── YTD Return + Alpha calculations
```

### Tamarac Excel Format
- 5 sheets named: QDVD, SMID, DAC, OR, DCP
- Columns: As of Date, Data For, Weight, Symbol, CUSIP, Description, Quantity
- Values use ="..." quoting (Tamarac export quirk) — parser handles this
- Each sheet has a CASH row at the bottom
- Weight column is decimal (e.g., 0.0466 = 4.66%)

### Monthly YTD Update Workflow
Ryan opens `data/monthly_returns.py` at the start of each month and updates:
```python
AS_OF_DATE = "2026-03-31"   # ← change date
STRATEGY_YTD = {
    "QDVD": 9.15,           # ← new numbers from Tamarac
    "DAC":  7.42,
    ...
}
```
Save, refresh dashboard. The YTD card shows the value with "as of Mar 31" in the label.

### Key Bug Fixes Applied
1. **Dividend Yield:** yfinance returns inconsistent values. _safe_dividend_yield() in both market_data.py and dividends.py checks if raw < 1 (decimal → multiply by 100), caps at 20%, falls back to dividendRate/price.
2. **Daily Return:** Includes cash weight in denominator so weighted return matches Finviz. Cash contributes 0% return but dilutes the equity moves.
3. **Plotly Layout:** Heatmaps can't use **PLOTLY_DARK spread if also passing custom xaxis/yaxis — spell out properties individually to avoid "multiple values for keyword" error.

### Caching Strategy
- Tamarac data: @st.cache_data(ttl=300) — 5 minutes
- Live prices (fetch_batch_prices): @st.cache_data(ttl=900) + SQLite 15-min TTL
- Dividend details: @st.cache_data(ttl=3600) — 1 hour
- Price history: @st.cache_data(ttl=3600) — 1 hour
- Market bar: @st.cache_data(ttl=300) — 5 minutes
- Delete data/market_cache.db to force fresh price data

### Graceful Fallback Pattern
All Sprint 2 features check `SPRINT2_AVAILABLE and tamarac_parsed and active in tamarac_parsed`. If any Sprint 2 module is missing or the Tamarac file isn't found, every tab falls back to Sprint 1 mock data automatically.

---

## Key Dependencies (all in venv)

streamlit, pandas, numpy, plotly, yfinance, openpyxl, notion-client, requests

---

## Development Notes

- Use Python write_project.py script pattern to generate files (avoids heredoc/quoting issues in bash)
- Windows permissions and file locking can cause issues with temp files
- The `initial_sidebar_state` in app.py is set to "collapsed" — sidebar is intentionally hidden
- Streamlit hides the sidebar nav via CSS: `[data-testid="stSidebarNav"] { display: none !important; }`
- Non-technical users (Cameron, Reid) access via browser on office WiFi — no PowerShell interaction
- When starting a new chat session, upload this handoff doc + 1_Dashboard.py + utils/config.py + Tamarac_Holdings.xlsx for best context
