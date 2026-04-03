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

# Multiselect chip colours — matching Capacity Risk app
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


# ==============================================================================
# --- 2. LOGIN ---
# ==============================================================================

def check_password():
    """Returns True if the user has entered the correct password."""
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

def render_risk_tower(df_all_tools, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_thresh, startup_count):
    """Renders the Risk Tower tab."""
    st.title("Run Rate Risk Tower")
    st.info(
        "This tower analyses performance over the last 4 weeks, identifying tools "
        "that require attention. Tools with the lowest scores are at the highest risk."
    )

    with st.expander("ℹ️ How the Risk Tower Works"):
        st.markdown(f"""
        The Risk Tower evaluates each tool based on its performance over its own most recent
        4-week period of operation. Here's how the metrics are calculated:

        - **Analysis Period**: Shows the exact 4-week date range used for each tool's analysis.
        - **Data Filters**:
            - **Run Interval**: Gaps longer than {run_interval_hours} hours are treated as breaks between runs.
            - **Min Shots**: Production runs with fewer than {min_shots_filter} shots are excluded.
        - **Risk Score**: A performance indicator from 0–100.
            - Starts with the tool's overall **Stability Index (%)** for the period.
            - A **20-point penalty** is applied if stability shows a declining trend.
        - **Primary Risk Factor**: Identifies the main issue affecting performance:
            1. **Declining Trend** — if stability is worsening over time.
            2. **High MTTR** — if avg stop duration is significantly above peer average.
            3. **Frequent Stops** — if MTBF is significantly below peer average.
            4. **Low Stability** — if none of the above but stability is still low.
        - **Color Coding**:
            - <span style='background-color:#ff6961;color:black;padding:2px 5px;border-radius:5px;'>Red (0–50)</span>: High Risk
            - <span style='background-color:#ffb347;color:black;padding:2px 5px;border-radius:5px;'>Orange (51–70)</span>: Medium Risk
            - <span style='background-color:#77dd77;color:black;padding:2px 5px;border-radius:5px;'>Green (>70)</span>: Low Risk
        """, unsafe_allow_html=True)

    risk_df = rr_utils.calculate_risk_scores(df_all_tools, run_interval_hours, min_shots_filter, tolerance, downtime_gap_tolerance, startup_thresh, startup_count)

    if risk_df.empty:
        st.warning("Not enough data across multiple tools in the last 4 weeks to generate a risk tower.")
        return

    def style_risk(row):
        score = row['Risk Score']
        if score > 70:
            color = rr_utils.PASTEL_COLORS['green']
        elif score > 50:
            color = rr_utils.PASTEL_COLORS['orange']
        else:
            color = rr_utils.PASTEL_COLORS['red']
        return [f'background-color: {color}' for _ in row]

    cols_order = ['Tool ID', 'Analysis Period', 'Risk Score',
                  'Primary Risk Factor', 'Weekly Stability', 'Details']
    display_df = risk_df[[col for col in cols_order if col in risk_df.columns]]
    st.dataframe(
        display_df.style.apply(style_risk, axis=1).format({'Risk Score': '{:.0f}'}),
        width='stretch', hide_index=True
    )


