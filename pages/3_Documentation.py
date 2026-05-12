"""
Martin Capital Partners — Dashboard Documentation
pages/3_Documentation.py

Living reference page documenting every tab, data source, and calculation
in the Portfolio Intelligence Dashboard. Accessible from the sidebar nav
and linked in the dashboard footer.

Last refresh: Sprint 25-4 (May 2026). Covers Sprints 1-25 inclusive.
When making material changes to the dashboard, update the corresponding
section below in the same PR.
"""

import streamlit as st
from utils.auth import check_password
from utils.styles import inject_global_css

st.set_page_config(
    page_title="Documentation — Martin Capital",
    page_icon="📖",
    layout="wide",
)

if not check_password():
    st.stop()

inject_global_css()

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
if st.button("← Back to Dashboard", key="back_to_dash"):
    st.switch_page("pages/1_Dashboard.py")
st.markdown('<div class="doc-title">Portfolio Intelligence Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="doc-subtitle">Data sources, calculations, and methodology reference — Martin Capital Partners LLC</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# STRATEGIES
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Strategies</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Five dividend-focused equity strategies. The strategy selector in the dashboard header switches all tabs to the selected strategy's data.
</div>

<table class="doc-table">
<tr><th>Code</th><th>Name</th><th>Description</th><th>Target Yield</th></tr>
<tr><td>QDVD</td><td>Quality Dividend</td><td>High-quality dividend payers with durable competitive advantages</td><td>2.5%</td></tr>
<tr><td>DAC</td><td>Quality All-Cap Dividend</td><td>S&P 500 Dividend Aristocrats with quality overlay</td><td>2.8%</td></tr>
<tr><td>SMID</td><td>Quality SMID Dividend</td><td>Small and mid-cap dividend growers with quality screens</td><td>2.2%</td></tr>
<tr><td>OR</td><td>Oregon Dividend</td><td>Opportunistic dividend recovery and special situations</td><td>2.0%</td></tr>
<tr><td>DCP</td><td>Dividend Core Plus</td><td>Dividend compounders with above-average earnings growth</td><td>1.8%</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# OVERVIEW TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Overview Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Primary dashboard view. Shows a snapshot of the selected strategy's key metrics, intraday context, sector allocation, top contributors / detractors, and top holdings preview.
</div>

<div class="doc-subsection">KPI Cards (Top of Every Tab)</div>
<table class="doc-table">
<tr><th>Metric</th><th>Source</th><th>Calculation</th></tr>
<tr><td>Daily Return</td><td><span class="doc-source">Supabase</span></td><td>Weighted average of each holding's 1-day % change, weighted by Tamarac portfolio weight. Cash is included in the denominator (dampens return).</td></tr>
<tr><td>Cash %</td><td><span class="doc-source">Tamarac</span></td><td>Read directly from the CASH row in the Tamarac Holdings export. Stored as a decimal — multiplied by 100 for display.</td></tr>
<tr><td>Dividend Yield</td><td><span class="doc-source">Tamarac</span> <span class="doc-source">Supabase</span></td><td>Weighted average of each holding's trailing yield, weighted by Tamarac portfolio weight (equity holdings only, cash excluded). Source hierarchy: Tamarac manual file → Supabase dividends.dividend_yield → Supabase prices.dividend_yield.</td></tr>
<tr><td>Holdings</td><td><span class="doc-source">Tamarac</span></td><td>Count of non-cash positions in the selected strategy from the Tamarac Holdings export.</td></tr>
</table>

<div class="doc-body">
YTD return is intentionally not displayed on the KPI cards — there is currently no source of truth for live intraday YTD figures that matches Tamarac's official monthly composite figures. Official YTDs live in monthly_returns.py (manually updated each month from Tamarac) and are surfaced on the Performance tab where the as-of date is explicit.
</div>

<div class="doc-subsection">Intraday Context Chart</div>
<div class="doc-body">
Single-row chart showing S&P 500 + SPYD (S&P 500 High Dividend ETF) intraday performance. Provides quick "what's the market doing right now" context above the strategy-specific content. Data: yfinance, 15-min cache.
</div>

<div class="doc-subsection">Sector Allocation Treemap</div>
<div class="doc-body">
Treemap visualization of strategy holdings, sized by portfolio weight and colored by YTD return (green positive, red negative). Each tile shows ticker, weight, and YTD %. Hovering reveals additional fundamentals. Cash is shown as its own grey tile.
</div>

<div class="doc-subsection">Top Contributors / Detractors</div>
<div class="doc-body">
Pure mathematical movers — each holding's weight × 1-day return, sorted descending (top contributors) and ascending (top detractors). Shows the top 3 in each direction with the dollar contribution to the strategy's daily return.
</div>

<div class="doc-subsection">Sector Contributors / Detractors</div>
<div class="doc-body">
Same calculation as above but aggregated by sector. Each sector's contribution = sum of (weight × 1-day return) for all holdings in that sector.
</div>

<div class="doc-subsection">Top Holdings Preview</div>
<div class="doc-body">
First 6 holdings by portfolio weight. Includes ticker, name, weight, price, 1D, YTD, dividend yield, and dividend safety grade. Click "View All →" to switch to the Holdings sub-tab.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# HOLDINGS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Holdings Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Two sub-tabs: <b>Holdings Detail</b> (full sortable table with row-click drill-through to Stock Detail) and <b>Charts</b> (4-column grid of mini-charts, one per holding, for at-a-glance survey of the portfolio).
</div>

<div class="doc-subsection">Holdings Detail Sub-tab</div>
<table class="doc-table">
<tr><th>Column</th><th>Source</th><th>Notes</th></tr>
<tr><td>Ticker</td><td><span class="doc-source">Tamarac</span></td><td>Click any row to navigate to the Stock Detail page for that ticker</td></tr>
<tr><td>Weight %</td><td><span class="doc-source">Tamarac</span></td><td>Portfolio weight from the latest Tamarac Holdings export</td></tr>
<tr><td>Price</td><td><span class="doc-source">Supabase</span></td><td>Last price from prefetch pipeline (15-min refresh during market hours)</td></tr>
<tr><td>1D Change</td><td><span class="doc-source">Supabase</span></td><td>Percentage change from previous close</td></tr>
<tr><td>YTD Return</td><td><span class="doc-source">Supabase</span></td><td>Year-to-date percentage return</td></tr>
<tr><td>Div Yield</td><td><span class="doc-source">Tamarac</span> <span class="doc-source">Supabase</span></td><td>Source hierarchy: Tamarac manual file → Supabase dividends → Supabase prices. Trailing 12-month yield.</td></tr>
<tr><td>Yield on Cost</td><td><span class="doc-source">Tamarac</span></td><td>Stored as a decimal in the export (e.g. 0.0558 = 5.58%). When yield_at_cost is missing in the API export, the parser falls back to annual_income / cost_basis, then annual_income / (qty × unit_cost) from the manual file.</td></tr>
<tr><td>Div Safety</td><td><span class="doc-source">Fish CCC</span> <span class="doc-source">yfinance</span></td><td>Letter grade A+ through C based on payout ratio, 5Y growth rate, and consecutive years of increases. See Dividends tab for the scoring formula.</td></tr>
<tr><td>MCP Target</td><td><span class="doc-source">Notion</span></td><td>Proprietary price target from the MCP Master Holdings database in Notion. Upside % = (target − price) / price × 100.</td></tr>
<tr><td>Sector</td><td><span class="doc-source">Tamarac</span></td><td>Normalized via normalize_sector() to MCP's preferred sector labels</td></tr>
</table>

<div class="doc-subsection">Charts Sub-tab</div>
<div class="doc-body">
4-column grid of mini-charts — one per holding. Each card shows ticker, current price, 1-day %, and a 1-year sparkline. Designed for survey mode (scanning all positions at once). For deep-dive on a single position, click the row in Holdings Detail to navigate to the Stock Detail page.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# WARBOOK TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Warbook Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Strategy-specific deep analytics. Four sub-tabs: Strategy Overview, QDG Characteristics, Risk Correlation, and Attribution. Currently scoped to QDVD / DAC / SMID / OR. DCP is not yet wired in.
</div>

<div class="doc-subsection">Strategy Overview Sub-tab</div>
<div class="doc-body">
Strategy-level summary: full holdings table with the same columns as Holdings Detail plus warbook-specific fields (MCP rating, last review date, position-size notes from Notion). Includes an export button that generates a downloadable Excel warbook matching Cameron's quarterly format.
</div>

<div class="doc-subsection">QDG Characteristics Sub-tab</div>
<div class="doc-body">
Per-holding fundamental characteristics for quality-dividend-growth analysis. Columns include Mkt Cap, P/E, Div Yield, Yield on Cost, 5Y Div Growth, Payout, Consecutive Years (CCC streak), Paid Since (year of first dividend payment, from Notion), and Timing (most recent dividend raise pay-month, from Fish CCC).
</div>

<div class="doc-body">
<b>Paid Since</b> requires a "Paid Since" Number property on the MCP Master Holdings Notion database. Per-ticker values are sourced from dividendinvestor.com (First Dividend Paid field). Blanks render as em-dashes. The Notion cache TTL is 5 minutes.
</div>

<div class="doc-body">
<b>Timing</b> is sourced from Fish CCC column Q ("Last Increased on: Pay") — the actual month of the most recent dividend-raise payment. This replaced an earlier yfinance modal-month heuristic that missed recent raises.
</div>

<div class="doc-subsection">Risk Correlation Sub-tab</div>
<div class="doc-body">
Holdings correlation matrix (90-day rolling) plus risk metrics per position. Identifies concentration risks and pairs that move together.
</div>

<div class="doc-subsection">Attribution Sub-tab</div>
<div class="doc-body">
Position-level YTD attribution: each holding's weight × YTD return, sorted by contribution. Shows which positions drove the strategy's YTD performance and which detracted.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# STOCK DETAIL PAGE
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Stock Detail Page</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Accessible by clicking a ticker row in the Holdings Detail, Dividends Detail, or Watchlist tabs. Also reachable via the searchable ticker selector at the top of the page. Sections appear in this order:
</div>

<table class="doc-table">
<tr><th>Section</th><th>Source</th><th>Details</th></tr>
<tr><td>Company Profile Header</td><td><span class="doc-source">yfinance</span></td><td>Ticker, company name, sector · industry. Compact nameplate at top of page.</td></tr>
<tr><td>Quick Stats Row</td><td><span class="doc-source">yfinance</span></td><td>Mkt Cap, Div Yield, Div Rate, P/E. Fundamental context only — price stats live in the Focus card under the Price Chart.</td></tr>
<tr><td>MCP Investment Thesis</td><td><span class="doc-source">Notion</span></td><td>Pulled from the callout block on the ticker's wiki page in Notion (Active or Archived Holdings). Archived tickers show the sell thesis.</td></tr>
<tr><td>Price Chart</td><td><span class="doc-source">Supabase</span> <span class="doc-source">yfinance</span></td><td>Focus stats card (Last / 1D Chg / YTD / 52W Range bar) above the chart. Period selector: 1M / 3M / YTD / 1Y / 2Y / 3Y / 5Y / 10Y / Max. Data primarily from Supabase prefetch, yfinance fallback when needed.</td></tr>
<tr><td>Valuation Metrics</td><td><span class="doc-source">Finviz</span></td><td>P/E, forward P/E, P/S, P/B, PEG, EV/EBITDA, analyst consensus, price targets, SMA signals</td></tr>
<tr><td>Revenue / Earnings / Margins</td><td><span class="doc-source">Finviz</span></td><td>Revenue, net income, profit margin, operating margin, ROE</td></tr>
<tr><td>Sector Peers</td><td><span class="doc-source">Finviz</span></td><td>Up to 8 peers in the same sector with comparative valuation metrics</td></tr>
<tr><td>Dividend History</td><td><span class="doc-source">Fish CCC</span> <span class="doc-source">yfinance</span></td><td>Annual dividend totals, year-over-year increase %, CAGR. Fish CCC is primary; yfinance is fallback for non-CCC tickers. Source badge shows which is used.</td></tr>
<tr><td>Dividend Commentary</td><td><span class="doc-source">Notion</span></td><td>Earnings call notes and dividend commentary from the ticker's "Dividend Commentary" subpage in Notion</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# PERFORMANCE TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Performance Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Strategy performance vs benchmarks using authoritative composite return data from Composite Returns.xlsx (updated quarterly). Coverage: QDVD since Jun 2010, SMID since Dec 2014, DAC since Dec 2015, OR since Sep 2017. All returns shown gross of fees. The parser auto-detects strategy block rows by scanning for label text rather than using hard-coded row numbers, so it survives row insertions when the file is updated. Both .xls (xlrd) and .xlsx (openpyxl) formats are supported.
</div>

<div class="doc-subsection">Strategy Benchmarks (from Composite Returns)</div>
<table class="doc-table">
<tr><th>Strategy</th><th>Primary Benchmark</th><th>Secondary Benchmark</th></tr>
<tr><td>QDVD</td><td>S&P 500</td><td>S&P 500 High Dividend</td></tr>
<tr><td>SMID</td><td>S&P Mid Cap 400</td><td>S&P 400 Aristocrats</td></tr>
<tr><td>DAC</td><td>Russell 3000</td><td>Dow Jones Select Dividend</td></tr>
<tr><td>OR</td><td>S&P 500</td><td>—</td></tr>
</table>

<div class="doc-subsection">Period Return Cards</div>
<div class="doc-body">
Cards above the chart showing QTD, YTD, 1Y, 3Y, 5Y, 10Y, and Since Inception (annualized) returns. Each card includes alpha vs the primary benchmark. These come directly from Cameron's quarterly composite spreadsheet — the as-of date in the caption matches Composite Returns. Chart's date-range selector does NOT change these cards.
</div>

<div class="doc-subsection">Growth of $100 Chart</div>
<div class="doc-body">
Cumulative performance chart with strategy (solid line) and benchmarks (dashed lines) overlaid. Primary benchmark is the brighter dashed line; secondary is lighter. Six preset range buttons (YTD / 1Y / 3Y / 5Y / 10Y / All) plus "From" and "To" date inputs for custom windows. The chart re-bases to $100 at the selected start date. Hover tooltips and legend show percent return from window start (e.g. "Quality Dividend +38.35%") rather than dollar values. Pan/zoom is disabled.
</div>

<div class="doc-subsection">Risk Metrics Row 1</div>
<table class="doc-table">
<tr><th>Metric</th><th>Calculation</th></tr>
<tr><td>Sharpe Ratio</td><td>(Annualized return − risk-free rate) / annualized standard deviation. Risk-free rate: 4%.</td></tr>
<tr><td>Sortino Ratio</td><td>Same as Sharpe but only uses downside deviation (negative returns only)</td></tr>
<tr><td>Beta</td><td>Covariance of strategy returns with primary benchmark returns / variance of benchmark returns</td></tr>
<tr><td>Max Drawdown</td><td>Largest peak-to-trough decline in cumulative returns over the period</td></tr>
<tr><td>Tracking Error</td><td>Annualized standard deviation of (strategy return − primary benchmark return)</td></tr>
<tr><td>Information Ratio</td><td>Annualized alpha / tracking error</td></tr>
</table>

<div class="doc-subsection">Capture & Drawdown Row 2 (Sprint 24-3)</div>
<table class="doc-table">
<tr><th>Metric</th><th>Calculation</th></tr>
<tr><td>Rolling 12M Std</td><td>Annualized vol over trailing 12 months</td></tr>
<tr><td>Worst Quarter</td><td>Lowest single-quarter return in series</td></tr>
<tr><td>Rolling 6M Loss Count</td><td>Number of 6-month rolling periods with negative return</td></tr>
<tr><td>Rolling Qtr Loss Count</td><td>Number of quarterly rolling periods with negative return</td></tr>
<tr><td>Calmar Ratio</td><td>Trailing 36-month annualized return / |36-month max drawdown|</td></tr>
<tr><td>MAR Ratio</td><td>Since-inception annualized return / |max drawdown|</td></tr>
<tr><td>Up Capture (Monthly)</td><td>Strategy avg return in benchmark-positive months / benchmark avg return in those months</td></tr>
<tr><td>Down Capture (Monthly)</td><td>Strategy avg return in benchmark-negative months / benchmark avg return in those months</td></tr>
<tr><td>Up / Down Capture (Quarterly)</td><td>Same as monthly but on quarterly returns</td></tr>
<tr><td>Ann Return When Bench Neg</td><td>Strategy annualized return computed only over periods when primary benchmark was negative</td></tr>
<tr><td>R-Squared Primary / Secondary</td><td>Coefficient of determination against each benchmark</td></tr>
</table>

<div class="doc-body">
Both risk metric rows have an "as of [date] · full series" caption — these don't update with the chart's date range. The chart can be scoped to any window without affecting the risk numbers, which always reflect the full composite return series.
</div>

<div class="doc-subsection">Monthly Returns Heatmap</div>
<div class="doc-body">
Monthly returns in a grid, color-coded green (positive) to red (negative). Newest year on top, scrollable on mobile to prevent column squishing.
</div>

<div class="doc-subsection">Calendar Year Returns</div>
<div class="doc-body">
Annual returns table showing strategy vs benchmarks with an Alpha column calculated against the primary benchmark.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# DIVIDENDS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Dividends Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Three sub-tabs: <b>Announcements</b> (upcoming ex-dividend calendar), <b>Dividend Detail</b> (full sortable metrics table with row-click drill-through to Stock Detail), and <b>Safety & Growth</b> (analytics — growth tier distribution, safety scores, payout chart, risk monitor).
</div>

<div class="doc-subsection">Dividend Detail Sub-tab KPI Row</div>
<div class="doc-body">
Five cards summarizing the strategy's dividend growth profile: Avg 1Y Div Growth, Avg 3Y Div Growth, Avg 5Y Div Growth, Avg 10Y Div Growth, and Avg Consecutive Years. Simple averages across holdings with valid data, excluding zeros and outliers (range guard: -50% to +100%). The 10Y row primarily uses Fish CCC data; holdings without a CCC streak show 0 and are excluded from the average.
</div>

<div class="doc-subsection">Dividend Safety Grades</div>
<div class="doc-body">
Each holding receives a letter grade (A+ through C) based on a composite score of three factors. Methodology is documented in the collapsible expander on the Safety & Growth sub-tab.
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
Holdings are grouped into tiers based on their 5-year dividend CAGR from Fish CCC. Non-Fish tickers with unreliable growth data (e.g. ADRs with FX-distorted payouts) are placed in an "Uncertain (non-CCC)" tier rather than being mislabeled as cuts.
</div>

<div class="doc-subsection">Dividend Calendar</div>
<div class="doc-body">
Generated weekly by dividend_calendar.py via Windows Task Scheduler. The script auto-commits and pushes to GitHub so the dashboard picks it up. Shows upcoming ex-dividend dates, amounts, and yield for all holdings.
</div>

<div class="doc-subsection">Data Sources</div>
<table class="doc-table">
<tr><th>Data Point</th><th>Primary Source</th><th>Fallback</th></tr>
<tr><td>Consecutive years of increases</td><td><span class="doc-source">Fish CCC</span></td><td>yfinance dividend history</td></tr>
<tr><td>5Y dividend CAGR</td><td><span class="doc-source">Fish CCC</span></td><td>Computed from yfinance annual totals</td></tr>
<tr><td>1Y dividend growth</td><td><span class="doc-source">Fish CCC</span></td><td>yfinance</td></tr>
<tr><td>Payout ratio</td><td><span class="doc-source">Finviz</span></td><td>yfinance</td></tr>
<tr><td>Ex-dividend dates</td><td><span class="doc-source">yfinance</span></td><td>—</td></tr>
<tr><td>Yield on cost</td><td><span class="doc-source">Tamarac</span></td><td>Fallback chain when yield_at_cost is missing (template 41 zeros it for many positions): annual_income / cost_basis, then annual_income / (qty × unit_cost) using the manual file. Holdings missing all three render em-dash.</td></tr>
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
Research candidate pipeline from Watchlists.xlsx (5 sheets: QDVD Watchlist A, QDVD Watchlist B, SMID Watchlist A, SMID Watchlist B, C Watch). Independent of Tamarac — loads tickers from the Excel file and enriches them with live yfinance data. A dropdown selector switches between watchlists.
</div>

<div class="doc-subsection">Table Columns</div>
<table class="doc-table">
<tr><th>Column</th><th>Source</th><th>Notes</th></tr>
<tr><td>Ticker</td><td><span class="doc-source">Watchlists.xlsx</span></td><td>Click any row to navigate to the Stock Detail page</td></tr>
<tr><td>Company</td><td><span class="doc-source">yfinance</span></td><td>Long name from yfinance</td></tr>
<tr><td>Sector</td><td><span class="doc-source">yfinance</span></td><td>Normalized via normalize_sector()</td></tr>
<tr><td>Price</td><td><span class="doc-source">yfinance</span></td><td>Current price</td></tr>
<tr><td>Div Yield</td><td><span class="doc-source">yfinance</span></td><td>Trailing 12-month yield, capped at 15% to filter out yfinance data glitches</td></tr>
<tr><td>P/E, Fwd P/E</td><td><span class="doc-source">yfinance</span></td><td>Trailing and forward earnings multiples</td></tr>
<tr><td>Beta</td><td><span class="doc-source">yfinance</span></td><td>3-year beta vs S&P 500</td></tr>
<tr><td>Mkt Cap</td><td><span class="doc-source">yfinance</span></td><td>Pre-formatted string (e.g. "$2.5T") — sorts lexicographically, not by numeric value</td></tr>
<tr><td>% From 52W Hi</td><td><span class="doc-source">yfinance</span></td><td>Negative = below the 52-week high</td></tr>
</table>

<div class="doc-subsection">Bottom Chart</div>
<div class="doc-body">
Horizontal bar chart comparing dividend yields across watchlist tickers, sorted ascending. Color-graded blue → gold → green by yield level.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MACRO TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Macro Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Macro environment context for dividend strategy positioning. Rate and economic data from FRED. Market valuation from yfinance. Fed Meeting probabilities from Kalshi prediction markets.
</div>

<div class="doc-subsection">Rates & Yields</div>
<div class="doc-body">
Live rate cards showing Fed Funds Rate, 2Y/10Y/30Y Treasury yields, 2s10s spread, and 15Y/30Y mortgage rates. The 2s10s spread is computed as (10Y yield − 2Y yield) × 100 basis points.
</div>

<div class="doc-subsection">Dividend Strategy Context</div>
<table class="doc-table">
<tr><th>Metric</th><th>Calculation</th></tr>
<tr><td>Yield Comparison</td><td>30Y Treasury yield vs S&P 500 dividend yield vs QDVD weighted yield — shows whether dividend stocks are competitive with bonds for income</td></tr>
<tr><td>Equity Risk Premium</td><td>S&P 500 earnings yield (1 / forward P/E × 100) minus the 30Y Treasury yield. Expressed in basis points. Below 50bp is flagged as tight.</td></tr>
<tr><td>IG Credit Spread</td><td>ICE BofA US Corporate Investment Grade OAS from FRED (BAMLC0A0CM), converted to basis points. Historical average ~120bp. Green &lt;100bp, Gold 100-180bp, Red &gt;180bp. Tight spreads = healthy credit conditions for dividend-paying companies.</td></tr>
</table>

<div class="doc-subsection">Sentiment</div>
<table class="doc-table">
<tr><th>Metric</th><th>Source</th><th>Signal Thresholds</th></tr>
<tr><td>VIX</td><td><span class="doc-source">yfinance</span></td><td>Green &lt;16, Gold 16-25, Red &gt;25</td></tr>
<tr><td>UMich Sentiment</td><td><span class="doc-source">FRED</span></td><td>Green &gt;80, Gold 60-80, Red &lt;60</td></tr>
<tr><td>Yield Curve</td><td><span class="doc-source">FRED</span></td><td>Green if normal (positive spread), Red if inverted</td></tr>
</table>

<div class="doc-body">
If a sentiment source is briefly unavailable, the row renders an em-dash placeholder rather than disappearing — keeps the layout stable across data states.
</div>

<div class="doc-subsection">Fed Meeting Calendar (Sprint 25-3)</div>
<div class="doc-body">
Live FOMC meeting probabilities from Kalshi's public prediction-market API. For each upcoming meeting, the dashboard reads the Kalshi market whose strike is 25bp below the current Fed Funds upper bound (from FRED series DFEDTARU) and computes P(at least one cut by that meeting) = 1 − YES price at that strike. Cached 15 minutes.
</div>

<div class="doc-body">
Color coding: ≥50% green ("Cut likely"), 30-49% gold ("Cut possible"), &lt;30% muted ("Hold likely"). Caveat — Kalshi's FOMC market liquidity is thinner than CME FedWatch, so far-out meetings (e.g. 6+ months) can reflect just a handful of recent trades. The closest meetings are most reliable.
</div>

<div class="doc-body">
Fallback: if Kalshi or FRED are unreachable, the widget renders a placeholder with a link to CME FedWatch.
</div>

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
Forward P/E, earnings yield, equity risk premium, S&P dividend yield (scraped from multpl.com), QDVD yield premium, and mortgage rates. Rendered in a single table with signal badges (positive, neutral, watch, alert, elevated).
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# MARKETS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Markets Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Broad market snapshot using ETF proxies and actual index tickers, organized into two sub-tabs (Tables and Charts). All data comes from a single batched yfinance call (~50 tickers), cached 15 minutes.
</div>

<div class="doc-subsection">Tables Sub-tab</div>
<div class="doc-body">
Compact tables grouped by section (Indices, Dividend Benchmarks, Sectors, Commodities, Fixed Income, Global Developed, Global Emerging), sorted by daily performance within each.
</div>

<div class="doc-subsection">Charts Sub-tab</div>
<div class="doc-body">
Lazy-loaded focus-chart layout (Sprint 18). Click "Load charts" to fetch a year of daily history for all ~50 tickers in one batch. Within each section, click a ticker pill to make it the focus — its full history renders below alongside a stats card (LAST / 1D / YTD / 52W range). Pill density adapts to name length: 3 per row for INDICES and DIVIDEND_BENCHMARKS, 4 for most sections, 6 for COMMODITIES. On mobile, all pills stack vertically. Period selector matches Holdings: 1M / 3M / YTD / 1Y / 2Y / 3Y / 5Y / 10Y / Max.
</div>

<table class="doc-table">
<tr><th>Section</th><th>Tickers</th><th>Notes</th></tr>
<tr><td>Indices</td><td>Nasdaq 100, DJIA, Russell 2000, Russell 1000 Value/Growth, AGG</td><td>S&P 500 lives in Dividend Benchmarks since it's the primary benchmark for QDVD/DAC/OR</td></tr>
<tr><td>Dividend Benchmarks</td><td>S&P 500, SPYD, SDY, REGL, S&P 400, Russell 3000, DWX, DVY</td><td>Key benchmarks for dividend strategies</td></tr>
<tr><td>S&P Sector ETFs</td><td>XLK, XLV, XLF, XLY, XLP, XLI, XLE, XLU, XLRE, XLB, XLC</td><td>All 11 GICS sectors</td></tr>
<tr><td>Commodities</td><td>GC=F, SI=F, CL=F, BZ=F, NG=F, HG=F, BTC-USD</td><td>Actual futures contracts plus Bitcoin</td></tr>
<tr><td>Fixed Income</td><td>^TNX, GOVT, TIP, LQD, HYG, MUB, CWB</td><td>10Y Treasury yield + Government, TIPS, IG, HY, Munis, Convertibles</td></tr>
<tr><td>Global Developed</td><td>EFA, EWJ, EWU, EWG, EWA, EWQ</td><td>Broad + major countries</td></tr>
<tr><td>Global Emerging</td><td>EEM, FXI, EPI, EWZ, EWW, EWY, EZA</td><td>Broad + major countries</td></tr>
</table>

<div class="doc-subsection">US Equity Factors Style Box</div>
<div class="doc-body">
A Koyfin-inspired 3×3 grid showing 1-day performance by size (Large/Mid/Small) and style (Value/Core/Growth) using 9 iShares Russell ETFs (IWD, IWB, IWF, IWS, IWR, IWP, IWN, IWM, IWO). Color intensity scales with daily change magnitude.
</div>

<div class="doc-subsection">% From High Column</div>
<div class="doc-body">
Distance from each ticker's 52-week high, calculated from 1 year of daily data. Red for any value below the high; green "AT HIGH" if at the 52-week peak.
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# NEWS & ALERTS TAB
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">News & Alerts Tab</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Section order: Portfolio Alerts (top), then Market Headlines, then Holdings News (bottom). Alerts are computed live; news is fetched and filtered for relevance and quality.
</div>

<div class="doc-subsection">Portfolio Alerts</div>
<div class="doc-body">
Computed live from Supabase + yfinance data across all unique tickers in the active strategy. Three categories:
</div>

<table class="doc-table">
<tr><th>Alert Type</th><th>Trigger</th><th>Data Source</th></tr>
<tr><td>Price Movers</td><td>Any holding with a daily move exceeding ±2%</td><td><span class="doc-source">Supabase</span></td></tr>
<tr><td>Dividend Events</td><td>Ex-dividend dates within 14 days (ex-dates only; dividend growth/decline alerts removed due to ADR/FX distortion)</td><td><span class="doc-source">Supabase</span></td></tr>
<tr><td>Upcoming Earnings</td><td>Holdings reporting within the next 14 days</td><td><span class="doc-source">yfinance</span> (cached 1hr)</td></tr>
</table>

<div class="doc-body">
The 52-Week Proximity alert category was removed in Sprint 25. Its data (price vs 52W high/low) is still visible in the Holdings table and Stock Detail Focus card.
</div>

<div class="doc-subsection">Market Headlines</div>
<div class="doc-body">
Four markets-focused RSS feeds (Sprint 25): CNBC Markets, MarketWatch Markets, Reuters Business, WSJ Markets. Fetched via feedparser, cached 15 minutes. Up to 12 headlines displayed, sorted newest first. Each headline links to the original article. If any feed is briefly unavailable the others still populate.
</div>

<div class="doc-subsection">Holdings News</div>
<div class="doc-body">
Ticker-specific news fetched via yfinance's .news property for all tickers in the active strategy. Filtered for relevance and quality. Up to 15 articles displayed, cached 15 minutes.
</div>

<div class="doc-body">
Three-stage filter chain (Sprint 25):
</div>

<div class="doc-calc">
1. Title relevance — ticker symbol or company name token must appear in the headline<br>
2. Listicle blocklist — drops "X top stocks", "stocks to buy/watch", "should you buy", "retirement income", "millionaire makers", "passive income", "buy the dip", etc.<br>
3. Publisher quality — Reuters / Bloomberg / WSJ / Barron's / FT / Seeking Alpha / CNBC / MarketWatch / NYT / AP / Axios / Fortune / Forbes are kept. Zacks / MarketBeat / Motley Fool / InvestorPlace / Benzinga / GuruFocus / Insider Monkey / Simply Wall St / 24/7 Wall St / SmartAsset / Investopedia / ValueWalk / TalkMarkets / TipRanks are suppressed unless they're the only result for a ticker (one junk fallback allowed per ticker rather than no result at all).
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# DATA PIPELINE
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Data Pipeline & Refresh</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Market data refreshes automatically during trading hours via prefetch_cloud.py running as a GitHub Actions workflow, triggered by an external cron job (cron-job.org) every 15 minutes.
</div>

<table class="doc-table">
<tr><th>Component</th><th>Frequency</th><th>Details</th></tr>
<tr><td>Supabase price data</td><td>Every 15 min (market hours)</td><td>prefetch_cloud.py runs via GitHub Actions. Fetches prices, changes, yields, 52-week data from yfinance and writes to Supabase prices + dividends tables.</td></tr>
<tr><td>Tamarac Holdings (Auto)</td><td>Daily, automated</td><td>Auto-pull script at Operations/Scripts/Tamarac Developer Portal/ pulls the Template 41 holdings export via the Tamarac Developer API. ZIP magic-byte detection, extracts the report, drops it in data/Tamarac_Holdings.xlsx. The five target composites (QDVD = *QDG, SMID, DAC, OR = *QDGR, DCP = 25208165 with display name override) are confirmed in the parser.</td></tr>
<tr><td>Tamarac Manual File</td><td>Quarterly (manual)</td><td>data/Tamarac_Holdings_Manual.xlsx provides per-(strategy_code, symbol) lookup for unit_cost, cost_basis, annual_income, cumulative_income, yield_at_cost, current_yield. The API template 41 zeros these for many positions, so the manual file fills the gap. Implemented in tamarac_parser.py.</td></tr>
<tr><td>File Watcher (Auto-commit)</td><td>Real-time</td><td>watch_tamarac.py + Start_Tamarac_Watcher.vbs monitor Tamarac_Holdings.xlsx, Watchlists.xlsx, Composite Returns (.xlsx/.xls), and Fish CCC files (glob-based, auto-removes old versions). Detects changes and auto-commits/pushes to GitHub within ~60 seconds.</td></tr>
<tr><td>Fish CCC data</td><td>Monthly</td><td>David Fish CCC spreadsheet placed in data/ folder. File pattern: Fish_*.xlsx (glob selects newest).</td></tr>
<tr><td>Composite Returns</td><td>Quarterly</td><td>data/Composite Returns.xlsx — official Tamarac-sourced strategy and benchmark returns. Updated each quarter.</td></tr>
<tr><td>Dividend Calendar</td><td>Weekly (Monday)</td><td>Generated by dividend_calendar.py via Windows Task Scheduler. Auto-commits and pushes to GitHub.</td></tr>
<tr><td>monthly_returns.py</td><td>Monthly (manual)</td><td>Tamarac-sourced YTD figures per strategy. Edit STRATEGY_YTD dict and AS_OF_DATE at start of each month.</td></tr>
<tr><td>Notion data</td><td>Live (cached 5-60 min)</td><td>Investment theses, dividend commentary, MCP price targets, Paid Since field. Notion cache TTL varies by query (5 min for Paid Since lookup, 1 hr for theses).</td></tr>
<tr><td>Finviz data</td><td>Live (cached 15 min)</td><td>Analyst data, valuation metrics, sector peers fetched via finvizfinance library.</td></tr>
<tr><td>FRED data</td><td>Live (cached 1 hr)</td><td>Rates, economic indicators, sentiment data fetched from FRED API.</td></tr>
<tr><td>Kalshi data</td><td>Live (cached 15 min)</td><td>FOMC meeting probabilities fetched from Kalshi public API. No auth required.</td></tr>
</table>

<div class="doc-subsection">Cron Job Maintenance</div>
<div class="doc-body">
The cron-job.org trigger uses a GitHub Personal Access Token (classic, repo scope) to dispatch the prefetch workflow. If the token expires, update the Authorization header in cron-job.org. Cron hours are set in EDT (UTC-4); a Python safety-net in prefetch_cloud.py handles EST fallback if needed.
</div>

<div class="doc-subsection">Caching Architecture</div>
<div class="doc-body">
Three-tier cache for expensive computations (Performance tab returns, dividend enrichment, batch yfinance fetches): in-memory @st.cache_data → disk @disk_cached (utils/disk_cache.py) with per-namespace version param → full rebuild on miss. Cache invalidation: bump the version param on the decorator AND ensure the function name actually changes — Streamlit Cloud has been observed serving stale rows even after a version bump. Renaming the function (e.g. _enriched_df_for_strategy → _enriched_df_for_strategy_v2) is the bulletproof bust because Python can't serve a cache entry under a name that no longer exists.
</div>

<div class="doc-subsection">Data Freshness Display</div>
<div class="doc-body">
The "Data refreshed X ago" indicator reads the most recent fetched_at timestamp from Supabase (sorted by fetched_at DESC). All timestamps are stored and compared in timezone-aware UTC. Pacific time display automatically adjusts for PDT/PST using Python's zoneinfo module.
</div>

<div class="doc-subsection">Tamarac File Detection</div>
<div class="doc-body">
The dashboard uses the internal "As of Date" from cell A2 of the Tamarac Excel file to determine data freshness — not the filesystem modification time. This is immune to OneDrive sync timestamps. The banner shows the as-of date and flags data older than 7 days as stale.
</div>

<div class="doc-subsection">Supabase Disk IO</div>
<div class="doc-body">
Free-tier Supabase has a Disk IO ceiling. The dividend_history table (4,190 rows rewritten every morning) was the primary IO contributor and was retired — Fish CCC is now the authoritative source for historical dividend data, streaks, and DGR calculations. The financials table (~200 rows, 114 tickers, deterministic IDs) is well-behaved.
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
<tr><td>yfinance</td><td>Real-time prices, dividend data, earnings dates, historical data, news feed</td><td>Python library (unofficial Yahoo Finance)</td><td>Free</td></tr>
<tr><td>FRED</td><td>Treasury yields, economic indicators, mortgage rates, sentiment, Fed target rate</td><td>REST API (key required)</td><td>Free</td></tr>
<tr><td>Notion API</td><td>Investment theses, dividend commentary, MCP price targets, holdings metadata, Paid Since</td><td>REST API (integration token)</td><td>Free</td></tr>
<tr><td>Finviz Elite</td><td>Analyst ratings, valuation metrics, sector peers, insider activity</td><td>finvizfinance Python library</td><td>Existing subscription</td></tr>
<tr><td>Fish CCC</td><td>Dividend streak data, growth rates, consecutive years, last raise pay-month</td><td>Monthly Excel spreadsheet</td><td>Free (David Fish list)</td></tr>
<tr><td>Tamarac</td><td>Portfolio holdings, weights, cost basis, yield on cost, composite returns</td><td>Tamarac Developer Portal API (auto) + quarterly composite export (manual)</td><td>Existing subscription</td></tr>
<tr><td>Kalshi</td><td>FOMC meeting cut probabilities</td><td>Public REST API (no auth)</td><td>Free</td></tr>
<tr><td>RSS Feeds</td><td>Market news headlines (CNBC Markets, MarketWatch Markets, Reuters Business, WSJ Markets)</td><td>feedparser Python library</td><td>Free</td></tr>
<tr><td>multpl.com</td><td>S&P 500 trailing P/E and dividend yield</td><td>BeautifulSoup scrape</td><td>Free</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# CHANGE LOG
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Recent Changes</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-body">
Selected sprint history for major dashboard changes. Full git log is the authoritative reference.
</div>

<table class="doc-table">
<tr><th>Sprint</th><th>Date</th><th>Changes</th></tr>
<tr><td>25-4</td><td>May 2026</td><td>Documentation page refresh (this update)</td></tr>
<tr><td>25-3</td><td>May 2026</td><td>Fed Meeting Calendar replaced with live Kalshi data; Sentiment card robustness fix with em-dash fallbacks; Watchlist horizontal vibration fix</td></tr>
<tr><td>25-2</td><td>May 2026</td><td>Watchlist converted to st.dataframe with row-click drill-through to Stock Detail</td></tr>
<tr><td>25</td><td>May 2026</td><td>Dead code purge (strategy_selector.py, performance.py, _render_income_dashboard); Stock Detail price displays consolidated into Focus stats card</td></tr>
<tr><td>24-5</td><td>May 2026</td><td>Warbook Paid Since field from Notion; Timing column from Fish CCC pay-date</td></tr>
<tr><td>24</td><td>May 2026</td><td>Performance tab: monthly heatmap newest-on-top; chart date-range controls (preset + custom); Capture & Drawdown metrics row (13 new fields); hover format showing % return from window start</td></tr>
<tr><td>20</td><td>Earlier</td><td>Stock Detail period selector matched to Holdings (10Y); Watchlist sector normalize; replaced Payout column with "% From 52W Hi"</td></tr>
<tr><td>18</td><td>Earlier</td><td>Markets Charts redesign: focus charts with ticker pills, lazy-load gate, stats card</td></tr>
</table>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# OPERATIONS NOTES
# ══════════════════════════════════════════════════════════════════════════
st.markdown('<div class="doc-section">Operations Notes</div>', unsafe_allow_html=True)

st.markdown("""
<div class="doc-subsection">Repo Layout</div>
<div class="doc-body">
Working repo at C:\\Users\\RyanAdair\\Martin Capital Partners LLC\\Eugene - Documents\\Operations\\Scripts\\Portfolio Dashboard, with .git as an NTFS junction pointing to C:\\GitData\\mcp-dashboard.git. OneDrive cannot touch the junction target. Verify integrity with: Get-Item .\\.git | Select LinkType,Target. If broken: clone fresh from github.com/ryansadair/mcp-dashboard.git, recreate the .git junction with mklink /J. GitHub is source of truth — nothing is ever lost.
</div>

<div class="doc-subsection">Monthly Updates Required</div>
<table class="doc-table">
<tr><th>Item</th><th>Cadence</th><th>Action</th></tr>
<tr><td>monthly_returns.py</td><td>Start of each month</td><td>Update STRATEGY_YTD dict and AS_OF_DATE with prior month-end Tamarac figures</td></tr>
<tr><td>Fish CCC spreadsheet</td><td>Monthly</td><td>Drop new Fish_MMDDYYYY.xlsx into data/ — watch_tamarac removes the old one automatically</td></tr>
<tr><td>Composite Returns</td><td>Quarterly</td><td>Drop new Composite Returns.xlsx into data/ — watcher auto-commits</td></tr>
<tr><td>Tamarac Holdings Manual</td><td>Quarterly</td><td>Refresh data/Tamarac_Holdings_Manual.xlsx with current unit_cost / cost_basis / yield_at_cost for legacy positions</td></tr>
<tr><td>Notion Paid Since field</td><td>One-time + as needed</td><td>Add "Paid Since" Number property to MCP Master Holdings DB; per-ticker values from dividendinvestor.com</td></tr>
</table>

<div class="doc-subsection">Authentication Tokens to Maintain</div>
<table class="doc-table">
<tr><th>Token</th><th>Used By</th><th>Refresh Action</th></tr>
<tr><td>GitHub PAT (classic, repo scope)</td><td>cron-job.org → workflow dispatch</td><td>Update Authorization header in cron-job.org when PAT expires</td></tr>
<tr><td>Notion Integration Token</td><td>Notion API calls</td><td>Streamlit secrets — rarely needs rotation</td></tr>
<tr><td>FRED API Key</td><td>FRED API calls</td><td>Free, doesn't expire</td></tr>
<tr><td>Tamarac Developer API credentials</td><td>Auto-pull script</td><td>Stored outside the dashboard repo (Operations/Scripts/Tamarac Developer Portal/) to prevent accidental commit</td></tr>
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