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


# --- TOOL CONTEXT ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(description="Get ALL assets for this unit")
    async def get_unit_assets(self):
        print(f"\n[TOOL CALLED] get_unit_assets for Unit {self.tenant['unit_number']}")
        try:
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
            results = [{
                "asset": r["asset_name"], "brand": r["brand"], "serial": r["serial_number"],
                "expires": r["warranty_expires"], "vendor_email": r["vendor_email"] or "maintenance@building.com"
            } for r in rows]
            return json.dumps(results)
        except Exception as e:
            return f"Error: {str(e)}"

    @llm.ai_callable(description="Send dispatch email. RETURNS 'Success' or 'Error'.")
    def send_email(self, recipient: str, subject: str, body: str):
        print(f"\n[TOOL CALLED] send_email to {recipient}")  # <--- DEBUG PRINT
        email = EmailDispatcher()
        # Ensure we connect to localhost (which maps to 0.0.0.0 in codespaces)
        result = email.send_email(subject, body, recipient)
        print(f"[TOOL RESULT] {result}")
        return result

    @llm.ai_callable(description="Check calendar availability")
    def check_calendar(self, date: str):
        print(f"\n[TOOL CALLED] check_calendar for {date}")
        cal = CalendarService()
        return f"Available slots: {cal.check_availability(date)}"

    @llm.ai_callable(description="Book a time slot")
    def book_slot(self, date: str, time: str, task: str):
        print(f"\n[TOOL CALLED] book_slot for {time}")
        cal = CalendarService()
        return cal.book_slot(date, time, task)


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
                        You are the Smart Dispatcher for {tenant['name']} (Unit {tenant['unit_number']}).
                        Today: {today_str}.

                        **RULES OF ENGAGEMENT:**
                        1. You CANNOT send emails or book slots yourself. You MUST call the tools.
                        2. If you say "I have emailed," but you didn't call the `send_email` tool, you are failing.
                        3. Execute the full chain of tools BEFORE speaking the final confirmation.

                        **WORKFLOW:**
                        1. User reports issue -> Call `get_unit_assets`.
                        2. Match User Term (e.g. "Washer") to DB Asset (e.g. "Dishwasher").
                        3. Check Warranty Date vs Today.

                        **IF ACTIVE:**
                        -> Call `send_email` (Recipient: vendor_email).
                        -> Wait for tool result.
                        -> Say: "I found your [Asset]. Warranty is active. I have notified the manufacturer."

                        **IF EXPIRED:**
                        -> Call `check_calendar`.
                        -> Call `book_slot`.
                        -> Call `send_email` (Recipient: maintenance@building.com).
                        -> Wait for tool result.
                        -> Say: "Warranty expired. I booked the handyman for [Time] and sent the work order."
                    """
                )
            )
            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online.", allow_interruptions=True)
            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))