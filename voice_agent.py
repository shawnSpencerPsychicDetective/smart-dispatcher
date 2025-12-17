import asyncio
import logging
import sys
import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv

# LIVEKIT IMPORTS
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero
from livekit import rtc

# MCP IMPORTS
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# LOCAL TOOLS
from email_service import EmailDispatcher
from calendar_service import CalendarService

load_dotenv()
logger = logging.getLogger("voice-agent")


# --- DATABASE HELPER ---
def get_tenant_from_db(user_identity):
    if not os.path.exists("maintenance.db"):
        return {"name": "Unknown", "unit_number": "Unknown"}

    target_id = "U205"
    try:
        conn = sqlite3.connect("maintenance.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", (target_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"name": row[0], "unit_number": row[1]}
    except:
        pass
    return {"name": "Valued Tenant", "unit_number": "Unknown"}


# --- TOOL CONTEXT ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(description="Get ALL assets for this unit, including WARRANTY and VENDOR EMAIL.")
    async def get_unit_assets(self):
        logger.info(f"⚡ Fetching assets + vendors for Unit {self.tenant['unit_number']}")
        try:
            # We bypass MCP 'get_assets' generic call to do a specific JOIN here for speed & accuracy.
            # (In a strict MCP architecture, you'd add a new MCP tool 'get_asset_details', but this works for the demo)
            conn = sqlite3.connect("maintenance.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # THE CRITICAL JOIN QUERY
            query = """
                SELECT 
                    a.asset_name, 
                    a.brand, 
                    a.serial_number, 
                    a.warranty_expires,
                    v.contact_email as vendor_email
                FROM assets a
                LEFT JOIN vendors v ON a.brand = v.brand_affiliation
                WHERE a.unit_number = ?
            """
            cursor.execute(query, (self.tenant['unit_number'],))
            rows = cursor.fetchall()
            conn.close()

            # Convert to list of dicts
            results = []
            for row in rows:
                results.append({
                    "asset": row["asset_name"],
                    "brand": row["brand"],
                    "serial": row["serial_number"],
                    "expires": row["warranty_expires"],
                    "vendor_email": row["vendor_email"] or "maintenance@building.com"  # Fallback if brand mismatch
                })

            return json.dumps(results)

        except Exception as e:
            return f"Error retrieving assets: {str(e)}"

    @llm.ai_callable(description="Send dispatch email to Manufacturer or Handyman")
    def send_email(self, recipient: str, subject: str, body: str):
        email = EmailDispatcher()
        return email.send_email(subject, body, recipient)

    @llm.ai_callable(description="Check calendar availability for the Internal Handyman")
    def check_calendar(self, date: str):
        cal = CalendarService()
        return f"Available slots: {cal.check_availability(date)}"

    @llm.ai_callable(description="Book a time slot with the Internal Handyman")
    def book_slot(self, date: str, time: str, task: str):
        cal = CalendarService()
        return cal.book_slot(date, time, task)


# --- ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    tenant = get_tenant_from_db(participant.identity)

    # VAD Load
    try:
        vad = silero.VAD.load()
    except:
        vad = silero.VAD()

    # MCP Connection (Still connected for future proofing)
    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)

    print(f"🔌 Connecting to MCP Server for Unit {tenant['unit_number']}...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected. Starting Voice Pipeline.")

            tools = DispatcherTools(tenant, session)

            today_str = datetime.now().strftime("%Y-%m-%d")

            agent = VoicePipelineAgent(
                vad=vad,
                stt=openai.STT(),
                llm=openai.LLM(model="gpt-4o"),
                tts=openai.TTS(),
                fnc_ctx=tools,
                chat_ctx=llm.ChatContext().append(
                    role="system",
                    text=f"""
                        You are the Smart Building Dispatcher for Unit {tenant['unit_number']} ({tenant['name']}).
                        Today's Date: {today_str}.

                        **CRITICAL PROTOCOL:**
                        1. When the user mentions a problem, call `get_unit_assets` immediately.
                        2. Look at the list. Fuzzy match the user's word (e.g., "fridge") to the `asset` name (e.g., "Refrigerator").

                        **DECISION LOGIC (Follow Exactly):**
                        Compare `expires` date with Today ({today_str}).

                        **IF ACTIVE (Future Date):**
                        - Say: "Your [Brand] [Asset] is under warranty until [Date]."
                        - Action: Call `send_email`.
                        - **RECIPIENT:** Use the exact `vendor_email` from the tool data. DO NOT GUESS.
                        - Subject: "Warranty Claim: [Serial]"
                        - Body: "Tenant: {tenant['name']}. Issue: User Report."

                        **IF EXPIRED (Past Date):**
                        - Say: "Your warranty expired on [Date]. I will book the internal handyman."
                        - Step 1: Call `check_calendar` for tomorrow.
                        - Step 2: Pick first available slot.
                        - Step 3: Call `book_slot`.
                        - Step 4: Call `send_email` to 'maintenance@building.com'.
                        - Subject: "Work Order: [Serial]"
                        - Body: "Expired asset. Booked for [Time]."

                        **Be efficient. Do not explain the process, just confirm the action.**
                    """
                )
            )

            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online. How can I help?", allow_interruptions=True)

            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))