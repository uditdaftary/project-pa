"""Unit and Component Tests for Hybrid Agent Engine."""

import pytest
import numpy as np

from core.messages import (
    DisplaySurface,
    AudioDestination,
    GestureType,
    AudioUplinkPayload,
    ImuTelemetryPayload,
    VpuVadEventType,
    VpuVadEventPayload,
)
from agent_engine.local.ring_buffer import AudioRingBuffer
from agent_engine.local.vad import VoiceActivityDetector
from agent_engine.local.sentence_parser import StreamingSentenceAccumulator, split_sentences
from agent_engine.router import CrossSurfaceRouter
from agent_engine.cloud.livekit_bridge import LiveKitBridge
from agent_engine.engine import HybridAgentEngine


# --- AudioRingBuffer Tests ---

def test_ring_buffer_write_read():
    rb = AudioRingBuffer(capacity_samples=1000, sample_rate=16000)
    data = np.full(200, 1000, dtype=np.int16)

    written = rb.write(data)
    assert written == 200
    assert rb.available_read() == 200
    assert rb.available_write == 800

    out = rb.read(200)
    assert len(out) == 200
    assert np.all(out == 1000)
    assert rb.available_read() == 0


def test_ring_buffer_generation_fencing():
    rb = AudioRingBuffer(capacity_samples=1000, sample_rate=16000)
    rb.write(np.full(100, 500, dtype=np.int16), generation=0)

    # Drain triggers generation increment
    rb.drain(fade_ms=2.0)
    assert rb.generation == 1

    # Stale write with generation=0 should be rejected
    rejected = rb.write(np.full(100, 999, dtype=np.int16), generation=0)
    assert rejected == 0

    # Valid write with current generation=1
    accepted = rb.write(np.full(100, 777, dtype=np.int16), generation=1)
    assert accepted == 100


def test_ring_buffer_half_cosine_fadeout():
    rb = AudioRingBuffer(capacity_samples=2000, sample_rate=24000)
    # Write loud constant signal
    rb.write(np.full(500, 20000, dtype=np.int16))

    # Drain with 2ms fadeout (2ms at 24kHz = 48 samples)
    rb.drain(fade_ms=2.0)
    assert rb.fadeout_tail is not None
    assert len(rb.fadeout_tail) == 48

    # The fadeout tail should start near 20000 and attenuate to 0 smoothly
    assert rb.fadeout_tail[0] > 18000
    assert rb.fadeout_tail[-1] == 0

    # Reading from ring buffer consumes the fadeout tail first
    out = rb.read(48)
    assert np.array_equal(out, rb.fadeout_tail) or len(out) == 48
    assert not rb.is_actively_playing()


# --- VoiceActivityDetector Tests ---

def test_vad_silence_and_noise_floor():
    vad = VoiceActivityDetector(sample_rate=16000, initial_noise_floor_dbfs=-60.0)
    # Generate 100ms of low-level silence/noise
    silence = (np.random.randn(1600) * 10).astype(np.int16)
    results = vad.process(silence)

    assert len(results) >= 3  # ~3 frames of 30ms (480 samples each)
    assert not any(results)
    assert vad.noise_floor_dbfs <= -50.0


def test_vad_loud_speech_and_hangover():
    vad = VoiceActivityDetector(
        sample_rate=16000,
        energy_threshold=300.0,
        onset_frames=2,
        hangover_frames=3,
        initial_noise_floor_dbfs=-60.0
    )

    # 3 frames of loud speech (480 * 3 = 1440 samples)
    t = np.linspace(0, 0.09, 1440, endpoint=False)
    loud_speech = (np.sin(2 * np.pi * 300.0 * t) * 20000).astype(np.int16)

    results = vad.process(loud_speech)
    assert any(results)
    assert vad.is_speech is True


def test_vad_vpu_whisper_fusion():
    vad = VoiceActivityDetector(sample_rate=16000, vpu_whisper_threshold=0.3)
    # Very quiet whisper signal (acoustic energy below normal airborne threshold)
    quiet_signal = (np.random.randn(960) * 50).astype(np.int16)

    # Without VPU resonance -> silent
    res_no_vpu = vad.process(quiet_signal, vpu_energy=0.0)
    assert not any(res_no_vpu)

    # With ST LIS25BA bone-conduction resonance -> activates whisper speech
    res_vpu = vad.process(quiet_signal, vpu_energy=0.85, vpu_confidence=0.95)
    assert any(res_vpu)
    assert vad.is_whisper_active is True


