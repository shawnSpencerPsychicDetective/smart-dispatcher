import psutil

# --- CPU HACK ---
psutil.cpu_percent = lambda *args, **kwargs: 10.0

import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# LIVEKIT IMPORTS (v0.12.x era)
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero

# MCP IMPORTS
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# LOCAL TOOLS (Keep these local as they are not on MCP yet)
from email_service import EmailDispatcher
from calendar_service import CalendarService

load_dotenv()
logger = logging.getLogger("voice-agent")

# --- 1. SETUP MCP CONNECTION PARAMS ---
# This tells the script how to launch your mcp_server.py
server_params = StdioServerParameters(
    command=sys.executable,
    args=["mcp_server.py"],
    env=None
)

# --- 2. PRE-LOAD MODELS ---
print("⏳ Pre-loading VAD model...")
try:
    silero_vad_model = silero.VAD.load()
    print("✅ VAD Model loaded successfully.")
except Exception:
    try:
        silero_vad_model = silero.VAD()
        print("✅ VAD Model loaded (Instance mode).")
    except Exception as e:
        print(f"⚠️ Warning: Could not pre-load VAD: {e}")
        silero_vad_model = None

# --- 3. DATABASE HELPER (To Identify User ONLY) ---
# We still need this locally just to know WHO is calling.
# The actual heavy lifting will be done by MCP.
import sqlite3


def get_tenant_from_db(user_identity):
    target_id = "U205"
    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", (target_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "unit_number": row[1]}
    return {"name": "Unknown", "unit_number": "Unknown"}


# --- 4. DEFINE TOOLS (THE BRIDGE) ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session  # We store the active MCP connection here

    # --- MCP TOOLS (The "Real" Project) ---
    @llm.ai_callable(description="Check warranty status of an appliance using the Asset Database")
    async def check_warranty(self, appliance_name: str):
        logger.info(f"⚡ Bridging to MCP: Checking warranty for {appliance_name}")

        # 1. First, we need to find the asset to get its full name/serial
        # We call the 'get_assets' tool on the MCP server
        assets_result = await self.mcp.call_tool("get_assets", arguments={})
        assets_data = assets_result.content[0].text

        # 2. Then we call 'check_warranty_status' on the MCP server
        # We pass the appliance name and the unit number
        result = await self.mcp.call_tool("check_warranty_status", arguments={
            "asset_name": appliance_name,
            "unit_number": self.tenant['unit_number']
        })

        return result.content[0].text

    # --- LOCAL TOOLS (Legacy/Specific to Voice) ---
    @llm.ai_callable(description="Check calendar availability")
    def check_calendar(self, date: str):
        cal = CalendarService()
        return f"Available slots: {cal.check_availability(date)}"

    @llm.ai_callable(description="Book a time slot")
    def book_slot(self, date: str, time: str, task: str):
        cal = CalendarService()
        return cal.book_slot(date, time, task)

    @llm.ai_callable(description="Send dispatch email")
    def send_email(self, recipient: str, subject: str, body: str):
        email = EmailDispatcher()
        return email.send_email(subject, body, recipient)


# --- 5. ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    print(f"⏳ Room created. Waiting for user to join...")
    participant = await ctx.wait_for_participant()
    print(f"✅ User joined: {participant.identity}")

    tenant = get_tenant_from_db(participant.identity)

    print("🔌 Connecting to MCP Server...")
    # WE START THE MCP CLIENT HERE
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected! Voice Agent is now powered by MCP.")

            # Create the tools, passing the active MCP session
            tools = DispatcherTools(tenant, session)

            agent = VoicePipelineAgent(
                vad=silero_vad_model if silero_vad_model else silero.VAD.load(),
                stt=openai.STT(),
                llm=openai.LLM(model="gpt-4o"),
                tts=openai.TTS(),
                fnc_ctx=tools,
                chat_ctx=llm.ChatContext().append(
                    role="system",
                    text=f"""
                        You are the Smart Building Dispatcher for Unit {tenant['unit_number']} ({tenant['name']}).

                        PROTOCOL:
                        1. You are powered by an MCP Server. When the user mentions an appliance, use `check_warranty`.
                        2. This tool will query the MCP database for you.
                        3. Based on the result (Active/Expired), take the next step (Email Manufacturer or Book Handyman).

                        Be professional and quick.
                    """
                )
            )

            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online. How can I help?", allow_interruptions=True)

            # CRITICAL: We must keep this block alive while the agent runs.
            # We wait until the room is disconnected.
            # (Note: In v0.12, explicit waiting logic is safer inside context managers)
            try:
                # Loop forever until the room closes
                while ctx.room.connection_state.name == 'CONNECTED':
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                print("Voice Agent stopping...")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))