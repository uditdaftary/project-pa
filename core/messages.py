"""Unified packet message definitions and data schemas for Project PA.

Implements ADR-007: Unified Binary/JSON Type-Length-Value (TLV) Protocol schemas
shared between Eyewear Wearable, Gateway, and Ambient Screen surfaces.
"""

from __future__ import annotations
import enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MessageType(enum.IntEnum):
    """TLV Message Types matching ADR-007 specification."""
    MSG_AUDIO_UPLINK = 0x01          # 16kHz Opus/PCM from Knowles mic + VPU
    MSG_AUDIO_DOWNLINK = 0x02        # Audio chunks to USound MEMS / Tarvos amp or Ambient Room
    MSG_HUD_DRAW_TEXT = 0x03         # 640x200 HUD text rendering commands
    MSG_HUD_DRAW_BITMAP = 0x04       # 1-bit monochrome MicroLED display buffer tiles
    MSG_IMU_TELEMETRY = 0x05         # 6-DoF pitch, yaw, roll, gestures, gaze vector
    MSG_VPU_VAD_EVENT = 0x06         # Bone-conduction vocal cord resonance trigger
    MSG_SYSTEM_CONTROL = 0x07        # Battery, brightness, thermal telemetry, sleep/wake
    MSG_CROSS_SURFACE_ROUTING = 0x08 # Display (private_hud/cast_ambient) & Audio (private_ear/ambient_room)
    MSG_AMBIENT_DISPLAY_CONTENT = 0x09 # Rich HTML/Markdown/cards for Ambient Screen Cast
    MSG_HEARTBEAT = 0x0A             # Keepalive ping/pong


class DisplaySurface(str, enum.Enum):
    """Target surface for visual output."""
    PRIVATE_HUD = "private_hud"
    CAST_AMBIENT = "cast_ambient"


class AudioDestination(str, enum.Enum):
    """Target destination for acoustic output."""
    PRIVATE_EAR = "private_ear"      # USound Ganymede MEMS dipole speaker
    AMBIENT_ROOM = "ambient_room"    # External Bluetooth / Auracast room speaker


class VpuVadEventType(str, enum.Enum):
    """Bone-conduction voice activity event types."""
    WHISPER_START = "whisper_start"
    WHISPER_STOP = "whisper_stop"
    SPEECH_ACTIVE = "speech_active"


class GestureType(str, enum.Enum):
    """Head gesture types detected by IMU."""
    NONE = "none"
    NOD = "nod"
    SHAKE = "shake"
    TILT_LEFT = "tilt_left"
    TILT_RIGHT = "tilt_right"
    LOOK_AT_AMBIENT = "look_at_ambient"


# --- Typed Payloads ---

class AudioUplinkPayload(BaseModel):
    """Payload for MSG_AUDIO_UPLINK."""
    sample_rate: int = 16000
    channels: int = 1
    codec: str = "pcm_s16le"  # "pcm_s16le" or "opus"
    is_vpu: bool = False       # True if captured via ST LIS25BA bone-conduction VPU
    vpu_energy: float = 0.0    # Normalized energy from bone conduction sensor [0.0 - 1.0]
    audio_data: bytes = b""    # Raw PCM or Opus bytes


class AudioDownlinkPayload(BaseModel):
    """Payload for MSG_AUDIO_DOWNLINK."""
    sample_rate: int = 24000
    channels: int = 1
    codec: str = "pcm_s16le"
    destination: AudioDestination = AudioDestination.PRIVATE_EAR
    attenuation_db: float = 0.0  # Optional software attenuation
    audio_data: bytes = b""


class HudDrawTextPayload(BaseModel):
    """Payload for MSG_HUD_DRAW_TEXT."""
    x: int = Field(default=0, ge=0, le=640)
    y: int = Field(default=20, ge=0, le=200)
    text: str = ""
    font_size: int = 14
    clear_screen: bool = False
    color: int = 1             # 1 = green (MicroLED on), 0 = black (off)
    cursor_active: bool = False
    teleprompter_mode: bool = False


class HudDrawBitmapPayload(BaseModel):
    """Payload for MSG_HUD_DRAW_BITMAP (1-bit monochrome tiles)."""
    x: int = Field(default=0, ge=0, le=640)
    y: int = Field(default=0, ge=0, le=200)
    width: int = Field(default=640, ge=1, le=640)
    height: int = Field(default=200, ge=1, le=200)
    bitmap_data: bytes = b""   # 1-bit packed bitmap data (width * height / 8 bytes)


class ImuTelemetryPayload(BaseModel):
    """Payload for MSG_IMU_TELEMETRY."""
    pitch: float = 0.0        # Degrees [-90.0, 90.0]
    yaw: float = 0.0          # Degrees [-180.0, 180.0]
    roll: float = 0.0         # Degrees [-180.0, 180.0]
    accel_x: float = 0.0      # m/s^2
    accel_y: float = 0.0
    accel_z: float = 9.81
    gesture: GestureType = GestureType.NONE
    gaze_vector: List[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0]) # [x, y, z] normalized
    gaze_confidence: float = 1.0


class VpuVadEventPayload(BaseModel):
    """Payload for MSG_VPU_VAD_EVENT."""
    event_type: VpuVadEventType = VpuVadEventType.WHISPER_START
    energy_level: float = 0.0  # Normalized [0.0, 1.0]
    confidence: float = 1.0    # Bone conduction confidence [0.0, 1.0]
    timestamp_ms: int = 0


class SystemControlPayload(BaseModel):
    """Payload for MSG_SYSTEM_CONTROL."""
    battery_pct: int = Field(default=100, ge=0, le=100)
    brightness: int = Field(default=80, ge=0, le=100) # MicroLED nits percentage
    temperature_c: float = 32.5
    sleep_state: str = "awake" # "awake", "low_power", "sleep"
    link_quality: int = Field(default=100, ge=0, le=100) # RSSI / link metric
    command: Optional[str] = None
    voice_query: Optional[str] = None


class CrossSurfaceRoutingPayload(BaseModel):
    """Payload for MSG_CROSS_SURFACE_ROUTING."""
    display_surface: DisplaySurface = DisplaySurface.PRIVATE_HUD
    audio_destination: AudioDestination = AudioDestination.PRIVATE_EAR
    reason: str = "default_routing"
    confidence: float = 1.0


class AmbientDisplayPayload(BaseModel):
    """Payload for MSG_AMBIENT_DISPLAY_CONTENT."""
    title: str = ""
    content_type: str = "markdown"  # "markdown", "html", "card", "dashboard"
    content: str = ""
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HeartbeatPayload(BaseModel):
    """Payload for MSG_HEARTBEAT."""
    timestamp_ms: int = 0
    seq: int = 0
    echo: bool = False
