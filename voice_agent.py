import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# --- NEW: Import Langfuse directly here ---
from langfuse import Langfuse

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.multimodal import MultimodalAgent
from livekit.plugins.openai import realtime
from livekit import rtc

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
logger = logging.getLogger("voice-agent")

# Initialize Langfuse directly in the agent process
langfuse = Langfuse()

class DispatcherClient(llm.FunctionContext):
    def __init__(self, mcp_session):
        super().__init__()
        self.mcp = mcp_session

    @llm.ai_callable(description="Execute maintenance for a specific asset using its SERIAL NUMBER.")
    async def execute_request(self, serial_number: str):
        print(f"⚡ [AGENT] Calling MCP Tool 'execute_maintenance' with {serial_number}")
        result = await self.mcp.call_tool("execute_maintenance", arguments={"serial_number": serial_number})
        return result.content[0].text

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    
    tenant_name = "Charlie"
    unit_number = "205"

    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)
    
    print(f"🔌 Connecting to MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected.")

            # 1. FETCH CONTEXT (Data) via MCP
            # We still use MCP for this because it needs the database!
            print("📋 Fetching Context from database...")
            context_result = await session.call_tool("get_tenant_context", arguments={"unit_number": unit_number})
            asset_context_string = context_result.content[0].text

            # 2. FETCH PROMPT (Configuration) via Direct Langfuse Call
            # No more "session.get_prompt()"
            print("📝 Fetching System Prompt directly from Langfuse...")
            
            # Retrieve the prompt object
            prompt_obj = langfuse.get_prompt("smart-dispatcher")
            
            # Compile it with the data we got from step 1
            system_instruction = prompt_obj.compile(
                tenant_name=tenant_name,
                asset_context_string=asset_context_string
            )

            # DEBUG: Print it to prove it works
            print(f"\n--- INSTRUCTION LOADED ---\n{system_instruction}\n--------------------------\n")

            # 3. CONFIGURE REALTIME MODEL
            model = realtime.RealtimeModel(
                instructions=system_instruction,
                voice="alloy",
                temperature=0.6,
            )

            agent = MultimodalAgent(
                model=model,
                fnc_ctx=DispatcherClient(session)
            )
            
            agent.start(ctx.room, participant)
            print("🔴 Realtime Agent Started.")

            while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
                await asyncio.sleep(1)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))