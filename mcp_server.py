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
    """Check if a specific asset is under warranty. Returns specific vendor instructions."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find the asset
    cursor.execute("""
        SELECT brand, warranty_expires FROM assets 
        WHERE unit_number = ? AND asset_name LIKE ?
    """, (unit_number, f"%{asset_name}%"))
    asset = cursor.fetchone()
    
    if not asset:
        return "Asset not found."

    brand, expires_str = asset
    expiration_date = datetime.strptime(expires_str, "%Y-%m-%d")
    is_active = expiration_date > datetime.now()

    if is_active:
        return f"WARRANTY ACTIVE. The {brand} {asset_name} is under warranty until {expires_str}. DO NOT CALL HANDYMAN. Dispatch to {brand} Support."
    else:
        return f"WARRANTY EXPIRED. The {brand} {asset_name} expired on {expires_str}. Authorized to dispatch Internal Handyman."

if __name__ == "__main__":
    mcp.run()