from mcp.server.fastmcp import FastMCP
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

# IMPORT THE REAL CALENDAR SERVICE
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
    try:
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT a.asset_name, a.brand, a.serial_number, a.warranty_expires FROM assets a WHERE a.unit_number = ?"
        cursor.execute(query, (unit_number,))
        rows = cursor.fetchall()
        conn.close()
        
        asset_list = []
        for r in rows:
            asset_list.append(f"- {r['brand']} {r['asset_name']} (Serial: {r['serial_number']}, Expires: {r['warranty_expires']})")
        
        return "\n".join(asset_list) if asset_list else "No assets found."
    except Exception as e:
        return f"Error loading context: {e}"

# --- TOOL 2: THE EXECUTOR (RESTORED) ---
@mcp.tool()
def execute_maintenance(serial_number: str) -> str:
    print(f"\n[MCP SERVER] Processing Serial: {serial_number}")
    
    # 1. DATABASE LOOKUP
    conn = sqlite3.connect("maintenance.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
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

    # 2. WARRANTY CHECK
    today = datetime.now().date()
    try:
        expires = datetime.strptime(row["warranty_expires"], "%Y-%m-%d").date()
    except ValueError:
        expires = today # Fallback
        
    is_active = expires >= today
    tenant_name = row["tenant_name"] or "Resident"
    asset_desc = f"{row['brand']} {row['asset_name']}"

    # 3. EXECUTION BRANCHES
    if is_active:
        # --- ACTIVE WARRANTY ---
        print(f"   -> Status: ACTIVE")
        recipient = row["contact_email"] or "warranty@generic.com"
        subject = f"Warranty Claim: {serial_number}"
        body = f"Tenant: {tenant_name}\nUnit: {row['unit_number']}\nAsset: {asset_desc}\nIssue: Reported by user."
        
        internal_send_email(recipient, subject, body)
        return f"I found your {asset_desc}. The warranty is active. I have notified the manufacturer and sent the confirmation email."

    else:
        # --- EXPIRED WARRANTY ---
        print(f"   -> Status: EXPIRED")
        
        try:
            # 1. Check Availability
            cal_service = CalendarService()
            available_slots = cal_service.check_availability("tomorrow")
            print(f"   -> Raw Slots: {available_slots}")

            # 2. Parse List Logic
            slot = "09:00" # Default
            if isinstance(available_slots, list) and len(available_slots) > 0:
                slot = available_slots[0] # Take the first free slot
            elif isinstance(available_slots, str):
                slot = available_slots # Fallback if string

            # 3. Book
            cal_service.book_slot("tomorrow", slot, f"Fix {asset_desc}")
            print(f"   -> Booked Slot: {slot}")

        except Exception as e:
            print(f"⚠️ [MCP SERVER] Calendar Error: {e}. Using emergency fallback.")
            slot = "09:00 (Emergency)"

        # 4. Email Maintenance
        recipient = "maintenance@building.com"
        subject = f"Work Order: {serial_number}"
        body = f"Tenant: {tenant_name}\nAsset: {asset_desc}\nStatus: Expired\nAction: Booked for {slot}."
        
        internal_send_email(recipient, subject, body)
        return f"Your {row['asset_name']} warranty is expired. I booked the handyman for {slot} tomorrow and emailed the maintenance team."

if __name__ == "__main__":
    mcp.run()