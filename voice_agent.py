import asyncio
import logging
import sys
import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero
from livekit import rtc

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from email_service import EmailDispatcher
from calendar_service import CalendarService

load_dotenv()
logger = logging.getLogger("voice-agent")


# --- DATABASE HELPER ---
def get_tenant_from_db(user_identity):
    if not os.path.exists("maintenance.db"):
        return {"name": "Unknown", "unit_number": "Unknown"}
    try:
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", ("U205",))
        row = cursor.fetchone()
        conn.close()
        if row: return {"name": row["name"], "unit_number": row["unit_number"]}
    except:
        pass
    return {"name": "Valued Tenant", "unit_number": "Unknown"}


# --- THE TOOLS (GRANULAR BUT POWERFUL) ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(
        description="Look up asset details, warranty status, and vendor email. Handles fuzzy matching (e.g. 'washer' -> 'dishwasher').")
    async def lookup_asset_metadata(self, item_name: str):
        print(f"\n[TOOL] Looking up metadata for: {item_name}")

        # 1. FETCH RAW DATA
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT a.asset_name, a.brand, a.serial_number, a.warranty_expires,
                   v.contact_email as vendor_email
            FROM assets a
            LEFT JOIN vendors v ON a.brand = v.brand_affiliation
            WHERE a.unit_number = ?
        """
        cursor.execute(query, (self.tenant['unit_number'],))
        rows = cursor.fetchall()
        conn.close()

        # 2. FUZZY MATCHING LOGIC (Python Helper)
        matched_row = None
        item_lower = item_name.lower()
        # Common slang map to help the search
        slang = {"washer": "dishwasher", "dryer": "washing", "fridge": "refrigerator", "ac": "conditioner"}
        search_term = slang.get(item_lower, item_lower)

        for row in rows:
            if search_term in row["asset_name"].lower():
                matched_row = row
                break

        if not matched_row:
            return "Asset not found in unit."

        # 3. CALCULATE STATUS
        today = datetime.now().date()
        expires = datetime.strptime(matched_row["warranty_expires"], "%Y-%m-%d").date()
        status = "ACTIVE" if expires >= today else "EXPIRED"

        # Return structured data so the LLM can MAKE THE DECISION
        return json.dumps({
            "asset": matched_row["asset_name"],
            "brand": matched_row["brand"],
            "serial": matched_row["serial_number"],
            "status": status,
            "expiry_date": matched_row["warranty_expires"],
            "vendor_email": matched_row["vendor_email"] or "maintenance@building.com"
        })

    @llm.ai_callable(description="For ACTIVE warranties: Send email to manufacturer.")
    def process_warranty_claim(self, recipient_email: str, brand: str, asset: str, serial: str):
        print(f"\n[TOOL] Processing Manufacturer Claim...")
        email = EmailDispatcher()
        subject = f"Warranty Claim: {serial}"
        body = f"Tenant: {self.tenant['name']}\nUnit: {self.tenant['unit_number']}\nAsset: {brand} {asset}\nIssue: Tenant reported defect."

        result = email.send_email(subject, body, recipient_email)
        return result

    @llm.ai_callable(description="For EXPIRED warranties: Book internal handyman and notify maintenance.")
    def schedule_internal_repair(self, asset: str, serial: str):
        print(f"\n[TOOL] Scheduling Internal Repair...")

        # 1. Calendar Logic
        cal = CalendarService()
        avail = cal.check_availability("tomorrow")
        slot = avail.split(",")[0].strip() if "," in avail else "09:00"

        # 2. Book
        cal.book_slot("tomorrow", slot, f"Fix {asset}")

        # 3. Email
        email = EmailDispatcher()
        subject = f"Work Order: {serial}"
        body = f"Tenant: {self.tenant['name']}\nAsset: {asset}\nStatus: Out of Warranty\nAction: Booked for tomorrow at {slot}"

        result = email.send_email(subject, body, "maintenance@building.com")
        return f"Booked for {slot} tomorrow. {result}"


# --- ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    tenant = get_tenant_from_db(participant.identity)

    try:
        vad = silero.VAD.load()
    except:
        vad = silero.VAD()

    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)

    print(f"🔌 Connecting to MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected.")

            tools = DispatcherTools(tenant, session)

            agent = VoicePipelineAgent(
                vad=vad,
                stt=openai.STT(),
                llm=openai.LLM(model="gpt-4o"),
                tts=openai.TTS(),
                fnc_ctx=tools,
                chat_ctx=llm.ChatContext().append(
                    role="system",
                    text=f"""
                        You are the Smart Dispatcher. Tenant: {tenant['name']} (Unit {tenant['unit_number']}).

                        **PROTOCOL: ONE-SHOT EXECUTION**
                        Do not have a conversation. Resolve the issue immediately.

                        **STEP 1: IDENTIFY**
                        Call `lookup_asset_metadata` with the user's term (e.g. "washer").

                        **STEP 2: DECIDE (Internal Thought)**
                        Read the JSON result.
                        - Is "status" == "ACTIVE"? -> Call `process_warranty_claim`.
                        - Is "status" == "EXPIRED"? -> Call `schedule_internal_repair`.

                        **STEP 3: REPORT**
                        Speak ONLY after the tools have returned "Success".
                        "I found your [Brand] [Asset]. The warranty is [Active/Expired]. I have [notified the manufacturer / booked the handyman] and sent the confirmation email."
                    """
                )
            )
            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online.", allow_interruptions=True)
            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))