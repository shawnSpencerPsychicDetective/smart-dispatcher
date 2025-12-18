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


# --- DIRECT SMTP HELPER ---
def internal_send_email(recipient, subject, body):
    print(f"⚡ [INTERNAL] Connecting to SMTP...")
    msg = MIMEMultipart()
    msg['From'] = "dispatch@smartbuilding.com"
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Port 1025 for Mock Server
        with smtplib.SMTP('localhost', 1025) as server:
            server.send_message(msg)
        print(f"✅ [INTERNAL] Email SENT to {recipient}")
        return "SUCCESS"
    except Exception as e:
        print(f"❌ [INTERNAL] Failed: {e}")
        return f"ERROR: SMTP Connection Failed. {e}"


# --- TOOLS ---
class DispatcherTools(llm.FunctionContext):
    def __init__(self, tenant_info, mcp_session):
        super().__init__()
        self.tenant = tenant_info
        self.mcp = mcp_session

    @llm.ai_callable(description="Lookup asset metadata. Returns JSON.")
    async def lookup_asset_metadata(self, item_name: str):
        print(f"\n🔎 [TOOL] Searching for '{item_name}'...")
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

        item_lower = item_name.lower()
        slang = {"washer": "dishwasher", "dryer": "washing", "fridge": "refrigerator", "ac": "conditioner"}
        search_term = slang.get(item_lower, item_lower)

        matched_row = None
        for row in rows:
            if search_term in row["asset_name"].lower():
                matched_row = row
                break

        if not matched_row: return "Asset not found."

        today = datetime.now().date()
        expires = datetime.strptime(matched_row["warranty_expires"], "%Y-%m-%d").date()
        status = "ACTIVE" if expires >= today else "EXPIRED"

        return json.dumps({
            "asset": matched_row["asset_name"],
            "brand": matched_row["brand"],
            "serial": matched_row["serial_number"],
            "status": status,
            "expiry_date": matched_row["warranty_expires"],
            "vendor_email": matched_row["vendor_email"] or "maintenance@building.com"
        })

    @llm.ai_callable(description="Send email to manufacturer. Returns SUCCESS or ERROR.")
    def process_warranty_claim(self, recipient_email: str, brand: str, asset: str, serial: str):
        print(f"\n📧 [TOOL] Sending Warranty Claim...")
        body = f"Tenant: {self.tenant['name']}\nAsset: {brand} {asset} ({serial})\nIssue: User Reported."
        return internal_send_email(recipient_email, f"Warranty Claim: {serial}", body)

    @llm.ai_callable(description="Book handyman AND email maintenance. Returns SUCCESS or ERROR.")
    def schedule_internal_repair(self, asset: str, serial: str):
        print(f"\n🛠️ [TOOL] Booking Handyman...")
        cal = CalendarService()
        avail = cal.check_availability("tomorrow")
        slot = avail.split(",")[0].strip() if "," in avail else "09:00"
        cal.book_slot("tomorrow", slot, f"Fix {asset}")

        body = f"Tenant: {self.tenant['name']}\nAsset: {asset} ({serial})\nStatus: Out of Warranty\nAction: Booked for {slot} tomorrow."
        email_res = internal_send_email("maintenance@building.com", f"Work Order: {serial}", body)

        return f"Booked for {slot}. Email Status: {email_res}"


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
                        You are an Autonomous Dispatch System. Tenant: {tenant['name']}.

                        **FATAL ERROR CONDITION:**
                        If you speak phrases like "I will now..." or "Let me check...", you have FAILED.
                        You must be SILENT while tools are running.

                        **EXECUTION LOOP (ATOMIC):**
                        1. User Request -> Call `lookup_asset_metadata` IMMEDIATELY.
                        2. Read JSON. 
                           - IF "ACTIVE" -> Call `process_warranty_claim`.
                           - IF "EXPIRED" -> Call `schedule_internal_repair`.
                        3. WAIT for the tool to return "SUCCESS".
                        4. ONLY THEN, speak: "Done. I have [action taken]."

                        **EXAMPLE:**
                        User: "Fix washer."
                        Agent (Internal): calls lookup... calls schedule... receives "SUCCESS"
                        Agent (Voice): "I found your expired Dishwasher. I booked the handyman for 9 AM and sent the email."
                    """
                )
            )
            agent.start(ctx.room, participant=participant)
            await agent.say(f"Hello {tenant['name']}, I am online.", allow_interruptions=True)
            while ctx.room.connection_state == rtc.ConnectionState.CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))