import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Standard Pastel Colors for the app
PASTEL_COLORS = {
    'red': '#ff6961',
    'orange': '#ffb347',
    'green': '#77dd77',
    'blue': '#3498DB',
    'purple': '#9B59B6',      # Startup Within Mode CT
    'plum': '#DDA0DD'         # Startup Outside Mode CT
}

@st.cache_data
def load_all_data(files, _cache_version=None):
    """Loads and standardizes production shot data."""
    df_list = []  # <--- FIX: Initialize list to avoid NameError
    for file in files:
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file, low_memory=False)
            else:
                df = pd.read_excel(file)
            
            # Simplified mapping logic for this demonstration
            # In your actual tool, ensure 'EQUIPMENT_CODE' maps to 'tool_id', etc.
            if 'EQUIPMENT_CODE' in df.columns:
                df.rename(columns={'EQUIPMENT_CODE': 'tool_id'}, inplace=True)
            if 'CT' in df.columns:
                df.rename(columns={'CT': 'ACTUAL CT'}, inplace=True)
            if 'LOCAL_SHOT_TIME' in df.columns:
                df['shot_time'] = pd.to_datetime(df['LOCAL_SHOT_TIME'], dayfirst=True, errors='coerce')
                
            if 'tool_id' in df.columns and 'shot_time' in df.columns:
                df_list.append(df)
        except Exception as e:
            st.warning(f"Could not load file: {file.name}. Error: {e}")

    if not df_list:
        return pd.DataFrame()

    return pd.concat(df_list, ignore_index=True)

def _get_stable_mode(series):
    """Computes the statistical mode of cycle times."""
    if series.empty: return 0.0
    rounded = series.round(2)
    modes = rounded.mode()
    return float(modes.iloc[0]) if not modes.empty else float(series.mean())

class RunRateCalculator:
    """Handles core metrics and Startup Shot classification."""
    def __init__(self, df, tolerance, downtime_gap_tolerance, run_interval_hours=8, startup_count=10):
        self.df_raw = df.copy()
        self.tolerance = tolerance
        self.downtime_gap = downtime_gap_tolerance
        self.run_interval = run_interval_hours
        self.startup_count = startup_count
        self.results = self._calculate_all_metrics()

    def _calculate_all_metrics(self) -> dict:
        df = self.df_raw.copy()
        if df.empty: return {}

        # 1. Base Setup & Deterministic Sort
        df['ACTUAL CT'] = pd.to_numeric(df['ACTUAL CT'], errors='coerce')
        df = df.dropna(subset=['shot_time', 'ACTUAL CT']).sort_values(['shot_time']).reset_index(drop=True)

        # 2. Run Grouping based on Run Interval Threshold
        df['time_diff'] = df['shot_time'].diff().dt.total_seconds().fillna(0)
        is_new_run = df['time_diff'] > (self.run_interval * 3600)
        df['run_id'] = is_new_run.cumsum()

        # 3. Parameter Initialization
        df['startup_flag'] = 0
        df['startup_event'] = False
        
        # Mode CT per run
        run_modes = df.groupby('run_id')['ACTUAL CT'].apply(_get_stable_mode)
        df['mode_ct'] = df['run_id'].map(run_modes)
        df['lower_limit'] = df['mode_ct'] * (1 - self.tolerance)
        df['upper_limit'] = df['mode_ct'] * (1 + self.tolerance)

        # 4. Startup Shot labeling (logic a & b)
        for rid, run_df in df.groupby('run_id'):
            # First N shots are startup shots, regardless of stops within that window
            startup_indices = run_df.index[:self.startup_count]
            df.loc[startup_indices, 'startup_flag'] = 1
            df.loc[startup_indices, 'startup_event'] = True

        # 5. Stop detection (logic d - no change to stop criteria)
        is_abnormal = (df['ACTUAL CT'] < df['lower_limit']) | (df['ACTUAL CT'] > df['upper_limit'])
        # A stop is only flagged if it's NOT a startup shot
        df['stop_flag'] = np.where((is_abnormal) & (df['startup_flag'] == 0), 1, 0)
        df['stop_event'] = (df['stop_flag'] == 1) & (df['stop_flag'].shift(1, fill_value=0) == 0)

        # 6. Normal shot calculation (logic c)
        df['normal_shot_flag'] = np.where((df['stop_flag'] == 0) & (df['startup_flag'] == 0), 1, 0)
        
        return {"processed_df": df}

def calculate_run_summaries(df_proc, tolerance, downtime_gap_tolerance, pre_processed=False, startup_count=10):
    """Summarizes runs including startup shot counts."""
    if not pre_processed:
        calc = RunRateCalculator(df_proc, tolerance, downtime_gap_tolerance, startup_count=startup_count)
        df_proc = calc.results['processed_df']
    
    summary_list = []
    for rid, group in df_proc.groupby('run_id'):
        summary_list.append({
            'run_id': rid,
            'total_shots': len(group),
            'startup_shots': int(group['startup_flag'].sum()),
            'normal_shots': int(group['normal_shot_flag'].sum()),
            'stopped_shots': int(group['stop_flag'].sum()),
            'stops': int(group['stop_event'].sum()),
            'total_runtime_sec': (group['shot_time'].max() - group['shot_time'].min()).total_seconds() + group['ACTUAL CT'].iloc[-1]
        })
    return pd.DataFrame(summary_list)

def plot_shot_bar_chart(df, lower, upper, mode, show_approved_ct=False, press_mode=False, stroke_unit='CT'):
    """Cycle time graph with Startup Shot color coding (logic g)."""
    # Color mapping: Startup-Within (Purple), Startup-Outside (Plum), Stop (Red), Normal (Blue)
    conds = [
        (df['stop_flag'] == 1),
        (df['startup_flag'] == 1) & (df['ACTUAL CT'] >= df['lower_limit']) & (df['ACTUAL CT'] <= df['upper_limit']),
        (df['startup_flag'] == 1),
        (df['normal_shot_flag'] == 1)
    ]
    colors = [PASTEL_COLORS['red'], PASTEL_COLORS['purple'], PASTEL_COLORS['plum'], PASTEL_COLORS['blue']]
    df['color'] = np.select(conds, colors, default=PASTEL_COLORS['blue'])

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df['shot_time'], y=df['ACTUAL CT'], marker_color=df['color'], name="Actual CT"))
    
    # Static Legend Entries
    fig.add_trace(go.Bar(x=[None], y=[None], name="Normal Shot", marker_color=PASTEL_COLORS['blue']))
    fig.add_trace(go.Bar(x=[None], y=[None], name="Startup (Within Mode)", marker_color=PASTEL_COLORS['purple']))
    fig.add_trace(go.Bar(x=[None], y=[None], name="Startup (Outside Mode)", marker_color=PASTEL_COLORS['plum']))
    fig.add_trace(go.Bar(x=[None], y=[None], name="Stop Event", marker_color=PASTEL_COLORS['red']))

    fig.update_layout(title="Cycle Time Analysis", xaxis_title="Time", yaxis_title="Seconds")
    st.plotly_chart(fig, use_container_width=True)

def calculate_risk_scores(df_all, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_count):
    # This is a placeholder for the risk tower calculation
    return pd.DataFrame()