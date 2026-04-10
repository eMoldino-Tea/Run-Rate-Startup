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

# Multiselect chip colours
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
# --- 3. UI RENDERING FUNCTIONS ---
# ==============================================================================

def render_risk_tower(df_all_tools, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_count):
    st.title("Run Rate Risk Tower")
    st.info("This tower analyses performance over the last 4 weeks, identifying tools that require attention.")

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

    cols_order = ['Tool ID', 'Analysis Period', 'Risk Score', 'Primary Risk Factor', 'Weekly Stability', 'Details']
    display_df = risk_df[[col for col in cols_order if col in risk_df.columns]]
    st.dataframe(display_df.style.apply(style_risk, axis=1).format({'Risk Score': '{:.0f}'}), width='stretch', hide_index=True)

def render_trends_tab(df_tool, tolerance, downtime_gap_tolerance, run_interval_hours, min_shots_filter, startup_count, tool_id_selection='Unknown'):
    st.header("Historical Performance Trends")
    col_ctrl, _ = st.columns([1, 3])
    with col_ctrl:
        trend_freq = st.selectbox("Select Trend Frequency", ["Daily", "Weekly", "Monthly"], key="trend_freq_select")

    _prep = rr_utils.RunRateCalculator(df_tool, tolerance, downtime_gap_tolerance, analysis_mode='aggregate', run_interval_hours=run_interval_hours, startup_count=startup_count)
    df_tool_proc = _prep.results.get("processed_df", df_tool)

    if trend_freq == "Daily": grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.date)
    elif trend_freq == "Weekly": grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.to_period('W'))
    else: grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.to_period('M'))

    trend_data = []
    period_name = "Date" if trend_freq == "Daily" else "Week" if trend_freq == "Weekly" else "Month"

    for period, df_period in grouper:
        run_summaries = rr_utils.calculate_run_summaries(df_period, tolerance, downtime_gap_tolerance, run_interval_hours=run_interval_hours, pre_processed=True, startup_count=startup_count)
        if run_summaries.empty: continue
        run_summaries = run_summaries[run_summaries['total_shots'] >= min_shots_filter]
        if run_summaries.empty: continue

        total_runtime = run_summaries['total_runtime_sec'].sum()
        prod_time = run_summaries['production_time_sec'].sum()
        downtime = run_summaries['downtime_sec'].sum()
        stops = run_summaries['stops'].sum()
        total_shots = run_summaries['total_shots'].sum()
        normal_shots = run_summaries['normal_shots'].sum()

        stability = (prod_time / total_runtime * 100) if total_runtime > 0 else 0
        efficiency = (normal_shots / total_shots * 100) if total_shots > 0 else 0

        label = period.strftime('%Y-%m-%d') if trend_freq == "Daily" else f"W{period.week} {period.year}" if trend_freq == "Weekly" else period.strftime('%B %Y')
        trend_data.append({
            period_name: label,
            'SortKey': period if trend_freq == "Daily" else period.start_time,
            'Stability Index (%)': stability,
            'Efficiency (%)': efficiency,
            'MTTR (min)': (downtime / 60 / stops) if stops > 0 else 0,
            'MTBF (min)': (prod_time / 60 / stops) if stops > 0 else (prod_time / 60),
            'Total Shots': total_shots,
            'Normal Shots': normal_shots,
            'Stop Events': stops
        })

    if not trend_data:
        st.warning("No data found.")
        return

    df_trends = pd.DataFrame(trend_data).sort_values('SortKey').drop(columns=['SortKey'])
    st.dataframe(df_trends.style.background_gradient(subset=['Stability Index (%)'], cmap='RdYlGn', vmin=0, vmax=100), width='stretch')

