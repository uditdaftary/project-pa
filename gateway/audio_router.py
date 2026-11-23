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
from typing import Any, Dict, List, Optional, Set
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


class ClientConnection:
    """Manages an individual WebSocket client connection with a dedicated outbound queue and drain loop.
    
    Prevents concurrent send_bytes() race conditions on Starlette WebSockets (BUG-013)
    and ensures explicit socket closure on disconnect (BUG-016).
    """

    def __init__(self, websocket: WebSocket, max_queue_size: int = 128):
        self.websocket = websocket
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue_size)
        self.is_active = True
        self.drain_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.drain_task = asyncio.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        try:
            while self.is_active:
                packet = await self.queue.get()
                try:
                    await self.websocket.send_bytes(packet)
                except Exception as e:
                    logger.warning(f"Error sending bytes to WebSocket: {e}")
                    break
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            self.is_active = False
            try:
                await self.websocket.close()
            except Exception:
                pass

    async def send(self, data: bytes, is_audio: bool = False) -> bool:
        if not self.is_active:
            return False
        if self.drain_task and self.drain_task.done():
            self.is_active = False
            return False
        if self.queue.full():
            if is_audio:
                # Selectively drop audio frames under backpressure (BUG-013)
                logger.debug("Dropping audio frame due to queue backpressure")
                return False
            else:
                # Critical packet (UI text, bitmaps, routing): await space with timeout to prevent deadlock
                try:
                    await asyncio.wait_for(self.queue.put(data), timeout=1.0)
                    return True
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Dropping packet due to persistent queue backpressure or stalled client: {e}")
                    self.is_active = False
                    return False
        else:
            self.queue.put_nowait(data)
            return True

    async def close(self) -> None:
        self.is_active = False
        if self.drain_task and not self.drain_task.done():
            self.drain_task.cancel()
            try:
                await self.drain_task
            except asyncio.CancelledError:
                pass
        try:
            await self.websocket.close()
        except Exception:
            pass


