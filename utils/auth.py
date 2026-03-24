import streamlit as st
import hmac
import base64
from pathlib import Path


def get_logo_b64() -> str:
    base_dir = Path(__file__).parent.parent
    logo_path = base_dir / "assets" / "M__Vector_.png"
    if logo_path.exists():
        return base64.b64encode(logo_path.read_bytes()).decode()
    return ""


def check_password() -> bool:
    def _submit():
        password = st.session_state.get("password", "")
        if not password:
            return
        if hmac.compare_digest(
            password,
            st.secrets.get("PASSWORD", "Mcpqdg2010$"),
        ):
            st.session_state["authenticated"] = True
            st.session_state.pop("password", None)
        else:
            st.session_state["authenticated"] = False
            st.error("Incorrect password.")

    if st.session_state.get("authenticated"):
        return True

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        logo_b64 = get_logo_b64()
        st.markdown(f"""
        <div style="text-align:center; margin-bottom:24px; margin-top:60px;">
            <img src="data:image/png;base64,{logo_b64}" style="width:64px;height:64px;border-radius:12px;object-fit:contain;margin-bottom:12px;"/>
            <div style="font-size:20px;font-weight:700;letter-spacing:0.1em;color:#fff;">
                MARTIN CAPITAL PARTNERS
            </div>
            <div style="font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:0.06em;margin-top:4px;">
                Portfolio Dashboard
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.text_input(
            "Password",
            type="password",
            key="password",
            on_change=_submit,
            placeholder="Enter password...",
            label_visibility="collapsed",
        )
        st.button("Sign In", on_click=_submit, use_container_width=True)

    return False