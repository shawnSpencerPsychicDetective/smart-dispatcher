from mcp.server.fastmcp import FastMCP
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

# Initialize the MCP Server
mcp = FastMCP("SmartBuildingDispatcher")


# --- HELPER: EMAIL (Now lives on the Server) ---
def internal_send_email(recipient, subject, body):
    print(f"⚡ [MCP SERVER] Sending email to {recipient}...")
    msg = MIMEMultipart()
    msg['From'] = "dispatch@smartbuilding.com"
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Port 1025 for Mock Server
        with smtplib.SMTP('localhost', 1025) as server:
            server.send_message(msg)
        print(f"✅ [MCP SERVER] Email SENT.")
        return True
    except Exception as e:
        print(f"❌ [MCP SERVER] Email Failed: {e}")
        return False


# --- TOOL 1: CONTEXT LOADER ---
@mcp.tool()
def get_tenant_context(unit_number: str) -> str:
    """
    Fetches all assets for a unit to load into the AI's System Prompt.
    """
    try:
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT a.asset_name, a.brand, a.serial_number, a.warranty_expires
            FROM assets a
            WHERE a.unit_number = ?
        """
        cursor.execute(query, (unit_number,))
        rows = cursor.fetchall()
        conn.close()

        asset_list = []
        for r in rows:
            asset_list.append(
                f"- {r['brand']} {r['asset_name']} (Serial: {r['serial_number']}, Expires: {r['warranty_expires']})")

        if not asset_list:
            return "No assets found."
        return "\n".join(asset_list)
    except Exception as e:
        return f"Error loading context: {e}"


# --- TOOL 2: THE EXECUTOR ---
@mcp.tool()
def execute_maintenance(serial_number: str) -> str:
    """
    Performs the full maintenance workflow: Checks warranty -> Sends Email.
    Returns the confirmation message for the AI to speak.
    """
    print(f"\n[MCP SERVER] Executing Maintenance for Serial: {serial_number}")

    # 1. FETCH DETAILS
    conn = sqlite3.connect("maintenance.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # We join with Tenants table to get the Name for the email body
    cursor.execute("""
        SELECT a.asset_name, a.brand, a.warranty_expires, a.unit_number,
               v.contact_email, t.name as tenant_name
        FROM assets a
        LEFT JOIN vendors v ON a.brand = v.brand_affiliation
        LEFT JOIN tenants t ON a.unit_number = t.unit_number
        WHERE a.serial_number = ?
    """, (serial_number,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "System Error: Asset not found in database."

    # 2. LOGIC
    today = datetime.now().date()
    expires = datetime.strptime(row["warranty_expires"], "%Y-%m-%d").date()
    is_active = expires >= today

    tenant_name = row["tenant_name"] or "Resident"

    if is_active:
        # SCENARIO A: ACTIVE
        recipient = row["contact_email"] or "warranty@generic.com"
        subject = f"Warranty Claim: {serial_number}"
        body = f"Tenant: {tenant_name}\nUnit: {row['unit_number']}\nAsset: {row['brand']} {row['asset_name']}\nIssue: Tenant reported defect."

        internal_send_email(recipient, subject, body)
        return f"I found your {row['brand']} {row['asset_name']}. The warranty is active. I have notified the manufacturer and sent the confirmation email."

    else:
        # SCENARIO B: EXPIRED
        # (Simplified: We assume next day 9am for the demo to save lines)
        slot = "09:00 AM Tomorrow"

        recipient = "maintenance@building.com"
        subject = f"Work Order: {serial_number}"
        body = f"Tenant: {tenant_name}\nAsset: {row['asset_name']}\nStatus: Expired\nAction: Booked for {slot}."

        internal_send_email(recipient, subject, body)
        return f"Your {row['asset_name']} warranty is expired. I booked the handyman for {slot} and emailed the maintenance team."


if __name__ == "__main__":
    mcp.run()