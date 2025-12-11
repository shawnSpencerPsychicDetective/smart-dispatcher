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

    # 2. Insert Mock Data 
    cursor.execute("INSERT INTO tenants (name, unit_number, phone_number) VALUES ('Alice', '402', '+15550199')")
    cursor.execute("INSERT INTO tenants (name, unit_number, phone_number) VALUES ('Bob', '101', '+15550200')")

    # Scenario A: Active Warranty (Samsung AC)
    cursor.execute("""
    INSERT INTO assets (unit_number, asset_name, brand, serial_number, warranty_expires) 
    VALUES ('402', 'Air Conditioner', 'Samsung', 'SN-998877', '2026-12-31')
    """)

    # Scenario B: Expired Warranty (Heater)
    cursor.execute("""
    INSERT INTO assets (unit_number, asset_name, brand, serial_number, warranty_expires) 
    VALUES ('101', 'Water Heater', 'GenericCorp', 'SN-112233', '2022-01-01')
    """)

    conn.commit()
    conn.close()
    print("✅ Database 'maintenance.db' created and seeded successfully.")

if __name__ == "__main__":
    create_database()