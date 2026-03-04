import streamlit as st
from data.market_data import get_market_bar


def render_market_ticker():
    market = get_market_bar()

    if not market:
        st.markdown(
            "<div style='padding:10px 28px; font-size:12px; color:rgba(255,255,255,0.3);'>Market data loading...</div>",
            unsafe_allow_html=True
        )
        return

    items_html = ""
    for m in market:
        color = "#569542" if m["up"] else "#c45454"
        items_html += (
            "<div style='display:flex;align-items:center;gap:8px;padding:10px 20px;"
            "border-right:1px solid rgba(255,255,255,0.04);white-space:nowrap;'>"
            f"<span style='font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;"
            f"letter-spacing:0.06em;'>{m['name']}</span>"
            f"<span style='font-size:13px;font-weight:600;color:rgba(255,255,255,0.9);'>{m['value']}</span>"
            f"<span style='font-size:12px;font-weight:500;color:{color};'>{m['chg']}</span>"
            "</div>"
        )

    html = (
        "<div style='display:flex;overflow-x:auto;border-bottom:1px solid rgba(255,255,255,0.06);"
        "background:rgba(0,0,0,0.2);padding:0 8px;'>"
        + items_html +
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)