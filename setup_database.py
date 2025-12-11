import sqlite3
import os


def create_database():
    if os.path.exists("maintenance.db"):
        os.remove("maintenance.db")

    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()

    # 1. Tenants Table (Updated with 'slack_user_id' per Section 3.4.2)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY,
        name TEXT,
        slack_user_id TEXT,  -- NEW: Links Chat ID to Tenant
        unit_number TEXT,
        phone_number TEXT
    )
    """)

    # 2. Assets Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY,
        unit_number TEXT,
        asset_name TEXT,
        brand TEXT,
        serial_number TEXT,
        warranty_expires DATE
    )
    """)

    # 3. NEW: Vendors Table (Per Section 3.4.2)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendors (
        id INTEGER PRIMARY KEY,
        brand_affiliation TEXT,
        contact_email TEXT,
        is_internal_staff BOOLEAN
    )
    """)

    # 4. Email Logs (For audit)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS email_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_email TEXT,
        subject TEXT,
        body TEXT,
        status TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --- SEED DATA ---

    # Tenants (Mapping U402 -> Alice)
    cursor.execute(
        "INSERT INTO tenants (name, slack_user_id, unit_number, phone_number) VALUES ('Alice', 'U402', '402', '+15550199')")
    cursor.execute(
        "INSERT INTO tenants (name, slack_user_id, unit_number, phone_number) VALUES ('Bob', 'U101', '101', '+15550200')")

    # Assets
    cursor.execute(
        "INSERT INTO assets (unit_number, asset_name, brand, serial_number, warranty_expires) VALUES ('402', 'Air Conditioner', 'Samsung', 'SN-AC-402', '2026-12-31')")
    cursor.execute(
        "INSERT INTO assets (unit_number, asset_name, brand, serial_number, warranty_expires) VALUES ('101', 'Water Heater', 'GenericCorp', 'SN-WH-101', '2022-01-01')")

    # Vendors (Strict contact info - No Hallucinations)
    vendors = [
        ('Samsung', 'warranty@samsung.com', False),  # Manufacturer
        ('GenericCorp', 'support@generic.com', False),  # Manufacturer
        ('Internal Handyman', 'maintenance@building.com', True)  # Internal Staff
    ]
    cursor.executemany("INSERT INTO vendors (brand_affiliation, contact_email, is_internal_staff) VALUES (?, ?, ?)",
                       vendors)

    conn.commit()
    conn.close()
    print("✅ Database aligned with Requirements.pdf (Tables: tenants, assets, vendors, email_logs).")


if __name__ == "__main__":
    create_database()