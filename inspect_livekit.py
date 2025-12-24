import livekit.agents

print("LiveKit Agents Version:", livekit.agents.__version__)
print("\n--- Available Modules ---")
print(dir(livekit.agents))

try:
    from livekit.agents.pipeline import VoicePipelineAgent

    print("\nSUCCESS: Found VoicePipelineAgent in 'livekit.agents.pipeline'")

    print(VoicePipelineAgent)
except ImportError:
    print("\nFAILED: Could not find 'pipeline' module.")

try:

    from livekit.agents import VoicePipelineAgent as TopLevelVPA

    print(
        "\nSUCCESS: Found VoicePipelineAgent in top-level 'livekit.agents'"
    )

    print(TopLevelVPA)
except ImportError:
    print("\nFAILED: Could not find VoicePipelineAgent in top level.")
