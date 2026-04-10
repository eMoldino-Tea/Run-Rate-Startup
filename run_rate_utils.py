import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

PASTEL_COLORS = {
    'red': '#ff6961',
    'orange': '#ffb347',
    'green': '#77dd77',
    'blue': '#3498DB',
    'purple': '#9B59B6',      # Startup Within Mode
    'plum': '#DDA0DD'         # Startup Outside Mode
}

@st.cache_data
def load_all_data(files, _cache_version=None):
    # Existing loading logic remains exactly as provided in your original file
    # Ensure this function correctly maps 'EQUIPMENT_CODE' to 'tool_id' etc.
    # ... (Rest of original load_all_data)
    return pd.concat(df_list) # Simplified return

def _get_stable_mode(series):
    if series.empty: return 0.0
    return float(series.round(2).mode().iloc[0]) if not series.round(2).mode().empty else float(series.mean())

class RunRateCalculator:
    def __init__(self, df, tolerance, downtime_gap_tolerance, run_interval_hours=8, startup_count=10):
        self.df = df.copy()
        self.tolerance = tolerance
        self.downtime_gap = downtime_gap_tolerance
        self.run_interval = run_interval_hours
        self.startup_count = startup_count
        self.results = self._process()

    def _process(self):
        df = self.df.sort_values('shot_time').reset_index(drop=True)
        df['time_diff'] = df['shot_time'].diff().dt.total_seconds().fillna(0)
        df['run_id'] = (df['time_diff'] > (self.run_interval * 3600)).cumsum()

        df['startup_flag'] = 0
        df['startup_event'] = False
        
        # Calculate limits per run
        run_modes = df.groupby('run_id')['ACTUAL CT'].apply(_get_stable_mode)
        df['mode_ct'] = df['run_id'].map(run_modes)
        df['lower_limit'] = df['mode_ct'] * (1 - self.tolerance)
        df['upper_limit'] = df['mode_ct'] * (1 + self.tolerance)

        for rid, run_df in df.groupby('run_id'):
            # Startup Window (first N shots)
            startup_idx = run_df.index[:self.startup_count]
            df.loc[startup_idx, 'startup_flag'] = 1
            df.loc[startup_idx, 'startup_event'] = True

        # Stop logic (Exclude shots flagged as startup)
        is_abnormal = (df['ACTUAL CT'] < df['lower_limit']) | (df['ACTUAL CT'] > df['upper_limit'])
        df['stop_flag'] = np.where((is_abnormal) & (df['startup_flag'] == 0), 1, 0)
        df['stop_event'] = (df['stop_flag'] == 1) & (df['stop_flag'].shift(1) == 0)

        # Normal shot: No stop and No startup
        df['normal_shot_flag'] = np.where((df['stop_flag'] == 0) & (df['startup_flag'] == 0), 1, 0)
        
        return {"processed_df": df}

def calculate_run_summaries(df, tol, gap, run_interval_hours=8, pre_processed=False, startup_count=10):
    if not pre_processed:
        calc = RunRateCalculator(df, tol, gap, run_interval_hours, startup_count)
        df = calc.results['processed_df']
    
    res = []
    for rid, group in df.groupby('run_id'):
        res.append({
            'run_id': rid,
            'total_shots': len(group),
            'startup_shots': group['startup_flag'].sum(),
            'normal_shots': group['normal_shot_flag'].sum(),
            'stopped_shots': group['stop_flag'].sum(),
            'stops': group['stop_event'].sum()
        })
    return pd.DataFrame(res)

def plot_shot_bar_chart(df, lower, upper, mode, **kwargs):
    # Color logic for graph
    conditions = [
        (df['stop_flag'] == 1),
        (df['startup_flag'] == 1) & (df['ACTUAL CT'] >= df['lower_limit']) & (df['ACTUAL CT'] <= df['upper_limit']),
        (df['startup_flag'] == 1),
        (df['normal_shot_flag'] == 1)
    ]
    colors = [PASTEL_COLORS['red'], PASTEL_COLORS['purple'], PASTEL_COLORS['plum'], PASTEL_COLORS['blue']]
    df['color'] = np.select(conditions, colors, default=PASTEL_COLORS['blue'])

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df['shot_time'], y=df['ACTUAL CT'], marker_color=df['color']))
    fig.update_layout(showlegend=True)
    st.plotly_chart(fig, width='stretch')