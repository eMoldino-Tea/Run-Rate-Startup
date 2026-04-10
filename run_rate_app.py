import streamlit as st
import pandas as pd
import numpy as np
import run_rate_utils as rr_utils

# ==============================================================================
# --- MAIN APP UI ---
# ==============================================================================
APP_VERSION = "v3.53"

def render_dashboard(df_tool, tool_id, tolerance, downtime_gap, run_interval, show_approved_ct, startup_count):
    st.header(f"Dashboard: {tool_id}")
    
    # Process data with Startup Shot logic
    calc = rr_utils.RunRateCalculator(df_tool, tolerance, downtime_gap, run_interval, startup_count)
    df_processed = calc.results.get("processed_df", pd.DataFrame())
    
    if df_processed.empty:
        st.warning("No data found for the selected parameters.")
        return

    # KPI Summary (logic c & 3)
    summaries = rr_utils.calculate_run_summaries(df_processed, tolerance, downtime_gap, pre_processed=True, startup_count=startup_count)
    
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Shots", f"{summaries['total_shots'].sum():,}")
        c2.metric("Normal Shots", f"{summaries['normal_shots'].sum():,}")
        c3.metric("Startup Shots", f"{summaries['startup_shots'].sum():,}")
        c4.metric("Stop Events", f"{summaries['stops'].sum():,}")

    # Visualization (logic 4 & g)
    rr_utils.plot_shot_bar_chart(df_processed, df_processed['lower_limit'].min(), df_processed['upper_limit'].max(), df_processed['mode_ct'].iloc[0])

    # Shot Data Table (logic 5, 6 & f)
    with st.expander("Detailed Shot Data Table", expanded=False):
        # Column mapping for display
        display_df = df_processed.copy()
        display_df['Startup Event'] = display_df['startup_event'].astype(bool)
        
        cols_to_show = ['shot_time', 'ACTUAL CT', 'mode_ct', 'stop_flag', 'startup_flag', 'Startup Event']
        st.dataframe(display_df[[c for c in cols_to_show if c in display_df.columns]], use_container_width=True)

def run_run_rate_ui():
    st.sidebar.title(f"Run Rate Analysis {APP_VERSION}")
    uploaded_files = st.sidebar.file_uploader("Upload CSV/Excel files", accept_multiple_files=True)
    
    if not uploaded_files:
        st.info("Please upload data files to begin.")
        return

    df_all = rr_utils.load_all_data(uploaded_files, _cache_version=APP_VERSION)
    if df_all.empty:
        st.error("No valid data found in uploaded files.")
        return

    # --- Sidebar Configurations (logic 1) ---
    st.sidebar.header("Configuration")
    startup_count = st.sidebar.slider("Startup Shot Count", 0, 100, 10, help="Number of shots at the start of each run to label as Startup.")
    tolerance = st.sidebar.slider("Tolerance Band (%)", 0.01, 0.50, 0.05)
    downtime_gap = st.sidebar.slider("Downtime Gap (sec)", 0.0, 10.0, 2.0)
    run_interval = st.sidebar.slider("Run Interval Threshold (hours)", 1, 24, 8)
    show_approved_ct = st.sidebar.checkbox("Show Approved CT", value=False)

    tool_id = st.sidebar.selectbox("Select Tooling ID", sorted(df_all['tool_id'].unique()))
    df_tool = df_all[df_all['tool_id'] == tool_id]

    tab1, tab2 = st.tabs(["Risk Tower", "Dashboard"])
    
    with tab1:
        st.info("Risk Tower analysis using startup configurations.")
        # Risk tower implementation would go here

    with tab2:
        render_dashboard(df_tool, tool_id, tolerance, downtime_gap, run_interval, show_approved_ct, startup_count)

if __name__ == "__main__":
    run_run_rate_ui()