# --- SentenceParser Tests ---

def test_split_sentences_abbreviation_shielding():
    text = "Dr. Smith met Mr. J. K. Rowling at 3.14 PM. The meeting cost $12.50 vs. $10.00! Did they agree? Yes."
    sentences = split_sentences(text)

    assert len(sentences) == 4
    assert sentences[0] == "Dr. Smith met Mr. J. K. Rowling at 3.14 PM."
    assert sentences[1] == "The meeting cost $12.50 vs. $10.00!"
    assert sentences[2] == "Did they agree?"
    assert sentences[3] == "Yes."


def test_streaming_sentence_accumulator():
    acc = StreamingSentenceAccumulator(max_card_chars=60)
    tokens = ["Hello ", "world. ", "This ", "is ", "Project ", "PA. ", "Enjoy ", "the ", "HUD."]

    chunks = []
    for token in tokens:
        chunks.extend(acc.feed(token))
    chunks.extend(acc.flush())

    assert len(chunks) >= 3
    assert "Hello world." in chunks[0]
    assert "This is Project PA." in chunks[1]


# --- CrossSurfaceRouter Tests ---

def test_router_gaze_alignment_look_to_cast():
    router = CrossSurfaceRouter(
        default_display=DisplaySurface.PRIVATE_HUD,
        default_audio=AudioDestination.PRIVATE_EAR,
        ambient_gaze_threshold=0.8
    )

    # User looking straight ahead at ambient screen: vector [0.0, 0.0, 1.0]
    aligned_imu = ImuTelemetryPayload(
        gaze_vector=[0.0, 0.0, 1.0],
        gaze_confidence=0.9
    )
    change = router.evaluate_imu_telemetry(aligned_imu)
    assert change is not None
    assert router.current_display == DisplaySurface.CAST_AMBIENT

    # User turns head away: vector [1.0, 0.0, 0.0]
    away_imu = ImuTelemetryPayload(
        gaze_vector=[1.0, 0.0, 0.0],
        gaze_confidence=0.9
    )
    change2 = router.evaluate_imu_telemetry(away_imu)
    assert change2 is not None
    assert router.current_display == DisplaySurface.PRIVATE_HUD


def test_router_vpu_whisper_audio_routing():
    router = CrossSurfaceRouter(default_audio=AudioDestination.AMBIENT_ROOM)
    vpu_ev = VpuVadEventPayload(
        event_type=VpuVadEventType.WHISPER_START,
        energy_level=0.8,
        confidence=0.9
    )

    change = router.evaluate_vpu_event(vpu_ev)
    assert change is not None
    assert router.current_audio == AudioDestination.PRIVATE_EAR


def test_router_content_complexity():
    router = CrossSurfaceRouter()
    short_teleprompter = "Turn right in 200 feet."
    rich_table = "Here is the comparison:\n| Plan | Speed |\n| Pro | 1 Gbps |"

    assert router.evaluate_content_complexity(short_teleprompter) == DisplaySurface.PRIVATE_HUD
    assert router.evaluate_content_complexity(rich_table) == DisplaySurface.CAST_AMBIENT


import asyncio

def test_hybrid_engine_audio_flow_and_barge_in():
    async def _run():
        engine = HybridAgentEngine(livekit_mode="mock")
        await engine.initialize()

        hud_packets = []
        engine.on_hud_text = lambda p: hud_packets.append(p)

        # Pre-load audio into ring buffer to simulate ongoing agent playback
        engine.ring_buffer.write(np.full(1000, 15000, dtype=np.int16))
        assert engine.ring_buffer.is_actively_playing()

        # User speaks loudly (simulating barge-in)
        loud_audio = (np.sin(np.linspace(0, 10, 1600)) * 25000).astype(np.int16).tobytes()
        uplink = AudioUplinkPayload(audio_data=loud_audio, is_vpu=False)

        await engine.process_audio_uplink(uplink)

        # Barge-in should have drained the narrative audio buffer and queued the 2ms click-free fadeout
        assert engine.ring_buffer.size == 0
        assert engine.ring_buffer.fadeout_tail is not None

        # Consuming the 2ms fadeout tail completes playback
        engine.ring_buffer.read(len(engine.ring_buffer.fadeout_tail))
        assert not engine.ring_buffer.is_actively_playing()

    asyncio.run(_run())


