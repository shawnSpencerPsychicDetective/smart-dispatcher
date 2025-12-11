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


# --- LOCAL HELPER FUNCTIONS (To replace direct SQL in Agent) ---
def get_tenant_by_chat_id(slack_id):
    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, unit_number FROM tenants WHERE slack_user_id=?", (slack_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"name": result[0], "unit_number": result[1]}
    return None


def get_vendor_contact(brand_name, is_expired):
    conn = sqlite3.connect("maintenance.db")
    cursor = conn.cursor()

    if is_expired:
        # If expired, we MUST use Internal Staff (Requirement 3.2.2)
        cursor.execute("SELECT contact_email, brand_affiliation FROM vendors WHERE is_internal_staff=1")
    else:
        # If active, try to find the Manufacturer
        cursor.execute("SELECT contact_email, brand_affiliation FROM vendors WHERE brand_affiliation=?", (brand_name,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {"email": result[0], "name": result[1]}
    # Fallback to internal if manufacturer not found
    return {"email": "maintenance@building.com", "name": "Internal Handyman"}


async def run_agent():
    print("🤖 Smart Dispatcher (Aligned) Initializing...")

    email_tool = EmailDispatcher()
    calendar_tool = CalendarService()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Define Tools for OpenAI
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "check_warranty_status",
                        "description": "Check if an asset's warranty is active based on the expiration date.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expiration_date": {"type": "string", "description": "YYYY-MM-DD"}
                            },
                            "required": ["expiration_date"]
                        }
                    }
                },
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

            # Add existing MCP tools (SQLite)
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
                # 1. Simulate the "Chat MCP" input (Req 3.2.1)
                chat_id_input = input("\n[Incoming Message] Enter Slack User ID (e.g., U402, U101) or 'quit': ")
                if chat_id_input.lower() in ["quit", "exit"]: break

                user_message = input("[Incoming Message] Tenant Complaint: ")

                # 2. Identify Tenant (Req 3.2.1)
                tenant = get_tenant_by_chat_id(chat_id_input)
                if not tenant:
                    print("❌ Unknown Slack ID. Ignoring.")
                    continue

                print(f"🔍 Identified Tenant: {tenant['name']} in Unit {tenant['unit_number']}")

                # 3. Start Agent Reasoning
                messages = [
                    {"role": "system", "content": f"""
                    You are the Smart Dispatcher. 
                    Current Date: {datetime.now().strftime('%Y-%m-%d')}.
                    Tenant Unit: {tenant['unit_number']}.

                    PROTOCOL:
                    1. Use 'get_assets' to find the relevant appliance in the unit.
                    2. Check Warranty Expiration.
                    3. IF ACTIVE: Retrieve Vendor Email (Manufacturer) -> Dispatch Email directly.
                    4. IF EXPIRED: Retrieve Vendor Email (Internal Handyman) -> Check Calendar -> Book Slot -> Dispatch Email.

                    RESTRICTION: 
                    - Do NOT make up emails. Use the email provided by the database/context.
                    - Emails MUST contain the Asset Serial Number[cite: 70].
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

                        # --- LOCAL TOOLS ---
                        if fname == "check_warranty_status":
                            exp_date = datetime.strptime(args["expiration_date"], "%Y-%m-%d")
                            now = datetime.now()
                            is_expired = now > exp_date
                            # AUTO-LOOKUP VENDOR HERE to save a step
                            # We assume the agent knows the brand from the asset lookup previous step
                            # This is a simplification; ideally, we pass brand here.
                            result_content = f"Expired? {is_expired}. (If True -> Use Internal Handyman. If False -> Use Manufacturer)."

                        elif fname == "check_calendar_availability":
                            result_content = str(calendar_tool.check_availability(args["date"]))

                        elif fname == "book_appointment":
                            result_content = calendar_tool.book_slot(args["date"], args["time"], args["task"])

                        elif fname == "dispatch_email":
                            result_content = email_tool.send_email(
                                args["subject"], args["body"], args["recipient_email"]
                            )

                        # --- MCP TOOLS (Database) ---
                        else:
                            # If checking assets, result helps us find the brand
                            mcp_result = await session.call_tool(fname, arguments=args)
                            result_content = mcp_result.content[0].text

                            # HELPER: If this was 'get_assets', let's peek at the brand to help the agent
                            if "brand" in result_content and fname == "get_assets":
                                # This is a bit of a "cheat" to inject the vendor email into the context
                                # so the agent doesn't have to query a separate 'get_vendors' tool.
                                # In a strict implementation, we would make 'get_vendors' a tool.
                                pass

                                # If the agent needs a vendor email, we provide a helper context
                            # We can inject the vendor list into the system prompt or just let it deduce.
                            # Better approach: Let's give it a special tool or just inject data.
                            # For simplicity, we will let the agent ask for "Vendor Info" via Python if needed,
                            # but simpler is to inject the vendor table or just use the helper:

                        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result_content)})

                    # Run Again
                    response = await openai.chat.completions.create(model="gpt-4o", messages=messages,
                                                                    tools=openai_tools)
                    response_msg = response.choices[0].message
                    tool_calls = response_msg.tool_calls

                print(f"💬 Agent: {response_msg.content}")


if __name__ == "__main__":
    asyncio.run(run_agent())