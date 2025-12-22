import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.multimodal import MultimodalAgent  # <--- NEW AGENT TYPE
from livekit.plugins.openai import realtime  # <--- NEW PLUGIN
from livekit import rtc

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
logger = logging.getLogger("voice-agent")

# --- CLIENT TOOL WRAPPER ---
# (Remains exactly the same, Realtime API supports function calling natively)
class DispatcherClient(llm.FunctionContext):
    def __init__(self, mcp_session):
        super().__init__()
        self.mcp = mcp_session

    @llm.ai_callable(description="Execute maintenance for a specific asset using its SERIAL NUMBER.")
    async def execute_request(self, serial_number: str):
        print(f"⚡ [AGENT] Calling MCP Tool 'execute_maintenance' with {serial_number}")
        # The Realtime API will pause audio generation while this runs
        result = await self.mcp.call_tool("execute_maintenance", arguments={"serial_number": serial_number})
        return result.content[0].text

# --- ENTRYPOINT ---
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    
    tenant_name = "Charlie"
    unit_number = "205"

    # START MCP CLIENT
    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=None)
    
    print(f"🔌 Connecting to MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ MCP Connected.")

            # 1. FETCH CONTEXT
            print("📋 Fetching Context from Server...")
            context_result = await session.call_tool("get_tenant_context", arguments={"unit_number": unit_number})
            asset_context_string = context_result.content[0].text
            print(f"   Received: {len(asset_context_string)} bytes of context.")

            # 2. CONFIGURE REALTIME MODEL
            # We move the System Prompt here.
            model = realtime.RealtimeModel(
                instructions=f"""
                    You are the Smart Dispatcher for {tenant_name}.

                    **USER'S ASSETS (LOADED FROM MCP):**
                    {asset_context_string}

                    **PROTOCOL:**
                    1. User speaks -> if user doesnt speak exact name of asset, match to whatever the user most likely means 
                        from one of the assets above (e.g. "washer -> Bosch Dishwasher").
                    2. **DO NOT SPEAK YET.**
                    3. Call `execute_request` using the asset's SERIAL NUMBER.
                    4. The server will do the work and return a sentence. Read that sentence to the user.
                    
                    **IMPORTANT:** Start the conversation by saying "Hello {tenant_name}, I am online."
                """,
                voice="alloy",
                temperature=0.6,
            )

            # 3. START MULTIMODAL AGENT
            # Note: We don't need 'vad', 'stt', or 'tts' anymore. The model handles all of it.
            agent = MultimodalAgent(
                model=model,
                fnc_ctx=DispatcherClient(session)
            )
            
            agent.start(ctx.room, participant)
            
            # Note: MultimodalAgent doesn't have a simple .say() method to start.
            # We rely on the "instructions" above telling it to speak first, 
            # or the user speaking first.

            print("🔴 Realtime Agent Started. Using GPT-4o Realtime API.")

            while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
                await asyncio.sleep(1)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))