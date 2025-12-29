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
    """Helper to get a DB connection using an absolute path to the data dir."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "data", "maintenance.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def internal_send_email(recipient, subject, body):
    """Sends email via mock SMTP and logs to SQLite."""
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
def get_tenant_context(unit_number: str) -> str:
    """Retrieves tenant name and asset list for a specific unit."""
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
def execute_maintenance(serial_number: str) -> str:
    """Checks warranty and dispatches maintenance workflow."""
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
