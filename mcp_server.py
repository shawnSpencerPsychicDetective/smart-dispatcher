from mcp.server.fastmcp import FastMCP
import sqlite3
from datetime import datetime

# Initialize the MCP Server
mcp = FastMCP("Smart Dispatcher Asset Server")

DB_PATH = "maintenance.db"


@mcp.tool()
def get_tenant_unit(tenant_name: str) -> str:
    """Look up a tenant's unit number by their name."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT unit_number FROM tenants WHERE name = ?", (tenant_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "Tenant not found"


@mcp.tool()
def get_unit_assets(unit_number: str) -> str:
    """List all assets (appliances) inside a specific unit."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT asset_name, brand, warranty_expires FROM assets WHERE unit_number = ?", (unit_number,))
    results = cursor.fetchall()
    conn.close()
    return str(results)


@mcp.tool()
def check_warranty_status(asset_name: str, unit_number: str) -> str:
    """
    Check if a specific asset is under warranty.
    RETURNS: Status, Serial Number, and the CORRECT Vendor Email to use.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Get Asset Details (Including Serial Number)
    cursor.execute("""
        SELECT brand, warranty_expires, serial_number FROM assets 
        WHERE unit_number = ? AND asset_name LIKE ?
    """, (unit_number, f"%{asset_name}%"))
    asset = cursor.fetchone()

    if not asset:
        conn.close()
        return "Asset not found."

    brand, expires_str, serial_number = asset
    expiration_date = datetime.strptime(expires_str, "%Y-%m-%d")
    is_active = expiration_date > datetime.now()

    # 2. Get Vendor Contact Logic (Strict Database Lookup)
    target_email = ""
    if is_active:
        # Fetch Manufacturer Email
        cursor.execute("SELECT contact_email FROM vendors WHERE brand_affiliation = ? AND is_internal_staff = 0",
                       (brand,))
    else:
        # Fetch Internal Handyman Email
        cursor.execute("SELECT contact_email FROM vendors WHERE is_internal_staff = 1")

    vendor_result = cursor.fetchone()
    target_email = vendor_result[0] if vendor_result else "Error: Vendor Email Not Found in DB"

    conn.close()

    # 3. Return a detailed instruction block to the Agent
    if is_active:
        return f"""
        STATUS: WARRANTY ACTIVE
        ASSET: {brand} {asset_name}
        SERIAL_NUMBER: {serial_number}
        EXPIRES: {expires_str}
        ACTION: Dispatch to Manufacturer.
        MANDATORY VENDOR EMAIL: {target_email}
        """
    else:
        return f"""
        STATUS: WARRANTY EXPIRED
        ASSET: {brand} {asset_name}
        SERIAL_NUMBER: {serial_number}
        EXPIRES: {expires_str}
        ACTION: Dispatch Internal Handyman.
        MANDATORY INTERNAL EMAIL: {target_email}
        """


if __name__ == "__main__":
    mcp.run()