def test_ring_buffer_2d_callback_arrays():
    """Verify AudioRingBuffer.read_into works with 2D mono and stereo audio callback buffers."""
    rb = AudioRingBuffer(capacity_samples=1000, sample_rate=16000)
    rb.write(np.full(500, 1234, dtype=np.int16))

    # 1. 2D mono buffer (frames, 1)
    mono_buf = np.zeros((200, 1), dtype=np.int16)
    read_mono = rb.read_into(mono_buf)
    assert read_mono == 200
    assert np.all(mono_buf == 1234)

    # 2. 2D stereo buffer (frames, 2)
    stereo_buf = np.zeros((200, 2), dtype=np.int16)
    read_stereo = rb.read_into(stereo_buf)
    assert read_stereo == 200
    assert np.all(stereo_buf == 1234)
    assert stereo_buf.shape == (200, 2)

    # 3. Micro-fadeout tail into 2D stereo buffer
    rb.drain(fade_ms=2.0)
    tail_buf = np.zeros((100, 2), dtype=np.int16)
    read_tail = rb.read_into(tail_buf)
    assert read_tail > 0
    assert tail_buf[0, 0] == tail_buf[0, 1]


def test_ring_buffer_readonly_array():
    """Verify AudioRingBuffer.write handles read-only numpy arrays without throwing ValueError."""
    rb = AudioRingBuffer(capacity_samples=1000, sample_rate=16000)
    ro_float = np.array([0.1, 0.5, -0.5, 0.9], dtype=np.float32)
    ro_float.flags.writeable = False

    written = rb.write(ro_float)
    assert written == 4
    out = rb.read(4)
    assert len(out) == 4


def test_vad_readonly_array():
    """Verify VoiceActivityDetector handles read-only numpy arrays without throwing ValueError."""
    vad = VoiceActivityDetector(sample_rate=16000)
    ro_samples = np.full(480, 500, dtype=np.int16)
    ro_samples.flags.writeable = False

    res = vad.process(ro_samples)
    assert isinstance(res, list)


def test_livekit_bridge_surface_routing_non_clobbering():
    """Verify LiveKitBridge tool calls do not clobber the other routing dimension."""
    engine = HybridAgentEngine(livekit_mode="mock")

    # Start: PRIVATE_HUD, PRIVATE_EAR
    assert engine.router.current_display == DisplaySurface.PRIVATE_HUD
    assert engine.router.current_audio == AudioDestination.PRIVATE_EAR

    # Switch audio to AMBIENT_ROOM
    engine.bridge.tool_set_audio_destination("ambient_room")
    assert engine.router.current_audio == AudioDestination.AMBIENT_ROOM
    assert engine.router.current_display == DisplaySurface.PRIVATE_HUD  # Must NOT be modified

    # Now switch display to CAST_AMBIENT
    engine.bridge.tool_set_display_surface("cast_ambient")
    assert engine.router.current_display == DisplaySurface.CAST_AMBIENT
    assert engine.router.current_audio == AudioDestination.AMBIENT_ROOM  # Must NOT be clobbered back to private_ear!


def test_hybrid_engine_voice_query_intent():
    """Verify setting voice query triggers the appropriate simulated turn response."""
    async def _run():
        engine = HybridAgentEngine(livekit_mode="mock")
        await engine.initialize()

        # Set intended voice query
        engine.set_voice_query("show on screen")

        # Send speech burst followed by silence (>= 22 frames) to trigger turn complete
        speech = (np.sin(np.arange(1920) * 0.1) * 20000).astype(np.int16).tobytes()
        silence = np.zeros(11040, dtype=np.int16).tobytes()

        await engine.process_audio_uplink(AudioUplinkPayload(audio_data=speech))
        await engine.process_audio_uplink(AudioUplinkPayload(audio_data=silence))

        # Should have routed to CAST_AMBIENT
        assert engine.router.current_display == DisplaySurface.CAST_AMBIENT

    asyncio.run(_run())
