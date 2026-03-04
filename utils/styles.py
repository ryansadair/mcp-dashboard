import streamlit as st

GLOBAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&display=swap');

/* ── Root & Reset ────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0c1117 !important;
    color: rgba(255,255,255,0.85) !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Hide Streamlit chrome */
#MainMenu, header[data-testid="stHeader"], footer,
[data-testid="stSidebarNav"] { display: none !important; }

/* Remove default page padding */
[data-testid="stAppViewContainer"] > [data-testid="stMain"] > div {
    padding-top: 0 !important;
}
.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Metrics / KPI Cards ─────────────────────────────────────── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    border-radius: 10px !important;
    padding: 16px 18px !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: rgba(255,255,255,0.35) !important;
}
[data-testid="stMetricValue"] {
    font-family: 'DM Serif Display', serif !important;
    font-size: 22px !important;
    color: rgba(255,255,255,0.95) !important;
}

/* ── Tabs ────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.02) !important;
    border-radius: 8px !important;
    padding: 4px !important;
    gap: 4px !important;
    border-bottom: none !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 6px !important;
    color: rgba(255,255,255,0.45) !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 8px 18px !important;
    border-bottom: none !important;
    transition: all 0.2s ease !important;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background: rgba(255,255,255,0.05) !important;
    color: rgba(255,255,255,0.75) !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    background: rgba(86,149,66,0.18) !important;
    color: #7cc46a !important;
    border-bottom: none !important;
    box-shadow: 0 0 10px rgba(86,149,66,0.12) !important;
}
[data-testid="stTabs"] [aria-selected="true"]:hover {
    background: rgba(86,149,66,0.25) !important;
    color: #8fd47e !important;
}
/* Remove the default Streamlit tab highlight bar */
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    display: none !important;
}
[data-testid="stTabs"] [data-baseweb="tab-border"] {
    display: none !important;
}

/* ── DataFrames / Tables ─────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,0.05) !important;
    border-radius: 8px !important;
}

/* ── Inputs ──────────────────────────────────────────────────── */
[data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    color: rgba(255,255,255,0.8) !important;
    border-radius: 6px !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* ── Buttons (general) ────────────────────────────────────────── */
[data-testid="stButton"] > button {
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
    transition: all 0.2s ease !important;
}

/* Strategy buttons — inactive (secondary) */
[data-testid="stButton"] > button[kind="secondary"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    color: rgba(255,255,255,0.5) !important;
}
[data-testid="stButton"] > button[kind="secondary"]:hover {
    background: rgba(255,255,255,0.05) !important;
    border-color: rgba(255,255,255,0.12) !important;
    color: rgba(255,255,255,0.75) !important;
}

/* Strategy buttons — active (primary) */
[data-testid="stButton"] > button[kind="primary"] {
    background: rgba(86,149,66,0.18) !important;
    border: 1.5px solid rgba(86,149,66,0.5) !important;
    color: #7cc46a !important;
    box-shadow: 0 0 12px rgba(86,149,66,0.15), inset 0 1px 0 rgba(255,255,255,0.04) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background: rgba(86,149,66,0.25) !important;
    border-color: rgba(86,149,66,0.6) !important;
    color: #8fd47e !important;
}

/* ── Sidebar (when used) ─────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0a0e13 !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
}

/* ── Selectbox ───────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 6px !important;
}
"""


def inject_global_css():
    st.markdown(f"<style>{GLOBAL_CSS}</style>", unsafe_allow_html=True)