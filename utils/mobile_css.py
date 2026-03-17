"""
Martin Capital Partners — Mobile Responsiveness CSS
utils/mobile_css.py

Injects CSS media queries to make the dashboard usable on iPhone and tablet.
Called once from 1_Dashboard.py after inject_global_css().

Target breakpoints:
  - ≤768px: Tablet (iPad portrait)
  - ≤480px: Phone (iPhone 14/15 portrait)

Key adaptations:
  1. Market ticker bar → horizontal scroll, smaller font
  2. KPI cards → 2-col grid on tablet, single-col on phone
  3. Strategy selector → full width
  4. Holdings table → horizontal scroll with sticky first column
  5. Plotly charts → reduced height, touch-friendly
  6. Overview layout → stacked (no side-by-side columns)
  7. Tab bar → horizontal scroll, no wrapping
  8. Sidebar content → hidden on mobile (tab-based nav only)
  9. Font sizes → slightly reduced for density
  10. Touch targets → minimum 44px tap targets
"""

import streamlit as st


def inject_mobile_css():
    """Inject responsive CSS media queries for mobile/tablet support."""

    st.markdown("""
<style>
/* ══════════════════════════════════════════════════════════════
   MOBILE RESPONSIVENESS — Martin Capital Dashboard
   ══════════════════════════════════════════════════════════════ */

/* ── Tablet (≤768px) ──────────────────────────────────────────── */
@media screen and (max-width: 768px) {

    /* Main container: reduce side padding */
    .stApp > header + div,
    [data-testid="stAppViewBlockContainer"] {
        padding-left: 12px !important;
        padding-right: 12px !important;
    }
    .block-container {
        padding-left: 12px !important;
        padding-right: 12px !important;
        max-width: 100% !important;
    }

    /* Strategy selector: full width */
    [data-testid="stSelectbox"] {
        max-width: 100% !important;
    }

    /* Tab bar: horizontal scroll, don't wrap */
    [data-testid="stTabs"] [role="tablist"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        flex-wrap: nowrap !important;
        scrollbar-width: none;  /* Firefox */
        -ms-overflow-style: none;  /* IE */
    }
    [data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {
        display: none;  /* Chrome/Safari */
    }
    [data-testid="stTabs"] [role="tab"] {
        white-space: nowrap !important;
        flex-shrink: 0 !important;
        font-size: 12px !important;
        padding: 8px 12px !important;
        min-height: 44px !important;  /* Touch target */
    }

    /* Columns: stack vertically when they're too narrow */
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    /* KPI cards column: 2-per-row on tablet */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width: 45% !important;
        flex: 1 1 45% !important;
    }

    /* Metric containers: slightly smaller */
    [data-testid="stMetric"] {
        padding: 8px !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 20px !important;
    }

    /* Dataframes: horizontal scroll */
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }
    [data-testid="stDataFrame"] table {
        min-width: 600px;
    }

    /* Plotly charts: reduce height */
    [data-testid="stPlotlyChart"] {
        max-height: 300px !important;
    }

    /* Custom HTML tables (markets, alerts): allow scroll */
    .stMarkdown table {
        display: block;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        white-space: nowrap;
    }

    /* Footer: wrap instead of flex */
    .stMarkdown div[style*="justify-content:center"] {
        flex-wrap: wrap !important;
        gap: 6px !important;
    }
}


/* ── Phone (≤480px) ──────────────────────────────────────────── */
@media screen and (max-width: 480px) {

    /* Even tighter padding */
    .block-container {
        padding-left: 8px !important;
        padding-right: 8px !important;
    }

    /* Strategy selector: compact */
    [data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
        min-height: 48px !important;
    }
    [data-testid="stSelectbox"] [data-baseweb="select"] div[class*="st-at"],
    [data-testid="stSelectbox"] [data-baseweb="select"] div[class*="st-ax"] {
        font-size: 13px !important;
    }

    /* KPI cards: single column stack */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }

    /* Tab labels: even smaller */
    [data-testid="stTabs"] [role="tab"] {
        font-size: 11px !important;
        padding: 8px 10px !important;
    }

    /* Metric value: smaller for phone */
    [data-testid="stMetricValue"] {
        font-size: 18px !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 10px !important;
    }

    /* Plotly: shorter on phone */
    [data-testid="stPlotlyChart"] {
        max-height: 240px !important;
    }

    /* Expanders: bigger touch target */
    [data-testid="stExpander"] summary {
        min-height: 44px !important;
        padding: 12px !important;
    }

    /* Radio buttons: bigger tap targets */
    [data-testid="stRadio"] label {
        min-height: 44px !important;
        display: flex !important;
        align-items: center !important;
        padding: 6px 12px !important;
    }

    /* Buttons: minimum touch size */
    .stButton > button {
        min-height: 44px !important;
        min-width: 44px !important;
    }

    /* Spinner: don't take full width on phone */
    [data-testid="stSpinner"] {
        font-size: 12px !important;
    }

    /* Selectbox dropdown: bigger items for touch */
    [data-baseweb="menu"] [role="option"] {
        min-height: 44px !important;
        padding: 10px 12px !important;
    }
}


/* ── Universal touch improvements ──────────────────────────────── */
@media (pointer: coarse) {
    /* Detected touch device — ensure minimum tap targets */

    /* All clickable elements */
    a, button, [role="tab"], [role="option"], label, summary {
        min-height: 44px;
    }

    /* Selectbox: easier to tap */
    [data-baseweb="select"] {
        min-height: 44px;
    }

    /* Checkbox/radio: bigger hit area */
    [data-testid="stCheckbox"] label,
    [data-testid="stRadio"] label {
        padding: 8px !important;
    }

    /* Disable hover effects that don't work on touch */
    .stButton > button:hover {
        transform: none !important;
    }
}


/* ── iPhone safe area (notch/home indicator) ───────────────────── */
@supports (padding-bottom: env(safe-area-inset-bottom)) {
    .stApp {
        padding-bottom: env(safe-area-inset-bottom);
    }
}


/* ── Landscape phone adjustments ───────────────────────────────── */
@media screen and (max-height: 500px) and (orientation: landscape) {
    /* Reduce vertical spacing in landscape mode */
    [data-testid="stMetric"] {
        padding: 4px !important;
    }
    [data-testid="stPlotlyChart"] {
        max-height: 200px !important;
    }
}


/* ── Market ticker bar responsiveness ──────────────────────────── */
/* The market ticker bar uses custom HTML; these target it */
@media screen and (max-width: 768px) {
    /* Ticker bar: horizontal scroll */
    .stMarkdown div[style*="display:flex"][style*="gap:0"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
        scrollbar-width: none;
    }
    .stMarkdown div[style*="display:flex"][style*="gap:0"]::-webkit-scrollbar {
        display: none;
    }
}

@media screen and (max-width: 480px) {
    /* Ticker items: compact on phone */
    .stMarkdown div[style*="padding:10px 20px"] {
        padding: 8px 12px !important;
    }
    .stMarkdown span[style*="font-size:10px"][style*="text-transform:uppercase"] {
        font-size: 9px !important;
    }
}


/* ── PWA / Home screen improvements ────────────────────────────── */
@media screen and (display-mode: standalone) {
    /* When added to home screen: no extra padding */
    .stApp {
        padding-top: env(safe-area-inset-top, 0px);
    }
}
</style>
""", unsafe_allow_html=True)