import streamlit as st

st.set_page_config(
    page_title="Martin Capital | Portfolio Intelligence",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from utils.auth import check_password
from utils.styles import inject_global_css

if not check_password():
    st.stop()

inject_global_css()
st.switch_page("pages/1_Dashboard.py")