"""Integration and Unit Tests for FastAPI & WebSocket Gateway."""

import pytest
from fastapi.testclient import TestClient

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    GestureType,
    HeartbeatPayload,
    ImuTelemetryPayload,
    AudioUplinkPayload,
    CrossSurfaceRoutingPayload,
    SystemControlPayload,
)
from core.protocol import (
    encode_message,
    decode_message,
    unpack_tlv,
    pack_tlv,
)
from gateway.server import app, engine, audio_router


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_rest_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "project-pa-gateway"


def test_rest_status(client):
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "metrics" in data
    assert "current_display" in data["metrics"]
    assert "current_audio" in data["metrics"]


def test_rest_route_override(client):
    # Set to cast_ambient & ambient_room
    res = client.post("/route", json={
        "display_surface": "cast_ambient",
        "audio_destination": "ambient_room",
        "reason": "test_override"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "updated"
    assert data["current_route"]["display"] == "cast_ambient"
    assert data["current_route"]["audio"] == "ambient_room"

    # Reset back to private
    res_reset = client.post("/route", json={
        "display_surface": "private_hud",
        "audio_destination": "private_ear",
        "reason": "test_reset"
    })
    assert res_reset.status_code == 200


def test_websocket_wearable_heartbeat(client):
    with client.websocket_connect("/ws/wearable") as ws:
        ping = encode_message(MessageType.MSG_HEARTBEAT, HeartbeatPayload(echo=False, seq=10), seq=10)
        ws.send_bytes(ping)

        resp = ws.receive_bytes()
        mtype, seq, payload_bytes = unpack_tlv(resp)
        assert mtype == MessageType.MSG_HEARTBEAT
        decoded: HeartbeatPayload = decode_message(mtype, payload_bytes)
        assert decoded.echo is True
        assert decoded.seq == 10


def test_websocket_wearable_imu_look_to_cast(client):
    with client.websocket_connect("/ws/wearable") as ws:
        # Send IMU gaze look-at-ambient
        imu = ImuTelemetryPayload(
            gesture=GestureType.LOOK_AT_AMBIENT,
            gaze_vector=[0.0, 0.0, 1.0],
            gaze_confidence=0.95
        )
        packet = encode_message(MessageType.MSG_IMU_TELEMETRY, imu, seq=1)
        ws.send_bytes(packet)

        # Give small moment for router notification
        import time
        time.sleep(0.05)

        assert engine.router.current_display == DisplaySurface.CAST_AMBIENT


def test_websocket_ambient_connection(client):
    with client.websocket_connect("/ws/ambient") as ws:
        # Upon connecting, gateway sends initial routing state
        data = ws.receive_bytes()
        mtype, seq, payload_bytes = unpack_tlv(data)
        assert mtype == MessageType.MSG_CROSS_SURFACE_ROUTING
        decoded: CrossSurfaceRoutingPayload = decode_message(mtype, payload_bytes)
        assert isinstance(decoded, CrossSurfaceRoutingPayload)


def test_system_control_voice_query_handling(client):
    """Verify MSG_SYSTEM_CONTROL setting voice_query updates pending query in agent engine."""
    with client.websocket_connect("/ws/wearable") as ws:
        ctrl = SystemControlPayload(voice_query="What is the battery level?")
        packet = encode_message(MessageType.MSG_SYSTEM_CONTROL, ctrl, seq=55)
        ws.send_bytes(packet)

        import time
        time.sleep(0.05)

        assert engine.pending_voice_query == "What is the battery level?"
        engine.pending_voice_query = None


def test_gateway_telemetry_uplink_and_latency_updated(client):
    """Verify BUG-018: last_uplink_ts and last_roundtrip_latency_ms are updated."""
    import time
    with client.websocket_connect("/ws/wearable") as ws:
        # Send audio uplink
        raw_audio = b"\x00\x01" * 80
        packet = encode_message(MessageType.MSG_AUDIO_UPLINK, raw_audio, seq=1)
        ws.send_bytes(packet)
        time.sleep(0.05)

        assert audio_router.last_uplink_ts > 0.0

        # Send heartbeat with client timestamp
        client_ts = int((time.time() - 0.025) * 1000)  # 25ms ago
        hb = HeartbeatPayload(timestamp_ms=client_ts, seq=2)
        hb_pkt = encode_message(MessageType.MSG_HEARTBEAT, hb, seq=2)
        ws.send_bytes(hb_pkt)
        ws.receive_bytes()  # Consume pong

        assert audio_router.last_roundtrip_latency_ms >= 0.0


def test_client_connection_selective_audio_drop():
    """Verify BUG-013: Queue drops audio frames on backpressure while keeping UI/routing messages."""
    import asyncio
    from gateway.audio_router import ClientConnection

    class DummyWS:
        def __init__(self):
            self.sent = []
        async def send_bytes(self, data):
            self.sent.append(data)
        async def close(self):
            pass

    async def _run():
        dummy_ws = DummyWS()
        conn = ClientConnection(dummy_ws, max_queue_size=2)
        # Fill queue to capacity (2 items)
        await conn.send(b"crit_1", is_audio=False)
        await conn.send(b"crit_2", is_audio=False)
        assert conn.queue.full()

        # Audio packet under backpressure should be dropped (return False)
        dropped = await conn.send(b"audio_dropped", is_audio=True)
        assert dropped is False
        assert conn.queue.qsize() == 2

    asyncio.run(_run())