def render_trends_tab(df_tool, tolerance, downtime_gap_tolerance,
                      run_interval_hours, min_shots_filter, startup_thresh, startup_count,
                      tool_id_selection='Unknown'):
    """Renders the Trends Analysis tab."""
    st.header("Historical Performance Trends")
    st.info(
        f"Trends are calculated using 'Run-Based' logic. Gaps larger than "
        f"{run_interval_hours} hours are excluded from the timeline to provide "
        f"accurate stability metrics."
    )

    col_ctrl, _ = st.columns([1, 3])
    with col_ctrl:
        trend_freq = st.selectbox("Select Trend Frequency", ["Daily", "Weekly", "Monthly"],
                                  key="trend_freq_select")

    with st.expander("ℹ️ About Trends Metrics"):
        st.markdown("""
        - **Stability Index (%)**: Percentage of run time spent in production.
        - **Efficiency (%)**: Percentage of shots that were normal (non-stops).
        - **MTTR (min)**: Mean Time To Repair (avg stop duration).
        - **MTBF (min)**: Mean Time Between Failures (avg uptime between stops).
        - **Total Shots**: Total output for the period.
        - **Stop Events**: Number of times the machine stopped.
        """)

    trend_data = []

    if trend_freq == "Daily":
        period_name = "Date"
    elif trend_freq == "Weekly":
        period_name = "Week"
    else:
        period_name = "Month"

    _prep = rr_utils.RunRateCalculator(
        df_tool, tolerance, downtime_gap_tolerance,
        analysis_mode='aggregate', run_interval_hours=run_interval_hours,
        startup_stop_threshold_minutes=startup_thresh, startup_shot_count=startup_count
    )
    df_tool_proc = _prep.results.get("processed_df", df_tool)

    if trend_freq == "Daily":
        grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.date)
    elif trend_freq == "Weekly":
        grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.to_period('W'))
    else:
        grouper = df_tool_proc.groupby(df_tool_proc['shot_time'].dt.to_period('M'))

    for period, df_period in grouper:
        if df_period.empty:
            continue

        run_summaries = rr_utils.calculate_run_summaries(
            df_period, tolerance, downtime_gap_tolerance,
            run_interval_hours=run_interval_hours,
            pre_processed=True,
            startup_stop_threshold_minutes=startup_thresh,
            startup_shot_count=startup_count
        )
        if run_summaries.empty:
            continue

        run_summaries = run_summaries[run_summaries['total_shots'] >= min_shots_filter]
        if run_summaries.empty:
            continue

        total_runtime = run_summaries['total_runtime_sec'].sum()
        prod_time = run_summaries['production_time_sec'].sum()
        downtime = run_summaries['downtime_sec'].sum()
        stops = run_summaries['stops'].sum()
        total_shots = run_summaries['total_shots'].sum()
        normal_shots = run_summaries['normal_shots'].sum()
        normal_startups = run_summaries.get('normal_startup_shots', pd.Series(dtype=int)).sum()
        slow_startups = run_summaries.get('slow_startup_shots', pd.Series(dtype=int)).sum()
        failed_startups = run_summaries.get('failed_startup_shots', pd.Series(dtype=int)).sum()

        stability = (prod_time / total_runtime * 100) if total_runtime > 0 else 0
        efficiency = (normal_shots / total_shots * 100) if total_shots > 0 else 0
        mttr = (downtime / 60 / stops) if stops > 0 else 0
        mtbf = (prod_time / 60 / stops) if stops > 0 else (prod_time / 60)

        if trend_freq == "Daily":
            label = period.strftime('%Y-%m-%d')
        elif trend_freq == "Weekly":
            label = f"W{period.week} {period.year}"
        else:
            label = period.strftime('%B %Y')

        trend_data.append({
            period_name: label,
            'SortKey': period if trend_freq == "Daily" else period.start_time,
            'Stability Index (%)': stability,
            'Efficiency (%)': efficiency,
            'MTTR (min)': mttr,
            'MTBF (min)': mtbf,
            'Total Shots': total_shots,
            'Normal Shots': normal_shots, 
            'Normal Start-ups': normal_startups,
            'Slow Start-ups': slow_startups,
            'Failed Start-ups': failed_startups,
            'Stop Events': stops,
            'Production Time (h)': prod_time / 3600,
            'Downtime (h)': downtime / 3600,
        })

    if not trend_data:
        st.warning("No data found for the selected tool to generate trends.")
        return

    df_trends = (pd.DataFrame(trend_data)
                 .sort_values('SortKey', ascending=True)
                 .drop(columns=['SortKey']))

    st.dataframe(
        df_trends.style.format({
            'Stability Index (%)': '{:.1f}', 'Efficiency (%)': '{:.1f}',
            'MTTR (min)': '{:.1f}', 'MTBF (min)': '{:.1f}',
            'Total Shots': '{:,.0f}', 'Normal Shots': '{:,.0f}', 
            'Normal Start-ups': '{:,.0f}', 'Slow Start-ups': '{:,.0f}', 'Failed Start-ups': '{:,.0f}', 
            'Stop Events': '{:,.0f}', 'Production Time (h)': '{:.1f}', 'Downtime (h)': '{:.1f}',
        }).background_gradient(subset=['Stability Index (%)'],
                               cmap='RdYlGn', vmin=0, vmax=100),
        width='stretch'
    )

    # ── Weekly comparison report download ────────────────────────────────────
    if trend_freq == "Weekly" and not df_trends.empty:
        st.markdown("---")
        col_dl, col_info = st.columns([1, 3])
        with col_dl:
            try:
                pptx_bytes = rr_utils.generate_weekly_comparison_pptx(
                    df_trends, tool_id_selection
                )
                st.download_button(
                    label="📊 Download Weekly Report (.pptx)",
                    data=pptx_bytes,
                    file_name=(
                        f"Weekly_Report_{tool_id_selection.replace(' ', '_')}_"
                        f"{pd.Timestamp.now().strftime('%Y%m%d')}.pptx"
                    ),
                    mime="application/vnd.openxmlformats-officedocument"
                          ".presentationml.presentation",
                    width='stretch',
                )
            except Exception as e:
                st.error(f"Could not generate report: {e}")
        with col_info:
            st.caption(
                "Generates a single-slide PowerPoint with a week-on-week "
                "comparison table including delta % vs the prior week."
            )
        st.markdown("---")

    st.subheader("Visual Trend")
    metric_to_plot = st.selectbox(
        "Select Metric to Visualize",
        ['Stability Index (%)', 'Efficiency (%)', 'MTTR (min)', 'MTBF (min)', 'Total Shots'],
        key="trend_viz_select"
    )

    fig = px.line(df_trends.sort_index(ascending=True), x=period_name,
                  y=metric_to_plot, markers=True,
                  title=f"{metric_to_plot} Trend ({trend_freq})")

    if '%)' in metric_to_plot:
        for y0, y1, c in [(0, 50, rr_utils.PASTEL_COLORS['red']),
                          (50, 70, rr_utils.PASTEL_COLORS['orange']),
                          (70, 100, rr_utils.PASTEL_COLORS['green'])]:
            fig.add_shape(type="rect", xref="paper", x0=0, x1=1, y0=y0, y1=y1,
                          fillcolor=c, opacity=0.1, layer="below", line_width=0)
        fig.update_yaxes(range=[0, 105])

    st.plotly_chart(fig, width='stretch')


