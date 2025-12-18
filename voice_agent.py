import asyncio
import logging
import sys
import os
import sqlite3
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero
from livekit import rtc

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
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


def fetch_all_assets_for_prompt(unit_number):
    """
    PRE-LOADS assets to inject into the System Prompt.
    """
    try:
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT a.asset_name, a.brand, a.serial_number, a.warranty_expires
            FROM assets a
            WHERE a.unit_number = ?
        """
        cursor.execute(query, (unit_number,))
        rows = cursor.fetchall()
        conn.close()

        # Format as a clear string for the LLM
        asset_list = []
        for r in rows:
            asset_list.append(
                f"- {r['brand']} {r['asset_name']} (Serial: {r['serial_number']}, Expires: {r['warranty_expires']})")
        return "\n".join(asset_list)
    except:
        return "No assets found."


# --- DIRECT SMTP HELPER ---
def internal_send_email(recipient, subject, body):
    print(f"⚡ [INTERNAL] Sending email to {recipient}...")
    msg = MIMEMultipart()
    msg['From'] = "dispatch@smartbuilding.com"
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('localhost', 1025) as server:
            server.send_message(msg)
        print(f"✅ [INTERNAL] Email SENT.")
        return "SUCCESS"
    except Exception as e:
        print(f"❌ [INTERNAL] Failed: {e}")
        return f"ERROR: {e}"


# --- EXECUTION TOOL ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(description="Execute maintenance for a specific asset using its SERIAL NUMBER.")
    async def execute_maintenance(self, serial_number: str):
        """
        The LLM provides the Serial Number (found in its context).
        We just execute the logic.
        """
        print(f"\n[EXECUTION TOOL] Processing Serial: {serial_number}")

        # 1. FETCH DETAILS
        conn = sqlite3.connect("maintenance.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.asset_name, a.brand, a.warranty_expires, v.contact_email
            FROM assets a
            LEFT JOIN vendors v ON a.brand = v.brand_affiliation
            WHERE a.serial_number = ?
        """, (serial_number,))
        row = cursor.fetchone()
        conn.close()

        if not row: return "Error: Serial number not found."

        # 2. LOGIC
        today = datetime.now().date()
        expires = datetime.strptime(row["warranty_expires"], "%Y-%m-%d").date()
        is_active = expires >= today

        if is_active:
            recipient = row["contact_email"]
            internal_send_email(recipient, f"Warranty Claim: {serial_number}",
                                f"Tenant reported issue with {row['brand']} {row['asset_name']}.")
            return f"I found your {row['brand']} {row['asset_name']}. The warranty is active. I have notified the manufacturer."
        else:
            cal = CalendarService()
            avail = cal.check_availability("tomorrow")
            slot = avail.split(",")[0].strip() if "," in avail else "09:00"
            cal.book_slot("tomorrow", slot, f"Fix {row['asset_name']}")
            internal_send_email("maintenance@building.com", f"Work Order: {serial_number}",
                                f"Expired Asset. Booked for {slot}.")
            return f"Your {row['asset_name']} warranty is expired. I booked the handyman for {slot} tomorrow and emailed maintenance."


# --- ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    tenant = get_tenant_from_db(participant.identity)

    # PRE-LOAD ASSETS FOR CONTEXT
    asset_context_string = fetch_all_assets_for_prompt(tenant['unit_number'])
    print(f"📋 Loaded Assets for Context:\n{asset_context_string}")

    try:
        vad = silero.VAD.load()
    except:
        vad = silero.VAD()

    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            agent = VoicePipelineAgent(
                vad=vad,
                stt=openai.STT(),
                llm=openai.LLM(model="gpt-4o"),
                tts=openai.TTS(),
                fnc_ctx=DispatcherTools(tenant, session),
                chat_ctx=llm.ChatContext().append(
                    role="system",
                    text=f"""
                        You are the Smart Dispatcher for {tenant['name']}.

                        **USER'S ASSETS (KNOWN FACTS):**
                        {asset_context_string}

                        **PROTOCOL:**
                        1. User speaks -> if user doesnt speak exact name of asset, match to whatever the user most likely means 
                        from one of the assets above (e.g. "washer -> Bosch Dishwasher").
                        2. **DO NOT SPEAK YET.**
                        3. Call `execute_maintenance` using the asset's SERIAL NUMBER from the list above.
                        4. The tool will return a confirmation sentence. Read that sentence to the user.
                    """
                )
            )
            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online.", allow_interruptions=True)
            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))