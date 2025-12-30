import sys
import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from src.services.calendar_service import CalendarService  # noqa: E402

mcp = FastMCP("SmartBuildingDispatcher")


def get_db_connection():
    """Establishes a connection to the SQLite database with row access enabled.

    Locates the database file in the 'data' directory relative to the project root.
    Sets the row_factory to sqlite3.Row to allow accessing columns by name.

    Returns:
        sqlite3.Connection: A configured connection object to the maintenance database.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "maintenance.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def internal_send_email(recipient: str, subject: str, body: str):
    """Sends an email via mock SMTP and logs the transaction to the database.

    Constructs a MIME multipart message and delivers it to a local SMTP server 
    on port 1025. Upon successful delivery, it creates a record in the 
    'email_logs' table for auditing in the dashboard.

    Args:
        recipient (str): The email address of the receiver.
        subject (str): The subject line of the email.
        body (str): The plain-text body of the email.

    Returns:
        bool: True if both the email was sent and the log was created, False otherwise.
    """
    print(f"[MCP SERVER] Sending email to {recipient}...")

    msg = MIMEMultipart()
    msg["From"] = "dispatch@smartbuilding.com"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("localhost", 1025) as server:
            server.send_message(msg)
        print("[MCP SERVER] Email SENT.")

        # Log to Database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO email_logs (recipient_email, subject, body, status) 
            VALUES (?, ?, ?, ?)
            """,
            (recipient, subject, body, "SENT"),
        )
        conn.commit()
        conn.close()
        print("[MCP SERVER] Logged to Database.")
        return True
    except Exception as e:
        print(f"[MCP SERVER] Email Failed: {e}")
        return False


@mcp.tool()
@mcp.tool()
def get_tenant_context(unit_number: str):
    """Retrieves tenant information and a list of unit assets for the AI context.

    Queries the database for the tenant's name and all assets associated with the 
    provided unit number, including brand, serial number, and warranty expiration.

    Args:
        unit_number (str): The residential unit number (e.g., "205").

    Returns:
        str: A formatted string containing the tenant name and a list of assets. 
             Returns an error message string if the query fails.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get Tenant Name
        cursor.execute("SELECT name FROM tenants WHERE unit_number = ?", (unit_number,))
        tenant = cursor.fetchone()
        tenant_name = tenant["name"] if tenant else "Unknown Tenant"

        # Get Assets
        query = (
            "SELECT a.asset_name, a.brand, a.serial_number, a.warranty_expires"
            " FROM assets a WHERE a.unit_number = ?"
        )
        cursor.execute(query, (unit_number,))
        rows = cursor.fetchall()
        conn.close()

        asset_list = [f"Tenant Name: {tenant_name}"]
        for r in rows:
            asset_list.append(
                f"- {r['brand']} {r['asset_name']} "
                f"(Serial: {r['serial_number']}, "
                f"Expires: {r['warranty_expires']})"
            )

        return "\n".join(asset_list) if len(asset_list) > 1 else "No assets found."
    except Exception as e:
        return f"Error loading context: {e}"


@mcp.tool()
@mcp.tool()
def execute_maintenance(serial_number: str):
    """Orchestrates the maintenance workflow based on warranty status.

    Performs a database lookup for an asset by serial number, determines if 
    it is under warranty, and executes the appropriate dispatch branch:
    - Active Warranty: Contacts the manufacturer's support email.
    - Expired Warranty: Books a slot via CalendarService and contacts internal staff.

    Args:
        serial_number (str): The unique serial number of the asset requiring repair.

    Returns:
        str: A confirmation message describing the action taken (email sent, 
             booking time, etc.) to be read back to the user.
    """
    print(f"\n[MCP SERVER] Processing Serial: {serial_number}")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.asset_name, a.brand, a.warranty_expires, a.unit_number, 
               v.contact_email, t.name as tenant_name
        FROM assets a
        LEFT JOIN vendors v ON a.brand = v.brand_affiliation
        LEFT JOIN tenants t ON a.unit_number = t.unit_number
        WHERE a.serial_number = ?
    """,
        (serial_number,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "System Error: Asset not found in database."

    today = datetime.now().date()
    try:
        expires = datetime.strptime(row["warranty_expires"], "%Y-%m-%d").date()
    except ValueError:
        expires = today

    is_active = expires >= today
    tenant_name = row["tenant_name"] or "Resident"
    asset_desc = f"{row['brand']} {row['asset_name']}"

    if is_active:
        print("   -> Status: ACTIVE")
        recipient = row["contact_email"] or "warranty@generic.com"
        subject = f"Warranty Claim: {serial_number}"
        body = (
            f"Tenant: {tenant_name}\nUnit: {row['unit_number']}\n"
            f"Asset: {asset_desc}\nIssue: Reported by user."
        )
        internal_send_email(recipient, subject, body)
        return (
            f"I found your {asset_desc}. The warranty is active. I have "
            "notified the manufacturer and sent the confirmation email."
        )
    else:
        print("   -> Status: EXPIRED")
        try:
            cal_service = CalendarService()
            available_slots = cal_service.check_availability("tomorrow")
            slot = available_slots[0] if available_slots else "09:00"
            cal_service.book_slot("tomorrow", slot, f"Fix {asset_desc}")
            print(f"   -> Booked Slot: {slot}")
        except Exception as e:
            print(f"[MCP SERVER] Calendar Error: {e}")
            slot = "09:00 (Emergency)"

        recipient = "maintenance@building.com"
        subject = f"Work Order: {serial_number}"
        body = (
            f"Tenant: {tenant_name}\nAsset: {asset_desc}\n"
            f"Status: Expired\nAction: Booked for {slot}."
        )
        internal_send_email(recipient, subject, body)
        return (
            f"Your {row['asset_name']} warranty is expired. I booked the "
            f"handyman for {slot} tomorrow and emailed the maintenance team."
        )


if __name__ == "__main__":
    mcp.run()