class GatewayAudioRouter:
    """Dispatches media frames and TLV messages between connected surfaces and agent engine."""

    def __init__(self, engine: HybridAgentEngine):
        self.engine = engine
        self.wearable_connections: Dict[WebSocket, ClientConnection] = {}
        self.ambient_connections: Dict[WebSocket, ClientConnection] = {}

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

    @property
    def wearable_sockets(self) -> Set[WebSocket]:
        return set(self.wearable_connections.keys())

    @property
    def ambient_sockets(self) -> Set[WebSocket]:
        return set(self.ambient_connections.keys())

    def register_wearable(self, ws: WebSocket) -> None:
        """Register active wearable WebSocket connection."""
        conn = ClientConnection(ws)
        conn.start()
        self.wearable_connections[ws] = conn
        logger.info(f"Wearable connected. Total: {len(self.wearable_connections)}")

    def unregister_wearable(self, ws: WebSocket) -> None:
        """Unregister wearable connection and ensure explicit closure (BUG-016)."""
        conn = self.wearable_connections.pop(ws, None)
        if conn:
            asyncio.create_task(conn.close())
        logger.info(f"Wearable disconnected. Remaining: {len(self.wearable_connections)}")

    def register_ambient(self, ws: WebSocket) -> None:
        """Register active ambient screen WebSocket connection."""
        conn = ClientConnection(ws)
        conn.start()
        self.ambient_connections[ws] = conn
        logger.info(f"Ambient screen connected. Total: {len(self.ambient_connections)}")

    def unregister_ambient(self, ws: WebSocket) -> None:
        """Unregister ambient screen connection and ensure explicit closure (BUG-016)."""
        conn = self.ambient_connections.pop(ws, None)
        if conn:
            asyncio.create_task(conn.close())
        logger.info(f"Ambient screen disconnected. Remaining: {len(self.ambient_connections)}")

    def record_audio_uplink(self, payload_size: int) -> None:
        """Update telemetry on incoming audio uplink frame (BUG-018)."""
        self.last_uplink_ts = time.time()
        self.total_uplink_bytes += payload_size

    def record_heartbeat(self, client_ts_ms: int = 0) -> None:
        """Calculate round-trip latency on heartbeat (BUG-018)."""
        if client_ts_ms > 0:
            now_ms = time.time() * 1000.0
            self.last_roundtrip_latency_ms = max(0.0, now_ms - client_ts_ms)

    # --- Engine Callback Handlers ---

    async def _on_engine_hud_text(self, payload: HudDrawTextPayload) -> None:
        """Dispatch HUD text rendering packet to wearable sockets."""
        packet = encode_message(MessageType.MSG_HUD_DRAW_TEXT, payload)
        await self.broadcast_binary(self.wearable_connections, packet, is_audio=False)

    async def _on_engine_hud_bitmap(self, payload: HudDrawBitmapPayload) -> None:
        """Dispatch HUD bitmap packet to wearable sockets."""
        packet = encode_message(MessageType.MSG_HUD_DRAW_BITMAP, payload)
        await self.broadcast_binary(self.wearable_connections, packet, is_audio=False)

    async def _on_engine_ambient_content(self, payload: AmbientDisplayPayload) -> None:
        """Dispatch rich ambient content packet to ambient screen sockets and wearable simulator."""
        packet = encode_message(MessageType.MSG_AMBIENT_DISPLAY_CONTENT, payload)
        await self.broadcast_binary(self.ambient_connections, packet, is_audio=False)
        await self.broadcast_binary(self.wearable_connections, packet, is_audio=False)

    async def _on_engine_audio_downlink(self, payload: AudioDownlinkPayload) -> None:
        """Asymmetrically route downlink audio based on destination."""
        packet = encode_message(MessageType.MSG_AUDIO_DOWNLINK, payload)
        self.total_downlink_bytes += len(payload.audio_data)

        if payload.destination == AudioDestination.AMBIENT_ROOM:
            # Route to external room speaker / ambient screen
            await self.broadcast_binary(self.ambient_connections, packet, is_audio=True)
        else:
            # Route to private USound MEMS speaker on wearable
            await self.broadcast_binary(self.wearable_connections, packet, is_audio=True)

    async def _on_engine_routing_change(self, payload: CrossSurfaceRoutingPayload) -> None:
        """Broadcast routing handoff event to all active endpoints."""
        self.active_surface_route = payload
        packet = encode_message(MessageType.MSG_CROSS_SURFACE_ROUTING, payload)
        await self.broadcast_binary(self.wearable_connections, packet, is_audio=False)
        await self.broadcast_binary(self.ambient_connections, packet, is_audio=False)

    async def broadcast_binary(self, sockets_or_conns: Any, data: bytes, is_audio: bool = False) -> None:
        """Broadcast binary TLV frame with queue protection (BUG-013, BUG-016)."""
        conns: List[ClientConnection] = []
        if isinstance(sockets_or_conns, dict):
            conns = list(sockets_or_conns.values())
        elif isinstance(sockets_or_conns, (set, list)):
            for item in list(sockets_or_conns):
                if isinstance(item, ClientConnection):
                    conns.append(item)
                elif isinstance(item, WebSocket):
                    conn = self.wearable_connections.get(item) or self.ambient_connections.get(item)
                    if conn:
                        conns.append(conn)
                    else:
                        try:
                            await item.send_bytes(data)
                        except Exception:
                            pass

        dead_conns = []
        for conn in conns:
            if not conn.is_active:
                dead_conns.append(conn)
                continue
            success = await conn.send(data, is_audio=is_audio)
            if not success and not conn.is_active:
                dead_conns.append(conn)

        for dc in dead_conns:
            self.wearable_connections.pop(dc.websocket, None)
            self.ambient_connections.pop(dc.websocket, None)

    def get_status(self) -> Dict[str, Any]:
        """Return gateway routing and connection status."""
        return {
            "wearable_connected": len(self.wearable_connections) > 0,
            "wearable_count": len(self.wearable_connections),
            "ambient_connected": len(self.ambient_connections) > 0,
            "ambient_count": len(self.ambient_connections),
            "current_display": self.active_surface_route.display_surface.value,
            "current_audio": self.active_surface_route.audio_destination.value,
            "routing_reason": self.active_surface_route.reason,
            "total_uplink_bytes": self.total_uplink_bytes,
            "total_downlink_bytes": self.total_downlink_bytes,
            "last_uplink_ts": self.last_uplink_ts,
            "last_roundtrip_latency_ms": self.last_roundtrip_latency_ms,
        }
