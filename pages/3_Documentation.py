"""
Martin Capital Partners — Dashboard Documentation
pages/3_Documentation.py

Living reference page documenting every tab, data source, and calculation
in the Portfolio Intelligence Dashboard. Accessible from the sidebar nav
and linked in the dashboard footer.
"""

import streamlit as st

st.set_page_config(
    page_title="Documentation — Martin Capital",
    page_icon="📖",
    layout="wide",
)

# ── Branding ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&display=swap');
    .doc-title {
        font-family: 'DM Serif Display', serif;
        font-size: 28px;
        color: rgba(255,255,255,0.95);
        margin-bottom: 4px;
    }
    .doc-subtitle {
        font-size: 13px;
        color: rgba(255,255,255,0.35);
        margin-bottom: 32px;
    }
    .doc-section {
        font-family: 'DM Serif Display', serif;
        font-size: 22px;
        color: rgba(255,255,255,0.9);
        padding: 20px 0 8px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 16px;
        margin-top: 12px;
    }
    .doc-subsection {
        font-size: 14px;
        font-weight: 700;
        color: #C9A84C;
        margin: 16px 0 8px;
    }
    .doc-body {
        font-family: 'DM Sans', sans-serif;
        font-size: 14px;
        color: rgba(255,255,255,0.6);
        line-height: 1.7;
        margin-bottom: 12px;
    }
    .doc-source {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        background: rgba(7,65,90,0.15);
        color: rgba(255,255,255,0.5);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
        margin-right: 4px;
    }
    .doc-calc {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 6px;
        padding: 12px 16px;
        font-family: monospace;
        font-size: 12px;
        color: rgba(255,255,255,0.5);
        margin: 8px 0 12px;
        line-height: 1.6;
    }
    .doc-table {
        width: 100%;
        border-collapse: collapse;
        margin: 8px 0 16px;
    }
    .doc-table th {
        text-align: left;
        padding: 8px 12px;
        font-size: 10px;
        font-weight: 600;
        color: rgba(255,255,255,0.3);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .doc-table td {
        padding: 8px 12px;
        font-size: 13px;
        color: rgba(255,255,255,0.6);
        border-bottom: 1px solid rgba(255,255,255,0.03);
    }
    .doc-table td:first-child {
        color: rgba(255,255,255,0.8);
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────
st.markdown('<div class="doc-title">Portfolio Intelligence Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="doc-subtitle">Data sources, calculations, and methodology reference — Martin Capital Partners LLC</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# OVERVIEW TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Overview Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
The Overview tab is the primary dashboard view, showing a snapshot of the selected strategy's key metrics, sector allocation, and top holdings.
</div>

<div class="doc-subsection">KPI Cards</div>
<div class="doc-body">
Displayed at the top of most tabs. Each card shows a real-time metric for the selected strategy.
</div>

<table class="doc-table">
<tr><th>Metric</th><th>Source</th><th>Calculation</th></tr>
<tr><td>Daily Return</td><td><span class="doc-source">Supabase</span></td><td>Weighted average of each holding's 1-day % change, weighted by Tamarac portfolio weight. Cash is included in the denominator (dampens return).</td></tr>
<tr><td>Cash %</td><td><span class="doc-source">Tamarac</span></td><td>Read directly from the "CASH" row in the Tamarac Holdings export. Stored as a decimal — multiplied by 100 for display.</td></tr>
<tr><td>Dividend Yield</td><td><span class="doc-source">Supabase</span> <span class="doc-source">yfinance</span></td><td>Weighted average of each holding's trailing 12-month dividend yield, weighted by Tamarac portfolio weight (equity holdings only, cash excluded).</td></tr>
<tr><td>Holdings</td><td><span class="doc-source">Tamarac</span></td><td>Count of non-cash positions in the selected strategy from the Tamarac Holdings export.</td></tr>
</table>

<div class="doc-subsection">Market Ticker Bar</div>
<div class="doc-body">
The scrolling bar at the top shows real-time quotes for S&P 500, DJIA, Nasdaq, VIX, US 10Y Treasury, and Brent Crude. Data is fetched from Supabase (prefetched from yfinance every 15 minutes during market hours via GitHub Actions).
</div>

<div class="doc-subsection">Sector Allocation</div>
<div class="doc-body">
Built from Tamarac holdings weights grouped by each ticker's GICS sector (fetched from yfinance). Cash is shown as its own "sector." The treemap on the Overview tab colors each tile by the holding's YTD return (green positive, red negative).
</div>

<div class="doc-subsection">Top Holdings</div>
<div class="doc-body">
The top 10 holdings by portfolio weight from the Tamarac export, enriched with live price data from Supabase. YTD return, dividend yield, and MCP price targets (from Notion) are shown alongside each position.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# HOLDINGS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Holdings Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Full sortable table of every position in the selected strategy. All columns can be sorted by clicking the header.
</div>

<table class="doc-table">
<tr><th>Column</th><th>Source</th><th>Notes</th></tr>
<tr><td>Weight %</td><td><span class="doc-source">Tamarac</span></td><td>Portfolio weight from the latest Tamarac Holdings export</td></tr>
<tr><td>Price</td><td><span class="doc-source">Supabase</span></td><td>Last price from prefetch pipeline (15-min refresh during market hours)</td></tr>
<tr><td>1D Change</td><td><span class="doc-source">Supabase</span></td><td>Percentage change from previous close</td></tr>
<tr><td>YTD Return</td><td><span class="doc-source">Supabase</span></td><td>Year-to-date percentage return</td></tr>
<tr><td>Div Yield</td><td><span class="doc-source">yfinance</span></td><td>Trailing 12-month dividend yield</td></tr>
<tr><td>Yield on Cost</td><td><span class="doc-source">Tamarac</span></td><td>Stored as a decimal in the export (e.g., 0.0558 = 5.58%). Multiplied by 100 for display.</td></tr>
<tr><td>Div Safety</td><td><span class="doc-source">Fish CCC</span> <span class="doc-source">yfinance</span></td><td>Letter grade (A+ through C) based on payout ratio, 5Y growth rate, and consecutive years of increases. See Dividends tab for full methodology.</td></tr>
<tr><td>MCP Target</td><td><span class="doc-source">Notion</span></td><td>Proprietary price target from the MCP Master Holdings database in Notion. Upside % = (target - price) / price × 100.</td></tr>
<tr><td>Sector</td><td><span class="doc-source">yfinance</span></td><td>GICS sector classification</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# STOCK DETAIL PAGE
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Stock Detail Page</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Accessible by clicking a ticker in the Holdings tab or via the searchable ticker selector. Shows a deep-dive on any single holding. Sections appear in this order:
</div>

<table class="doc-table">
<tr><th>Section</th><th>Source</th><th>Details</th></tr>
<tr><td>Company Profile</td><td><span class="doc-source">yfinance</span></td><td>Name, sector, industry, market cap, description</td></tr>
<tr><td>MCP Investment Thesis</td><td><span class="doc-source">Notion</span></td><td>Pulled from the callout block on the ticker's wiki page in Notion (Active or Archived Holdings). Archived tickers show the sell thesis.</td></tr>
<tr><td>Price Chart</td><td><span class="doc-source">yfinance</span></td><td>Interactive Plotly chart with configurable time range</td></tr>
<tr><td>Analyst & Technical Signals</td><td><span class="doc-source">Finviz</span></td><td>Analyst consensus, price target (Wall Street), SMA signals</td></tr>
<tr><td>Valuation Metrics</td><td><span class="doc-source">Finviz</span></td><td>P/E, forward P/E, P/S, P/B, PEG, EV/EBITDA</td></tr>
<tr><td>Revenue / Earnings / Margins</td><td><span class="doc-source">Finviz</span></td><td>Revenue, net income, profit margin, operating margin, ROE</td></tr>
<tr><td>Sector Peers</td><td><span class="doc-source">Finviz</span></td><td>Up to 8 peers in the same sector, showing comparative valuation metrics</td></tr>
<tr><td>Dividend History</td><td><span class="doc-source">Fish CCC</span> <span class="doc-source">yfinance</span></td><td>Annual dividend totals, year-over-year increase %, CAGR. Fish CCC is primary source; yfinance is fallback for non-CCC tickers. Source badge shows which is used.</td></tr>
<tr><td>Dividend Commentary</td><td><span class="doc-source">Notion</span></td><td>Earnings call notes and dividend commentary from the ticker's "Dividend Commentary" subpage in Notion</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# PERFORMANCE TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Performance Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Shows strategy performance vs benchmark over time. Currently uses a weighted projection based on current holdings. A rebuild using authoritative composite return data from Tamarac's Composite_Returns.xls is planned for a future sprint.
</div>

<div class="doc-subsection">Monthly Returns Heatmap</div>
<div class="doc-body">
Displays monthly returns in a grid, color-coded green (positive) to red (negative). Risk metrics are displayed above the heatmap in a responsive flex grid.
</div>

<div class="doc-subsection">Risk Metrics</div>
<table class="doc-table">
<tr><th>Metric</th><th>Calculation</th></tr>
<tr><td>Sharpe Ratio</td><td>(Annualized return − risk-free rate) / annualized standard deviation. Risk-free rate from FRED (3-month T-bill).</td></tr>
<tr><td>Sortino Ratio</td><td>Same as Sharpe but only uses downside deviation (negative returns only).</td></tr>
<tr><td>Beta</td><td>Covariance of strategy returns with benchmark returns / variance of benchmark returns.</td></tr>
<tr><td>Max Drawdown</td><td>Largest peak-to-trough decline in cumulative returns over the period.</td></tr>
<tr><td>Tracking Error</td><td>Annualized standard deviation of the difference between strategy and benchmark returns.</td></tr>
<tr><td>Information Ratio</td><td>Annualized alpha / tracking error.</td></tr>
</table>

<div class="doc-subsection">Important Note</div>
<div class="doc-body">
The current performance data projects current holdings backward, which creates a look-ahead bias — it assumes today's portfolio was held throughout the period. The planned rebuild using Composite_Returns.xls will use actual historical composite returns aggregated from client accounts, which is the authoritative source. This file is updated quarterly and covers six composites: QDVD (since Jun 2010), SMID (Dec 2014), DAC (Dec 2015), OR (Sep 2017), Balanced, and Income.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# DIVIDENDS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Dividends Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Comprehensive dividend intelligence across multiple sub-tabs: Snapshot, Safety & Growth, Dividend History, and Dividend Calendar.
</div>

<div class="doc-subsection">Dividend Safety Grades</div>
<div class="doc-body">
Each holding receives a letter grade (A+ through C) based on a composite score of three factors. The scoring methodology is documented in the collapsible expander on the Safety & Growth sub-tab.
</div>

<div class="doc-calc">
Payout Ratio (0-5 pts): &lt;40% = 5, &lt;60% = 4, &lt;75% = 3, &lt;90% = 2, else 1<br>
5Y Dividend Growth (0-5 pts): &gt;10% = 5, &gt;7% = 4, &gt;5% = 3, &gt;3% = 2, &gt;0% = 1<br>
Consecutive Years (0-5 pts): &gt;25y = 5, &gt;15y = 4, &gt;10y = 3, &gt;5y = 2, &gt;1y = 1<br>
<br>
Total Score → Grade: 13-15 = A+, 11-12 = A, 9-10 = B+, 7-8 = B, 5-6 = C+, &lt;5 = C
</div>

<div class="doc-subsection">Growth Tiers</div>
<div class="doc-body">
Holdings are grouped into tiers based on their 5-year dividend CAGR from Fish CCC data. Non-Fish tickers with unreliable growth data (e.g., ADRs with FX-distorted payouts) are placed in an "Uncertain (non-CCC)" tier rather than being mislabeled as cuts.
</div>

<div class="doc-subsection">Dividend Calendar</div>
<div class="doc-body">
Generated weekly by a Python script that runs every Monday via Windows Task Scheduler. The script auto-commits and pushes to GitHub so the dashboard picks it up. Shows upcoming ex-dividend dates, amounts, and yield for all holdings.
</div>

<div class="doc-subsection">Data Sources</div>
<table class="doc-table">
<tr><th>Data Point</th><th>Primary Source</th><th>Fallback</th></tr>
<tr><td>Consecutive years of increases</td><td><span class="doc-source">Fish CCC</span></td><td>yfinance dividend history</td></tr>
<tr><td>5Y dividend CAGR</td><td><span class="doc-source">Fish CCC</span></td><td>Computed from yfinance annual totals</td></tr>
<tr><td>1Y dividend growth</td><td><span class="doc-source">Fish CCC</span></td><td>yfinance</td></tr>
<tr><td>Payout ratio</td><td><span class="doc-source">Finviz</span></td><td>yfinance</td></tr>
<tr><td>Ex-dividend dates</td><td><span class="doc-source">yfinance</span></td><td>—</td></tr>
<tr><td>Yield on cost</td><td><span class="doc-source">Tamarac</span></td><td>— (computed by Tamarac from cost basis)</td></tr>
</table>

<div class="doc-subsection">ADR / Special Dividend Handling</div>
<div class="doc-body">
ADRs like KOF, TTE, and CME can show misleading dividend growth rates due to FX effects and special dividend timing. The dashboard uses stricter thresholds for non-Fish tickers: only flags a decline if 1Y growth is worse than -15% (vs -5% for reliable CCC data), and labels these as "Uncertain" rather than "Cut/Frozen."
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# WATCHLIST TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Watchlist Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Displays the research candidate pipeline from the Watchlist Excel file. Shows tickers under consideration with basic valuation and dividend metrics. This tab is independent of Tamarac data and loads from the local Excel file.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MACRO TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Macro Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Macro environment context for dividend strategy positioning. All rate and economic data comes from the FRED API (Federal Reserve Economic Data). Market valuation data comes from yfinance.
</div>

<div class="doc-subsection">Rates & Yields</div>
<div class="doc-body">
Live rate cards showing Fed Funds Rate, 2Y/10Y/30Y Treasury yields, 2s10s spread, and 15Y/30Y mortgage rates. The 2s10s spread is computed as (10Y yield − 2Y yield) × 100 basis points.
</div>

<div class="doc-subsection">Dividend Strategy Context</div>
<table class="doc-table">
<tr><th>Metric</th><th>Calculation</th></tr>
<tr><td>Yield Comparison</td><td>10Y Treasury yield vs S&P 500 dividend yield vs QDVD weighted yield — shows whether dividend stocks are competitive with bonds for income.</td></tr>
<tr><td>Equity Risk Premium</td><td>S&P 500 earnings yield (1 / forward P/E × 100) minus the 10Y Treasury yield. Expressed in basis points. Below 50bp is flagged as tight.</td></tr>
<tr><td>Yield Curve</td><td>2s10s spread in basis points. Positive = normal curve, negative = inverted.</td></tr>
</table>

<div class="doc-subsection">Sentiment</div>
<table class="doc-table">
<tr><th>Metric</th><th>Source</th><th>Signal Thresholds</th></tr>
<tr><td>VIX</td><td><span class="doc-source">yfinance</span></td><td>Green &lt;16, Gold 16-25, Red &gt;25</td></tr>
<tr><td>UMich Sentiment</td><td><span class="doc-source">FRED</span></td><td>Green &gt;80, Gold 60-80, Red &lt;60</td></tr>
<tr><td>Yield Curve</td><td><span class="doc-source">FRED</span></td><td>Green if normal (positive spread), Red if inverted</td></tr>
</table>

<div class="doc-subsection">Fear & Greed Index</div>
<div class="doc-body">
Proprietary composite score (0-100) computed from four equally-weighted components. Cached 15 minutes.
</div>

<div class="doc-calc">
VIX (25%): Maps VIX 10-40 inversely to 0-100. Low VIX = high score (greed).<br>
Momentum (25%): S&P 500 price vs 125-day SMA. Maps -10% to +10% range to 0-100.<br>
Sentiment (25%): UMich Consumer Sentiment. Maps 50-100 range to 0-100.<br>
Breadth (25%): RSP/SPY ratio vs its 60-day average. Broad participation = greed.<br>
<br>
Score → Label: 0-24 Extreme Fear, 25-44 Fear, 45-54 Neutral, 55-74 Greed, 75-100 Extreme Greed
</div>

<div class="doc-subsection">Economic Indicators</div>
<div class="doc-body">
All sourced from FRED. CPI, Core CPI, and PCE are computed as year-over-year percentage changes from the raw index values. Other indicators (unemployment, GDP, ISM, consumer confidence, jobless claims) display the latest reported value with trend arrows and signal badges.
</div>

<div class="doc-subsection">Market Valuation</div>
<div class="doc-body">
Forward P/E, earnings yield, equity risk premium, S&P dividend yield, QDVD yield premium, and mortgage rates. All rendered in a single table with signal badges (positive, neutral, watch, alert, elevated).
</div>

<div class="doc-subsection">Fed Meeting Calendar</div>
<div class="doc-body">
Manually maintained list of upcoming FOMC meeting dates with CME FedWatch probability estimates. Updated periodically — not live from an API.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MARKETS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Markets Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Broad market snapshot using ETF proxies, sorted by daily performance (best to worst) within each section. All data from a single batched yfinance call (~45 tickers), cached 15 minutes.
</div>

<table class="doc-table">
<tr><th>Section</th><th>Tickers</th><th>Notes</th></tr>
<tr><td>Indices</td><td>Nasdaq 100, DJIA, Russell 2000, Russell 1000 Value/Growth, AGG, Bitcoin</td><td>Bitcoin uses BTC-USD</td></tr>
<tr><td>Dividend Benchmarks</td><td>S&P 500, SPYD, SDY, REGL, S&P 400, Russell 3000, DWX, DVY</td><td>Key benchmarks for dividend strategies</td></tr>
<tr><td>S&P Sector ETFs</td><td>XLK, XLV, XLF, XLY, XLP, XLI, XLE, XLU, XLRE, XLB, XLC</td><td>All 11 GICS sectors</td></tr>
<tr><td>Fixed Income</td><td>GOVT, TIP, LQD, HYG, MUB, CWB</td><td>Government, TIPS, IG, HY, Munis, Convertibles</td></tr>
<tr><td>Global Developed</td><td>EFA, EWJ, EWU, EWG, EWA, EWQ</td><td>Broad + major countries</td></tr>
<tr><td>Global Emerging</td><td>EEM, FXI, EPI, EWZ, EWW, EWY, EZA</td><td>Broad + major countries</td></tr>
<tr><td>Commodities</td><td>GC=F, SI=F, CL=F, BZ=F, NG=F, HG=F</td><td>Actual futures contracts, not ETF proxies</td></tr>
</table>

<div class="doc-subsection">% From High Column</div>
<div class="doc-body">
Shows each ticker's distance from its 52-week high, calculated from 1 year of daily data. Displayed in red for any value below the high; green "AT HIGH" if at the 52-week peak.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# NEWS & ALERTS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">News & Alerts Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-subsection">Market Headlines</div>
<div class="doc-body">
RSS feeds from MarketWatch Top Stories, CNBC Top News, and CNBC Economy. Fetched via the feedparser library, cached 15 minutes. Up to 12 headlines displayed, sorted newest first. Headlines link to the original article.
</div>

<div class="doc-subsection">Portfolio Alerts</div>
<div class="doc-body">
Computed live from Supabase data across all strategies (all unique tickers from the Tamarac export). Four alert categories:
</div>

<table class="doc-table">
<tr><th>Alert Type</th><th>Trigger</th><th>Data Source</th></tr>
<tr><td>Price Movers</td><td>Any holding with a daily move exceeding ±2%</td><td><span class="doc-source">Supabase</span></td></tr>
<tr><td>Dividend Events</td><td>Ex-dividend dates within 14 days; dividend growth/decline alerts based on 1Y change</td><td><span class="doc-source">Supabase</span> <span class="doc-source">Fish CCC</span></td></tr>
<tr><td>Upcoming Earnings</td><td>Holdings reporting within the next 14 days</td><td><span class="doc-source">yfinance</span> (cached 1hr)</td></tr>
<tr><td>52-Week Proximity</td><td>Holdings within 5% of their 52-week high or low</td><td><span class="doc-source">Supabase</span></td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# DATA PIPELINE
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Data Pipeline & Refresh</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Market data is refreshed automatically during trading hours. The pipeline runs as a GitHub Actions workflow triggered by an external cron job (cron-job.org).
</div>

<table class="doc-table">
<tr><th>Component</th><th>Frequency</th><th>Details</th></tr>
<tr><td>Supabase price data</td><td>Every 15 min (market hours)</td><td>prefetch_cloud.py runs via GitHub Actions. Fetches prices, changes, yields, 52-week data from yfinance and writes to Supabase.</td></tr>
<tr><td>Tamarac Holdings</td><td>Manual export, auto-pushed</td><td>Ryan exports from Tamarac, drops file in data/ folder. A background file watcher (watch_tamarac.py) detects the change and auto-commits/pushes to GitHub within 60 seconds.</td></tr>
<tr><td>Fish CCC data</td><td>Monthly</td><td>Monthly David Fish CCC spreadsheet placed in data/ folder. File pattern: Fish_*.xlsx (glob selects newest).</td></tr>
<tr><td>Dividend Calendar</td><td>Weekly (Monday)</td><td>Generated by dividend_calendar.py via Windows Task Scheduler. Auto-commits and pushes to GitHub.</td></tr>
<tr><td>Notion data</td><td>Live (cached 1hr)</td><td>Investment theses, dividend commentary, and MCP price targets fetched from Notion API on each page load.</td></tr>
<tr><td>Finviz data</td><td>Live (cached 15min)</td><td>Analyst data, valuation metrics, sector peers fetched via finvizfinance library.</td></tr>
<tr><td>FRED data</td><td>Live (cached 1hr)</td><td>Rates, economic indicators, sentiment data fetched from FRED API.</td></tr>
</table>

<div class="doc-subsection">Cron Job Maintenance</div>
<div class="doc-body">
The cron-job.org trigger uses a GitHub Personal Access Token (classic, repo scope) to dispatch the workflow. If the token expires, update the Authorization header in cron-job.org. Prefetch hours are set for EDT (UTC-4); the EST (UTC-5) shift in November may require adjustment.
</div>

<div class="doc-subsection">Tamarac File Detection</div>
<div class="doc-body">
The dashboard uses an internal "As of Date" from cell A2 of the Tamarac Excel file to determine data freshness — not the filesystem modification time. This is immune to OneDrive sync timestamps. The banner shows the as-of date and flags data older than 7 days as stale.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# DATA SOURCES SUMMARY
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Data Sources Summary</div>', unsafe_allow_html=True)

st.markdown("""
<table class="doc-table">
<tr><th>Source</th><th>What It Provides</th><th>Access Method</th><th>Cost</th></tr>
<tr><td>Supabase (PostgreSQL)</td><td>Cached price data, daily changes, yields, 52-week ranges</td><td>REST API via prefetch pipeline</td><td>Free tier</td></tr>
<tr><td>yfinance</td><td>Real-time prices, dividend data, earnings dates, historical data</td><td>Python library (unofficial Yahoo Finance)</td><td>Free</td></tr>
<tr><td>FRED</td><td>Treasury yields, economic indicators, mortgage rates, sentiment</td><td>REST API (key required)</td><td>Free</td></tr>
<tr><td>Notion API</td><td>Investment theses, dividend commentary, MCP price targets, holdings metadata</td><td>REST API (integration token)</td><td>Free</td></tr>
<tr><td>Finviz Elite</td><td>Analyst ratings, valuation metrics, sector peers, insider activity</td><td>finvizfinance Python library</td><td>Existing subscription</td></tr>
<tr><td>Fish CCC</td><td>Dividend streak data, growth rates, consecutive years</td><td>Monthly Excel spreadsheet</td><td>Free (David Fish list)</td></tr>
<tr><td>Tamarac</td><td>Portfolio holdings, weights, cost basis, yield on cost</td><td>Manual Excel export</td><td>Existing subscription</td></tr>
<tr><td>RSS Feeds</td><td>Market news headlines (MarketWatch, CNBC)</td><td>feedparser Python library</td><td>Free</td></tr>
</table>
""", unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────────────────
st.markdown(
    "<div style='padding:24px 0 12px;border-top:1px solid rgba(255,255,255,0.04);"
    "font-size:11px;color:rgba(255,255,255,0.2);text-align:center;margin-top:32px'>"
    "Martin Capital Partners LLC · Portfolio Intelligence Dashboard · Internal Use Only"
    "</div>",
    unsafe_allow_html=True,
)