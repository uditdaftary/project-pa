"""FastAPI and WebSocket Gateway Server for Project PA.

Manages:
- `/ws/wearable`: Eyewear simulator or physical glasses BLE/Wi-Fi proxy.
- `/ws/ambient`: Ambient Screen cast target receiver.
- `/simulator`: Static HTML/JS MicroLED eyewear simulator UI.
- `/ambient`: Static HTML/JS ambient screen receiver UI.
- REST endpoints for health, telemetry, and manual surface routing override.
"""

from __future__ import annotations
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    AudioUplinkPayload,
    ImuTelemetryPayload,
    VpuVadEventPayload,
    SystemControlPayload,
    HeartbeatPayload,
)
from core.protocol import (
    TLVStreamParser,
    decode_message,
    encode_message,
    pack_tlv,
)
from agent_engine.engine import HybridAgentEngine
from gateway.audio_router import GatewayAudioRouter

# Global instances
engine = HybridAgentEngine(livekit_mode="mock")
audio_router = GatewayAudioRouter(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for background engine initialization and graceful teardown."""
    await engine.initialize()
    try:
        yield
    finally:
        await engine.shutdown()


app = FastAPI(
    title="Project PA Gateway & Media Orchestrator",
    version="1.0.0",
    description="Physical-First Embodied AI Agent Gateway with dynamic visual & acoustic handoff",
    lifespan=lifespan,
)

# CORS middleware for local browser simulator access
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static web clients
SIMULATOR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "simulator")
AMBIENT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ambient_screen")

os.makedirs(SIMULATOR_DIR, exist_ok=True)
os.makedirs(AMBIENT_DIR, exist_ok=True)

app.mount("/simulator", StaticFiles(directory=SIMULATOR_DIR, html=True), name="simulator")
app.mount("/ambient", StaticFiles(directory=AMBIENT_DIR, html=True), name="ambient")


@app.get("/")
def get_root():
    """Redirect root access to the Wearable Eyebox Simulator."""
    return RedirectResponse(url="/simulator/")


# --- REST Endpoints ---

class RouteOverrideRequest(BaseModel):
    display_surface: Optional[DisplaySurface] = None
    audio_destination: Optional[AudioDestination] = None
    reason: str = "manual_rest_override"


@app.get("/health")
def get_health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "project-pa-gateway",
        "timestamp": time.time(),
    }


@app.get("/status")
def get_status():
    """Returns runtime telemetry, active connections, and routing state."""
    return {
        "status": "ok",
        "metrics": audio_router.get_status(),
        "playhead_seconds": engine.ring_buffer.playhead_seconds,
        "ring_buffer_size": engine.ring_buffer.size,
        "vad_speech": engine.vad.is_speech,
        "vad_noise_floor_dbfs": engine.vad.noise_floor_dbfs,
    }


@app.post("/route")
async def override_route(req: RouteOverrideRequest):
    """Manually force cross-surface display or audio routing."""
    res = {}
    if req.display_surface:
        routing = engine.router.set_display_surface(req.display_surface, reason=req.reason)
        res["display"] = routing.display_surface.value
    if req.audio_destination:
        routing = engine.router.set_audio_destination(req.audio_destination, reason=req.reason)
        res["audio"] = routing.audio_destination.value
    return {"status": "updated", "current_route": res}


# --- WebSocket Endpoints ---

@app.websocket("/ws/wearable")
async def websocket_wearable_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Wearable Eyewear (Simulator or Hardware)."""
    await websocket.accept()
    audio_router.register_wearable(websocket)
    parser = TLVStreamParser(verify_crc=True)

    try:
        while True:
            # Receive raw binary or text frame
            data = await websocket.receive_bytes()

            packets = parser.feed(data)
            for msg_type_val, seq, payload_bytes in packets:
                try:
                    payload = decode_message(msg_type_val, payload_bytes)
                    msg_type = MessageType(msg_type_val)

                    if msg_type == MessageType.MSG_AUDIO_UPLINK and isinstance(payload, AudioUplinkPayload):
                        audio_router.record_audio_uplink(len(payload.audio_data))
                        await engine.process_audio_uplink(payload)

                    elif msg_type == MessageType.MSG_IMU_TELEMETRY and isinstance(payload, ImuTelemetryPayload):
                        await engine.process_imu_telemetry(payload)

                    elif msg_type == MessageType.MSG_VPU_VAD_EVENT and isinstance(payload, VpuVadEventPayload):
                        await engine.process_vpu_vad_event(payload)

                    elif msg_type == MessageType.MSG_SYSTEM_CONTROL and isinstance(payload, SystemControlPayload):
                        if payload.voice_query:
                            engine.set_voice_query(payload.voice_query)

                    elif msg_type == MessageType.MSG_HEARTBEAT:
                        hb_seq = payload.seq if isinstance(payload, HeartbeatPayload) else seq
                        hb_ts = payload.timestamp_ms if isinstance(payload, HeartbeatPayload) else 0
                        audio_router.record_heartbeat(hb_ts)
                        pong = encode_message(MessageType.MSG_HEARTBEAT, HeartbeatPayload(echo=True, seq=hb_seq, timestamp_ms=hb_ts), seq=hb_seq)
                        conn = audio_router.wearable_connections.get(websocket)
                        if conn:
                            await conn.send(pong)
                        else:
                            await websocket.send_bytes(pong)

                except Exception as e:
                    pass

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        audio_router.unregister_wearable(websocket)


@app.websocket("/ws/ambient")
async def websocket_ambient_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Ambient Screen Cast Target."""
    await websocket.accept()
    audio_router.register_ambient(websocket)
    parser = TLVStreamParser(verify_crc=True)

    # Send initial routing state immediately to the newly connected ambient screen
    initial_route = encode_message(MessageType.MSG_CROSS_SURFACE_ROUTING, audio_router.active_surface_route)
    conn = audio_router.ambient_connections.get(websocket)
    if conn:
        await conn.send(initial_route)
    else:
        await websocket.send_bytes(initial_route)

    try:
        while True:
            data = await websocket.receive_bytes()
            packets = parser.feed(data)
            for msg_type_val, seq, payload_bytes in packets:
                # Handle ambient uplink (e.g. touch/interaction or heartbeat)
                if msg_type_val == MessageType.MSG_HEARTBEAT:
                    payload = decode_message(msg_type_val, payload_bytes)
                    hb_seq = payload.seq if isinstance(payload, HeartbeatPayload) else seq
                    hb_ts = payload.timestamp_ms if isinstance(payload, HeartbeatPayload) else 0
                    audio_router.record_heartbeat(hb_ts)
                    pong = encode_message(MessageType.MSG_HEARTBEAT, HeartbeatPayload(echo=True, seq=hb_seq, timestamp_ms=hb_ts), seq=hb_seq)
                    conn = audio_router.ambient_connections.get(websocket)
                    if conn:
                        await conn.send(pong)
                    else:
                        await websocket.send_bytes(pong)

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        audio_router.unregister_ambient(websocket)


@app.websocket("/ws")
async def websocket_coexistence_endpoint(websocket: WebSocket):
    """Coexistence endpoint multiplexing wearable TLV protocol and local voice agent JSON.
    
    Prevents 403 Forbidden connection rejection loops when interactive-voice-agent
    is run alternately or alongside Project PA on port 8000.
    """
    await websocket.accept()
    audio_router.register_wearable(websocket)
    parser = TLVStreamParser(verify_crc=True)

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                data = message["bytes"]
                packets = parser.feed(data)
                for msg_type_val, seq, payload_bytes in packets:
                    try:
                        payload = decode_message(msg_type_val, payload_bytes)
                        msg_type = MessageType(msg_type_val)

                        if msg_type == MessageType.MSG_AUDIO_UPLINK and isinstance(payload, AudioUplinkPayload):
                            audio_router.record_audio_uplink(len(payload.audio_data))
                            await engine.process_audio_uplink(payload)

                        elif msg_type == MessageType.MSG_IMU_TELEMETRY and isinstance(payload, ImuTelemetryPayload):
                            await engine.process_imu_telemetry(payload)

                        elif msg_type == MessageType.MSG_VPU_VAD_EVENT and isinstance(payload, VpuVadEventPayload):
                            await engine.process_vpu_vad_event(payload)

                        elif msg_type == MessageType.MSG_SYSTEM_CONTROL and isinstance(payload, SystemControlPayload):
                            if payload.voice_query:
                                engine.set_voice_query(payload.voice_query)

                        elif msg_type == MessageType.MSG_HEARTBEAT:
                            hb_seq = payload.seq if isinstance(payload, HeartbeatPayload) else seq
                            hb_ts = payload.timestamp_ms if isinstance(payload, HeartbeatPayload) else 0
                            audio_router.record_heartbeat(hb_ts)
                            pong = encode_message(MessageType.MSG_HEARTBEAT, HeartbeatPayload(echo=True, seq=hb_seq, timestamp_ms=hb_ts), seq=hb_seq)
                            conn = audio_router.wearable_connections.get(websocket)
                            if conn:
                                await conn.send(pong)
                            else:
                                await websocket.send_bytes(pong)
                    except Exception:
                        pass
            elif "text" in message and message["text"]:
                # Coexistence handshake response for interactive-voice-agent clients
                sync_payload = {
                    "type": "state_sync",
                    "status": "ready",
                    "server": "project-pa-gateway",
                    "info": "Project PA Gateway active. Wearable HUD at /simulator/, Ambient Screen at /ambient/"
                }
                await websocket.send_json(sync_payload)

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        audio_router.unregister_wearable(websocket)


def find_available_port(preferred_port: int = 8080, max_attempts: int = 20) -> int:
    """Finds an open port starting from preferred_port without conflicting with existing services."""
    import socket
    for p in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return preferred_port


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("PA_GATEWAY_HOST", "127.0.0.1")
    if "PA_GATEWAY_PORT" in os.environ:
        port = int(os.environ["PA_GATEWAY_PORT"])
    else:
        # Default to 8080 to seamlessly coexist with interactive-voice-agent (which uses 8000)
        port = find_available_port(preferred_port=8080)

    print("\n" + "=" * 65)
    print(" PROJECT PA DUAL-SURFACE GATEWAY RUNNING")
    print(f" URL:                       http://{host}:{port}/")
    print(f" Wearable HUD Simulator:    http://{host}:{port}/simulator/")
    print(f" Ambient Screen Receiver:   http://{host}:{port}/ambient/")
    print(f" Port:                      {port} (Coexists with voice-agent on 8000)")
    print("=" * 65 + "\n")
    uvicorn.run("gateway.server:app", host=host, port=port, reload=False)


