<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# Python Outbound Call Agent

<p>
  <a href="https://docs.livekit.io/agents/overview/">LiveKit Agents Docs</a>
  •
  <a href="https://livekit.io/cloud">LiveKit Cloud</a>
  •
  <a href="https://blog.livekit.io/">Blog</a>
</p>

This example demonstrates an full workflow of an AI agent that makes outbound calls. It uses LiveKit SIP and Python [Agents Framework](https://github.com/livekit/agents).

It can use a pipeline of STT, LLM, and TTS models, or a realtime speech-to-speech model. (such as ones from OpenAI and Gemini).

This example builds on concepts from the [Outbound Calls](https://docs.livekit.io/agents/start/telephony/#outbound-calls) section of the docs. Ensure that a SIP outbound trunk is configured before proceeding.

## Features

This example demonstrates the following features:

- Making outbound calls
- Detecting voicemail
- Looking up availability via function calling
- Transferring to a human operator
- Detecting intent to end the call
- Uses Krisp background voice cancellation to handle noisy environments

## Dev Setup

Clone the repository and install dependencies to a virtual environment:

```shell
git clone https://github.com/livekit-examples/outbound-caller-python.git
cd outbound-caller-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python agent.py download-files
```

Set up the environment by copying `.env.example` to `.env.local` and filling in the required values:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `SIP_OUTBOUND_TRUNK_ID`
- `DEEPGRAM_API_KEY` - optional, only needed when using pipelined models
- `CARTESIA_API_KEY` - optional, only needed when using pipelined models

Run the agent:

```shell
python3 agent.py dev
```

Now, your worker is running, and waiting for dispatches in order to make outbound calls.

### Making a call

You can dispatch an agent to make a call by using the `lk` CLI:

```shell
lk dispatch create \
  --new-room \
  --agent-name outbound-caller \
  --metadata '{"phone_number": "+1234567890", "transfer_to": "+9876543210"}'
```

Or use the Flask API server (see Docker Setup below):

```shell
curl -X POST http://localhost:5000/dispatch \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

## Docker Setup

### Architecture Overview

The system consists of two containers that work together:

1. **API Server Container** (`api-server`):
   - Receives HTTP POST requests to `/dispatch`
   - Executes `lk dispatch create` command to create dispatches
   - Sends dispatch requests to the LiveKit server
   - **Needs**: `lk` CLI installed (for creating dispatches)

2. **Agent Worker Container** (`agent`):
   - Runs `python agent.py dev` to connect to LiveKit server as a worker
   - Registers itself with agent name "outbound-caller"
   - Listens for job assignments from LiveKit server
   - When a dispatch is created, LiveKit server routes it to this worker
   - Executes the actual call handling logic
   - **Needs**: Agent code and dependencies (doesn't need `lk` CLI, but it's installed since containers share the same Dockerfile)

**Flow**: 
```
HTTP Request → API Container → lk dispatch create → LiveKit Server → Agent Worker Container → Executes Call
```

### Prerequisites

1. Ensure you have Docker and Docker Compose installed
2. Copy `.env.example` to `.env.local` and fill in the required values (same as Dev Setup above)
3. Ensure your LiveKit server is running and accessible (configured via `LIVEKIT_URL`)

### Running with Docker Compose

Simply run:

```shell
docker-compose up
```

This will:
- Build the Docker image with all dependencies
- Download required model files
- Install LiveKit CLI (`lk`) for creating dispatches
- Start the Flask API server on port 5000
- Start the agent worker (running `python agent.py dev`) to accept dispatches

The services will be available at:
- **API Server**: http://localhost:5000
- **Health Check**: http://localhost:5000/health
- **Agent Worker**: Running in background, waiting for dispatches

**Important Notes**:
- Both containers are **required** and work together
- The API container creates dispatches, but the agent container processes them
- The agent worker must be running (`python agent.py dev`) to accept dispatches created via the API
- Both services connect to the same LiveKit server (configured via `LIVEKIT_URL`)

### API Endpoints

#### POST /dispatch

Create an outbound call dispatch.

**Request Body:**
```json
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
```

**Query Parameters (optional):**
- `agent_name`: Override the default agent name
- `room_name`: Specify a room name (if not provided, a new room will be created)
- `create_new_room`: Whether to create a new room (default: true)

**Response:**
```json
{
  "success": true,
  "dispatch_id": "dispatch_id_here",
  "room_name": "room-abc123",
  "agent_name": "outbound-caller"
}
```

#### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy"
}
```

### Running in Background

To run in detached mode:

```shell
docker-compose up -d
```

To view logs:

```shell
docker-compose logs -f
```

To stop:

```shell
docker-compose down
```
