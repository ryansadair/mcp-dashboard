"""
KPI card row for strategy-level metrics.
"""

import streamlit as st
from utils.config import STRATEGIES, BRAND


def render_kpi_cards(strategy: str, kpis: dict, bench_ytd: float):
    """Render the 5 KPI metric cards for a strategy."""
    s = STRATEGIES[strategy]
    ytd = kpis.get("ytd", 0)
    daily_return = kpis.get("daily_return", 0)
    div_yield = kpis.get("div_yield", 0)
    holdings = kpis.get("holdings", 0)
    ytd_as_of = kpis.get("ytd_as_of", "")
    cash_pct = kpis.get("cash_pct", 0)

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        daily_str = f"{daily_return:+.2f}%" if daily_return != 0 else "0.00%"
        st.metric("Daily Return", daily_str)
    with c2:
        ytd_str = f"+{ytd:.2f}%" if ytd >= 0 else f"{ytd:.2f}%"
        if ytd_as_of:
            from datetime import datetime
            try:
                dt = datetime.strptime(ytd_as_of, "%Y-%m-%d")
                as_of_display = dt.strftime("%b %d")
            except ValueError:
                as_of_display = ytd_as_of
            label = f"YTD Return (as of {as_of_display})"
        else:
            label = "YTD Return"
        st.metric(label, ytd_str)
    with c3:
        cash_str = f"{cash_pct:.1f}%" if cash_pct > 0 else "—"
        st.metric("Cash", cash_str)
    with c4:
        st.metric("Dividend Yield", f"{div_yield:.2f}%")
    with c5:
        st.metric("Holdings", str(holdings))