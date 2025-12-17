import livekit.agents
print("LiveKit Agents Version:", livekit.agents.__version__)
print("\n--- Available Modules ---")
print(dir(livekit.agents))

try:
    from livekit.agents.pipeline import VoicePipelineAgent
    print("\n✅ SUCCESS: Found VoicePipelineAgent in 'livekit.agents.pipeline'")
except ImportError:
    print("\n❌ FAILED: Could not find 'pipeline' module.")

try:
    from livekit.agents import VoicePipelineAgent
    print("\n✅ SUCCESS: Found VoicePipelineAgent in top-level 'livekit.agents'")
except ImportError:
    print("\n❌ FAILED: Could not find VoicePipelineAgent in top level.")