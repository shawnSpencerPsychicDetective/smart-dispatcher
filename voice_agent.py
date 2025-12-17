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
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", (target_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"name": row["name"], "unit_number": row["unit_number"]}
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
            conn = sqlite3.connect("maintenance.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

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

            results = []
            for row in rows:
                results.append({
                    "asset": row["asset_name"],
                    "brand": row["brand"],
                    "serial": row["serial_number"],
                    "expires": row["warranty_expires"],
                    "vendor_email": row["vendor_email"] or "maintenance@building.com"
                })

            return json.dumps(results)

        except Exception as e:
            return f"Error retrieving assets: {str(e)}"

    @llm.ai_callable(description="Send dispatch email to Manufacturer or Handyman")
    def send_email(self, recipient: str, subject: str, body: str):
        email = EmailDispatcher()
        result = email.send_email(subject, body, recipient)
        return result

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

    # MCP Connection
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

                        **CORE BEHAVIOR: INTELLIGENT MATCHING**
                        1. When the user mentions an issue, call `get_unit_assets` immediately to see what they own.
                        2. **DO NOT play dumb.** If the user uses slang, a generic term, or a slightly wrong name (e.g., "Washer" for "Dishwasher", "Cooler" for "Fridge"), use your intelligence to pick the most logical match from their asset list. 
                        3. Only ask for clarification if there are two truly conflicting options (e.g., they say "Washer" and they own BOTH a Dishwasher and a Washing Machine). Otherwise, assume the match and proceed.

                        **EXECUTION WORKFLOW (Auto-Execute)**
                        Once the asset is identified, check the `expires` date against Today ({today_str}).

                        **IF ACTIVE (Future Date):**
                        1. Say: "Your [Brand] [Asset] is under warranty until [Date]. I am notifying the manufacturer."
                        2. Call `send_email`.
                           - Recipient: Use the `vendor_email` from the data.
                           - Subject: "Warranty Claim: [Serial]"
                           - Body: Write a professional email stating the Tenant Name, Unit, Asset, Serial, and report the issue.

                        **IF EXPIRED (Past Date):**
                        1. Say: "Your warranty expired on [Date]. I am booking the internal handyman."
                        2. Call `check_calendar` for tomorrow.
                        3. Pick the first available slot.
                        4. Call `book_slot`.
                        5. Call `send_email`.
                           - Recipient: 'maintenance@building.com'
                           - Subject: "Work Order: [Serial] - [Asset]"
                           - Body: Write a detailed work order including Tenant details, Asset details, Serial Number, and the booked appointment time.

                        **FINAL RULE:** Be efficient. Do not ask for permission to send emails or book slots. Just solve the problem.
                    """
                )
            )

            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online. How can I help?", allow_interruptions=True)

            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))