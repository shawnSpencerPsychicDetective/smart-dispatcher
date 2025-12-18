from mcp.server.fastmcp import FastMCP
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

# IMPORT THE REAL CALENDAR LOGIC
from calendar_service import CalendarService

# Initialize the MCP Server
mcp = FastMCP("SmartBuildingDispatcher")


# --- HELPER: EMAIL ---
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


# --- TOOL 2: THE EXECUTOR (FULL LOGIC) ---
@mcp.tool()
def execute_maintenance(serial_number: str) -> str:
    """
    Performs the full maintenance workflow:
    1. Checks warranty status in DB.
    2. IF ACTIVE: Emails manufacturer.
    3. IF EXPIRED: Checks real calendar availability, Books first slot, Emails maintenance.
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

    # 2. LOGIC CHECK
    today = datetime.now().date()
    expires = datetime.strptime(row["warranty_expires"], "%Y-%m-%d").date()
    is_active = expires >= today

    tenant_name = row["tenant_name"] or "Resident"
    asset_desc = f"{row['brand']} {row['asset_name']}"

    if is_active:
        # --- SCENARIO A: ACTIVE WARRANTY ---
        print(f"   -> Status: ACTIVE (Expires {row['warranty_expires']})")
        recipient = row["contact_email"] or "warranty@generic.com"
        subject = f"Warranty Claim: {serial_number}"
        body = f"""
        URGENT: Warranty Claim Request
        ------------------------------
        Tenant: {tenant_name}
        Unit: {row['unit_number']}
        Asset: {asset_desc}
        Serial: {serial_number}
        Issue: Reported by tenant via Voice Agent.
        Action Required: Please contact tenant immediately.
        """

        internal_send_email(recipient, subject, body)
        return f"I found your {asset_desc}. The warranty is active. I have notified the manufacturer and sent the confirmation email."

    else:
        # --- SCENARIO B: EXPIRED WARRANTY (FULL WORKFLOW) ---
        print(f"   -> Status: EXPIRED (Expired {row['warranty_expires']})")

        # Step 1: Check Calendar (Real Logic)
        cal_service = CalendarService()
        availability_str = cal_service.check_availability("tomorrow")
        print(f"   -> Availability: {availability_str}")

        # Parse first available slot
        # Assuming format "9:00, 10:00, 14:00" -> takes "9:00"
        if "No slots" in availability_str:
            return "I tried to book a handyman, but there are no slots available for tomorrow. Please contact the front desk."

        first_slot = availability_str.split(",")[0].strip()

        # Step 2: Book Slot (Real Logic)
        booking_res = cal_service.book_slot("tomorrow", first_slot, f"Fix {asset_desc}")
        print(f"   -> Booking: {booking_res}")

        # Step 3: Email Maintenance
        recipient = "maintenance@building.com"
        subject = f"Work Order: {serial_number}"
        body = f"""
        WORK ORDER: Internal Repair
        ---------------------------
        Status: Out of Warranty
        Tenant: {tenant_name} (Unit {row['unit_number']})
        Asset: {asset_desc} ({serial_number})

        APPOINTMENT CONFIRMED:
        Date: Tomorrow
        Time: {first_slot}
        task: Repair {row['asset_name']}
        """

        internal_send_email(recipient, subject, body)
        return f"Your {row['asset_name']} warranty is expired. I checked the schedule and booked the handyman for {first_slot} tomorrow. I have also emailed the work order to the maintenance team."


if __name__ == "__main__":
    mcp.run()