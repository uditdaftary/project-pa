"""Unified Hybrid Agent Engine for Project PA.

Integrates:
- Local AudioRingBuffer with sub-0.05ms atomic drain and 2ms half-cosine fadeout (ADR-006).
- 80Hz IIR VoiceActivityDetector with adaptive noise floor and ST LIS25BA VPU fusion (ADR-003).
- Sentence boundary parser with Unicode sentinel shielding for 640x200 MicroLED display.
- Dynamic CrossSurfaceRouter for look-to-cast gaze alignment and asymmetric audio handoff.
- Pluggable LiveKitBridge for real-time speech-to-speech agent sessions.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Callable, List, Optional

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    AudioUplinkPayload,
    AudioDownlinkPayload,
    HudDrawTextPayload,
    HudDrawBitmapPayload,
    ImuTelemetryPayload,
    VpuVadEventType,
    VpuVadEventPayload,
    CrossSurfaceRoutingPayload,
    AmbientDisplayPayload,
)
from agent_engine.local.ring_buffer import AudioRingBuffer
from agent_engine.local.vad import VoiceActivityDetector
from agent_engine.local.sentence_parser import StreamingSentenceAccumulator, split_sentences
from agent_engine.router import CrossSurfaceRouter
from agent_engine.cloud.livekit_bridge import LiveKitBridge

logger = logging.getLogger("agent_engine.hybrid")


class HybridAgentEngine:
    """Coordinates local real-time DSP, sentence tokenization, cross-surface routing, and agent bridge."""

    def __init__(
        self,
        sample_rate: int = 16000,
        downlink_sample_rate: int = 24000,
        livekit_mode: str = "mock",
    ):
        self.sample_rate = sample_rate
        self.downlink_sample_rate = downlink_sample_rate

        # 1. Local DSP and Buffering
        self.ring_buffer = AudioRingBuffer(capacity_samples=downlink_sample_rate * 10, sample_rate=downlink_sample_rate)
        self.vad = VoiceActivityDetector(sample_rate=sample_rate)
        self.sentence_accumulator = StreamingSentenceAccumulator(max_card_chars=90)

        # 2. Dynamic Cross-Surface Router
        self.router = CrossSurfaceRouter(
            default_display=DisplaySurface.PRIVATE_HUD,
            default_audio=AudioDestination.PRIVATE_EAR,
        )

        # 3. Cloud / Mock Agent Bridge
        self.bridge = LiveKitBridge(
            mode=livekit_mode,
            on_text_output=self._handle_bridge_text,
            on_audio_output=self._handle_bridge_audio,
            on_ambient_output=self._handle_bridge_ambient,
            on_surface_route=self._handle_bridge_surface_route,
        )

        # Outward Event Callbacks (Dispatched to Gateway)
        self.on_hud_text: Optional[Callable[[HudDrawTextPayload], None]] = None
        self.on_hud_bitmap: Optional[Callable[[HudDrawBitmapPayload], None]] = None
        self.on_ambient_content: Optional[Callable[[AmbientDisplayPayload], None]] = None
        self.on_audio_downlink: Optional[Callable[[AudioDownlinkPayload], None]] = None
        self.on_routing_change: Optional[Callable[[CrossSurfaceRoutingPayload], None]] = None

        self.pending_voice_query: Optional[str] = None

        # Wire router notifications
        self.router.add_listener(self._on_router_event)

    def set_voice_query(self, query: str) -> None:
        """Sets the pending voice query intent for speech recognition turnaround."""
        self.pending_voice_query = query

    def _safe_dispatch(self, cb: Optional[Callable], arg: Any) -> None:
        if cb is not None:
            res = cb(arg)
            if asyncio.iscoroutine(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    new_loop = asyncio.new_event_loop()
                    try:
                        new_loop.run_until_complete(res)
                    finally:
                        new_loop.close()

    def _on_router_event(self, routing: CrossSurfaceRoutingPayload) -> None:
        """Propagate router state changes."""
        logger.info(f"Surface handoff: display={routing.display_surface.value}, audio={routing.audio_destination.value} ({routing.reason})")
        self._safe_dispatch(self.on_routing_change, routing)

    # --- LiveKit Bridge Event Handlers ---

    def _handle_bridge_text(self, text: str) -> None:
        """Handle incoming streaming text from agent bridge."""
        if not text:
            # Clear command
            self._safe_dispatch(self.on_hud_text, HudDrawTextPayload(text="", clear_screen=True))
            return

        # Check content routing
        recommended_surface = self.router.evaluate_content_complexity(text)
        if recommended_surface == DisplaySurface.CAST_AMBIENT and self.router.current_display != DisplaySurface.CAST_AMBIENT:
            self.router.set_display_surface(DisplaySurface.CAST_AMBIENT, reason="rich_content_density_auto_route")
            self._safe_dispatch(self.on_ambient_content, AmbientDisplayPayload(title="Agent Response", content=text))
        else:
            # Route to private HUD: feed sentence accumulator
            chunks = self.sentence_accumulator.feed(text)
            chunks.extend(self.sentence_accumulator.flush())
            for idx, chunk in enumerate(chunks):
                self._safe_dispatch(self.on_hud_text, HudDrawTextPayload(
                    x=10,
                    y=20,
                    text=chunk,
                    font_size=14,
                    clear_screen=(idx == 0),
                    teleprompter_mode=True
                ))

    def _handle_bridge_audio(self, downlink: AudioDownlinkPayload) -> None:
        """Handle synthesized audio downlink from agent bridge."""
        # Enforce current audio destination from router
        downlink.destination = self.router.current_audio

        # Write to ring buffer for tracking/playback
        self.ring_buffer.write(downlink.audio_data)
        self._safe_dispatch(self.on_audio_downlink, downlink)

    def _handle_bridge_ambient(self, payload: AmbientDisplayPayload) -> None:
        """Handle rich ambient card from agent bridge tool."""
        if self.router.current_display != DisplaySurface.CAST_AMBIENT:
            self.router.set_display_surface(DisplaySurface.CAST_AMBIENT, reason="tool_display_ambient_card")
        self._safe_dispatch(self.on_ambient_content, payload)

    def _handle_bridge_surface_route(
        self,
        display: Optional[DisplaySurface] = None,
        audio: Optional[AudioDestination] = None
    ) -> None:
        """Handle surface route requested by AI tool."""
        if display is not None and display != self.router.current_display:
            self.router.set_display_surface(display, reason="ai_tool_invocation")
        if audio is not None and audio != self.router.current_audio:
            self.router.set_audio_destination(audio, reason="ai_tool_invocation")

    # --- Inward Processing Methods ---

    async def initialize(self) -> None:
        """Initialize engine components and agent bridge."""
        await self.bridge.connect()

    async def process_audio_uplink(self, uplink: AudioUplinkPayload) -> None:
        """Process incoming 16kHz audio from wearable Knowles mic and ST LIS25BA VPU."""
        # Feed VAD
        speech_frames = self.vad.process(
            uplink.audio_data,
            vpu_energy=uplink.vpu_energy if uplink.is_vpu else None
        )

        # Barge-in interruption check:
        # If user starts speaking while agent is playing audio, execute instant 2ms half-cosine fadeout!
        if self.vad.is_speech and self.ring_buffer.is_actively_playing():
            logger.info("Barge-in interruption detected! Draining audio ring buffer with 2ms half-cosine fadeout.")
            self.ring_buffer.drain(fade_ms=2.0)
            self.vad.set_playback_active(False)

        # Turn completion check: if user finishes speaking, simulate turn in mock mode
        if self.vad.is_turn_complete:
            logger.info("User turn complete detected by VAD.")
            self.vad.is_turn_complete = False
            # In mock mode, generate response with dynamic pending query
            query = self.pending_voice_query or "Summarize the system status"
            self.pending_voice_query = None
            await self.bridge.simulate_mock_turn(query)

    async def process_imu_telemetry(self, imu: ImuTelemetryPayload) -> None:
        """Process 6-DoF IMU orientation, head gestures, and gaze vector."""
        self.router.evaluate_imu_telemetry(imu)

    async def process_vpu_vad_event(self, vpu_event: VpuVadEventPayload) -> None:
        """Process direct bone-conduction whisper triggers from eyewear hardware."""
        self.vad.fuse_vpu_resonance(vpu_event.energy_level, vpu_event.confidence)
        self.router.evaluate_vpu_event(vpu_event)
