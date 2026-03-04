"""
Strategy tab selector — renders the strategy navigation bar.
Returns the currently selected strategy key.
"""

import streamlit as st
from utils.config import STRATEGIES
from data.performance import get_strategy_kpis


def render_strategy_selector() -> str:
    """
    Render strategy tabs and return selected strategy key.
    Uses session state to persist selection across reruns.
    """
    if "active_strategy" not in st.session_state:
        st.session_state["active_strategy"] = "QDVD"

    # Build tab HTML
    tabs_html = ""
    for key, s in STRATEGIES.items():
        kpis = get_strategy_kpis(key)
        ytd = kpis.get("ytd", 0)
        ytd_color = "#569542" if ytd >= 0 else "#c45454"
        ytd_str = f"+{ytd:.2f}%" if ytd >= 0 else f"{ytd:.2f}%"
        is_active = st.session_state["active_strategy"] == key

        tabs_html += f"""
        <button
            onclick="selectStrategy('{key}')"
            id="strat-btn-{key}"
            style="
                padding:14px 22px;
                background:{'rgba(255,255,255,0.02)' if is_active else 'none'};
                border:none;
                border-bottom:3px solid {s['color'] if is_active else 'transparent'};
                cursor:pointer;
                display:flex; flex-direction:column; align-items:flex-start;
                gap:2px; flex-shrink:0;
                transition:all 0.2s;
            "
        >
            <span style="font-size:14px; font-weight:700; color:rgba(255,255,255,0.9); letter-spacing:0.04em;">{key}</span>
            <span style="font-size:10px; color:rgba(255,255,255,0.35);">{s['name']}</span>
            <span style="font-size:12px; font-weight:600; color:{ytd_color}; margin-top:2px;">{ytd_str}</span>
        </button>
        """

    # Use Streamlit radio as the actual state holder (hidden via CSS)
    # and HTML buttons as the visual layer
    st.markdown(f"""
    <div style="
        display:flex;
        border-bottom:1px solid rgba(255,255,255,0.06);
        overflow-x:auto; padding:0 28px;
    ">
        {tabs_html}
    </div>
    """, unsafe_allow_html=True)

    # Streamlit-native fallback selector (visible, functional)
    selected = st.radio(
        "Strategy",
        options=list(STRATEGIES.keys()),
        index=list(STRATEGIES.keys()).index(st.session_state["active_strategy"]),
        format_func=lambda k: f"{k} — {STRATEGIES[k]['name']}",
        horizontal=True,
        key="strategy_radio",
        label_visibility="collapsed",
    )
    st.session_state["active_strategy"] = selected
    return selected