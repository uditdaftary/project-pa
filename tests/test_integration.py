"""End-to-End Multi-Surface Integration Tests for Project PA.

Verifies complete conversational and physical-grounding loop:
- Eyewear Simulator (/ws/wearable)
- Ambient Screen Target (/ws/ambient)
- TLV Binary Protocol
- Dynamic Visual & Acoustic Handoff
"""

import time
import pytest
from fastapi.testclient import TestClient

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    GestureType,
    AudioUplinkPayload,
    ImuTelemetryPayload,
    VpuVadEventType,
    VpuVadEventPayload,
    CrossSurfaceRoutingPayload,
    AmbientDisplayPayload,
)
from core.protocol import (
    encode_message,
    decode_message,
    unpack_tlv,
)
from gateway.server import app, engine, audio_router


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_static_files_served(client):
    """Verify that both simulator and ambient screen web apps are served."""
    resp_sim = client.get("/simulator/index.html")
    assert resp_sim.status_code == 200
    assert "MicroLED" in resp_sim.text

    resp_amb = client.get("/ambient/index.html")
    assert resp_amb.status_code == 200
    assert "AMBIENT CAST TARGET" in resp_amb.text


def test_end_to_end_cross_surface_handoff(client):
    """Verify simultaneous dual-surface WebSocket connection and dynamic handoff."""
    with client.websocket_connect("/ws/wearable") as ws_wearable:
        with client.websocket_connect("/ws/ambient") as ws_ambient:

            # 1. Ambient receiver should get initial routing packet upon connect
            initial_pkg = ws_ambient.receive_bytes()
            mtype, seq, payload_bytes = unpack_tlv(initial_pkg)
            assert mtype == MessageType.MSG_CROSS_SURFACE_ROUTING
            initial_route: CrossSurfaceRoutingPayload = decode_message(mtype, payload_bytes)
            assert initial_route.display_surface in [DisplaySurface.PRIVATE_HUD, DisplaySurface.CAST_AMBIENT]

            # 2. Eyewear user performs Look-to-Cast gaze alignment towards Ambient Screen
            look_cast_imu = ImuTelemetryPayload(
                gesture=GestureType.LOOK_AT_AMBIENT,
                gaze_vector=[0.0, 0.0, 1.0],
                gaze_confidence=0.98,
            )
            imu_packet = encode_message(MessageType.MSG_IMU_TELEMETRY, look_cast_imu, seq=101)
            ws_wearable.send_bytes(imu_packet)

            # Both surfaces should receive cross-surface routing update: display -> cast_ambient
            route_update_wearable = ws_wearable.receive_bytes()
            mtype_w, _, p_w = unpack_tlv(route_update_wearable)
            assert mtype_w == MessageType.MSG_CROSS_SURFACE_ROUTING
            route_w: CrossSurfaceRoutingPayload = decode_message(mtype_w, p_w)
            assert route_w.display_surface == DisplaySurface.CAST_AMBIENT

            route_update_ambient = ws_ambient.receive_bytes()
            mtype_a, _, p_a = unpack_tlv(route_update_ambient)
            assert mtype_a == MessageType.MSG_CROSS_SURFACE_ROUTING
            route_a: CrossSurfaceRoutingPayload = decode_message(mtype_a, p_a)
            assert route_a.display_surface == DisplaySurface.CAST_AMBIENT

            # 3. Eyewear user activates ST LIS25BA bone-conduction VPU whisper trigger
            whisper_event = VpuVadEventPayload(
                event_type=VpuVadEventType.WHISPER_START,
                energy_level=0.92,
                confidence=0.99,
            )
            vpu_packet = encode_message(MessageType.MSG_VPU_VAD_EVENT, whisper_event, seq=102)
            ws_wearable.send_bytes(vpu_packet)

            # Audio routing locks to private_ear
            assert engine.router.current_audio == AudioDestination.PRIVATE_EAR

            # 4. Agent Bridge tool triggers rich ambient card display
            engine.bridge.tool_display_ambient_card(
                title="System Telemetry",
                content="### Performance\n- End-to-end Latency: 230ms\n- Audio: Dipole Active"
            )

            # Ambient screen should receive MSG_AMBIENT_DISPLAY_CONTENT packet
            ambient_content_packet = ws_ambient.receive_bytes()
            mtype_c, _, p_c = unpack_tlv(ambient_content_packet)
            assert mtype_c == MessageType.MSG_AMBIENT_DISPLAY_CONTENT
            card: AmbientDisplayPayload = decode_message(mtype_c, p_c)
            assert card.title == "System Telemetry"
            assert "230ms" in card.content

            # Wearable simulator mirror should also receive MSG_AMBIENT_DISPLAY_CONTENT packet
            wearable_content_packet = ws_wearable.receive_bytes()
            mtype_w2, _, p_w2 = unpack_tlv(wearable_content_packet)
            assert mtype_w2 == MessageType.MSG_AMBIENT_DISPLAY_CONTENT
            card_w: AmbientDisplayPayload = decode_message(mtype_w2, p_w2)
            assert card_w.title == "System Telemetry"


def test_voice_query_turn_and_hud_text_completion(client):
    """Verify that voice queries generate real-time agent responses on HUD with audio and complete buffer flush."""
    import struct
    import numpy as np

    with client.websocket_connect("/ws/wearable") as ws_wearable:
        # Switch display to private_hud
        engine.router.set_display_surface(DisplaySurface.PRIVATE_HUD, reason="test_init")
        time.sleep(0.05)

        # 1. Send system control voice query
        ctrl_pkt = encode_message(
            MessageType.MSG_SYSTEM_CONTROL,
            {"command": "voice_query", "voice_query": "What is the system status?"},
            seq=201
        )
        ws_wearable.send_bytes(ctrl_pkt)

        # 2. Send 16kHz speech burst (4 frames = 1920 samples)
        hdr = struct.pack(">HBBBBf", 16000, 1, 0, 0, 0, 0.1)
        speech = (np.sin(np.arange(1920) * 0.1) * 20000).astype(np.int16).tobytes()
        ws_wearable.send_bytes(encode_message(MessageType.MSG_AUDIO_UPLINK, hdr + speech, seq=202))

        # 3. Send trailing silence (23 frames = 11040 samples) to trigger VAD turn completion
        sil_hdr = struct.pack(">HBBBBf", 16000, 1, 0, 0, 0, 0.0)
        sil = np.zeros(11040, dtype=np.int16).tobytes()
        ws_wearable.send_bytes(encode_message(MessageType.MSG_AUDIO_UPLINK, sil_hdr + sil, seq=203))

        time.sleep(0.1)

        # Receive responses: exactly 2 packets (HUD text + audio downlink)
        received_hud_text = []
        received_audio = False

        for _ in range(2):
            pkt = ws_wearable.receive_bytes()
            mtype, seq, payload = unpack_tlv(pkt)
            if mtype == MessageType.MSG_HUD_DRAW_TEXT:
                decoded = decode_message(mtype, payload)
                received_hud_text.append(decoded.text)
            elif mtype == MessageType.MSG_AUDIO_DOWNLINK:
                received_audio = True

        assert len(received_hud_text) > 0, "Expected HUD text response from agent"
        assert any("nominal" in t.lower() or "latency" in t.lower() or "system" in t.lower() for t in received_hud_text)
        assert received_audio is True, "Expected audio chime downlink from agent"
        assert engine.sentence_accumulator.buffer == "", "Expected sentence accumulator to be completely flushed"

