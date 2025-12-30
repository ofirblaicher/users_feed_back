import streamlit as st
import pandas as pd
import json
from pathlib import Path
import plotly.express as px

st.set_page_config(page_title="Alert Triage Analysis Dashboard", layout="wide")

st.title("🛡️ AI-Powered Alert Triage Analysis")
st.markdown("### Visualization of Axial Coding & Theme Classification")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AXIAL_CODING_FILE = PROJECT_ROOT / "data" / "axial_coding.json"
FEEDBACK_ALERTS_FILE = PROJECT_ROOT / "data" / "feedback_alerts.json"

def load_data():
    # Load original feedback data
    if not FEEDBACK_ALERTS_FILE.exists():
        st.error(f"Missing {FEEDBACK_ALERTS_FILE}. Run `fetch_traces.py` first.")
        return None, None
    
    with open(FEEDBACK_ALERTS_FILE, 'r') as f:
        feedback_data = json.load(f)
    
    # Load axial coding results (NDJSON)
    if not AXIAL_CODING_FILE.exists():
        st.warning(f"No results found in {AXIAL_CODING_FILE}. Run `classify.py` first.")
        return feedback_data, None
    
    results = []
    with open(AXIAL_CODING_FILE, 'r') as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    
    return feedback_data, results

feedback_data, results_data = load_data()

if feedback_data:
    # Sidebar stats
    st.sidebar.header("Data Summary")
    st.sidebar.metric("Total Alerts", len(feedback_data))
    
    if results_data:
        df_results = pd.DataFrame(results_data)
        st.sidebar.metric("Classified Alerts", len(df_results))
        
        # Main Dashboard Layout
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Theme Distribution")
            fig_themes = px.pie(df_results, names='theme', color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_themes, use_container_width=True)
            
        with col2:
            st.subheader("Confidence Levels")
            fig_conf = px.histogram(df_results, x='confidence', color='confidence', 
                                    color_discrete_map={'HIGH': 'green', 'MEDIUM': 'orange', 'LOW': 'red'})
            st.plotly_chart(fig_conf, use_container_width=True)
        
        # Detailed Table
        st.divider()
        st.subheader("Detailed Classification Results")
        
        # Filter by Theme
        selected_theme = st.multiselect("Filter by Theme", options=df_results['theme'].unique())
        filtered_df = df_results if not selected_theme else df_results[df_results['theme'].isin(selected_theme)]
        
        # Export Functionality
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Filtered Results to CSV",
            data=csv,
            file_name=f"axial_coding_export_{len(filtered_df)}_items.csv",
            mime="text/csv",
        )
        
        st.dataframe(filtered_df[['alert_id', 'theme', 'confidence', 'reasoning']], use_container_width=True)
        
        # Drill Down
        st.divider()
        st.subheader("🔍 Alert Drill-down")
        selected_id = st.selectbox("Select an Alert ID to view details", filtered_df['alert_id'].unique())
        
        if selected_id:
            # Find in results
            res_item = next((r for r in results_data if r['alert_id'] == selected_id), None)
            # Find in original feedback
            fb_item = next((f for f in feedback_data if f['alert_id'] == selected_id), None)
            
            det_col1, det_col2 = st.columns(2)
            
            with det_col1:
                st.info("**AI Classification**")
                st.write(f"**Theme:** {res_item['theme']}")
                st.write(f"**Confidence:** {res_item['confidence']}")
                st.write(f"**Reasoning:** {res_item['reasoning']}")
                if res_item.get('missing_context'):
                    st.warning(f"**Missing Context:** {res_item['missing_context']}")
            
            with det_col2:
                st.success("**Human Input & Context**")
                metadata = fb_item.get('metadata', {})
                st.write(f"**Human Comment:** {metadata.get('human_comment', 'N/A')}")
                st.write(f"**Verdict:** {metadata.get('verdict', 'N/A')}")
                st.write(f"**Tenant:** {metadata.get('account_short_name', 'N/A')}")
                
            # Show Trace observations if any
            if fb_item.get('traces'):
                with st.expander("View Raw Trace Observations"):
                    st.json(fb_item['traces'][0].get('observations', []))

else:
    st.info("👋 Welcome! Please run the classification pipeline to see results here.")
    st.code("uv run scripts/fetch_traces.py\nuv run scripts/axial_coding/classify.py")

