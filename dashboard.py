import streamlit as st
import sqlite3
import pandas as pd
import time

# Set page configuration
st.set_page_config(
    page_title="Smart Dispatcher Command Center",
    page_icon="🏢",
    layout="wide"
)


# --- DATABASE CONNECTION ---
def get_connection():
    """Establishes and returns a connection to the local SQLite database."""
    return sqlite3.connect("maintenance.db")


def load_data(query):
    """Executes a SQL query against the database and returns the result as a Pandas DataFrame."""
    conn = get_connection()
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


# --- TITLE & METRICS ---
st.title("🏢 Smart Dispatcher Command Center")
st.markdown("Real-time monitoring of tenant complaints, asset warranties, and automated dispatch actions.")

# Top Level Metrics
col1, col2, col3 = st.columns(3)

# Metric 1: Total Tenants
with col1:
    count_tenants = load_data("SELECT COUNT(*) as count FROM tenants")
    st.metric(label="Total Tenants", value=count_tenants.iloc[0]['count'])

# Metric 2: Active Assets
with col2:
    # Count assets where warranty expires in the future
    query_active = f"SELECT COUNT(*) as count FROM assets WHERE warranty_expires > '{pd.Timestamp.now().strftime('%Y-%m-%d')}'"
    count_active = load_data(query_active)
    st.metric(label="Active Warranties", value=count_active.iloc[0]['count'])

# Metric 3: Total Dispatches (Emails Sent)
with col3:
    count_emails = load_data("SELECT COUNT(*) as count FROM email_logs WHERE status='SENT'")
    st.metric(label="Total Dispatches", value=count_emails.iloc[0]['count'])

st.divider()

# --- MAIN DASHBOARD LAYOUT ---
tab1, tab2, tab3 = st.tabs(["📧 Dispatch Logs", "🛠️ Asset Database", "👥 Tenant Directory"])

# TAB 1: EMAIL LOGS (The Audit Trail)
with tab1:
    st.subheader("Live Dispatch Communications")
    st.caption("This log tracks every email drafted and sent by the AI Agent.")

    # Auto-refresh button
    if st.button('🔄 Refresh Logs'):
        st.rerun()

    df_emails = load_data("SELECT id, recipient_email, subject, status, sent_at FROM email_logs ORDER BY id DESC")


    # Color code the status
    def highlight_status(val):
        """Returns CSS styling to color-code the status: Green for SENT, Red for others."""
        color = 'green' if val == 'SENT' else 'red'
        return f'color: {color}; font-weight: bold'


    st.dataframe(
        df_emails.style.map(highlight_status, subset=['status']),
        use_container_width=True,
        hide_index=True
    )

    # Detailed View
    st.write("### 🔍 Inspect Email Content")
    if not df_emails.empty:
        selected_id = st.selectbox("Select Email ID to view body:", df_emails['id'])

        if selected_id:
            email_body = load_data(f"SELECT body FROM email_logs WHERE id={selected_id}")
            if not email_body.empty:
                st.text_area("Email Content:", value=email_body.iloc[0]['body'], height=200, disabled=True)

# TAB 2: ASSETS (Warranty Status)
with tab2:
    st.subheader("Building Asset Inventory")

    df_assets = load_data("SELECT * FROM assets")

    # Add a calculated column for "Status"
    df_assets['Status'] = df_assets['warranty_expires'].apply(
        lambda x: "✅ Active" if x > pd.Timestamp.now().strftime('%Y-%m-%d') else "⚠️ Expired"
    )

    st.dataframe(
        df_assets,
        use_container_width=True,
        column_order=("unit_number", "asset_name", "brand", "Status", "warranty_expires", "serial_number")
    )

# TAB 3: TENANTS (Directory)
with tab3:
    st.subheader("Tenant Directory")
    df_tenants = load_data("SELECT * FROM tenants")
    st.dataframe(df_tenants, use_container_width=True)

# --- SIDEBAR: SYSTEM HEALTH ---
st.sidebar.header("System Status")
st.sidebar.success("Database: Connected")
st.sidebar.info("Agent Status: Idle (Run 'python agent.py' to activate)")

# Quick Link to run instructions
with st.sidebar.expander("How to run the Agent?"):
    st.code("python agent.py", language="bash")