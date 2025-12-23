import asyncio
import os
import sys
import json
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

# Import Local Services
from email_service import EmailDispatcher
from calendar_service import CalendarService

load_dotenv()
openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# MCP Server Parameters (for SQLite)
server_params = StdioServerParameters(
    command=sys.executable,
    args=["mcp_server.py"],
    env=None
)

# --- LOCAL HELPER FUNCTIONS ---
def get_tenant_by_chat_id(slack_id):
    """Retrieves tenant name and unit number from the database using their Slack User ID."""
    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", (slack_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"name": result[0], "unit_number": result[1]}
    return None

async def run_agent():
    """Initializes the agent, sets up tools (Local & MCP), and runs the main chat loop for handling tenant requests."""
    print("🤖 Smart Dispatcher (Aligned) Initializing...")

    email_tool = EmailDispatcher()
    calendar_tool = CalendarService()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Define Local Tools (Calendar & Email ONLY)
            # Note: check_warranty_status is REMOVED from here because it is now an MCP tool
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "check_calendar_availability",
                        "description": "Get free slots for the Internal Handyman.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "description": "YYYY-MM-DD"}
                            },
                            "required": ["date"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "book_appointment",
                        "description": "Book a time slot for the Internal Handyman.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string"},
                                "time": {"type": "string"},
                                "task": {"type": "string"}
                            },
                            "required": ["date", "time", "task"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "dispatch_email",
                        "description": "Send work order. MUST include Serial Number.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "recipient_email": {"type": "string"},
                                "subject": {"type": "string"},
                                "body": {"type": "string"}
                            },
                            "required": ["recipient_email", "subject", "body"]
                        }
                    }
                }
            ]

            # 2. Add MCP tools (This automatically pulls 'check_warranty_status' from mcp_server.py)
            mcp_tools = await session.list_tools()
            for tool in mcp_tools.tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })

            print("\n✅ System Ready. Simulating Chat Interface.")

            while True:
                chat_id_input = input("\n[Incoming Message] Enter Slack User ID (e.g., U402, U101) or 'quit': ")
                if chat_id_input.lower() in ["quit", "exit"]: break

                user_message = input("[Incoming Message] Tenant Complaint: ")

                tenant = get_tenant_by_chat_id(chat_id_input)
                if not tenant:
                    print("❌ Unknown Slack ID. Ignoring.")
                    continue

                print(f"🔍 Identified Tenant: {tenant['name']} in Unit {tenant['unit_number']}")

                messages = [
                    {"role": "system", "content": f"""
                    You are the Smart Dispatcher. 
                    Current Date: {datetime.now().strftime('%Y-%m-%d')}.
                    Tenant Unit: {tenant['unit_number']}.

                    PROTOCOL (STRICT ORDER):
                    1. SEARCH: Use 'get_assets' to find the appliance.
                    2. CHECK: Use 'check_warranty_status' (Requires asset_name and unit_number).
                    3. DECIDE:
                        - IF ACTIVE: The tool returns the Manufacturer Email. Dispatch Email immediately.
                        - IF EXPIRED: The tool returns the Internal Handyman Email.
                            a. Call 'check_calendar_availability'.
                            b. Call 'book_appointment'.
                            c. Call 'dispatch_email' with the time slot details.

                    RESTRICTIONS:
                    - Use the EXACT email and Serial Number returned by 'check_warranty_status'.
                    """},
                    {"role": "user", "content": user_message}
                ]

                # --- AGENT LOOP ---
                response = await openai.chat.completions.create(model="gpt-4o", messages=messages, tools=openai_tools)
                response_msg = response.choices[0].message
                tool_calls = response_msg.tool_calls

                while tool_calls:
                    messages.append(response_msg)
                    print(f"⚡ Agent Thinking... ({len(tool_calls)} steps)")

                    for tool_call in tool_calls:
                        fname = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        print(f"🔧 Tool: {fname}")

                        result_content = ""

                        # --- LOCAL TOOLS (Calendar/Email) ---
                        if fname == "check_calendar_availability":
                            result_content = str(calendar_tool.check_availability(args["date"]))

                        elif fname == "book_appointment":
                            result_content = calendar_tool.book_slot(args["date"], args["time"], args["task"])

                        elif fname == "dispatch_email":
                            result_content = email_tool.send_email(
                                args["subject"], args["body"], args["recipient_email"]
                            )

                        # --- MCP TOOLS (Database & Warranty Logic) ---
                        # This now handles 'check_warranty_status' automatically!
                        else:
                            mcp_result = await session.call_tool(fname, arguments=args)
                            result_content = mcp_result.content[0].text

                        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result_content)})

                    # Run Again
                    response = await openai.chat.completions.create(model="gpt-4o", messages=messages, tools=openai_tools)
                    response_msg = response.choices[0].message
                    tool_calls = response_msg.tool_calls

                print(f"💬 Agent: {response_msg.content}")

if __name__ == "__main__":
    asyncio.run(run_agent())