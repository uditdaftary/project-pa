"""Audio and Packet Router for Project PA Gateway.

Orchestrates asymmetric audio routing and latency measurement between:
- Wearable client (/ws/wearable): Knowles PDM mics + ST LIS25BA VPU uplink, USound MEMS downlink
- Ambient screen (/ws/ambient): Cast room audio downlink
- Agent Engine: Local DSP, VAD, and real-time speech pipeline
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set
from fastapi import WebSocket

from core.messages import (
    MessageType,
    AudioDestination,
    DisplaySurface,
    AudioUplinkPayload,
    AudioDownlinkPayload,
    HudDrawTextPayload,
    HudDrawBitmapPayload,
    CrossSurfaceRoutingPayload,
    AmbientDisplayPayload,
)
from core.protocol import pack_tlv, encode_message
from agent_engine.engine import HybridAgentEngine

logger = logging.getLogger("gateway.router")


class GatewayAudioRouter:
    """Dispatches media frames and TLV messages between connected surfaces and agent engine."""

    def __init__(self, engine: HybridAgentEngine):
        self.engine = engine
        self.wearable_sockets: Set[WebSocket] = set()
        self.ambient_sockets: Set[WebSocket] = set()

        # Telemetry metrics
        self.total_uplink_bytes = 0
        self.total_downlink_bytes = 0
        self.last_uplink_ts = 0.0
        self.last_roundtrip_latency_ms = 0.0
        self.active_surface_route = CrossSurfaceRoutingPayload(
            display_surface=DisplaySurface.PRIVATE_HUD,
            audio_destination=AudioDestination.PRIVATE_EAR,
        )

        # Wire engine callbacks
        self.engine.on_hud_text = self._on_engine_hud_text
        self.engine.on_hud_bitmap = self._on_engine_hud_bitmap
        self.engine.on_ambient_content = self._on_engine_ambient_content
        self.engine.on_audio_downlink = self._on_engine_audio_downlink
        self.engine.on_routing_change = self._on_engine_routing_change

    def register_wearable(self, ws: WebSocket) -> None:
        """Register active wearable WebSocket connection."""
        self.wearable_sockets.add(ws)
        logger.info(f"Wearable connected. Total: {len(self.wearable_sockets)}")

    def unregister_wearable(self, ws: WebSocket) -> None:
        """Unregister wearable connection."""
        self.wearable_sockets.discard(ws)
        logger.info(f"Wearable disconnected. Remaining: {len(self.wearable_sockets)}")

    def register_ambient(self, ws: WebSocket) -> None:
        """Register active ambient screen WebSocket connection."""
        self.ambient_sockets.add(ws)
        logger.info(f"Ambient screen connected. Total: {len(self.ambient_sockets)}")

    def unregister_ambient(self, ws: WebSocket) -> None:
        """Unregister ambient screen connection."""
        self.ambient_sockets.discard(ws)
        logger.info(f"Ambient screen disconnected. Remaining: {len(self.ambient_sockets)}")

    # --- Engine Callback Handlers ---

    async def _on_engine_hud_text(self, payload: HudDrawTextPayload) -> None:
        """Dispatch HUD text rendering packet to wearable sockets."""
        packet = encode_message(MessageType.MSG_HUD_DRAW_TEXT, payload)
        await self.broadcast_binary(self.wearable_sockets, packet)

    async def _on_engine_hud_bitmap(self, payload: HudDrawBitmapPayload) -> None:
        """Dispatch HUD bitmap packet to wearable sockets."""
        packet = encode_message(MessageType.MSG_HUD_DRAW_BITMAP, payload)
        await self.broadcast_binary(self.wearable_sockets, packet)

    async def _on_engine_ambient_content(self, payload: AmbientDisplayPayload) -> None:
        """Dispatch rich ambient content packet to ambient screen sockets."""
        packet = encode_message(MessageType.MSG_AMBIENT_DISPLAY_CONTENT, payload)
        await self.broadcast_binary(self.ambient_sockets, packet)

    async def _on_engine_audio_downlink(self, payload: AudioDownlinkPayload) -> None:
        """Asymmetrically route downlink audio based on destination."""
        packet = encode_message(MessageType.MSG_AUDIO_DOWNLINK, payload)
        self.total_downlink_bytes += len(payload.audio_data)

        if payload.destination == AudioDestination.AMBIENT_ROOM:
            # Route to external room speaker / ambient screen
            await self.broadcast_binary(self.ambient_sockets, packet)
        else:
            # Route to private USound MEMS speaker on wearable
            await self.broadcast_binary(self.wearable_sockets, packet)

    async def _on_engine_routing_change(self, payload: CrossSurfaceRoutingPayload) -> None:
        """Broadcast routing handoff event to all active endpoints."""
        self.active_surface_route = payload
        packet = encode_message(MessageType.MSG_CROSS_SURFACE_ROUTING, payload)
        await self.broadcast_binary(self.wearable_sockets, packet)
        await self.broadcast_binary(self.ambient_sockets, packet)

    async def broadcast_binary(self, sockets: Set[WebSocket], data: bytes) -> None:
        """Broadcast binary TLV frame to a set of sockets."""
        if not sockets:
            return

        dead_sockets = []
        for ws in list(sockets):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            sockets.discard(ws)

    def get_status(self) -> Dict[str, Any]:
        """Return gateway routing and connection status."""
        return {
            "wearable_connected": len(self.wearable_sockets) > 0,
            "wearable_count": len(self.wearable_sockets),
            "ambient_connected": len(self.ambient_sockets) > 0,
            "ambient_count": len(self.ambient_sockets),
            "current_display": self.active_surface_route.display_surface.value,
            "current_audio": self.active_surface_route.audio_destination.value,
            "routing_reason": self.active_surface_route.reason,
            "total_uplink_bytes": self.total_uplink_bytes,
            "total_downlink_bytes": self.total_downlink_bytes,
        }
