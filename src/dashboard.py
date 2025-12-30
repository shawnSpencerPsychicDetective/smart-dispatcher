import streamlit as st
import sqlite3
import pandas as pd
import os

# Set page configuration
st.set_page_config(
    page_title="Smart Dispatcher Command Center", page_icon="🏢", layout="wide"
)


# --- DATABASE CONNECTION ---
def get_connection():
    """Establishes a connection to the local SQLite database.

    Calculates the absolute path to the 'maintenance.db' file located in the 
    'data' directory relative to the project root.

    Returns:
        sqlite3.Connection: A connection object to the SQLite database.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "maintenance.db")
    return sqlite3.connect(db_path)


def load_data(query: str) -> pd.DataFrame:
    """Executes a SQL query and returns the results as a DataFrame.

    This helper function manages the lifecycle of a database connection: 
    opening the connection, executing the provided SQL query via Pandas, 
    and ensuring the connection is closed afterward.

    Args:
        query (str): The SQL SELECT query to be executed.

    Returns:
        pd.DataFrame: A Pandas DataFrame containing the results of the query.
    """
    conn = get_connection()
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


# --- TITLE & METRICS ---
st.title("Smart Dispatcher Command Center")
st.markdown(
    "Real-time monitoring of tenant complaints, asset warranties, and "
    "automated dispatch actions."
)

# Top Level Metrics
col1, col2, col3 = st.columns(3)

# Metric 1: Total Tenants
with col1:
    count_tenants = load_data("SELECT COUNT(*) as count FROM tenants")
    st.metric(label="Total Tenants", value=count_tenants.iloc[0]["count"])

# Metric 2: Active Assets
with col2:
    # Count assets where warranty expires in the future
    query_active = (
        "SELECT COUNT(*) as count FROM assets WHERE warranty_expires > "
        f"'{pd.Timestamp.now().strftime('%Y-%m-%d')}'"
    )
    count_active = load_data(query_active)
    st.metric(label="Active Warranties", value=count_active.iloc[0]["count"])

# Metric 3: Total Dispatches (Emails Sent)
with col3:
    count_emails = load_data(
        "SELECT COUNT(*) as count FROM email_logs WHERE status='SENT'"
    )
    st.metric(label="Total Dispatches", value=count_emails.iloc[0]["count"])

st.divider()

# --- MAIN DASHBOARD LAYOUT ---
tab1, tab2, tab3 = st.tabs(["Dispatch Logs", "Asset Database", "Tenant Directory"])

# TAB 1: EMAIL LOGS (The Audit Trail)
with tab1:
    st.subheader("Live Dispatch Communications")
    st.caption("This log tracks every email drafted and sent by the AI Agent.")

    # Auto-refresh button
    if st.button("Refresh Logs"):
        st.rerun()

    df_emails = load_data(
        "SELECT id, recipient_email, subject, status, sent_at FROM email_logs "
        "ORDER BY id DESC"
    )

    # Color code the status
    def highlight_status(val: str) -> str:
        """Returns CSS styling for color-coding the dispatch status.

        Applies a green color to 'SENT' statuses and red to any other values 
        (like failures or pending) to provide immediate visual feedback 
        in the data table.

        Args:
            val (str): The status string from the database column.

        Returns:
            str: A CSS string for styling the specific table cell.
        """
        color = "green" if val == "SENT" else "red"
        return f"color: {color}; font-weight: bold"

    st.dataframe(
        df_emails.style.map(highlight_status, subset=["status"]),
        use_container_width=True,
        hide_index=True,
    )

    # Detailed View
    st.write("### Inspect Email Content")
    if not df_emails.empty:
        selected_id = st.selectbox("Select Email ID to view body:", df_emails["id"])

        if selected_id:
            email_body = load_data(
                f"SELECT body FROM email_logs WHERE id={selected_id}"
            )
            if not email_body.empty:
                st.text_area(
                    "Email Content:",
                    value=email_body.iloc[0]["body"],
                    height=200,
                    disabled=True,
                )

# TAB 2: ASSETS (Warranty Status)
with tab2:
    st.subheader("Building Asset Inventory")

    df_assets = load_data("SELECT * FROM assets")

    # Add a calculated column for "Status"
    df_assets["Status"] = df_assets["warranty_expires"].apply(
        lambda x: (
            "Active" if x > pd.Timestamp.now().strftime("%Y-%m-%d") else "Expired"
        )
    )

    st.dataframe(
        df_assets,
        use_container_width=True,
        column_order=(
            "unit_number",
            "asset_name",
            "brand",
            "Status",
            "warranty_expires",
            "serial_number",
        ),
    )

# TAB 3: TENANTS (Directory)
with tab3:
    st.subheader("Tenant Directory")
    df_tenants = load_data("SELECT * FROM tenants")
    st.dataframe(df_tenants, use_container_width=True)

# --- SIDEBAR: SYSTEM HEALTH ---
st.sidebar.header("System Status")
st.sidebar.success("Database: Connected")
st.sidebar.info("Agent Status: Idle (Run 'python -m src.voice_agent' to activate)")

# Quick Link to run instructions
with st.sidebar.expander("How to run the Agent?"):
    st.code("python -m src.voice_agent", language="bash")
