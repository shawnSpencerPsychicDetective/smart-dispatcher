import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

from langfuse import Langfuse

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.multimodal import MultimodalAgent
from livekit.plugins.openai import realtime
from livekit import rtc

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
logger = logging.getLogger("voice-agent")

langfuse = Langfuse()


class DispatcherClient(llm.FunctionContext):
    """Provides a bridge between the AI agent and the Model Context Protocol (MCP) server.

    This class defines the tools available to the LLM during the conversation,
    allowing it to fetch tenant context and execute maintenance workflows
    dynamically based on user input.
    """

    def __init__(self, mcp_session):
        """Initializes the client with an active MCP session."""
        super().__init__()
        self.mcp = mcp_session

    @llm.ai_callable(
        description=(
            "Look up tenant details and asset list using the Unit Number "
            "(e.g., '205'). Call this immediately when the user provides "
            "their location."
        )
    )
    async def lookup_unit(self, unit_number: str):
        """Fetches the tenant's name and asset inventory for a specific unit.

        Args:
            unit_number (str): The residential unit number provided by the tenant.

        Returns:
            str: A raw text string containing the tenant name and a list of 
                available assets (brands, names, and serial numbers).
        """
        print(f"[AGENT] Looking up context for Unit: {unit_number}")
        result = await self.mcp.call_tool(
            "get_tenant_context", arguments={"unit_number": unit_number}
        )
        # The result (text string of assets) is automatically added to the
        # conversation history so the LLM can see it.
        return result.content[0].text

    @llm.ai_callable(
        description=(
            "Execute maintenance for a specific asset using its SERIAL NUMBER. "
            "Only call this after identifying the correct serial number from "
            "the context."
        )
    )
    async def execute_request(self, serial_number: str):
        """Triggers the backend maintenance workflow for a specific serial number.

        Args:
            serial_number (str): The unique serial number of the asset to be repaired.

        Returns:
            str: The confirmation message from the MCP server regarding 
                the dispatch or booking status.
        """
        print(f"[AGENT] Executing Request for Serial: {serial_number}")
        result = await self.mcp.call_tool(
            "execute_maintenance", arguments={"serial_number": serial_number}
        )
        return result.content[0].text


async def entrypoint(ctx: JobContext):
    """The main execution loop for the LiveKit Voice Agent.

    This function orchestrates the following lifecycle:
    1. Connects to the LiveKit room with audio-only permissions.
    2. Spawns the MCP server as a subprocess via stdio.
    3. Retrieves the latest system prompt from Langfuse.
    4. Initializes the OpenAI Realtime model with environment-based settings.
    5. Starts the MultimodalAgent and forces an initial greeting reply.

    Args:
        ctx (JobContext): The LiveKit job context providing room and 
            participant information.
    """
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    server_params = StdioServerParameters(
        command=sys.executable, args=["src/mcp_server.py"], env=None
    )

    print("Connecting to MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP Connected.")

            # 1. FETCH PROMPT FROM LANGFUSE
            print("Fetching System Prompt directly from Langfuse...")
            prompt_obj = langfuse.get_prompt("smart-dispatcher")

            # 2. COMPILE
            system_instruction = prompt_obj.compile()

            # 3. CONFIGURE REALTIME MODEL
            model = realtime.RealtimeModel(
                instructions=system_instruction,
                voice=os.getenv("VOICE_PRESET"),
                temperature=0.6,
            )

            agent = MultimodalAgent(model=model, fnc_ctx=DispatcherClient(session))

            agent.start(ctx.room, participant)

            # 4. KICKSTART CONVERSATION
            agent.generate_reply()

            print("Realtime Agent Started.")

            while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
                await asyncio.sleep(1)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
