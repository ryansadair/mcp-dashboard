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

    # Sub-tabs: Strategy Overview | Attribution (23C will add QDG + Risk)
    sub_overview, sub_attribution = st.tabs([
        "Strategy Overview",
        "Attribution",
    ])

    # Pre-fetch all data once — both sub-tabs share the same underlying calls.
    # Streamlit's st.tabs() runs every body on every interaction, so any
    # heavy fetches need to be cached. Each of these has its own caching
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

    # ── Strategy Overview (Tab 1) ────────────────────────────────────────
    with sub_overview:
        _render_strategy_overview(
            tam_df, active_strategy,
            price_data, notion_data, div_data,
        )

    # ── Attribution (Tab 4) ──────────────────────────────────────────────
    with sub_attribution:
        _render_attribution(
            tam_df, active_strategy,
            price_data, warbook_data,
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
        })
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
            "FWD P/E":           wm.get("forward_pe"),
            "CF/EV Yield":       wm.get("cash_flow_ev_yield"),
            "Weight":            round(h["weight_pct"], 2),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No data available for attribution view.")
        return

    df = df.sort_values("Weight", ascending=False).reset_index(drop=True)

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
        })
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