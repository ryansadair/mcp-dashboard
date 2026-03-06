"""
Dividend Announcement Calendar tab for the Dashboard.
Reads data/dividend_calendar.xlsx (generated weekly by dividend_calendar.py)
and renders a grouped-by-month HTML table in the Dividends tab.
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime, date


# ── Paths to check ─────────────────────────────────────────────────────────
CALENDAR_PATHS = [
    "data/dividend_calendar.xlsx",
    "dividend_calendar.xlsx",
]


@st.cache_data(ttl=600)
def _load_calendar():
    """Load the 'Upcoming Announcements' sheet from the dividend calendar Excel."""
    for p in CALENDAR_PATHS:
        if os.path.exists(p):
            try:
                df = pd.read_excel(p, sheet_name="Upcoming Announcements", header=4)
                # Standardize column names (strip whitespace)
                df.columns = [c.strip() for c in df.columns]
                return df, os.path.getmtime(p)
            except Exception as e:
                st.warning(f"Error reading dividend calendar: {e}")
                return None, None
    return None, None


def _fmt_pct(val):
    """Format a percentage value with color."""
    if pd.isna(val) or val is None:
        return "—"
    # Handle values that are already decimals (0.05 = 5%)
    pct = val * 100 if abs(val) < 1 else val
    if pct > 0.1:
        return f'<span style="color:#569542">+{pct:.1f}%</span>'
    elif pct < -0.1:
        return f'<span style="color:#c45454">{pct:.1f}%</span>'
    return f'<span style="color:#C9A84C">{pct:.1f}%</span>'


def _fmt_money(val):
    if pd.isna(val) or val is None:
        return "—"
    return f"${val:.4f}"


def _fmt_date(val):
    if pd.isna(val) or val is None:
        return "—"
    if isinstance(val, (datetime, date)):
        return val.strftime("%m/%d/%Y")
    return str(val)


def _fmt_yield(val):
    if pd.isna(val) or val is None:
        return "—"
    pct = val * 100 if abs(val) < 1 else val
    return f'{pct:.2f}%'


def _fmt_baseline(val):
    if pd.isna(val) or val is None:
        return "—"
    pct = val * 100 if val <= 1 else val
    return f'{pct:.0f}%'


def _days_badge(days):
    """Render days-until with color coding."""
    if pd.isna(days) or days is None:
        return "—"
    d = int(days)
    if d < 0:
        return f'<span style="background:rgba(196,84,84,0.15);color:#c45454;padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">{d}d</span>'
    elif d <= 14:
        return f'<span style="background:rgba(201,168,76,0.15);color:#C9A84C;padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">{d}d</span>'
    elif d <= 30:
        return f'<span style="background:rgba(86,149,66,0.10);color:#569542;padding:2px 8px;border-radius:4px;font-size:11px">{d}d</span>'
    return f'<span style="color:rgba(255,255,255,0.4);font-size:11px">{d}d</span>'


def _source_badge(source):
    if pd.isna(source) or not source:
        return "—"
    s = str(source)
    if "Notion" in s:
        return f'<span style="background:rgba(86,149,66,0.12);color:#569542;padding:2px 8px;border-radius:4px;font-size:10px">Notion + yf</span>'
    elif "yfinance" in s:
        return f'<span style="background:rgba(7,65,90,0.15);color:rgba(255,255,255,0.5);padding:2px 8px;border-radius:4px;font-size:10px">yfinance</span>'
    return f'<span style="color:rgba(255,255,255,0.3);font-size:10px">{s}</span>'


def render_dividend_calendar():
    """Render the dividend announcement calendar in the Dividends tab."""

    df, file_mtime = _load_calendar()
    if df is None:
        st.info(
            "Dividend calendar not yet available. "
            "Run `dividend_calendar.py` to generate `data/dividend_calendar.xlsx`."
        )
        return

    # ── Column mapping (match Excel headers) ───────────────────────────────
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "ticker": col_map["ticker"] = c
        elif "est. announce" in cl or "announce date" in cl: col_map["announce"] = c
        elif "days" in cl: col_map["days"] = c
        elif "est." in cl and "ex" in cl and "date" in cl: col_map["ex_date"] = c
        elif "last amount" in cl: col_map["amount"] = c
        elif "last change" in cl: col_map["change"] = c
        elif "baseline" in cl or "mcp" in cl.lower(): col_map["baseline"] = c
        elif "source" in cl: col_map["source"] = c
        elif "yield" in cl: col_map["yield"] = c
        elif "frequency" in cl or "freq" in cl: col_map["frequency"] = c
        elif "increase ex-month" in cl or "increase ex" in cl: col_map["inc_month"] = c

    if "ticker" not in col_map or "announce" not in col_map:
        st.warning("Dividend calendar file format not recognized. Check column headers.")
        return

    # ── Filter & sort ──────────────────────────────────────────────────────
    # Drop rows without an estimated announce date
    valid = df[df[col_map["announce"]].notna()].copy()
    if valid.empty:
        st.info("No upcoming dividend announcements found.")
        return

    # Parse announce dates
    valid["_announce_dt"] = pd.to_datetime(valid[col_map["announce"]], errors="coerce")
    valid = valid[valid["_announce_dt"].notna()].copy()
    valid = valid.sort_values("_announce_dt")

    # Group by month
    valid["_month_key"] = valid["_announce_dt"].dt.to_period("M")

    # ── KPI summary row ────────────────────────────────────────────────────
    today = date.today()
    next_30 = valid[valid["_announce_dt"].dt.date <= (pd.Timestamp(today) + pd.Timedelta(days=30)).date()]
    notion_count = 0
    if "source" in col_map:
        notion_count = valid[col_map["source"]].astype(str).str.contains("Notion", case=False, na=False).sum()

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Total Tracked", f"{len(valid)}")
    with k2:
        st.metric("Next 30 Days", f"{len(next_30)}")
    with k3:
        st.metric("Notion-Verified", f"{notion_count}")
    with k4:
        # File freshness
        if file_mtime:
            updated = datetime.fromtimestamp(file_mtime)
            st.metric("Last Updated", updated.strftime("%b %d"))
        else:
            st.metric("Last Updated", "—")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Grouped HTML table ─────────────────────────────────────────────────
    html_parts = []
    html_parts.append("""
    <style>
    .divcal-table { width:100%; border-collapse:collapse; font-family:'DM Sans',sans-serif; }
    .divcal-table th {
        text-align:right; padding:7px 10px; font-size:10px; font-weight:600;
        color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.06em;
        border-bottom:1px solid rgba(255,255,255,0.08);
    }
    .divcal-table th:first-child, .divcal-table th:nth-child(2) { text-align:left; }
    .divcal-table td {
        padding:8px 10px; font-size:13px; text-align:right;
        color:rgba(255,255,255,0.65); border-bottom:1px solid rgba(255,255,255,0.03);
    }
    .divcal-table td:first-child { text-align:left; font-weight:600; color:#C9A84C; letter-spacing:0.03em; }
    .divcal-table td:nth-child(2) { text-align:left; }
    .divcal-table tr:hover td { background:rgba(255,255,255,0.02); }
    .divcal-month {
        font-size:15px; font-weight:700; color:rgba(255,255,255,0.85);
        padding:18px 0 8px 0; border-bottom:2px solid rgba(201,168,76,0.25);
        margin-top:8px; font-family:'DM Sans',sans-serif;
    }
    .divcal-notion-row td { background:rgba(86,149,66,0.04) !important; }
    </style>
    """)

    month_names = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December"
    }

    for period, group in valid.groupby("_month_key"):
        month_label = f"{month_names.get(period.month, str(period.month))} {period.year}"
        html_parts.append(f'<div class="divcal-month">{month_label}</div>')
        html_parts.append('<table class="divcal-table"><thead><tr>')
        html_parts.append('<th style="text-align:left">Ticker</th>')
        html_parts.append('<th style="text-align:left">Est. Announce</th>')
        html_parts.append('<th>Days</th>')
        html_parts.append('<th>Est. Ex-Date</th>')
        html_parts.append('<th>Last Amt</th>')
        html_parts.append('<th>Last Chg</th>')
        if "baseline" in col_map:
            html_parts.append('<th>MCP Base</th>')
        if "yield" in col_map:
            html_parts.append('<th>Est. Yield</th>')
        html_parts.append('<th>Source</th>')
        html_parts.append('</tr></thead><tbody>')

        for _, row in group.iterrows():
            # Check if Notion-verified for row styling
            is_notion = False
            if "source" in col_map:
                is_notion = "Notion" in str(row.get(col_map["source"], ""))
            row_class = ' class="divcal-notion-row"' if is_notion else ""

            ticker = row.get(col_map["ticker"], "")
            announce = _fmt_date(row.get(col_map["announce"]))
            days = _days_badge(row.get(col_map.get("days", ""), None))
            ex_date = _fmt_date(row.get(col_map.get("ex_date", ""), None))
            amount = _fmt_money(row.get(col_map.get("amount", ""), None))
            change = _fmt_pct(row.get(col_map.get("change", ""), None))
            source = _source_badge(row.get(col_map.get("source", ""), None))

            html_parts.append(f'<tr{row_class}>')
            html_parts.append(f'<td>{ticker}</td>')
            html_parts.append(f'<td>{announce}</td>')
            html_parts.append(f'<td>{days}</td>')
            html_parts.append(f'<td>{ex_date}</td>')
            html_parts.append(f'<td>{amount}</td>')
            html_parts.append(f'<td>{change}</td>')

            if "baseline" in col_map:
                baseline = _fmt_baseline(row.get(col_map["baseline"], None))
                html_parts.append(f'<td>{baseline}</td>')
            if "yield" in col_map:
                yld = _fmt_yield(row.get(col_map["yield"], None))
                html_parts.append(f'<td>{yld}</td>')

            html_parts.append(f'<td>{source}</td>')
            html_parts.append('</tr>')

        html_parts.append('</tbody></table>')

    html_parts.append("""
    <div style="margin-top:12px;font-size:10px;color:rgba(255,255,255,0.25);">
        <span style="display:inline-block;width:10px;height:10px;background:rgba(86,149,66,0.15);
              border:1px solid rgba(86,149,66,0.3);border-radius:2px;vertical-align:middle;margin-right:4px;"></span>
        Notion-verified &nbsp;|&nbsp; White = yfinance estimate
    </div>
    """)

    st.markdown("".join(html_parts), unsafe_allow_html=True)