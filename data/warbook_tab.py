"""
Martin Capital Partners — Warbook Tab
data/warbook_tab.py

Replaces the printed "Warbook" spreadsheets (Strategy Holdings Overview,
QDG Characteristics, Risk Correlation, Attribution) with on-screen views
fed by Tamarac, yfinance, Notion, and the Distress Scorecard.

Sprint 23B scope:
  • Strategy Overview (Tab 1)  — yield, cost basis, MCP target, CLD,
                                 style bucket, dividend baseline & growth,
                                 date evaluated. Sorted by weight desc.
  • Attribution (Tab 4)        — total return windows (MTD/QTD/YTD/3M/1Y)
                                 plus vs-SPX, % from 52W high, leverage,
                                 ROE 5yr avg, EPS / CF / FCF div coverage,
                                 forward P/E, CF/EV yield. Sorted by
                                 weight desc.

Sprint 23C will add:
  • QDG Characteristics (Tab 2)
  • Risk Correlation   (Tab 3)
  • Per-tab PDF export

Notes:
  - DCP is excluded from warbook scope (MCP doesn't print warbook for DCP)
  - Strategy-aware: uses the active_strategy from Dashboard.py
  - All Notion fields are pulled via fetch_notion_metrics()
  - All yfinance-derived fields come from warbook_metrics.fetch_warbook_metrics_batch()
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils.config import BRAND, normalize_sector
from data.tamarac_parser import get_holdings_for_strategy
from data.market_data import fetch_batch_prices
from data.notion_metrics import fetch_notion_metrics
from data.warbook_metrics import fetch_warbook_metrics_batch
from data.dividends import get_batch_dividend_details
from data.warbook_export import (
    build_strategy_xlsx,
    build_single_tab_xlsx,
    build_filename,
)

# Fish CCC data is optional — gracefully degrade if not available
try:
    from data.dividend_streaks import get_fish_metrics, get_dividend_history
    FISH_AVAILABLE = True
except ImportError:
    FISH_AVAILABLE = False


# ── Strategies that get a warbook (DCP excluded per MCP workflow) ─────────
WARBOOK_STRATEGIES = {"DAC", "OR", "QDVD", "SMID"}


def _fmt_date_short(dt):
    """
    Format a datetime as M/YY (e.g., "1/20" for Jan 2020). Cross-platform —
    avoids the Linux-only %-m / Windows-only %#m strftime tokens by building
    the string from datetime attributes directly.
    """
    if dt is None:
        return ""
    try:
        return f"{dt.month}/{str(dt.year)[-2:]}"
    except (AttributeError, TypeError):
        return ""


def _fmt_date_md(dt):
    """Format a datetime as M/D/YY. Cross-platform (no strftime tokens)."""
    if dt is None:
        return ""
    try:
        return f"{dt.month}/{dt.day}/{str(dt.year)[-2:]}"
    except (AttributeError, TypeError):
        return ""


# Super Sector mapping. Mirrors the one in warbook_metrics.py but applied at
# render time using the Supabase-sourced sector (not yfinance info, which is
# throttled on Streamlit Cloud). Supabase reliably has the sector string.
_SUPER_SECTOR_BY_SECTOR = {
    # Cyclical
    "Materials":               "Cyclical",
    "Basic Materials":         "Cyclical",
    "Consumer Discretionary":  "Cyclical",
    "Consumer Cyclical":       "Cyclical",
    "Financials":              "Cyclical",
    "Financial Services":      "Cyclical",
    "Real Estate":             "Cyclical",
    # Sensitive
    "Communication Services":  "Sensitive",
    "Energy":                  "Sensitive",
    "Industrials":             "Sensitive",
    "Technology":              "Sensitive",
    # Defensive
    "Consumer Staples":        "Defensive",
    "Consumer Defensive":      "Defensive",
    "Healthcare":              "Defensive",
    "Utilities":               "Defensive",
}


def _is_num(v):
    """
    True if v is a non-NaN numeric. Used by all format lambdas in this module
    because pandas coerces None to NaN when building DataFrames with mixed
    columns, and isinstance(NaN, float) is True — so a plain isinstance check
    would render NaN as "nanx" or "nan%" instead of an em dash.
    """
    if v is None:
        return False
    if not isinstance(v, (int, float)):
        return False
    # NaN check: NaN is the only float that doesn't equal itself
    return v == v


def render_warbook_tab(tamarac_parsed, active_strategy, strat_config):
    """
    Top-level entry point. Renders the warbook sub-tabs for the active
    strategy. Called from `1_Dashboard.py` inside `with tab_warbook:`.

    Args:
        tamarac_parsed:    dict {strategy_code: DataFrame}
        active_strategy:   str — current strategy code from session state
        strat_config:      dict — strategy config (name, color, benchmark)
    """
    # Skip DCP — MCP doesn't maintain warbook for DCP
    if active_strategy not in WARBOOK_STRATEGIES:
        st.info(
            f"**Warbook is not maintained for {active_strategy}.**\n\n"
            f"MCP's warbook covers DAC, OR, QDVD, and SMID. Switch to one of "
            f"those strategies above to view the warbook tabs."
        )
        return

    # Need Tamarac data to drive the table
    if not tamarac_parsed or active_strategy not in tamarac_parsed:
        st.info("Tamarac holdings unavailable for this strategy.")
        return

    tam_df = get_holdings_for_strategy(tamarac_parsed, active_strategy)
    if tam_df.empty:
        st.info(f"No holdings in Tamarac file for {active_strategy}.")
        return

    # Compact header — matches scorecard / dividends styling
    strat_name = strat_config.get("name", active_strategy)
    bench_name = strat_config.get("bench_name") or strat_config.get("benchmark", "S&P 500")
    st.markdown(
        f"<div style='font-size:12px;color:rgba(255,255,255,0.45);"
        f"margin-top:-4px;margin-bottom:14px;'>"
        f"<strong>{strat_name}</strong>&nbsp;·&nbsp;"
        f"{len(tam_df)} holdings&nbsp;·&nbsp;"
        f"benchmark {bench_name}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Sub-tabs: 4 warbook views matching the printed spreadsheet layout.
    # All four share the same pre-fetched data underneath.
    sub_overview, sub_qdg, sub_risk, sub_attribution = st.tabs([
        "Strategy Overview",
        "QDG Characteristics",
        "Risk Correlation",
        "Attribution",
    ])

    # Pre-fetch all data once — all four sub-tabs share the same underlying
    # calls. Streamlit's st.tabs() runs every body on every interaction, so
    # any heavy fetches need to be cached. Each of these has its own caching
    # layer (st.cache_data + disk_cached) so this call is cheap on warm
    # cache.
    tickers = tuple(tam_df["symbol"].astype(str).str.upper().tolist())

    with st.spinner("Loading warbook data..."):
        price_data = fetch_batch_prices(tickers)
        notion_data = {}
        try:
            notion_data = fetch_notion_metrics()
        except Exception:
            pass
        div_data = {}
        try:
            div_data = get_batch_dividend_details(tickers)
        except Exception:
            pass
        warbook_data = {}
        try:
            warbook_data = fetch_warbook_metrics_batch(tickers)
        except Exception:
            pass

        # Fish CCC data — for QDG Characteristics tab. Fish has authoritative
        # streak_began (Raised Since), payout_ratio, and DGR series. Each
        # ticker lookup goes through @st.cache_data on _load_fish_data so
        # this batch call is cheap.
        fish_data = {}
        fish_history = {}
        if FISH_AVAILABLE:
            for t in tickers:
                try:
                    m = get_fish_metrics(t)
                    if m:
                        fish_data[t] = m
                    h = get_dividend_history(t)
                    if h:
                        fish_history[t] = h
                except Exception:
                    pass

    # ── XLSX Archive Export (Sprint 23D) ─────────────────────────────────
    # Per-tab download buttons + bundle of all 4. Uses the data dicts
    # already fetched in the spinner block above — no extra calls.
    _render_export_section(
        active_strategy=active_strategy,
        tam_df=tam_df,
        price_data=price_data,
        notion_data=notion_data,
        div_data=div_data,
        warbook_data=warbook_data,
        fish_data=fish_data,
        fish_history=fish_history,
    )

    # ── Strategy Overview (Tab 1) ────────────────────────────────────────
    with sub_overview:
        _render_strategy_overview(
            tam_df, active_strategy,
            price_data, notion_data, div_data,
        )

    # ── QDG Characteristics (Tab 2) ──────────────────────────────────────
    with sub_qdg:
        _render_qdg_characteristics(
            tam_df, active_strategy,
            price_data, notion_data, warbook_data,
            fish_data, fish_history,
        )

    # ── Risk Correlation (Tab 3) ─────────────────────────────────────────
    with sub_risk:
        _render_risk_correlation(
            tam_df, active_strategy,
            price_data, notion_data, warbook_data,
        )

    # ── Attribution (Tab 4) ──────────────────────────────────────────────
    with sub_attribution:
        _render_attribution(
            tam_df, active_strategy,
            price_data, warbook_data,
        )


# ══════════════════════════════════════════════════════════════════════════
# XLSX EXPORT — Sprint 23D
# ══════════════════════════════════════════════════════════════════════════

def _render_export_section(
    *,
    active_strategy,
    tam_df,
    price_data,
    notion_data,
    div_data,
    warbook_data,
    fish_data,
    fish_history,
):
    """
    Renders the xlsx archive download row above the sub-tabs.

    Five buttons in one row:
        [Strategy Overview] [QDG] [Risk] [Attribution] [Download All 4]

    Each download_button accepts BytesIO. The build_*_xlsx functions are
    cheap (~50ms for ~30 holdings on warm cache) since all data dicts are
    already populated. Any build failure is caught and surfaced via st.error
    rather than crashing the warbook.
    """
    st.markdown(
        "<div style='font-size:11px;color:rgba(255,255,255,0.4);"
        "margin-top:4px;margin-bottom:8px;text-transform:uppercase;"
        "letter-spacing:0.06em;font-weight:600;'>"
        "Archive Export"
        "</div>",
        unsafe_allow_html=True,
    )

    col_ov, col_qdg, col_risk, col_attr, col_all = st.columns([1, 1, 1, 1, 1.4])

    common = dict(
        strategy_code=active_strategy,
        tam_df=tam_df,
        price_data=price_data,
        notion_data=notion_data,
        div_data=div_data,
        warbook_data=warbook_data,
        fish_data=fish_data,
        fish_history=fish_history,
    )

    def _safe_build_single(tab_key):
        try:
            return build_single_tab_xlsx(tab_key=tab_key, **common).getvalue()
        except Exception as e:
            st.error(f"{tab_key} export failed: {e}")
            return None

    def _safe_build_all():
        try:
            return build_strategy_xlsx(**common).getvalue()
        except Exception as e:
            st.error(f"Bundle export failed: {e}")
            return None

    MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    with col_ov:
        data = _safe_build_single("overview")
        if data:
            st.download_button(
                label="Strategy Overview",
                data=data,
                file_name=build_filename(active_strategy, tab_key="overview"),
                mime=MIME,
                width="stretch",
                key=f"dl_overview_{active_strategy}",
            )

    with col_qdg:
        data = _safe_build_single("qdg")
        if data:
            st.download_button(
                label="QDG Characteristics",
                data=data,
                file_name=build_filename(active_strategy, tab_key="qdg"),
                mime=MIME,
                width="stretch",
                key=f"dl_qdg_{active_strategy}",
            )

    with col_risk:
        data = _safe_build_single("risk")
        if data:
            st.download_button(
                label="Risk Correlation",
                data=data,
                file_name=build_filename(active_strategy, tab_key="risk"),
                mime=MIME,
                width="stretch",
                key=f"dl_risk_{active_strategy}",
            )

    with col_attr:
        data = _safe_build_single("attribution")
        if data:
            st.download_button(
                label="Attribution",
                data=data,
                file_name=build_filename(active_strategy, tab_key="attribution"),
                mime=MIME,
                width="stretch",
                key=f"dl_attr_{active_strategy}",
            )

    with col_all:
        data = _safe_build_all()
        if data:
            st.download_button(
                label="Download All 4",
                data=data,
                file_name=build_filename(active_strategy),
                mime=MIME,
                width="stretch",
                type="primary",
                key=f"dl_all_{active_strategy}",
            )

    st.markdown(
        "<div style='height:1px;background:rgba(255,255,255,0.06);"
        "margin:14px 0 12px;'></div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — STRATEGY HOLDINGS OVERVIEW
# ══════════════════════════════════════════════════════════════════════════

def _render_strategy_overview(tam_df, active_strategy, price_data, notion_data, div_data):
    """
    Replicates the warbook spreadsheet's "Strategy Holdings Overview" tab.

    Columns (matching the spreadsheet column order, sorted by weight desc):
      Company · Symbol · Weight · Sector · Yield · Original Purchase Date ·
      Cost Basis · Yesterday's Close · Δ from Cost · CLD · CLD Source ·
      MCP Style Bucket · 3yr Upside Tgt · % To Upside · MCP 5yr DG Baseline ·
      5yr Dividend Growth · 5yr DG Exceeds Baseline · Date Evaluated

    Red text formatting: 5yr DG cell when it falls below the MCP baseline
    (matches the spreadsheet's red 4% on PFE).
    """
    rows = []
    for _, h in tam_df.iterrows():
        sym = str(h["symbol"]).strip().upper()
        mkt = price_data.get(sym, {})
        nm = notion_data.get(sym, {})
        dd = div_data.get(sym, {})

        price = mkt.get("price") or 0
        unit_cost = h.get("unit_cost") or 0

        # Δ from Cost — percent change from cost basis to current price
        delta_from_cost = None
        if unit_cost and price:
            delta_from_cost = round((price - unit_cost) / unit_cost * 100, 2)

        # 3yr upside target — pulled from Notion's MCP Target (price target)
        mcp_target = nm.get("mcp_target")

        # % to upside (price-only — TR variant would need dividends over 3y,
        # which we don't have a clean source for. Keeping price-only for
        # parity with the spreadsheet's column header "% To Up Tgt (TR)").
        # TODO: revisit in 23C/D — can be a 3y total return upside if we
        # decide that's better.
        pct_to_target = None
        if mcp_target and price:
            pct_to_target = round((mcp_target - price) / price * 100, 1)

        # 5yr dividend growth — prefer Fish (Supabase) over yfinance
        growth_5y = dd.get("div_growth_5y")
        baseline = nm.get("div_baseline")

        # Does 5yr DG exceed baseline?
        exceeds = None
        if isinstance(growth_5y, (int, float)) and isinstance(baseline, (int, float)):
            exceeds = "Yes" if growth_5y >= baseline else "No"

        # Original purchase date from Tamarac (open_date column).
        # Tamarac stores it variously as datetime, ISO string, or M/D/YYYY.
        # _fmt_date_short produces "M/YY" cross-platform (avoids %-m issues).
        open_date_raw = h.get("open_date", "")
        open_date_str = ""
        if open_date_raw:
            if isinstance(open_date_raw, datetime):
                open_date_str = _fmt_date_short(open_date_raw)
            else:
                # Tamarac sometimes stores as string — try to parse
                try:
                    parsed = pd.to_datetime(open_date_raw, errors="coerce")
                    if pd.notna(parsed):
                        open_date_str = _fmt_date_short(parsed)
                    else:
                        open_date_str = str(open_date_raw)
                except Exception:
                    open_date_str = str(open_date_raw)

        # Date Evaluated from Notion — formatted M/D/YY
        date_eval_str = ""
        date_eval_raw = nm.get("date_evaluated") or ""
        if date_eval_raw:
            try:
                d = datetime.strptime(date_eval_raw, "%Y-%m-%d")
                date_eval_str = _fmt_date_md(d)
            except Exception:
                date_eval_str = str(date_eval_raw)

        rows.append({
            "Company":              h["description"],
            "Symbol":               sym,
            "Weight":               round(h["weight_pct"], 2),
            "Sector":               normalize_sector(mkt.get("sector", "")),
            "Yield":                mkt.get("dividend_yield") or 0,
            "Open Date":            open_date_str,
            "Cost Basis":           round(unit_cost, 2) if unit_cost else None,
            "Close":                round(price, 2) if price else None,
            "Δ from Cost":          delta_from_cost,
            "CLD":                  nm.get("cld"),
            "CLD Source":           nm.get("cld_source") or "",
            "Style":                nm.get("style_bucket") or "",
            "3yr Tgt":              mcp_target,
            "% To Tgt":             pct_to_target,
            "Baseline":             baseline,
            "5yr DG":               growth_5y,
            "DG ≥ Base":            exceeds or "—",
            "Date Eval":            date_eval_str,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data available for the warbook.")
        return

    # Coerce numeric columns to float dtype. None values in object-dtype
    # columns break Streamlit's click-sort. See _render_attribution for
    # the full rationale.
    numeric_cols = [
        "Weight", "Yield", "Cost Basis", "Close", "Δ from Cost",
        "CLD", "3yr Tgt", "% To Tgt", "Baseline", "5yr DG",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Sort by weight descending — matches printed spreadsheet
    df = df.sort_values("Weight", ascending=False).reset_index(drop=True)

    # Build a separate boolean mask for "5yr DG below baseline" so we can
    # color those cells red. We can't compute it inside the styler easily
    # because the styler operates per-cell without the row context.
    below_baseline = df.apply(
        lambda r: (
            isinstance(r["5yr DG"], (int, float)) and
            isinstance(r["Baseline"], (int, float)) and
            r["5yr DG"] < r["Baseline"]
        ),
        axis=1,
    )

    def _color_dg(val, idx):
        """Red if 5yr DG below baseline; otherwise default."""
        if idx < len(below_baseline) and below_baseline.iloc[idx]:
            return f"color: {BRAND['red']}; font-weight: 600;"
        return ""

    def _color_delta_from_cost(v):
        """Green/red based on sign — matches the dashboard's 1D % logic."""
        if not _is_num(v):
            return ""
        if v >= 0:
            return f"color: {BRAND['green']};"
        return f"color: {BRAND['red']};"

    def _color_pct_to_tgt(v):
        """Color: positive (room above price) green, negative red."""
        if not _is_num(v):
            return ""
        if v >= 0:
            return f"color: {BRAND['green']};"
        return f"color: {BRAND['red']};"

    # Build the styler. Column-level formatting + per-cell DG coloring.
    styler = (
        df.style
        .format({
            "Weight":      lambda v: f"{v:.2f}%" if _is_num(v) else "—",
            "Yield":       lambda v: f"{v:.2f}%" if _is_num(v) else "—",
            "Cost Basis":  lambda v: f"${v:,.2f}" if _is_num(v) else "—",
            "Close":       lambda v: f"${v:,.2f}" if _is_num(v) else "—",
            "Δ from Cost": lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "CLD":         lambda v: f"{v:.0f}" if _is_num(v) else "—",
            "3yr Tgt":     lambda v: f"${v:,.0f}" if _is_num(v) else "—",
            "% To Tgt":    lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "Baseline":    lambda v: f"{v:.0f}%" if _is_num(v) else "—",
            "5yr DG":      lambda v: f"{v:.1f}%" if _is_num(v) else "—",
        }, na_rep="—")
        .map(_color_delta_from_cost, subset=["Δ from Cost"])
        .map(_color_pct_to_tgt, subset=["% To Tgt"])
    )

    # Per-cell DG coloring needs an apply() at the column level so we get
    # the row index context.
    def _color_dg_column(col):
        return [
            f"color: {BRAND['red']}; font-weight: 600;" if below_baseline.iloc[i] else ""
            for i in range(len(col))
        ]
    styler = styler.apply(_color_dg_column, subset=["5yr DG"])

    # Render
    height = min(80 + len(df) * 36, 1400)
    st.dataframe(
        styler, width="stretch", hide_index=True, height=height,
        column_config={
            "Company":      st.column_config.TextColumn("Company", width="medium"),
            "Symbol":       st.column_config.TextColumn("Symbol", width="small"),
            "Weight":       st.column_config.TextColumn("Wt", width="small"),
            "Sector":       st.column_config.TextColumn("Sector", width="medium"),
            "Yield":        st.column_config.TextColumn("Yield", width="small"),
            "Open Date":    st.column_config.TextColumn("Open Date", width="small"),
            "Cost Basis":   st.column_config.TextColumn("Cost", width="small"),
            "Close":        st.column_config.TextColumn("Close", width="small"),
            "Δ from Cost":  st.column_config.TextColumn("Δ Cost", width="small"),
            "CLD":          st.column_config.TextColumn("CLD", width="small"),
            "CLD Source":   st.column_config.TextColumn("CLD Source", width="medium"),
            "Style":        st.column_config.TextColumn("Style", width="small"),
            "3yr Tgt":      st.column_config.TextColumn("3yr Tgt", width="small"),
            "% To Tgt":     st.column_config.TextColumn("% To Tgt", width="small"),
            "Baseline":     st.column_config.TextColumn("Base", width="small"),
            "5yr DG":       st.column_config.TextColumn("5yr DG", width="small"),
            "DG ≥ Base":    st.column_config.TextColumn("≥ Base", width="small"),
            "Date Eval":    st.column_config.TextColumn("Date Eval", width="small"),
        },
    )

    # Footer attribution
    st.markdown(
        "<div style='font-size:10px;color:rgba(255,255,255,0.3);"
        "margin-top:14px;text-align:right;'>"
        "Source: Tamarac (positions, cost basis) · yfinance (price, yield) · "
        "Fish CCC (5yr DG) · Notion (CLD, MCP Target, Baseline, Style, Date Eval)"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — QDG CHARACTERISTICS
# ══════════════════════════════════════════════════════════════════════════

def _render_qdg_characteristics(
    tam_df, active_strategy,
    price_data, notion_data, warbook_data,
    fish_data, fish_history,
):
    """
    Replicates the warbook spreadsheet's "QDG Characteristics" tab.

    Columns (sorted by weight desc):
      Symbol · Shares · Value · Company · Yield · Mkt Cap $Bln · Sector ·
      ROE % · LT Debt/Cap % · Quality (S&P) · Paid Since · Raised Since ·
      Timing of Raise · Frequency · Payout Ratio % · Last Bump % ·
      1Y/3Y/5Y DG % · FCF Yield · Weight

    Sources:
      - Yield, Mkt Cap, Sector, ROE, LT Debt/Cap, FCF Yield: yfinance / warbook_metrics
      - Quality (S&P): Notion
      - Raised Since, Payout, 1Y/3Y/5Y DG: Fish CCC (preferred — authoritative)
      - Paid Since: Notion (manually curated; Sprint 24-5)
      - Last Bump: Fish Historical (most recent ÷ prior annual)
      - Timing: Fish CCC "Last Increased on: Pay" month (Sprint 24-5)
      - Frequency: yfinance via warbook_metrics
    """
    rows = []
    for _, h in tam_df.iterrows():
        sym = str(h["symbol"]).strip().upper()
        mkt = price_data.get(sym, {})
        nm = notion_data.get(sym, {})
        wm = warbook_data.get(sym, {})
        fm = fish_data.get(sym, {})
        fh = fish_history.get(sym, {})

        price = mkt.get("price") or 0
        qty = h.get("quantity") or 0
        tam_value = h.get("value") or 0
        value = tam_value if tam_value else (qty * price if qty and price else 0)

        # Market cap in billions for compactness (warbook column is "$Bln")
        mkt_cap_raw = mkt.get("market_cap") or 0
        mkt_cap_bln = round(mkt_cap_raw / 1e9, 1) if mkt_cap_raw else None

        # Paid Since — Sprint 24-5: manually curated in Notion (was previously
        # derived from Fish Historical's earliest non-zero year, but Fish's
        # Historical sheet floors at 1999, which was producing misleading
        # values like "1999" for JNJ (real answer: 1944). When the Notion
        # property is blank the warbook shows an em dash so the team knows
        # to fill it in.
        paid_since_raw = nm.get("paid_since")
        paid_since = None
        if paid_since_raw is not None:
            try:
                paid_since = int(float(str(paid_since_raw)))
            except (ValueError, TypeError):
                pass

        # Raised Since — Sprint 24-6: now manually curated in Notion (was
        # previously fm.get("streak_began") from Fish). Notion is now source
        # of truth across the entire book, including ADRs that Fish doesn't
        # carry. Blank → em dash, same pattern as paid_since.
        raised_since_raw = nm.get("raised_since")
        raised_since = None
        if raised_since_raw is not None:
            try:
                raised_since = int(float(str(raised_since_raw)))
            except (ValueError, TypeError):
                pass

        # Last Bump % — most recent annual ÷ prior annual, expressed as %.
        # Use Fish Historical because Fish is curated and consistent.
        # Filter to years with actual non-zero dividends before picking the
        # last two — Fish sometimes stores zeros for years before a name
        # started paying, which would otherwise yield prior_v=0 and skip
        # the calculation. Also skip the current calendar year if we have
        # data through last year (otherwise an incomplete current year
        # would be compared against last year's full annual).
        last_bump = None
        if fh:
            from datetime import date as _date
            current_year = _date.today().year
            # Years with actual dividends (>0)
            valid_years = sorted(y for y, v in fh.items() if v and v > 0)
            # If we have at least 2 historical years, compute bump.
            # Prefer last-completed-year vs prior. If only the current year
            # is in valid_years (not yet annualized), we still try.
            past_years = [y for y in valid_years if y < current_year]
            if len(past_years) >= 2:
                latest_y = past_years[-1]
                prior_y = past_years[-2]
                latest_v = fh.get(latest_y)
                prior_v = fh.get(prior_y)
                if latest_v and prior_v and prior_v > 0:
                    last_bump = round((latest_v / prior_v - 1) * 100, 1)

        # Dividend growth — Sprint 24-6: Notion-first, Fish-fallback.
        # Notion carries manually curated values for the ADRs (ASML, UL, NVO,
        # KOF, TTE) where Fish has no coverage and yfinance-derived growth
        # carries FX/cadence noise. For U.S. names Notion is typically blank
        # and we fall through to Fish (which already handles them well).
        # Fish stores 0.0 when data is missing — treat 0 as missing for the
        # Fish path only. Notion 0 is taken at face value (rare, but if Ryan
        # ever enters 0 for a flat-dividend year we want to show it).
        def _dgr_with_fallback(notion_v, fish_v):
            if notion_v is not None:
                return notion_v
            if fish_v == 0:
                return None
            return fish_v

        dgr_1y = _dgr_with_fallback(nm.get("dgr_1y"), fm.get("dgr_1y"))
        dgr_3y = _dgr_with_fallback(nm.get("dgr_3y"), fm.get("dgr_3y"))
        dgr_5y = _dgr_with_fallback(nm.get("dgr_5y"), fm.get("dgr_5y"))

        # Payout ratio — prefer Fish (curated). Stored as percentage (e.g. 45.0)
        payout = fm.get("payout_ratio")
        if payout == 0:
            payout = None

        rows.append({
            "Symbol":            sym,
            "Shares":             qty,
            "Value":              value,
            "Company":            h["description"],
            "Yield":              mkt.get("dividend_yield") or 0,
            "Mkt Cap $Bln":       mkt_cap_bln,
            "Sector":             normalize_sector(mkt.get("sector", "")),
            "ROE %":              wm.get("roe_ttm"),
            "LT D/Cap %":         wm.get("lt_debt_to_capital"),
            "Qual (S&P)":         nm.get("sp_quality") or "",
            "Paid Since":         paid_since,
            "Raised Since":       raised_since,
            # Sprint 24-6: Timing now reads from Notion "Timing of Raise"
            # (manually curated 3-letter month abbreviation, e.g. "Feb").
            # Was previously fm.get("last_increased_pay_month") from Fish.
            # Notion format ("Feb") matches Fish format ("Apr") so direct
            # passthrough — no conversion needed. Blank → em dash via
            # downstream numeric/dash formatting.
            "Timing":             nm.get("timing_of_raise"),
            "Freq":               wm.get("dividend_frequency") or "",
            "Payout %":           payout,
            "Last Bump %":        last_bump,
            "1Y DG %":            dgr_1y,
            "3Y DG %":            dgr_3y,
            "5Y DG %":            dgr_5y,
            "FCF Yld %":          wm.get("fcf_yield"),
            "Weight":             round(h["weight_pct"], 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data available for QDG Characteristics view.")
        return

    # Coerce numeric columns to float dtype for proper sort + na_rep handling.
    numeric_cols = [
        "Shares", "Value", "Yield", "Mkt Cap $Bln", "ROE %", "LT D/Cap %",
        "Paid Since", "Raised Since", "Payout %", "Last Bump %",
        "1Y DG %", "3Y DG %", "5Y DG %", "FCF Yld %", "Weight",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Sort by weight descending — same as Strategy Overview.
    df = df.sort_values("Weight", ascending=False).reset_index(drop=True)

    styler = (
        df.style
        .format({
            "Shares":        lambda v: f"{v:,.0f}" if _is_num(v) else "—",
            "Value":         lambda v: f"${v:,.0f}" if _is_num(v) else "—",
            "Yield":         lambda v: f"{v:.2f}%" if _is_num(v) else "—",
            "Mkt Cap $Bln":  lambda v: f"${v:,.1f}" if _is_num(v) else "—",
            "ROE %":         lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "LT D/Cap %":    lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "Paid Since":    lambda v: f"{int(v)}" if _is_num(v) else "—",
            "Raised Since":  lambda v: f"{int(v)}" if _is_num(v) else "—",
            # Sprint 24-5: Timing is a string column (e.g. "Jun") but can
            # arrive as None when Fish doesn't carry the ticker — explicit
            # em-dash formatter matches the column's na_rep behavior.
            "Timing":        lambda v: v if (v is not None and str(v).strip() and str(v).strip() != "nan") else "—",
            "Payout %":      lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "Last Bump %":   lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "1Y DG %":       lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "3Y DG %":       lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "5Y DG %":       lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "FCF Yld %":     lambda v: f"{v:.2f}%" if _is_num(v) else "—",
            "Weight":        lambda v: f"{v:.2f}%" if _is_num(v) else "—",
        }, na_rep="—")
    )

    height = min(80 + len(df) * 36, 1400)
    st.dataframe(
        styler, width="stretch", hide_index=True, height=height,
        column_config={
            "Symbol":        st.column_config.TextColumn("Symbol", width="small"),
            "Shares":        st.column_config.TextColumn("Shares", width="small"),
            "Value":         st.column_config.TextColumn("Value", width="small"),
            "Company":       st.column_config.TextColumn("Company", width="medium"),
            "Yield":         st.column_config.TextColumn("Yield", width="small"),
            "Mkt Cap $Bln":  st.column_config.TextColumn("Mkt Cap", width="small"),
            "Sector":        st.column_config.TextColumn("Sector", width="medium"),
            "ROE %":         st.column_config.TextColumn("ROE", width="small"),
            "LT D/Cap %":    st.column_config.TextColumn("LT D/Cap", width="small"),
            "Qual (S&P)":    st.column_config.TextColumn("S&P Q", width="small"),
            "Paid Since":    st.column_config.TextColumn("Paid", width="small"),
            "Raised Since":  st.column_config.TextColumn("Raised", width="small"),
            "Timing":        st.column_config.TextColumn("Timing", width="small"),
            "Freq":          st.column_config.TextColumn("Freq", width="small"),
            "Payout %":      st.column_config.TextColumn("Payout", width="small"),
            "Last Bump %":   st.column_config.TextColumn("Last Bump", width="small"),
            "1Y DG %":       st.column_config.TextColumn("1Y DG", width="small"),
            "3Y DG %":       st.column_config.TextColumn("3Y DG", width="small"),
            "5Y DG %":       st.column_config.TextColumn("5Y DG", width="small"),
            "FCF Yld %":     st.column_config.TextColumn("FCF Yld", width="small"),
            "Weight":        st.column_config.TextColumn("Wt", width="small"),
        },
    )

    st.markdown(
        "<div style='font-size:10px;color:rgba(255,255,255,0.3);"
        "margin-top:14px;text-align:right;'>"
        "Source: Tamarac (positions) · yfinance (yield, market cap, ROE, "
        "leverage, FCF yield, frequency) · Fish CCC (payout, last bump, "
        "DGR fallback) · Notion (S&amp;P quality, paid since, raised since, "
        "timing, DGR for ADRs)"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# TAB 3 — RISK CORRELATION
# ══════════════════════════════════════════════════════════════════════════

def _render_risk_correlation(
    tam_df, active_strategy,
    price_data, notion_data, warbook_data,
):
    """
    Replicates the warbook spreadsheet's "Risk Correlation" tab.

    Columns (sorted by Super Sector A→Z, then Sector A→Z, then Symbol A→Z):
      Symbol · Yesterday's Close · Mkt Cap $Bln · Super Sector · Sector ·
      Sub-Industry · Credit (S&P) · Debt Coverage Ratio · LT Debt/Cap % ·
      Beta · Style Classification · Mstar Growth Grade · Mstar Profitability
      Grade · Mstar Financial Health Grade · Country · Weight

    Sources:
      - Yesterday's Close, Mkt Cap, Sector, Beta: yfinance / market_data
      - Super Sector, Sub-Industry, Country, Debt Coverage, LT D/Cap: warbook_metrics
      - Credit (S&P), all 4 Mstar grades, Style Classification: Notion
    """
    rows = []
    for _, h in tam_df.iterrows():
        sym = str(h["symbol"]).strip().upper()
        mkt = price_data.get(sym, {})
        nm = notion_data.get(sym, {})
        wm = warbook_data.get(sym, {})

        mkt_cap_raw = mkt.get("market_cap") or 0
        mkt_cap_bln = round(mkt_cap_raw / 1e9, 1) if mkt_cap_raw else None

        # Super Sector: derive from the Supabase-sourced sector at render time
        # rather than relying on warbook_metrics' yfinance-info-derived value.
        # yfinance info is throttled on Streamlit Cloud, so the render-time
        # mapping using Supabase data is dramatically more reliable. Fall
        # back to warbook_metrics' value if the local mapping doesn't have
        # the sector (shouldn't happen, but defensive).
        sector_normalized = normalize_sector(mkt.get("sector", ""))
        super_sector = (
            _SUPER_SECTOR_BY_SECTOR.get(sector_normalized)
            or wm.get("super_sector")
            or ""
        )

        rows.append({
            "Symbol":            sym,
            "Close":              mkt.get("price") or 0,
            "Mkt Cap $Bln":       mkt_cap_bln,
            "Super Sector":       super_sector,
            "Sector":             sector_normalized,
            "Sub-Industry":       wm.get("sub_industry") or "",
            "Credit (S&P)":       nm.get("sp_credit") or "",
            "Debt Cov":           wm.get("debt_coverage_ratio"),
            "LT D/Cap %":         wm.get("lt_debt_to_capital"),
            "Beta":               mkt.get("beta") if mkt.get("beta") else None,
            "Style":              nm.get("mstar_style") or "",
            "Mstar Gr":           nm.get("mstar_growth") or "",
            "Mstar Pf":           nm.get("mstar_profitability") or "",
            "Mstar FH":           nm.get("mstar_fin_health") or "",
            "Country":            wm.get("country") or "",
            "Weight":             round(h["weight_pct"], 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data available for Risk Correlation view.")
        return

    numeric_cols = [
        "Close", "Mkt Cap $Bln", "Debt Cov", "LT D/Cap %", "Beta", "Weight",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Sort: Super Sector A→Z, Sector A→Z, Symbol A→Z (Symbol is tiebreaker
    # within same sector, per Sprint 23C scope decision).
    # NaN/empty Super Sector goes last via na_position="last".
    df = df.sort_values(
        by=["Super Sector", "Sector", "Symbol"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    styler = (
        df.style
        .format({
            "Close":         lambda v: f"${v:,.2f}" if _is_num(v) else "—",
            "Mkt Cap $Bln":  lambda v: f"${v:,.1f}" if _is_num(v) else "—",
            "Debt Cov":      lambda v: f"{v:.1f}x" if _is_num(v) else "—",
            "LT D/Cap %":    lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "Beta":          lambda v: f"{v:.2f}" if _is_num(v) else "—",
            "Weight":        lambda v: f"{v:.2f}%" if _is_num(v) else "—",
        }, na_rep="—")
    )

    height = min(80 + len(df) * 36, 1400)
    st.dataframe(
        styler, width="stretch", hide_index=True, height=height,
        column_config={
            "Symbol":        st.column_config.TextColumn("Symbol", width="small"),
            "Close":         st.column_config.TextColumn("Close", width="small"),
            "Mkt Cap $Bln":  st.column_config.TextColumn("Mkt Cap", width="small"),
            "Super Sector":  st.column_config.TextColumn("Super Sector", width="small"),
            "Sector":        st.column_config.TextColumn("Sector", width="medium"),
            "Sub-Industry":  st.column_config.TextColumn("Sub-Industry", width="medium"),
            "Credit (S&P)":  st.column_config.TextColumn("S&P Cr", width="small"),
            "Debt Cov":      st.column_config.TextColumn("Debt Cov", width="small"),
            "LT D/Cap %":    st.column_config.TextColumn("LT D/Cap", width="small"),
            "Beta":          st.column_config.TextColumn("Beta", width="small"),
            "Style":         st.column_config.TextColumn("Style", width="small"),
            "Mstar Gr":      st.column_config.TextColumn("Gr", width="small"),
            "Mstar Pf":      st.column_config.TextColumn("Pf", width="small"),
            "Mstar FH":      st.column_config.TextColumn("FH", width="small"),
            "Country":       st.column_config.TextColumn("Country", width="small"),
            "Weight":        st.column_config.TextColumn("Wt", width="small"),
        },
    )

    st.markdown(
        "<div style='font-size:10px;color:rgba(255,255,255,0.3);"
        "margin-top:14px;text-align:right;'>"
        "Source: Tamarac (positions) · yfinance (price, market cap, beta) · "
        "warbook_metrics (super sector, sub-industry, country, debt coverage) · "
        "Notion (S&amp;P credit, Mstar grades, style)"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# TAB 4 — ATTRIBUTION & QUALITY
# ══════════════════════════════════════════════════════════════════════════

def _render_attribution(tam_df, active_strategy, price_data, warbook_data):
    """
    Replicates the warbook spreadsheet's "Attribution" tab.

    Columns (sorted by weight desc):
      Symbol · Shares · Value · Company · YTD TR % · 3M TR % · 1Y TR % ·
      MTD TR % · QTD TR % · QTD vs SPX · YTD vs SPX · % From 52W High ·
      % Net Debt to Capital · ROE 5yr Avg · EPS Div Coverage · CF Div Cov ·
      FCF Div Cov · FWD P/E · CF/EV Yield · Weight

    Red text on negative TR values (matches spreadsheet convention).
    """
    rows = []
    for _, h in tam_df.iterrows():
        sym = str(h["symbol"]).strip().upper()
        mkt = price_data.get(sym, {})
        wm = warbook_data.get(sym, {})

        price = mkt.get("price") or 0
        w52_high = mkt.get("52w_high") or 0
        from_52w_high = None
        if price and w52_high:
            from_52w_high = round((price - w52_high) / w52_high * 100, 1)

        # Value: prefer Tamarac's `value` column, fall back to qty × price.
        # Some Tamarac export templates don't include the Value column
        # (template 41 omits it); the fallback ensures we still show a
        # meaningful position size in the warbook.
        qty = h.get("quantity") or 0
        tam_value = h.get("value") or 0
        value = tam_value if tam_value else (qty * price if qty and price else 0)

        rows.append({
            "Symbol":           sym,
            "Shares":            qty,
            "Value":             value,
            "Company":           h["description"],
            "YTD TR":            wm.get("tr_ytd"),
            "3M TR":             wm.get("tr_3m"),
            "1Y TR":             wm.get("tr_1y"),
            "MTD TR":            wm.get("tr_mtd"),
            "QTD TR":            wm.get("tr_qtd"),
            "QTD vs SPX":        wm.get("tr_qtd_vs_spx"),
            "YTD vs SPX":        wm.get("tr_ytd_vs_spx"),
            "% From 52W Hi":     from_52w_high,
            "% Net Debt/Cap":    wm.get("net_debt_to_capital"),
            "ROE 5Y Avg":        wm.get("roe_5y_avg"),
            "EPS Cov":           wm.get("eps_div_coverage"),
            "CF Cov":            wm.get("cf_div_coverage"),
            "FCF Cov":           wm.get("fcf_div_coverage"),
            # Forward P/E: prefer Supabase (more reliable on Streamlit Cloud
            # where yfinance is throttled), fall back to warbook_metrics.
            "FWD P/E":           mkt.get("forward_pe") or wm.get("forward_pe"),
            "CF/EV Yield":       wm.get("cash_flow_ev_yield"),
            "Weight":            round(h["weight_pct"], 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data available for attribution view.")
        return

    # Coerce numeric columns to float dtype. None values in object-dtype
    # columns break Streamlit's click-sort and trigger the styler's
    # missing-value path. pd.to_numeric with errors='coerce' turns None
    # into NaN, and na_rep on the styler handles the display.
    numeric_cols = [
        "Shares", "Value", "YTD TR", "3M TR", "1Y TR", "MTD TR", "QTD TR",
        "QTD vs SPX", "YTD vs SPX", "% From 52W Hi", "% Net Debt/Cap",
        "ROE 5Y Avg", "EPS Cov", "CF Cov", "FCF Cov", "FWD P/E",
        "CF/EV Yield", "Weight",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Default sort: YTD TR descending (best YTD performers at top).
    # NaN values sort to the bottom via na_position="last".
    df = df.sort_values("YTD TR", ascending=False, na_position="last").reset_index(drop=True)

    def _color_signed(v):
        if not _is_num(v):
            return ""
        if v > 0:
            return f"color: {BRAND['green']};"
        if v < 0:
            return f"color: {BRAND['red']};"
        return ""

    def _color_neg_only(v):
        """Red only on negative — neutral on positive."""
        if not _is_num(v):
            return ""
        if v < 0:
            return f"color: {BRAND['red']};"
        return ""

    styler = (
        df.style
        .format({
            "Shares":         lambda v: f"{v:,.0f}" if _is_num(v) else "—",
            "Value":          lambda v: f"${v:,.0f}" if _is_num(v) else "—",
            "YTD TR":         lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "3M TR":          lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "1Y TR":          lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "MTD TR":         lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "QTD TR":         lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "QTD vs SPX":     lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "YTD vs SPX":     lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "% From 52W Hi":  lambda v: f"{v:+.1f}%" if _is_num(v) else "—",
            "% Net Debt/Cap": lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "ROE 5Y Avg":     lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "EPS Cov":        lambda v: f"{v:.1f}x" if _is_num(v) else "—",
            "CF Cov":         lambda v: f"{v:.1f}x" if _is_num(v) else "—",
            "FCF Cov":        lambda v: f"{v:.1f}x" if _is_num(v) else "—",
            "FWD P/E":        lambda v: f"{v:.1f}" if _is_num(v) else "—",
            "CF/EV Yield":    lambda v: f"{v:.1f}%" if _is_num(v) else "—",
            "Weight":         lambda v: f"{v:.2f}%" if _is_num(v) else "—",
        }, na_rep="—")
        .map(_color_neg_only, subset=[
            "YTD TR", "3M TR", "1Y TR", "MTD TR", "QTD TR",
            "QTD vs SPX", "YTD vs SPX", "% From 52W Hi",
        ])
    )

    height = min(80 + len(df) * 36, 1400)
    st.dataframe(
        styler, width="stretch", hide_index=True, height=height,
        column_config={
            "Symbol":         st.column_config.TextColumn("Symbol", width="small"),
            "Shares":         st.column_config.TextColumn("Shares", width="small"),
            "Value":          st.column_config.TextColumn("Value", width="small"),
            "Company":        st.column_config.TextColumn("Company", width="medium"),
            "YTD TR":         st.column_config.TextColumn("YTD TR", width="small"),
            "3M TR":          st.column_config.TextColumn("3M TR", width="small"),
            "1Y TR":          st.column_config.TextColumn("1Y TR", width="small"),
            "MTD TR":         st.column_config.TextColumn("MTD TR", width="small"),
            "QTD TR":         st.column_config.TextColumn("QTD TR", width="small"),
            "QTD vs SPX":     st.column_config.TextColumn("QTD v SPX", width="small"),
            "YTD vs SPX":     st.column_config.TextColumn("YTD v SPX", width="small"),
            "% From 52W Hi":  st.column_config.TextColumn("% Frm 52W Hi", width="small"),
            "% Net Debt/Cap": st.column_config.TextColumn("Net D/Cap", width="small"),
            "ROE 5Y Avg":     st.column_config.TextColumn("ROE 5Y", width="small"),
            "EPS Cov":        st.column_config.TextColumn("EPS Cov", width="small"),
            "CF Cov":         st.column_config.TextColumn("CF Cov", width="small"),
            "FCF Cov":        st.column_config.TextColumn("FCF Cov", width="small"),
            "FWD P/E":        st.column_config.TextColumn("Fwd P/E", width="small"),
            "CF/EV Yield":    st.column_config.TextColumn("CF/EV", width="small"),
            "Weight":         st.column_config.TextColumn("Wt", width="small"),
        },
    )

    st.markdown(
        "<div style='font-size:10px;color:rgba(255,255,255,0.3);"
        "margin-top:14px;text-align:right;'>"
        "Source: Tamarac (positions) · yfinance (TR windows, financials, "
        "ratios) · SPY proxy for vs-SPX comparisons"
        "</div>",
        unsafe_allow_html=True,
    )