"""
Branded header component with firm name, date/time, and market status.
"""

import streamlit as st
from datetime import datetime
import pytz
import base64
from pathlib import Path

def get_logo_b64() -> str:
    base_dir = Path(__file__).parent.parent
    logo_path = base_dir / "assets" / "M__Vector_.png"
    if logo_path.exists():
        return base64.b64encode(logo_path.read_bytes()).decode()
    return ""

def render_header():
    et = pytz.timezone("America/Los_Angeles")
    now = datetime.now(et)
    time_str = now.strftime("%I:%M %p PT")
    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")

    is_weekday = now.weekday() < 5
    market_hour = now.hour + now.minute / 60
    is_open = is_weekday and 6.5 <= market_hour < 13.0
    market_status = "Market Open — Live" if is_open else "Market Closed"
    status_color = "#569542" if is_open else "#C9A84C"
    logo_b64 = get_logo_b64()

    # Sprint 26: dropped white-space:nowrap from .mcp-firm-name so phone media
    # query can break the long firm name to a second line if the viewport is
    # narrow enough. Desktop keeps it on one line because the container has
    # plenty of horizontal room.
    st.markdown(f"""
    <div class="mcp-header" style="display:flex;justify-content:space-between;align-items:center;
        padding:14px 28px;border-bottom:1px solid rgba(255,255,255,0.06);
        background:linear-gradient(180deg,rgba(7,65,90,0.12) 0%,transparent 100%);flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:14px;min-width:0;">
            <img class="mcp-logo" src="data:image/png;base64,{logo_b64}" style="width:40px;height:40px;border-radius:8px;object-fit:contain;flex-shrink:0;"/>
            <div style="min-width:0;">
                <div class="mcp-firm-name" style="font-size:16px;font-weight:700;letter-spacing:0.12em;color:#fff;">MARTIN CAPITAL PARTNERS</div>
                <div class="mcp-firm-sub" style="font-size:11px;color:rgba(255,255,255,0.35);letter-spacing:0.06em;margin-top:1px;">Portfolio Dashboard</div>
            </div>
        </div>
        <div class="mcp-header-right" style="text-align:right;min-width:0;">
            <div style="font-size:13px;color:rgba(255,255,255,0.6);">
                {date_str}<span style="opacity:0.4;margin-left:10px;">{time_str}</span>
                <span style="margin-left:10px;color:rgba(255,255,255,0.15);font-size:12px;"
                      title="Auto-refreshes every 15 min">⟳</span>
            </div>
            <div style="font-size:11px;color:{status_color};margin-top:4px;">
                <span style="width:6px;height:6px;border-radius:50%;background:{status_color};display:inline-block;margin-right:6px;"></span>
                {market_status}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Mobile-only refinements (Sprint 27) ────────────────────────────────
    # Every rule lives inside @media (max-width: 640px), which desktop
    # browsers never evaluate — the desktop render is untouched by
    # construction. Phones get: reclaimed side padding (the single biggest
    # usable-width win for tables and charts), denser tab strip (more of
    # the 9 tabs visible per screen), a compacted header (subtitle hidden,
    # smaller logo), tighter ticker-bar items (more quotes per screen),
    # and slightly smaller KPI values so the 2x2 card grid breathes.
    st.markdown("""
    <style>
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
        button[data-baseweb="tab"] {
            padding-left: 10px !important;
            padding-right: 10px !important;
        }
        button[data-baseweb="tab"] p { font-size: 12px !important; }
        .mcp-header { padding: 8px 2px !important; }
        .mcp-firm-name { font-size: 14px !important; }
        .mcp-firm-sub { display: none !important; }
        .mcp-logo, .mcp-logo img { height: 30px !important; width: 30px !important; }
        .mcp-header-right { font-size: 11px !important; }
        .mc-ticker-track > div {
            padding: 8px 12px !important;
            gap: 6px !important;
        }
        .mcp-kpi-value { font-size: 19px !important; }
    }
    </style>
    """, unsafe_allow_html=True)