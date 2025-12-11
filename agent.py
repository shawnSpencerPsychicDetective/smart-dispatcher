import asyncio
import os
import sys
import json
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

# Import your local Email Service
from email_service import EmailDispatcher

load_dotenv()
openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Use sys.executable to ensure we use the correct Python environment
server_params = StdioServerParameters(
    command=sys.executable,
    args=["mcp_server.py"],
    env=None
)


async def run_agent():
    print("🤖 Smart Dispatcher Agent Initializing...")

    # Initialize Local Tools
    email_dispatcher = EmailDispatcher()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Discover Remote Tools (from MCP Server)
            tools_list = await session.list_tools()
            print(f"✅ Connected to MCP Server. Found {len(tools_list.tools)} remote tools.")

            # 2. Build Tool Definitions for OpenAI
            # Start with MCP tools...
            openai_tools = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            } for tool in tools_list.tools]

            # ...Append Local Email Tool manually
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send an email notification to a tenant or vendor. If recipient_email is omitted, a fake one is generated.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                            "recipient_email": {"type": "string"}
                        },
                        "required": ["subject", "body"]
                    }
                }
            })
            print("✅ Local Email Tool registered.")

            print("\n💬 Agent Ready! Type 'quit' to exit.")
            print("--------------------------------------------------")

            messages = [
                {"role": "system",
                 "content": "You are a Property Maintenance Manager. Check the database for warranty status. If active -> Email Manufacturer. If expired -> Email Handyman. You can also email the tenant updates. Be professional."}
            ]

            while True:
                user_input = input("\nTenant (You): ")
                if user_input.lower() in ["quit", "exit"]:
                    break

                messages.append({"role": "user", "content": user_input})

                # Initial Call to OpenAI
                response = await openai.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    tools=openai_tools
                )

                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                # Loop while the Agent wants to use tools
                while tool_calls:
                    print(f"⚡ Agent Thinking... (Needs {len(tool_calls)} tools)")
                    messages.append(response_message)

                    for tool_call in tool_calls:
                        func_name = tool_call.function.name
                        func_args = json.loads(tool_call.function.arguments)

                        print(f"🔧 Calling Tool: {func_name}({func_args})...")

                        tool_output = ""

                        # --- ROUTING LOGIC ---
                        if func_name == "send_email":
                            # Execute LOCAL Tool
                            tool_output = email_dispatcher.send_email(
                                subject=func_args.get("subject"),
                                body=func_args.get("body"),
                                recipient_email=func_args.get("recipient_email")
                            )
                        else:
                            # Execute REMOTE MCP Tool
                            result = await session.call_tool(func_name, arguments=func_args)
                            tool_output = result.content[0].text

                        print(f"📥 Result: {tool_output}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output
                        })

                    # Send results back to OpenAI
                    response = await openai.chat.completions.create(
                        model="gpt-4o",
                        messages=messages,
                        tools=openai_tools
                    )
                    response_message = response.choices[0].message
                    tool_calls = response_message.tool_calls

                # Final Answer
                agent_reply = response_message.content
                print(f"\nAgent: {agent_reply}")
                messages.append({"role": "assistant", "content": agent_reply})


if __name__ == "__main__":
    asyncio.run(run_agent())