import asyncio
import logging
import sys
import os
import sqlite3
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
        print("⚠️ ERROR: maintenance.db not found! Did you upload it?")
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
    except Exception as e:
        print(f"⚠️ DB Read Error: {e}")
        pass
    return {"name": "Valued Tenant", "unit_number": "Unknown"}


# --- TOOL CONTEXT ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(description="Check warranty status of an appliance via MCP")
    async def check_warranty(self, appliance_name: str):
        logger.info(f"⚡ Bridging to MCP: Checking warranty for {appliance_name}")
        try:
            # 1. Get Assets
            assets_result = await self.mcp.call_tool("get_assets", arguments={})

            # 2. Check Warranty
            result = await self.mcp.call_tool("check_warranty_status", arguments={
                "asset_name": appliance_name,
                "unit_number": self.tenant['unit_number']
            })
            return result.content[0].text
        except Exception as e:
            return f"Error connecting to database via MCP: {str(e)}"

    @llm.ai_callable(description="Send dispatch email")
    def send_email(self, recipient: str, subject: str, body: str):
        email = EmailDispatcher()
        return email.send_email(subject, body, recipient)

    @llm.ai_callable(description="Check calendar availability")
    def check_calendar(self, date: str):
        cal = CalendarService()
        return f"Available slots: {cal.check_availability(date)}"

    @llm.ai_callable(description="Book a time slot")
    def book_slot(self, date: str, time: str, task: str):
        cal = CalendarService()
        return cal.book_slot(date, time, task)


# --- ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    # 1. Connect
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    tenant = get_tenant_from_db(participant.identity)

    # 2. Initialize VAD
    try:
        vad = silero.VAD.load()
    except:
        vad = silero.VAD()

    # 3. Start MCP Client & Agent
    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)

    print(f"🔌 Connecting to MCP Server for Unit {tenant['unit_number']}...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected. Starting Voice Pipeline.")

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
                        You are the Smart Building Dispatcher for Unit {tenant['unit_number']} ({tenant['name']}).
                        PROTOCOL:
                        1. You have direct access to the asset database via MCP.
                        2. When the user mentions an appliance, IMMEDIATELY call `check_warranty`.
                        3. Based on the result (Active/Expired), Email Manufacturer or Book Handyman.
                        4. Do not ask for details you can look up.
                    """
                )
            )

            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online. How can I help?", allow_interruptions=True)

            # --- ROBUST WAIT FOREVER ---
            # This keeps the script running until the room is closed by the user/server
            # It replaces the buggy 'while loop' that caused the crash.
            await asyncio.Event().wait()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))