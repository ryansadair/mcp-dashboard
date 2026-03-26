"""
KPI card row for strategy-level metrics.
components/kpi_cards.py

Custom HTML cards with institutional styling — uppercase labels,
DM Serif Display values, color-coded returns.
"""

import streamlit as st
from utils.config import STRATEGIES, BRAND

GREEN = BRAND["green"]
GOLD  = BRAND["gold"]
RED   = BRAND["red"]


def _kpi_card(label, value, color="rgba(255,255,255,0.95)", sub_text=None):
    """Render a single styled KPI card."""
    sub_html = ""
    if sub_text:
        sub_html = (
            f'<div style="font-size:10px;color:rgba(255,255,255,0.25);'
            f'margin-top:4px;">{sub_text}</div>'
        )
    return (
        f'<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);'
        f'border-radius:10px;padding:14px 16px;">'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;'
        f'letter-spacing:0.08em;font-weight:600;margin-bottom:6px;">{label}</div>'
        f'<div style="font-size:22px;font-weight:700;font-family:\'DM Serif Display\',serif;'
        f'color:{color};line-height:1.1;">{value}</div>'
        f'{sub_html}'
        f'</div>'
    )


def render_kpi_cards(strategy: str, kpis: dict, bench_ytd: float):
    """Render the 4 KPI metric cards for a strategy."""
    s = STRATEGIES[strategy]
    daily_return = kpis.get("daily_return", 0)
    div_yield = kpis.get("div_yield", 0)
    holdings = kpis.get("holdings", 0)
    cash_pct = kpis.get("cash_pct", 0)

    # Format values
    daily_str = f"{daily_return:+.2f}%" if daily_return != 0 else "0.00%"
    daily_color = GREEN if daily_return > 0 else RED if daily_return < 0 else "rgba(255,255,255,0.95)"

    cash_str = f"{cash_pct:.2f}%" if cash_pct > 0 else "—"

    yield_str = f"{div_yield:.2f}%"
    yield_color = GOLD if div_yield > 0 else "rgba(255,255,255,0.95)"

    holdings_str = str(holdings)

    cards_html = (
        f'<div style="display:flex;flex-wrap:wrap;gap:10px;">'
        f'<div style="flex:1 1 180px;min-width:140px;">{_kpi_card("Daily Return", daily_str, daily_color)}</div>'
        f'<div style="flex:1 1 180px;min-width:140px;">{_kpi_card("Cash", cash_str)}</div>'
        f'<div style="flex:1 1 180px;min-width:140px;">{_kpi_card("Dividend Yield", yield_str, yield_color)}</div>'
        f'<div style="flex:1 1 180px;min-width:140px;">{_kpi_card("Holdings", holdings_str)}</div>'
        f'</div>'
    )
    st.markdown(cards_html, unsafe_allow_html=True)