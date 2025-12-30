import streamlit as st
import pandas as pd
import json
from pathlib import Path
import plotly.express as px

st.set_page_config(page_title="Alert Triage Analysis Dashboard", layout="wide")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AXIAL_CODING_FILE = PROJECT_ROOT / "data" / "axial_coding.json"
FEEDBACK_ALERTS_FILE = PROJECT_ROOT / "data" / "feedback_alerts.json"
GLOBAL_TRENDS_FILE = PROJECT_ROOT / "data" / "global_trends.json"

def load_data():
    # Load original feedback data
    if not FEEDBACK_ALERTS_FILE.exists():
        st.error(f"Missing {FEEDBACK_ALERTS_FILE}. Run `fetch_traces.py` first.")
        return None, None, None
    
    with open(FEEDBACK_ALERTS_FILE, 'r') as f:
        feedback_data = json.load(f)
    
    # Load axial coding results (NDJSON)
    results = []
    if AXIAL_CODING_FILE.exists():
        with open(AXIAL_CODING_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))
    
    # Load global trends if they exist
    global_trends = None
    if GLOBAL_TRENDS_FILE.exists():
        with open(GLOBAL_TRENDS_FILE, 'r') as f:
            global_trends = json.load(f)
    
    return feedback_data, results, global_trends

feedback_data, results_data, global_trends_data = load_data()

st.title("🛡️ AI-Powered Alert Triage Analysis")
st.markdown("### Visualization of Axial Coding & Theme Classification")

# Global Trends Section
if global_trends_data:
    with st.expander("🌐 **Global Security Trends & Strategic Insights**", expanded=True):
        st.info(f"**Executive Summary:** {global_trends_data['summary']}")
        
        # Display trends in a grid
        num_trends = len(global_trends_data['trends'])
        if num_trends > 0:
            cols = st.columns(min(num_trends, 3))
            for i, trend in enumerate(global_trends_data['trends']):
                with cols[i % 3]:
                    severity_color = {"HIGH": "red", "MEDIUM": "orange", "LOW": "blue"}.get(trend['severity'].upper(), "gray")
                    st.markdown(f"#### :{severity_color}[{trend['title']}]")
                    st.write(trend['description'])
                    if trend.get('affected_tenants'):
                        st.caption(f"**Affected:** {', '.join(trend['affected_tenants'])}")
                    st.success(f"**💡 Rec:** {trend['recommendation']}")
else:
    st.info("💡 Run individual classification with `--global-trends` to see strategic trend analysis here.")

if feedback_data:
    # Sidebar stats
    st.sidebar.header("Data Summary")
    st.sidebar.metric("Total Alerts", len(feedback_data))
    
    if results_data:
        df_results = pd.DataFrame(results_data)
        
        # Merge with tenant info from feedback_data
        tenant_map = {item['alert_id']: item.get('metadata', {}).get('account_short_name', 'Unknown') 
                     for item in feedback_data}
        df_results['tenant'] = df_results['alert_id'].map(tenant_map)
        
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
        
        # Filters
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            selected_theme = st.multiselect("Filter by Theme", options=sorted(df_results['theme'].unique()))
        with filter_col2:
            selected_tenant = st.multiselect("Filter by Tenant", options=sorted(df_results['tenant'].unique()))
        
        # Apply Filters
        filtered_df = df_results
        if selected_theme:
            filtered_df = filtered_df[filtered_df['theme'].isin(selected_theme)]
        if selected_tenant:
            filtered_df = filtered_df[filtered_df['tenant'].isin(selected_tenant)]
        
        # Export Functionality
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Filtered Results to CSV",
            data=csv,
            file_name=f"axial_coding_export_{len(filtered_df)}_items.csv",
            mime="text/csv",
        )
        
        st.dataframe(filtered_df[['alert_id', 'tenant', 'theme', 'confidence', 'reasoning']], use_container_width=True)
        
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
                if res_item.get('trend_insight'):
                    st.success(f"**📈 Trend Insight:** {res_item['trend_insight']}")
            
            with det_col2:
                st.success("**Human Input & Context**")
                metadata = fb_item.get('metadata', {})
                
                # Extract AI Verdict (Initial) from traces
                ai_verdict = "N/A"
                if fb_item.get('traces'):
                    for obs in fb_item['traces'][0].get('observations', []):
                        if obs.get('type') == 'GENERATION' or (isinstance(obs.get('output'), str) and '"final_decision"' in obs.get('output')):
                            try:
                                output = obs.get('output', "")
                                if isinstance(output, str) and output.strip().startswith('{'):
                                    import json as json_lib
                                    gen_data = json_lib.loads(output)
                                    if "properties" in gen_data: gen_data = gen_data["properties"]
                                    ai_verdict = gen_data.get("final_decision", "N/A")
                                    break
                            except:
                                continue

                st.write(f"**Human Comment:** {metadata.get('human_comment', 'N/A')}")
                st.write(f"**Initial (AI) Verdict:** :blue[{ai_verdict}]")
                st.write(f"**Final (Human) Verdict:** :green[{metadata.get('verdict', 'N/A')}]")
                st.write(f"**Tenant:** {metadata.get('account_short_name', 'N/A')}")
                
            # Show Trace observations if any
            if fb_item.get('traces'):
                with st.expander("View Raw Trace Observations"):
                    st.json(fb_item['traces'][0].get('observations', []))

else:
    st.info("👋 Welcome! Please run the classification pipeline to see results here.")
    st.code("uv run scripts/fetch_traces.py\nuv run scripts/axial_coding/classify.py")

