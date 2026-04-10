# (Keep all imports from the original file)

PASTEL_COLORS = {
    'red': '#ff6961',
    'orange': '#ffb347',
    'green': '#77dd77',
    'blue': '#3498DB',
    'purple': '#9B59B6',      # Within Mode Startup
    'plum': '#DDA0DD'         # Outside Mode Startup
}

# ... (Keep existing utility functions like format_duration, etc.) ...

class RunRateCalculator:
    def __init__(self, df, tolerance, downtime_gap_tolerance, analysis_mode='aggregate', run_interval_hours=8, startup_count=10):
        self.df_raw = df.copy()
        self.tolerance = tolerance
        self.downtime_gap_tolerance = downtime_gap_tolerance
        self.run_interval_hours = run_interval_hours
        self.startup_count = startup_count
        self.results = self._calculate_all_metrics()

    def _calculate_all_metrics(self) -> dict:
        df = self.df_raw.copy()
        if df.empty: return {}

        # 1. Base Setup
        df['ACTUAL CT'] = pd.to_numeric(df['ACTUAL CT'], errors='coerce')
        df = df.dropna(subset=['shot_time', 'ACTUAL CT']).sort_values(['shot_time']).reset_index(drop=True)

        # 2. Run Grouping
        df['time_diff_sec'] = df['shot_time'].diff().dt.total_seconds().fillna(0)
        is_new_run = df['time_diff_sec'] > (self.run_interval_hours * 3600)
        df['run_id'] = is_new_run.cumsum()

        # 3. Calculation & Startup Labeling
        df['startup_flag'] = 0
        df['startup_event'] = False
        
        # We calculate mode CT per run first
        run_modes = df.groupby('run_id')['ACTUAL CT'].apply(_get_stable_mode)
        df['mode_ct'] = df['run_id'].map(run_modes)
        df['lower_limit'] = df['mode_ct'] * (1 - self.tolerance)
        df['upper_limit'] = df['mode_ct'] * (1 + self.tolerance)

        # Apply Startup logic per run
        for rid, run_df in df.groupby('run_id'):
            # The first N shots of the run are startup
            startup_indices = run_df.index[:self.startup_count]
            df.loc[startup_indices, 'startup_flag'] = 1
            df.loc[startup_indices, 'startup_event'] = True

        # 4. Stop Detection
        df['next_diff'] = df['time_diff_sec'].shift(-1).fillna(0)
        is_gap = df['next_diff'] > (df['ACTUAL CT'] + self.downtime_gap_tolerance)
        is_abnormal = (df['ACTUAL CT'] < df['lower_limit']) | (df['ACTUAL CT'] > df['upper_limit'])
        
        # Stop flag: 1 if it's a stop, 0 otherwise. 
        # Requirement: Total Shot = Normal + Startup + Stop.
        # Startup shots are prioritized over stop flags for labeling.
        df['stop_flag'] = np.where((is_gap | is_abnormal) & (df['startup_flag'] == 0), 1, 0)
        df['stop_event'] = (df['stop_flag'] == 1) & (df['stop_flag'].shift(1, fill_value=0) == 0)

        # Production calculation
        # Normal shots = not startup AND not stop
        df['normal_shot_flag'] = np.where((df['startup_flag'] == 0) & (df['stop_flag'] == 0), 1, 0)
        
        return {"processed_df": df}

def calculate_run_summaries(df_proc, tolerance, downtime_gap_tolerance, run_interval_hours=8, pre_processed=False, startup_count=10):
    if not pre_processed:
        calc = RunRateCalculator(df_proc, tolerance, downtime_gap_tolerance, run_interval_hours=run_interval_hours, startup_count=startup_count)
        df_proc = calc.results['processed_df']
    
    summaries = []
    for rid, group in df_proc.groupby('run_id'):
        total = len(group)
        startup = group['startup_flag'].sum()
        stops = group['stop_flag'].sum()
        normal = group['normal_shot_flag'].sum()
        
        summaries.append({
            'run_id': rid,
            'total_shots': total,
            'startup_shots': startup,
            'normal_shots': normal,
            'stopped_shots': stops,
            'stops': group['stop_event'].sum(),
            'total_runtime_sec': (group['shot_time'].max() - group['shot_time'].min()).total_seconds() + group['ACTUAL CT'].iloc[-1],
            'production_time_sec': group[group['stop_flag'] == 0]['ACTUAL CT'].sum()
        })
    return pd.DataFrame(summaries)

def plot_shot_bar_chart(df, lower_limit, upper_limit, mode_ct, **kwargs):
    # Logic to color code based on Startup Status
    # Standard: Blue, Stop: Red, Startup-Within: Purple, Startup-Outside: Plum
    conditions = [
        (df['stop_flag'] == 1),
        (df['startup_flag'] == 1) & (df['ACTUAL CT'] >= df['lower_limit']) & (df['ACTUAL CT'] <= df['upper_limit']),
        (df['startup_flag'] == 1),
        (df['stop_flag'] == 0)
    ]
    choices = [PASTEL_COLORS['red'], PASTEL_COLORS['purple'], PASTEL_COLORS['plum'], PASTEL_COLORS['blue']]
    df['color'] = np.select(conditions, choices, default=PASTEL_COLORS['blue'])

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df['shot_time'], y=df['ACTUAL CT'], marker_color=df['color'], name="Shots"))
    
    # Custom Legend
    legend_elements = [
        ("Normal Shot", PASTEL_COLORS['blue']),
        ("Stop Event", PASTEL_COLORS['red']),
        ("Startup (Within Mode)", PASTEL_COLORS['purple']),
        ("Startup (Outside Mode)", PASTEL_COLORS['plum'])
    ]
    for name, color in legend_elements:
        fig.add_trace(go.Bar(x=[None], y=[None], name=name, marker_color=color))

    st.plotly_chart(fig, width='stretch')

# ... (Keep remaining Risk, Excel, and Text Analysis functions, ensuring they pass startup_count where needed) ...