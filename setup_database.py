import sqlite3
import os


def create_database():
    # Ensure we overwrite any broken/empty file
    if os.path.exists("maintenance.db"):
        os.remove("maintenance.db")

    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()

    # 1. Create Tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY,
        name TEXT,
        unit_number TEXT,
        phone_number TEXT
    )
    """)

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

    # Email Logs Table (Required for the new email feature)
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

    # 2. Insert Mock Data (5 Tenants)
    tenants_data = [
        ('Alice', '402', '+15550199'),
        ('Bob', '101', '+15550200'),
        ('Charlie', '205', '+15550201'),
        ('Diana', '303', '+15550202'),
        ('Evan', '501', '+15550203')
    ]
    cursor.executemany("INSERT INTO tenants (name, unit_number, phone_number) VALUES (?, ?, ?)", tenants_data)

    # 3. Insert Mock Data (5 Assets with mixed warranty status)
    # Note: Dates are in YYYY-MM-DD format
    assets_data = [
        # Active Warranty
        ('402', 'Air Conditioner', 'Samsung', 'SN-AC-402', '2026-12-31'),
        # Expired Warranty
        ('101', 'Water Heater', 'GenericCorp', 'SN-WH-101', '2022-01-01'),
        # Active Warranty
        ('205', 'Refrigerator', 'LG', 'SN-REF-205', '2027-05-20'),
        # Expired Warranty
        ('303', 'Washing Machine', 'Whirlpool', 'SN-WM-303', '2023-11-15'),
        # Active Warranty
        ('501', 'Dishwasher', 'Bosch', 'SN-DW-501', '2025-10-10')
    ]
    cursor.executemany("""
    INSERT INTO assets (unit_number, asset_name, brand, serial_number, warranty_expires) 
    VALUES (?, ?, ?, ?, ?)
    """, assets_data)

    conn.commit()
    conn.close()
    print("✅ Database 'maintenance.db' created.")
    print(f"   - Added {len(tenants_data)} Tenants")
    print(f"   - Added {len(assets_data)} Assets")
    print("   - Created 'email_logs' table")


if __name__ == "__main__":
    create_database()