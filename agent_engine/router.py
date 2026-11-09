"""Dynamic Cross-Surface Router for Project PA.

Implements ADR-002 (Dynamic Visual Routing) & ADR-003 (Asymmetric Audio Routing):
- Display Surfaces: `private_hud` (640x200 MicroLED) vs `cast_ambient` (1080p/4K Ambient Screen)
- Audio Destinations: `private_ear` (USound MEMS dipole) vs `ambient_room` (Bluetooth/Auracast)
- Look-to-cast gaze alignment and bone-conduction whisper detection rules.
"""

from __future__ import annotations
import enum
import math
from typing import Callable, List, Optional
from core.messages import (
    DisplaySurface,
    AudioDestination,
    GestureType,
    ImuTelemetryPayload,
    VpuVadEventType,
    VpuVadEventPayload,
    CrossSurfaceRoutingPayload,
)


class RoutingOrigin(str, enum.Enum):
    """Origin source of display cast routing."""
    GAZE = "gaze"
    EXPLICIT_TOOL = "explicit_tool"


class CrossSurfaceRouter:
    """Orchestrates runtime visual and acoustic handoff across physical surfaces."""

    def __init__(
        self,
        default_display: DisplaySurface = DisplaySurface.PRIVATE_HUD,
        default_audio: AudioDestination = AudioDestination.PRIVATE_EAR,
        ambient_gaze_threshold: float = 0.75,
        rich_content_char_threshold: int = 120,
    ):
        self.current_display = default_display
        self.current_audio = default_audio
        self.ambient_gaze_threshold = ambient_gaze_threshold
        self.rich_content_char_threshold = rich_content_char_threshold
        self.cast_origin: Optional[RoutingOrigin] = None

        # Target ambient screen direction vector in eyewear coordinate frame:
        # e.g., Ambient screen is situated at [0.0, 0.0, 1.0] (straight ahead) or slight offset
        self.ambient_target_vector = [0.0, 0.0, 1.0]

        # Callbacks for routing change events
        self._listeners: List[Callable[[CrossSurfaceRoutingPayload], None]] = []

    def add_listener(self, listener: Callable[[CrossSurfaceRoutingPayload], None]) -> None:
        """Register a callback for routing change notifications."""
        self._listeners.append(listener)

    def _notify(self, reason: str, confidence: float = 1.0) -> CrossSurfaceRoutingPayload:
        payload = CrossSurfaceRoutingPayload(
            display_surface=self.current_display,
            audio_destination=self.current_audio,
            reason=reason,
            confidence=confidence,
        )
        for listener in self._listeners:
            try:
                listener(payload)
            except Exception:
                pass
        return payload

    def set_display_surface(
        self, surface: DisplaySurface, reason: str = "explicit_command"
    ) -> CrossSurfaceRoutingPayload:
        """Explicitly switch display surface."""
        if self.current_display != surface:
            self.current_display = surface
            self.cast_origin = RoutingOrigin.EXPLICIT_TOOL if surface == DisplaySurface.CAST_AMBIENT else None
            return self._notify(reason=reason)
        return CrossSurfaceRoutingPayload(
            display_surface=self.current_display,
            audio_destination=self.current_audio,
            reason="unchanged",
            confidence=1.0,
        )

    def set_audio_destination(
        self, destination: AudioDestination, reason: str = "explicit_command"
    ) -> CrossSurfaceRoutingPayload:
        """Explicitly switch audio destination."""
        if self.current_audio != destination:
            self.current_audio = destination
            return self._notify(reason=reason)
        return CrossSurfaceRoutingPayload(
            display_surface=self.current_display,
            audio_destination=self.current_audio,
            reason="unchanged",
            confidence=1.0,
        )

    def evaluate_imu_telemetry(self, imu: ImuTelemetryPayload) -> Optional[CrossSurfaceRoutingPayload]:
        """Evaluates IMU head orientation and gaze vector for look-to-cast transitions."""
        # 1. Direct gesture trigger
        if imu.gesture == GestureType.LOOK_AT_AMBIENT:
            if self.current_display != DisplaySurface.CAST_AMBIENT:
                self.current_display = DisplaySurface.CAST_AMBIENT
                self.cast_origin = RoutingOrigin.GAZE
                return self._notify(reason="imu_look_at_ambient_gesture", confidence=imu.gaze_confidence)
            return None

        # 2. Gaze vector dot product calculation
        if imu.gaze_vector and len(imu.gaze_vector) == 3:
            gx, gy, gz = imu.gaze_vector
            norm = math.sqrt(gx * gx + gy * gy + gz * gz)
            if norm > 1e-6:
                gx, gy, gz = gx / norm, gy / norm, gz / norm
                tx, ty, tz = self.ambient_target_vector
                dot_prod = gx * tx + gy * ty + gz * tz

                # If user is gazing towards ambient screen with high alignment
                if dot_prod >= self.ambient_gaze_threshold and imu.gaze_confidence >= 0.7:
                    if self.current_display != DisplaySurface.CAST_AMBIENT:
                        self.current_display = DisplaySurface.CAST_AMBIENT
                        self.cast_origin = RoutingOrigin.GAZE
                        return self._notify(
                            reason=f"gaze_alignment_trigger (dot={dot_prod:.2f})",
                            confidence=imu.gaze_confidence * dot_prod,
                        )
                # If gaze moved significantly away from ambient screen, revert to private HUD
                # BUG-005: Only auto-revert if origin was GAZE
                elif dot_prod < (self.ambient_gaze_threshold - 0.25):
                    if self.current_display == DisplaySurface.CAST_AMBIENT and self.cast_origin == RoutingOrigin.GAZE:
                        self.current_display = DisplaySurface.PRIVATE_HUD
                        self.cast_origin = None
                        return self._notify(reason="gaze_glance_away_revert", confidence=1.0)

        return None

    def evaluate_vpu_event(self, vpu: VpuVadEventPayload) -> Optional[CrossSurfaceRoutingPayload]:
        """Evaluates bone-conduction whisper events.
        
        Whispers lock audio output strictly to private ear dipole speaker.
        """
        if vpu.event_type == VpuVadEventType.WHISPER_START:
            if self.current_audio != AudioDestination.PRIVATE_EAR:
                self.current_audio = AudioDestination.PRIVATE_EAR
                return self._notify(reason="vpu_whisper_activated_private_ear", confidence=vpu.confidence)
        return None

    def evaluate_content_complexity(self, content: str) -> DisplaySurface:
        """Determines optimal display surface based on text density, markdown structure, and cards."""
        if not content:
            return DisplaySurface.PRIVATE_HUD

        # Complex indicators: code blocks, markdown tables, long paragraphs
        has_code_block = "```" in content
        has_markdown_table = "|" in content and content.count("|") >= 4
        is_lengthy = len(content) > self.rich_content_char_threshold

        if has_code_block or has_markdown_table or is_lengthy:
            return DisplaySurface.CAST_AMBIENT
        return DisplaySurface.PRIVATE_HUD
