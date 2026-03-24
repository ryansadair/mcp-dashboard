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

    st.markdown(f"""
    <div class="mcp-header" style="display:flex;justify-content:space-between;align-items:center;
        padding:14px 28px;border-bottom:1px solid rgba(255,255,255,0.06);
        background:linear-gradient(180deg,rgba(7,65,90,0.12) 0%,transparent 100%);flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:14px;min-width:0;">
            <img class="mcp-logo" src="data:image/png;base64,{logo_b64}" style="width:40px;height:40px;border-radius:8px;object-fit:contain;flex-shrink:0;"/>
            <div style="min-width:0;">
                <div class="mcp-firm-name" style="font-size:16px;font-weight:700;letter-spacing:0.12em;color:#fff;white-space:nowrap;">MARTIN CAPITAL PARTNERS</div>
                <div class="mcp-firm-sub" style="font-size:11px;color:rgba(255,255,255,0.35);letter-spacing:0.06em;margin-top:1px;">Portfolio Dashboard</div>
            </div>
        </div>
        <div class="mcp-header-right" style="text-align:right;">
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