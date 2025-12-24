import sqlite3
import os


def create_database():
    """Initializes the SQLite database by creating tables (tenants, assets,
    vendors, email_logs) and populating them with seed data for testing.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    db_path = os.path.join(data_dir, "maintenance.db")

    # Ensure data directory exists
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Ensure we overwrite any broken/empty file
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Tenants Table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY,
        name TEXT,
        slack_user_id TEXT,  -- Links Chat ID to Tenant
        unit_number TEXT,
        phone_number TEXT
    )
    """
    )

    # 2. Assets Table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY,
        unit_number TEXT,
        asset_name TEXT,
        brand TEXT,
        serial_number TEXT,
        warranty_expires DATE
    )
    """
    )

    # 3. Vendors Table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS vendors (
        id INTEGER PRIMARY KEY,
        brand_affiliation TEXT,
        contact_email TEXT,
        is_internal_staff BOOLEAN
    )
    """
    )

    # 4. Email Logs
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS email_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_email TEXT,
        subject TEXT,
        body TEXT,
        status TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    )

    # --- SEED DATA ---

    # Tenants
    tenants_data = [
        ("Alice", "U402", "402", "+15550199"),
        ("Bob", "U101", "101", "+15550200"),
        ("Charlie", "U205", "205", "+15550201"),
        ("Diana", "U303", "303", "+15550202"),
    ]
    cursor.executemany(
        "INSERT INTO tenants (name, slack_user_id, unit_number, phone_number) "
        "VALUES (?, ?, ?, ?)",
        tenants_data,
    )

    # Assets
    assets_data = [
        ("402", "Air Conditioner", "Samsung", "SN-AC-402", "2026-12-31"),
        ("101", "Water Heater", "GenericCorp", "SN-WH-101", "2022-01-01"),
        ("205", "Refrigerator", "LG", "SN-REF-205", "2027-05-20"),
        (
            "205",
            "Dishwasher",
            "Bosch",
            "SN-DW-205",
            "2023-11-15",
        ),  # Charlie Asset 2 (Expired)
        ("303", "Washing Machine", "Whirlpool", "SN-WM-303", "2025-08-10"),
    ]
    cursor.executemany(
        "INSERT INTO assets (unit_number, asset_name, brand, serial_number, "
        "warranty_expires) VALUES (?, ?, ?, ?, ?)",
        assets_data,
    )

    # Vendors
    vendors_data = [
        ("Samsung", "warranty@samsung.com", False),
        ("GenericCorp", "support@generic.com", False),
        ("Internal Handyman", "maintenance@building.com", True),
        ("LG", "warranty@lg.com", False),
        ("Bosch", "service@bosch-home.com", False),
        ("Whirlpool", "help@whirlpool.com", False),
    ]
    cursor.executemany(
        "INSERT INTO vendors (brand_affiliation, contact_email, "
        "is_internal_staff) VALUES (?, ?, ?)",
        vendors_data,
    )

    conn.commit()
    conn.close()
    print(f"Database created successfully at: {db_path}")


if __name__ == "__main__":
    create_database()
