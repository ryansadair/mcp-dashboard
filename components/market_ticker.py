import streamlit as st
from data.market_data import get_index_data


def render_market_ticker():
    raw = get_index_data()

    if not raw:
        st.markdown(
            "<div style='padding:10px 28px; font-size:12px; color:rgba(255,255,255,0.3);'>Market data loading...</div>",
            unsafe_allow_html=True
        )
        return

    # Symbols to display and their formatting
    DISPLAY = [
        ("^GSPC",    "S&P 500",     ""),
        ("^DJI",     "DJIA",        ""),
        ("^IXIC",    "Nasdaq",      ""),
        ("^TNX",     "10Y Treasury","%"),
        ("GC=F",     "Gold",        "$"),
        ("CL=F",     "Crude Oil",   "$"),
        ("DX-Y.NYB", "US Dollar",   ""),
    ]

    items_html = ""
    for symbol, label, prefix in DISPLAY:
        d = raw.get(symbol, {})
        price = d.get("price", 0)
        chg   = d.get("change_pct", 0)
        up    = chg >= 0
        color = "#569542" if up else "#c45454"
        arrow = "+" if up else ""

        # Format price
        if prefix == "$":
            price_str = f"${price:,.2f}"
        elif prefix == "%":
            price_str = f"{price:.2f}%"
        else:
            price_str = f"{price:,.2f}"

        chg_str = f"{arrow}{chg:.2f}%"

        items_html += (
            "<div style='display:flex;align-items:center;gap:8px;padding:10px 20px;"
            "border-right:1px solid rgba(255,255,255,0.04);white-space:nowrap;'>"
            f"<span style='font-size:10px;color:rgba(255,255,255,0.35);text-transform:uppercase;"
            f"letter-spacing:0.06em;'>{label}</span>"
            f"<span style='font-size:13px;font-weight:600;color:rgba(255,255,255,0.9);'>{price_str}</span>"
            f"<span style='font-size:12px;font-weight:500;color:{color};'>{chg_str}</span>"
            "</div>"
        )

    # Duplicate items so the scroll loops seamlessly
    ticker_content = items_html + items_html

    css = """<style>
@keyframes ticker-scroll {
    0%   { transform: translateX(0); }
    100% { transform: translateX(-50%); }
}
.mc-ticker-wrap {
    overflow: hidden;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    background: rgba(0,0,0,0.2);
    width: 100%;
}
.mc-ticker-track {
    display: flex;
    width: max-content;
    animation: ticker-scroll 40s linear infinite;
}
.mc-ticker-track:hover {
    animation-play-state: paused;
}
</style>"""

    html = (
        css +
        "<div class='mc-ticker-wrap'><div class='mc-ticker-track'>" +
        ticker_content +
        "</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)