import streamlit as st
import pandas as pd
import numpy as np
import warnings
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import run_rate_utils as rr_utils

# ==============================================================================
# --- 1. PAGE CONFIG & SETUP ---
# ==============================================================================
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    st.set_page_config(layout="wide", page_title="Run Rate Analysis Dashboard")
except Exception:
    pass

st.markdown("""
<style>
    span[data-baseweb="tag"] {
        background-color: #34495e !important;
        color: #ecf0f1 !important;
    }
    span[data-baseweb="tag"] svg {
        fill: #ecf0f1 !important;
    }
</style>
""", unsafe_allow_html=True)

def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.header("🔒 Protected Internal Tool")
    password_input = st.text_input("Enter Company Password", type="password")
    if password_input:
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Password incorrect")
    return False

if not check_password():
    st.stop()

# ==============================================================================
# --- 3. UI RENDERING FUNCTIONS (UPDATED) ---
# ==============================================================================

def render_risk_tower(df_all_tools, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_count):
    st.title("Run Rate Risk Tower")
    risk_df = rr_utils.calculate_risk_scores(df_all_tools, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_count)

    if risk_df.empty:
        st.warning("Not enough data to generate a risk tower.")
        return

    def style_risk(row):
        score = row['Risk Score']
        if score > 70: color = rr_utils.PASTEL_COLORS['green']
        elif score > 50: color = rr_utils.PASTEL_COLORS['orange']
        else: color = rr_utils.PASTEL_COLORS['red']
        return [f'background-color: {color}' for _ in row]

    st.dataframe(
        risk_df.style.apply(style_risk, axis=1).format({'Risk Score': '{:.0f}'}),
        width='stretch', hide_index=True
    )

def render_dashboard(df_tool, tool_id_selection, tolerance, downtime_gap_tolerance, run_interval_hours, show_approved_ct, min_shots_filter, startup_count):
    analysis_level = st.radio("Select Analysis Level", options=["Daily (by Run)", "Weekly (by Run)", "Custom Period (by Run)"], horizontal=True)
    
    # Logic to identify tooling type for Press Mode
    _press_auto = df_tool['tooling_type'].str.lower().str.contains('press|stamp', na=False).any() if 'tooling_type' in df_tool.columns else False
    press_mode = st.toggle("Press / Stamping Mode", value=bool(_press_auto))
    stroke_unit = st.radio("Unit", ["SPM", "SPH", "CT"], horizontal=True) if press_mode else "CT"

    @st.cache_data
    def get_processed_data(df, interval, tol, gap, s_count):
        calc = rr_utils.RunRateCalculator(df, tol, gap, run_interval_hours=interval, startup_count=s_count)
        return calc.results.get("processed_df", pd.DataFrame())

    df_processed = get_processed_data(df_tool, run_interval_hours, tolerance, downtime_gap_tolerance, startup_count)

    # Calculation logic for KPIs
    run_summary = rr_utils.calculate_run_summaries(df_processed, tolerance, downtime_gap_tolerance, pre_processed=True, startup_count=startup_count)
    
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        t_s = run_summary['total_shots'].sum() if not run_summary.empty else 0
        n_s = run_summary['normal_shots'].sum() if not run_summary.empty else 0
        su_s = run_summary['startup_shots'].sum() if not run_summary.empty else 0
        st_s = run_summary['stopped_shots'].sum() if not run_summary.empty else 0
        
        c1.metric("Total Shots", f"{t_s:,}")
        c2.metric("Normal Shots", f"{n_s:,}")
        c3.metric("Startup Shots", f"{su_s:,}")
        c4.metric("Stop Events", f"{run_summary['stops'].sum() if not run_summary.empty else 0}")

    rr_utils.plot_shot_bar_chart(df_processed, df_processed['lower_limit'].min(), df_processed['upper_limit'].max(), df_processed['mode_ct'].iloc[0], show_approved_ct=show_approved_ct, press_mode=press_mode, stroke_unit=stroke_unit)

    with st.expander("View Shot Data Table"):
        cols = ['run_label', 'shot_time', 'ACTUAL CT', 'mode_ct', 'stop_flag', 'startup_flag', 'startup_event']
        st.dataframe(df_processed[[c for c in cols if c in df_processed.columns]])

APP_VERSION = "v3.53"

def run_run_rate_ui():
    st.sidebar.markdown(f"Run Rate Analysis | **{APP_VERSION}**")
    uploaded_files = st.sidebar.file_uploader("Upload Files", accept_multiple_files=True)
    if not uploaded_files: st.info("Upload files to begin."); st.stop()

    df_all = rr_utils.load_all_data(uploaded_files, _cache_version=APP_VERSION)

    st.sidebar.markdown("### Analysis Parameters")
    tolerance = st.sidebar.slider("Tolerance Band", 0.01, 0.50, 0.05)
    downtime_gap = st.sidebar.slider("Downtime Gap (sec)", 0.0, 5.0, 2.0)
    run_interval = st.sidebar.slider("Run Interval (hours)", 1, 24, 8)
    startup_count = st.sidebar.slider("Startup Shot Count", 0, 100, 10)
    show_approved_ct = st.sidebar.checkbox("Show Approved CT")

    tool_id = st.sidebar.selectbox("Select Tool", sorted(df_all['tool_id'].unique()))
    df_tool = df_all[df_all['tool_id'] == tool_id]

    tab1, tab2 = st.tabs(["Risk Tower", "Dashboard"])
    with tab1: render_risk_tower(df_all, run_interval, 1, tolerance, downtime_gap, startup_count)
    with tab2: render_dashboard(df_tool, tool_id, tolerance, downtime_gap, run_interval, show_approved_ct, 1, startup_count)

if __name__ == "__main__":
    run_run_rate_ui()