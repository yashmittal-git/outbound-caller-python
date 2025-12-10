#!/usr/bin/env python3
"""
Flask API server for creating outbound call dispatches.

This server provides an endpoint to create LiveKit agent dispatches
for making outbound calls using the lk CLI command.
"""

import json
import logging
import os
import subprocess
from typing import Any

import flask
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=".env.local")

logger = logging.getLogger("api-server")
logger.setLevel(logging.INFO)

app = flask.Flask(__name__)

# Configuration
DEFAULT_AGENT_NAME = os.getenv("AGENT_NAME", "outbound-caller")


def validate_metadata(metadata: dict[str, Any]) -> tuple[bool, str]:
    """Validate the metadata payload."""
    if not isinstance(metadata, dict):
        return False, "metadata must be a JSON object"
    
    if "phone_number" not in metadata:
        return False, "phone_number is required in metadata"
    
    return True, ""


def create_dispatch_via_cli(
    metadata: dict[str, Any],
    agent_name: str | None = None,
    room_name: str | None = None,
    create_new_room: bool = True,
) -> dict[str, Any]:
    """Create a dispatch using the lk CLI command."""
    # Use default agent name if not provided
    agent_name = agent_name or DEFAULT_AGENT_NAME

    # Convert metadata to JSON string
    metadata_json = json.dumps(metadata)

    # Build command
    command_parts = ["lk", "dispatch", "create"]
    
    if create_new_room:
        command_parts.append("--new-room")
    
    command_parts.extend(["--agent-name", agent_name])
    command_parts.extend(["--metadata", metadata_json])
    
    if room_name:
        command_parts.extend(["--room", room_name])

    logger.info(f"Executing command: lk dispatch create --agent-name {agent_name} ... (metadata hidden)")

    try:
        # Execute the command
        result = subprocess.run(
            command_parts,
            capture_output=True,
            text=True,
            check=True,
            env=os.environ.copy(),
        )
        
        logger.info(f"Dispatch created successfully. Output: {result.stdout}")
        
        # Try to extract dispatch ID from output if available
        dispatch_id = None
        if result.stdout:
            # The CLI might output the dispatch ID, try to extract it
            for line in result.stdout.split("\n"):
                if "dispatch" in line.lower() or "id" in line.lower():
                    # Try to extract any ID-like string
                    parts = line.split()
                    for part in parts:
                        if len(part) > 10 and ("dispatch" in part.lower() or part.startswith("DI_")):
                            dispatch_id = part
                            break
                    if dispatch_id:
                        break

        return {
            "success": True,
            "dispatch_id": dispatch_id,
            "room_name": room_name,
            "agent_name": agent_name,
            "message": "Dispatch created successfully",
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        logger.error(f"Error creating dispatch: {error_msg}")
        raise ValueError(f"Failed to create dispatch: {error_msg}")
    except FileNotFoundError:
        raise ValueError(
            "lk CLI not found. Please ensure LiveKit CLI is installed and in PATH."
        )


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return flask.jsonify({"status": "healthy"}), 200


@app.route("/dispatch", methods=["POST"])
def create_dispatch():
    """
    Create an outbound call dispatch using the lk CLI.
    
    Request body should be a JSON object with the following structure:
    {
        "phone_number": "+1234567890",
        "customer_name": "John Doe",
        "tts_config": {
            "provider": "elevenlabs",
            "voice_id": "Sljl8mdsZ6BckhbY2Pon"
        },
        "stt_config": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
            "base_url": "wss://deepgram.convin.ai/v1/listen"
        },
        "llm_config": {
            "provider": "openai",
            "model": "gpt-4.1-mini"
        },
        "prompt": "Talk.",
        "variables": {},
        "sip_trunk_id": "ST_jrcQk5yYCvGg"
    }
    
    Optional query parameters:
    - agent_name: Override the default agent name
    - room_name: Specify a room name (if not provided, a new room will be created)
    - create_new_room: Whether to create a new room (default: true)
    """
    try:
        # Get JSON payload
        if not flask.request.is_json:
            return flask.jsonify({"error": "Request must be JSON"}), 400

        metadata = flask.request.get_json()
        if not metadata:
            return flask.jsonify({"error": "Request body cannot be empty"}), 400

        # Validate metadata
        is_valid, error_msg = validate_metadata(metadata)
        if not is_valid:
            return flask.jsonify({"error": error_msg}), 400

        # Get optional parameters
        agent_name = flask.request.args.get("agent_name")
        room_name = flask.request.args.get("room_name")
        create_new_room = flask.request.args.get("create_new_room", "true").lower() == "true"

        # Create dispatch via CLI
        result = create_dispatch_via_cli(
            metadata=metadata,
            agent_name=agent_name,
            room_name=room_name,
            create_new_room=create_new_room,
        )
        return flask.jsonify(result), 200

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return flask.jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating dispatch: {e}", exc_info=True)
        return flask.jsonify({"error": "Internal server error", "message": str(e)}), 500


if __name__ == "__main__":
    # Run the Flask app
    port = int(os.getenv("API_PORT", "5000"))
    host = os.getenv("API_HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