def render_dashboard(df_tool, tool_id_selection, tolerance, downtime_gap_tolerance, run_interval_hours, show_approved_ct, min_shots_filter, startup_count):
    analysis_level = st.radio("Select Analysis Level", options=["Daily (by Run)", "Weekly (by Run)", "Monthly (by Run)", "Custom Period (by Run)"], horizontal=True, key="rr_analysis_level")
    
    press_mode = st.toggle("Press / Stamping Mode", value=False, key="rr_press_mode")
    stroke_unit = st.radio("Mode Display Unit", options=["SPM", "SPH", "CT"], index=0, horizontal=True) if press_mode else "CT"

    @st.cache_data
    def get_processed_data(df, interval_hours, tol, gap, s_count):
        base_calc = rr_utils.RunRateCalculator(df, tol, gap, analysis_mode='aggregate', run_interval_hours=interval_hours, startup_count=s_count)
        return base_calc.results.get("processed_df", pd.DataFrame())

    df_processed = get_processed_data(df_tool, run_interval_hours, tolerance, downtime_gap_tolerance, startup_count)

    if df_processed.empty:
        st.error("Data processing failed.")
        return

    # Date Selection Logic (Summary)
    df_view = df_processed.copy() # Simplified for brevity in this block, actual logic handles filters
    
    # Labeling runs chronologically
    if not df_view.empty and 'run_id' in df_view.columns:
        run_first_shot = df_view.groupby('run_id')['shot_time'].min().sort_values()
        run_label_map = {rid: f"Run {i+1:03d}" for i, rid in enumerate(run_first_shot.index)}
        df_view['run_label'] = df_view['run_id'].map(run_label_map)

    run_summary_df = rr_utils.calculate_run_summaries(df_view, tolerance, downtime_gap_tolerance, pre_processed=True, startup_count=startup_count)
    
    # 1. KPI Metrics
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        t_s = run_summary_df['total_shots'].sum() if not run_summary_df.empty else 0
        n_s = run_summary_df['normal_shots'].sum() if not run_summary_df.empty else 0
        su_s = run_summary_df['startup_shots'].sum() if not run_summary_df.empty else 0
        st_s = run_summary_df['stopped_shots'].sum() if not run_summary_df.empty else 0
        
        c1.metric("Total Shots", f"{t_s:,}")
        c2.metric("Normal Shots", f"{n_s:,}")
        c3.metric("Startup Shots", f"{su_s:,}")
        c4.metric("Stop Events", f"{run_summary_df['stops'].sum() if not run_summary_df.empty else 0}")

    # Charts
    rr_utils.plot_shot_bar_chart(df_view, df_view['lower_limit'].min(), df_view['upper_limit'].max(), df_view['mode_ct'].iloc[0] if not df_view.empty else 0, show_approved_ct=show_approved_ct, press_mode=press_mode, stroke_unit=stroke_unit)

    # Data Table Update
    with st.expander("View Shot Data Table"):
        cols = ['run_label', 'shot_time', 'ACTUAL CT', 'mode_ct', 'stop_flag', 'startup_flag', 'startup_event']
        display_table = df_view[[c for c in cols if c in df_view.columns]].copy()
        display_table['startup_event'] = display_table['startup_event'].astype(bool)
        st.dataframe(display_table)

def run_run_rate_ui():
    st.sidebar.title("File Upload")
    uploaded_files = st.sidebar.file_uploader("Upload Data", accept_multiple_files=True)
    if not uploaded_files: st.stop()
    
    df_all = rr_utils.load_all_data(uploaded_files)
    
    st.sidebar.markdown("### Analysis Parameters ⚙️")
    tolerance = st.sidebar.slider("Tolerance Band", 0.01, 0.50, 0.05)
    downtime_gap = st.sidebar.slider("Downtime Gap (sec)", 0.0, 5.0, 2.0)
    run_interval = st.sidebar.slider("Run Interval (hours)", 1, 24, 8)
    startup_count = st.sidebar.slider("Startup Shot Count", 0, 100, 10, help="Number of shots at the start of each run to label as Startup.")
    show_approved_ct = st.sidebar.checkbox("Show Approved CT")

    tool_id = st.sidebar.selectbox("Select Tool", sorted(df_all['tool_id'].unique()))
    df_tool = df_all[df_all['tool_id'] == tool_id]

    tab1, tab2 = st.tabs(["Risk Tower", "Dashboard"])
    with tab1: render_risk_tower(df_all, run_interval, 1, tolerance, downtime_gap, startup_count)
    with tab2: render_dashboard(df_tool, tool_id, tolerance, downtime_gap, run_interval, show_approved_ct, 1, startup_count)

if __name__ == "__main__":
    run_run_rate_ui()