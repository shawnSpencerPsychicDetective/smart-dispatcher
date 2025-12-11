import asyncio
import os
import sys
import json
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

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
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # 1. Discover Tools
            tools_list = await session.list_tools()
            print(f"✅ Connected to MCP Server. Found {len(tools_list.tools)} tools.")

            openai_tools = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            } for tool in tools_list.tools]

            print("\n💬 Agent Ready! Type 'quit' to exit.")
            print("--------------------------------------------------")

            messages = [
                {"role": "system", "content": "You are a Property Maintenance Manager. You must check the asset database for warranty status before calling any vendor. If warranty is active, route to Manufacturer. If expired, route to Handyman. Be professional and concise."}
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

                # Process the response
                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                # THE FIX: Loop as long as the AI wants to use tools
                while tool_calls:
                    print(f"⚡ Agent Thinking... (Needs {len(tool_calls)} tools)")
                    
                    # 1. Add the Agent's "Request" to history
                    messages.append(response_message)

                    # 2. Run every tool requested
                    for tool_call in tool_calls:
                        func_name = tool_call.function.name
                        func_args = json.loads(tool_call.function.arguments)
                        
                        print(f"🔧 Calling Tool: {func_name}({func_args})...")
                        
                        # Execute via MCP
                        result = await session.call_tool(func_name, arguments=func_args)
                        tool_output = result.content[0].text
                        
                        print(f"📥 Result: {tool_output}")

                        # 3. Add Result to history
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output
                        })

                    # 4. Send results back to OpenAI to see if it needs MORE tools
                    response = await openai.chat.completions.create(
                        model="gpt-4o",
                        messages=messages,
                        tools=openai_tools
                    )
                    response_message = response.choices[0].message
                    tool_calls = response_message.tool_calls
                
                # Final Answer (No more tools needed)
                agent_reply = response_message.content
                print(f"\nAgent: {agent_reply}")
                messages.append({"role": "assistant", "content": agent_reply})

if __name__ == "__main__":
    asyncio.run(run_agent())