def render_dashboard(df_tool, tool_id_selection, tolerance, downtime_gap_tolerance,
                     run_interval_hours, show_approved_ct, min_shots_filter,
                     startup_thresh, startup_count):
    """Renders the main Run Rate Dashboard tab."""

    analysis_level = st.radio(
        "Select Analysis Level",
        options=["Daily (by Run)", "Weekly (by Run)", "Monthly (by Run)", "Custom Period (by Run)"],
        horizontal=True,
        key="rr_analysis_level"
    )

    st.markdown("---")

    @st.cache_data(show_spinner="Performing initial data processing...")
    def get_processed_data(df, interval_hours, tolerance, downtime_gap_tolerance, startup_thresh, startup_count):
        """
        Single authoritative processing pass over the FULL tool dataset.
        """
        base_calc = rr_utils.RunRateCalculator(
            df, tolerance, downtime_gap_tolerance,
            analysis_mode='aggregate', run_interval_hours=interval_hours,
            startup_stop_threshold_minutes=startup_thresh, startup_shot_count=startup_count
        )
        df_processed = base_calc.results.get("processed_df", pd.DataFrame())
        if not df_processed.empty:
            df_processed['run_group'] = df_processed['stop_event'].cumsum()
            df_processed['week'] = df_processed['shot_time'].dt.isocalendar().week
            df_processed['year'] = df_processed['shot_time'].dt.isocalendar().year
            df_processed['date'] = df_processed['shot_time'].dt.date
            df_processed['month'] = df_processed['shot_time'].dt.to_period('M')
        return df_processed

    df_processed = get_processed_data(
        df_tool, run_interval_hours, tolerance, downtime_gap_tolerance, startup_thresh, startup_count
    )

    detailed_view = st.toggle("Show Detailed Analysis", value=True, key="rr_detailed_view")

    if df_processed.empty:
        st.error(f"Could not process data for {tool_id_selection}. "
                 f"Check file format or data range.")
        st.stop()

    st.markdown(f"### {tool_id_selection} Overview")

    mode = 'by_run'
    df_view = pd.DataFrame()
    info_placeholder = None
    info_base_text = ""

    # ------------------------------------------------------------------
    # Date / period selection
    # ------------------------------------------------------------------
    if "Daily" in analysis_level:
        min_date = df_processed['date'].min()
        max_date = df_processed['date'].max()

        col_sel, col_info = st.columns([1, 2])
        with col_sel:
            selected_date = st.date_input(
                "Select Date", value=max_date,
                min_value=min_date, max_value=max_date,
                key="rr_daily_select"
            )
        with col_info:
            info_placeholder = st.empty()
            info_base_text = f"**Viewing Date:** {selected_date.strftime('%A, %d %b %Y')}"

        df_view = df_processed[df_processed["date"] == selected_date]
        if df_view.empty:
            st.warning(f"No data available for {selected_date.strftime('%d %b %Y')}.")
        sub_header = f"Summary for {selected_date.strftime('%d %b %Y')}"

    elif "Weekly" in analysis_level:
        available_years = sorted(df_processed['year'].unique())
        col_w_sel, col_w_info = st.columns([1, 2])
        with col_w_sel:
            c_yr, c_wk = st.columns(2)
            with c_yr:
                selected_year = st.selectbox(
                    "Select Year", options=available_years,
                    index=len(available_years) - 1, key="rr_year_week_select"
                )
            weeks_in_year = df_processed[df_processed['year'] == selected_year]['week'].unique()
            sorted_weeks = sorted(weeks_in_year)
            with c_wk:
                selected_week = st.selectbox(
                    "Select Week", options=sorted_weeks,
                    index=len(sorted_weeks) - 1,
                    format_func=lambda w: f"Week {w}",
                    key="rr_week_select"
                )
        try:
            start_of_week = datetime.strptime(
                f'{selected_year}-W{int(selected_week):02d}-1', "%G-W%V-%u"
            )
        except Exception:
            start_of_week = (datetime(selected_year, 1, 1)
                             + timedelta(weeks=int(selected_week)))
        end_of_week = start_of_week + timedelta(days=6)

        with col_w_info:
            info_placeholder = st.empty()
            info_base_text = (
                f"**Viewing Week {selected_week}, {selected_year}**\n\n"
                f"({start_of_week.strftime('%d %b')} – {end_of_week.strftime('%d %b %Y')})"
            )

        df_view = df_processed[
            (df_processed["week"] == selected_week)
            & (df_processed["year"] == selected_year)
        ]
        sub_header = f"Summary for Week {selected_week} ({selected_year})"

    elif "Monthly" in analysis_level:
        df_processed['year_cal'] = df_processed['shot_time'].dt.year
        available_years = sorted(df_processed['year_cal'].unique())
        col_m_sel, col_m_info = st.columns([1, 2])
        with col_m_sel:
            c_yr, c_mo = st.columns(2)
            with c_yr:
                selected_year = st.selectbox(
                    "Select Year", options=available_years,
                    index=len(available_years) - 1, key="rr_year_select"
                )
            months_in_year = df_processed[
                df_processed['year_cal'] == selected_year
            ]['month'].unique()
            sorted_months = sorted(months_in_year)
            with c_mo:
                selected_month_period = st.selectbox(
                    "Select Month", options=sorted_months,
                    index=len(sorted_months) - 1,
                    format_func=lambda p: p.strftime('%B'),
                    key="rr_month_select"
                )
        with col_m_info:
            info_placeholder = st.empty()
            info_base_text = f"**Viewing Month:** {selected_month_period.strftime('%B %Y')}"

        df_view = df_processed[df_processed["month"] == selected_month_period]
        sub_header = f"Summary for {selected_month_period.strftime('%B %Y')}"

    elif "Custom Period" in analysis_level:
        min_date = df_processed['date'].min()
        max_date = df_processed['date'].max()
        col_c_sel, col_c_info = st.columns([1, 2])
        with col_c_sel:
            c1, c2 = st.columns(2)
            with c1:
                start_date = st.date_input("Start date", min_date,
                                           min_value=min_date, max_value=max_date,
                                           key="rr_custom_start")
            with c2:
                end_date = st.date_input("End date", max_date,
                                         min_value=start_date, max_value=max_date,
                                         key="rr_custom_end")
        with col_c_info:
            info_placeholder = st.empty()
            info_base_text = (
                f"**Viewing Period:** {start_date.strftime('%d %b %Y')} "
                f"to {end_date.strftime('%d %b %Y')}"
                if start_date and end_date else "**Viewing Period:** Select dates"
            )

        if start_date and end_date:
            mask = (df_processed['date'] >= start_date) & (df_processed['date'] <= end_date)
            df_view = df_processed[mask]
            sub_header = (f"Summary for {start_date.strftime('%d %b %Y')} "
                          f"to {end_date.strftime('%d %b %Y')}")

    # ------------------------------------------------------------------
    # Run labelling on the slice
    # ------------------------------------------------------------------
    if not df_view.empty:
        df_view = df_view.copy()
        if 'run_id' in df_view.columns:
            run_first_shot = (df_view.groupby('run_id')['shot_time']
                              .min().sort_values())
            run_label_map = {rid: f"Run {i+1:03d}"
                             for i, rid in enumerate(run_first_shot.index)}
            df_view['run_label'] = df_view['run_id'].map(run_label_map)

    # Min-shots filter
    run_count = 0
    if 'by Run' in analysis_level and not df_view.empty:
        run_shot_counts = df_view.groupby('run_label')['run_label'].transform('count')
        df_view = df_view[run_shot_counts >= min_shots_filter]
        run_count = df_view['run_label'].nunique() if not df_view.empty else 0
    elif not df_view.empty and 'run_label' in df_view.columns:
        run_count = df_view['run_label'].nunique()

    if info_placeholder:
        info_placeholder.info(
            f"{info_base_text}\n\n**Number of Production Runs:** {run_count}"
        )

    if df_view.empty:
        st.warning("No data for the selected period (or all runs were filtered out).")
        return

    # ------------------------------------------------------------------
    # KPI computation
    # ------------------------------------------------------------------
    run_summary_df_for_totals = rr_utils.calculate_run_summaries(
        df_view, tolerance, downtime_gap_tolerance, pre_processed=True,
        startup_stop_threshold_minutes=startup_thresh, startup_shot_count=startup_count
    )

    summary_metrics = {}
    if not run_summary_df_for_totals.empty:
        total_runtime_sec = run_summary_df_for_totals['total_runtime_sec'].sum()
        production_time_sec = run_summary_df_for_totals['production_time_sec'].sum()
        downtime_sec = run_summary_df_for_totals['downtime_sec'].sum()
        total_shots = run_summary_df_for_totals['total_shots'].sum()
        normal_shots = run_summary_df_for_totals['normal_shots'].sum()
        stop_events = run_summary_df_for_totals['stops'].sum()

        summary_metrics = {
            'total_runtime_sec': total_runtime_sec,
            'production_time_sec': production_time_sec,
            'downtime_sec': downtime_sec,
            'total_shots': total_shots,
            'normal_shots': normal_shots,
            'stop_events': stop_events,
            'normal_startup_shots': run_summary_df_for_totals.get('normal_startup_shots', pd.Series(dtype=int)).sum(),
            'slow_startup_shots': run_summary_df_for_totals.get('slow_startup_shots', pd.Series(dtype=int)).sum(),
            'failed_startup_shots': run_summary_df_for_totals.get('failed_startup_shots', pd.Series(dtype=int)).sum(),
            'mttr_min': (downtime_sec / 60 / stop_events) if stop_events > 0 else 0,
            'mtbf_min': ((production_time_sec / 60 / stop_events)
                         if stop_events > 0 else (production_time_sec / 60)),
            'stability_index': ((production_time_sec / total_runtime_sec * 100)
                                if total_runtime_sec > 0 else 100.0),
            'efficiency': (normal_shots / total_shots) if total_shots > 0 else 0,
        }
        sub_header = sub_header.replace("Summary for", "Summary for (Combined Runs)")

    if 'mode_ct' in df_view.columns:
        summary_metrics['min_mode_ct'] = df_view['mode_ct'].min()
        summary_metrics['max_mode_ct'] = df_view['mode_ct'].max()
    else:
        summary_metrics['min_mode_ct'] = 0
        summary_metrics['max_mode_ct'] = 0

    if 'lower_limit' in df_view.columns:
        summary_metrics['min_lower_limit'] = df_view['lower_limit'].min()
        summary_metrics['max_lower_limit'] = df_view['lower_limit'].max()
    else:
        summary_metrics['min_lower_limit'] = 0
        summary_metrics['max_lower_limit'] = 0

    if 'upper_limit' in df_view.columns:
        summary_metrics['min_upper_limit'] = df_view['upper_limit'].min()
        summary_metrics['max_upper_limit'] = df_view['upper_limit'].max()
    else:
        summary_metrics['min_upper_limit'] = 0
        summary_metrics['max_upper_limit'] = 0

    if 'approved_ct' in df_view.columns:
        valid_app = df_view['approved_ct'].dropna()
        summary_metrics['min_approved_ct'] = valid_app.min() if not valid_app.empty else np.nan
        summary_metrics['max_approved_ct'] = valid_app.max() if not valid_app.empty else np.nan
    else:
        summary_metrics['min_approved_ct'] = np.nan
        summary_metrics['max_approved_ct'] = np.nan

    results = rr_utils.build_display_results(df_view, run_interval_hours)

    # ------------------------------------------------------------------
    # Trend / run summary (for charts and tables)
    # ------------------------------------------------------------------
    trend_summary_df = None
    run_summary_df = None
    if "by Run" in analysis_level:
        trend_summary_df = rr_utils.calculate_run_summaries(
            df_view, tolerance, downtime_gap_tolerance, pre_processed=True,
            startup_stop_threshold_minutes=startup_thresh, startup_shot_count=startup_count
        )
        if trend_summary_df is not None and not trend_summary_df.empty:
            trend_summary_df.rename(columns={
                'run_label': 'RUN ID', 'stability_index': 'STABILITY %',
                'stops': 'STOPS', 'mttr_min': 'MTTR (min)',
                'mtbf_min': 'MTBF (min)', 'total_shots': 'Total Shots',
                'approved_ct': 'Approved CT'
            }, inplace=True)
        run_summary_df = trend_summary_df

    # ------------------------------------------------------------------
    # Header + export button
    # ------------------------------------------------------------------
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(sub_header)
    with col2:
        st.download_button(
            label="📥 Export Run-Based Report",
            data=rr_utils.prepare_and_generate_run_based_excel(
                df_view.copy(), tolerance, downtime_gap_tolerance,
                run_interval_hours, tool_id_selection, startup_thresh, startup_count
            ),
            file_name=(
                f"Run_Based_Report_"
                f"{tool_id_selection.replace(' / ', '_').replace(' ', '_')}_"
                f"{analysis_level.replace(' ', '_')}_"
                f"{datetime.now():%Y%m%d}.xlsx"
            ),
            mime="application/vnd.openxmlformats-offic