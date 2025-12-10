from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import json
import os
from typing import Any

from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
    stt,
    tts,
    llm,
)
from livekit.plugins import (
    deepgram,
    openai,
    cartesia,
    silero,
    elevenlabs,
    noise_cancellation,  # noqa: F401
)
from livekit.plugins.turn_detector.english import EnglishModel
from livekit.plugins.turn_detector.multilingual import MultilingualModel


# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)


def _format_prompt(prompt: str, variables: dict[str, Any]) -> str:
    """Format prompt template with variables."""
    try:
        return prompt.format(**variables)
    except KeyError as e:
        logger.warning(f"Missing variable in prompt template: {e}, using prompt as-is")
        return prompt
    except Exception as e:
        logger.warning(f"Error formatting prompt: {e}, using prompt as-is")
        return prompt


def _create_stt(stt_config: dict[str, Any]) -> stt.STT:
    """Create STT provider based on configuration."""
    provider = stt_config.get("provider", "deepgram").lower()
    # Remove provider from config to pass remaining as kwargs
    config = {k: v for k, v in stt_config.items() if k != "provider" and v is not None}
    
    if provider == "deepgram":
        return deepgram.STT(**config)
    elif provider == "openai":
        return openai.STT(**config)
    else:
        raise ValueError(f"Unsupported STT provider: {provider}")


def _create_tts(tts_config: dict[str, Any]) -> tts.TTS:
    """Create TTS provider based on configuration."""
    provider = tts_config.get("provider", "elevenlabs").lower()
    # Remove provider from config to pass remaining as kwargs
    config = {k: v for k, v in tts_config.items() if k != "provider" and v is not None}
    
    if provider == "elevenlabs":
        # Set default voice_id if not provided
        if "voice_id" not in config:
            config["voice_id"] = "Sljl8mdsZ6BckhbY2Pon"
        return elevenlabs.TTS(**config)
    elif provider == "cartesia":
        return cartesia.TTS(**config)
    elif provider == "openai":
        return openai.TTS(**config)
    elif provider == "deepgram":
        return deepgram.TTS(**config)
    else:
        raise ValueError(f"Unsupported TTS provider: {provider}")


def _create_llm(llm_config: dict[str, Any]) -> llm.LLM:
    """Create LLM provider based on configuration."""
    provider = llm_config.get("provider", "openai").lower()
    # Remove provider from config to pass remaining as kwargs
    config = {k: v for k, v in llm_config.items() if k != "provider" and v is not None}
    
    if provider == "openai":
        return openai.LLM(**config)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


class OutboundCaller(Agent):
    def __init__(
        self,
        *,
        instructions: str,
        metadata: dict[str, Any],
    ):
        super().__init__(instructions=instructions)
        # keep reference to the participant for transfers
        self.participant: rtc.RemoteParticipant | None = None
        self.metadata = metadata

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

    async def hangup(self):
        """Helper function to hang up the call by deleting the room"""
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(
                room=job_ctx.room.name,
            )
        )

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")

        # let the agent finish speaking
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()

        await self.hangup()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()

    # Parse metadata from dispatch request
    metadata = json.loads(ctx.job.metadata)
    
    # Extract configuration with defaults
    phone_number = metadata.get("phone_number")
    if not phone_number:
        raise ValueError("phone_number is required in metadata")
    
    participant_identity = phone_number
    customer_name = metadata.get("customer_name", "Customer")
    sip_trunk_id = metadata.get("sip_trunk_id") or os.getenv("SIP_OUTBOUND_TRUNK_ID")
    if not sip_trunk_id:
        raise ValueError("sip_trunk_id is required in metadata or SIP_OUTBOUND_TRUNK_ID environment variable")
    
    # Get provider configurations with defaults
    tts_config = metadata.get("tts_config", {"provider": "elevenlabs", "voice_id": "Sljl8mdsZ6BckhbY2Pon"})
    stt_config = metadata.get("stt_config", {"provider": "deepgram", "model": "nova-2", "language": "en"})
    llm_config = metadata.get("llm_config", {"provider": "openai", "model": "gpt-4.1-mini"})
    
    # Get prompt and variables
    prompt = metadata.get("prompt", "You are a helpful assistant.")
    variables = metadata.get("variables", {})
    
    # Format prompt with variables
    instructions = _format_prompt(prompt, variables)
    
    # Create agent with instructions
    agent = OutboundCaller(
        instructions=instructions,
        metadata=metadata,
    )

    # Create providers dynamically based on configuration
    stt_provider = _create_stt(stt_config)
    tts_provider = _create_tts(tts_config)
    llm_provider = _create_llm(llm_config)

    logger.info(
        f"Creating session with STT: {stt_config.get('provider')}, "
        f"TTS: {tts_config.get('provider')}, LLM: {llm_config.get('provider')}"
    )

    # Create agent session with configured providers
    # Try to use turn detector, fallback to "stt" if files aren't available
    turn_detection_mode = "stt"  # Default fallback
    try:
        # Try to initialize EnglishModel - if files are available, use it
        # Otherwise, we'll catch the error and use "stt" mode
        turn_detector = EnglishModel()
        turn_detection_mode = turn_detector
        logger.info("Using EnglishModel for turn detection")
    except Exception as e:
        # Catch any exception during turn detector initialization
        # This includes RuntimeError (missing files), ImportError, OSError, etc.
        logger.warning(
            f"Could not initialize turn detector (files may not be downloaded): {type(e).__name__}: {e}. "
            "Falling back to STT-based turn detection. "
            "Run 'python agent.py download-files' to download turn detector models."
        )
        turn_detection_mode = "stt"
    
    session = AgentSession(
        turn_detection=turn_detection_mode,
        vad=silero.VAD.load(),
        stt=stt_provider,
        tts=tts_provider,
        llm=llm_provider,
    )

    # start the session first before dialing, to ensure that when the user picks up
    # the agent does not miss anything the user says
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # enable Krisp background voice and noise removal
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    # `create_sip_participant` starts dialing the user
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                # function blocks until user answers the call, or if the call fails
                wait_until_answered=True,
            )
        )

        # wait for the agent session start and participant join
        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined: {participant.identity}")

        agent.set_participant(participant)

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )
