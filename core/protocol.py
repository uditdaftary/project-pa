"""Unified Type-Length-Value (TLV) Binary Framing Protocol for Project PA.

Standardizes communication across:
- WebSocket streams (Wearable Eyewear Simulator and Ambient Screen)
- Nordic nRF5340 / ESP32-S3 BLE GATT/L2CAP and Serial UART

Wire Format:
+---------------+---------------+---------------+-------------------+---------------------+----------------+-------------------+
| Magic (2B)    | Version (1B)  | Msg Type (1B) | Sequence (2B)     | Payload Length (4B) | CRC16 (2B)     | Payload (N bytes) |
| 0x50, 0x41    | 0x01          | 0x01 - 0x0A   | uint16 big-endian | uint32 big-endian   | uint16 (CCITT) | N bytes           |
+---------------+---------------+---------------+-------------------+---------------------+----------------+-------------------+
Header size: 12 bytes.
"""

from __future__ import annotations
import json
import struct
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    VpuVadEventType,
    GestureType,
    AudioUplinkPayload,
    AudioDownlinkPayload,
    HudDrawTextPayload,
    HudDrawBitmapPayload,
    ImuTelemetryPayload,
    VpuVadEventPayload,
    SystemControlPayload,
    CrossSurfaceRoutingPayload,
    AmbientDisplayPayload,
    HeartbeatPayload,
)

# Constants
MAGIC_BYTES = b"PA"
PROTOCOL_VERSION = 0x01
HEADER_FORMAT = ">2sBBHIH"  # magic (2s), version (B), msg_type (B), seq (H), length (I), crc16 (H)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 12 bytes
MAX_PAYLOAD_SIZE = 4 * 1024 * 1024  # 4 MB max payload safety limit


def compute_crc16(data: bytes) -> int:
    """Computes CRC-16-CCITT (poly 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class ProtocolError(Exception):
    """Base exception for protocol framing errors."""
    pass


class InvalidMagicError(ProtocolError):
    """Raised when magic header bytes do not match b'PA'."""
    pass


class CRCValidationError(ProtocolError):
    """Raised when frame CRC does not match."""
    pass


class PayloadTooLargeError(ProtocolError):
    """Raised when frame payload exceeds maximum safety threshold."""
    pass


def pack_tlv(msg_type: Union[int, MessageType], payload: bytes, seq: int = 0) -> bytes:
    """Packs raw bytes payload into standard 12-byte header TLV packet.
    
    CRC16 is computed over [version, msg_type, seq, length, payload].
    """
    msg_type_val = int(msg_type)
    payload_len = len(payload)
    if payload_len > MAX_PAYLOAD_SIZE:
        raise PayloadTooLargeError(f"Payload size {payload_len} exceeds limit of {MAX_PAYLOAD_SIZE}")

    # Build intermediate buffer for CRC calculation: version (1B) + msg_type (1B) + seq (2B) + len (4B) + payload
    crc_data = struct.pack(">BBHI", PROTOCOL_VERSION, msg_type_val, seq & 0xFFFF, payload_len) + payload
    crc = compute_crc16(crc_data)

    header = struct.pack(HEADER_FORMAT, MAGIC_BYTES, PROTOCOL_VERSION, msg_type_val, seq & 0xFFFF, payload_len, crc)
    return header + payload


def unpack_tlv(data: bytes, verify_crc: bool = True) -> Tuple[int, int, bytes]:
    """Unpacks a single complete TLV packet from bytes.
    
    Returns: (msg_type, seq, payload_bytes)
    Raises:
        ValueError if data is smaller than header or incomplete payload
        InvalidMagicError if magic bytes != b'PA'
        CRCValidationError if CRC16 check fails
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Data length {len(data)} is less than header size {HEADER_SIZE}")

    magic, version, msg_type, seq, payload_len, crc = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])

    if magic != MAGIC_BYTES:
        raise InvalidMagicError(f"Invalid magic bytes: expected {MAGIC_BYTES!r}, got {magic!r}")

    if payload_len > MAX_PAYLOAD_SIZE:
        raise PayloadTooLargeError(f"Packet payload length {payload_len} exceeds limit {MAX_PAYLOAD_SIZE}")

    total_len = HEADER_SIZE + payload_len
    if len(data) < total_len:
        raise ValueError(f"Incomplete packet: expected {total_len} bytes, got {len(data)}")

    payload = data[HEADER_SIZE:total_len]

    if verify_crc and crc != 0:
        crc_data = struct.pack(">BBHI", version, msg_type, seq, payload_len) + payload
        expected_crc = compute_crc16(crc_data)
        if crc != expected_crc:
            raise CRCValidationError(f"CRC mismatch: header={crc:#06x}, computed={expected_crc:#06x}")

    return msg_type, seq, payload


class TLVStreamParser:
    """Stateful stream parser for reassembling fragmented TLV packets from TCP/WebSocket streams."""

    def __init__(self, verify_crc: bool = True):
        self.buffer = bytearray()
        self.verify_crc = verify_crc

    def feed(self, chunk: bytes) -> List[Tuple[int, int, bytes]]:
        """Feed incoming stream bytes and return list of fully parsed (msg_type, seq, payload) tuples."""
        self.buffer.extend(chunk)
        packets = []

        while len(self.buffer) >= HEADER_SIZE:
            # Check magic bytes; if corrupted, slide forward by 1 byte until magic matches
            if self.buffer[0:2] != MAGIC_BYTES:
                magic_idx = self.buffer.find(MAGIC_BYTES)
                if magic_idx == -1:
                    # Keep at most 1 byte in case 'P' is the last byte
                    self.buffer = self.buffer[-1:] if self.buffer.endswith(b"P") else bytearray()
                    break
                else:
                    del self.buffer[:magic_idx]
                    if len(self.buffer) < HEADER_SIZE:
                        break

            # Parse header
            _, version, msg_type, seq, payload_len, crc = struct.unpack(HEADER_FORMAT, self.buffer[:HEADER_SIZE])

            if payload_len > MAX_PAYLOAD_SIZE:
                # Corrupted packet length, discard magic bytes and resync
                del self.buffer[:2]
                continue

            total_len = HEADER_SIZE + payload_len
            if len(self.buffer) < total_len:
                # Wait for more data
                break

            # Extract full frame
            frame = bytes(self.buffer[:total_len])
            del self.buffer[:total_len]

            payload = frame[HEADER_SIZE:]
            if self.verify_crc and crc != 0:
                crc_data = struct.pack(">BBHI", version, msg_type, seq, payload_len) + payload
                expected_crc = compute_crc16(crc_data)
                if crc != expected_crc:
                    # Corrupted frame or false sync: restore rest of frame after magic to buffer and resync
                    self.buffer = bytearray(frame[2:]) + self.buffer
                    continue

            packets.append((msg_type, seq, payload))

        return packets


# --- High-Level Typed Message Encoders and Decoders ---

def encode_message(
    msg_type: Union[int, MessageType],
    payload: Union[BaseModel, Dict[str, Any], bytes],
    seq: int = 0
) -> bytes:
    """Encodes a typed message object into a framed binary TLV packet."""
    if isinstance(payload, dict):
        try:
            mtype_enum = MessageType(int(msg_type))
            if mtype_enum == MessageType.MSG_AUDIO_UPLINK:
                payload = AudioUplinkPayload(**payload)
            elif mtype_enum == MessageType.MSG_AUDIO_DOWNLINK:
                payload = AudioDownlinkPayload(**payload)
            elif mtype_enum == MessageType.MSG_HUD_DRAW_BITMAP:
                payload = HudDrawBitmapPayload(**payload)
            elif mtype_enum == MessageType.MSG_HUD_DRAW_TEXT:
                payload = HudDrawTextPayload(**payload)
            elif mtype_enum == MessageType.MSG_IMU_TELEMETRY:
                payload = ImuTelemetryPayload(**payload)
            elif mtype_enum == MessageType.MSG_VPU_VAD_EVENT:
                payload = VpuVadEventPayload(**payload)
            elif mtype_enum == MessageType.MSG_SYSTEM_CONTROL:
                payload = SystemControlPayload(**payload)
            elif mtype_enum == MessageType.MSG_CROSS_SURFACE_ROUTING:
                payload = CrossSurfaceRoutingPayload(**payload)
            elif mtype_enum == MessageType.MSG_AMBIENT_DISPLAY_CONTENT:
                payload = AmbientDisplayPayload(**payload)
            elif mtype_enum == MessageType.MSG_HEARTBEAT:
                payload = HeartbeatPayload(**payload)
        except (ValueError, TypeError):
            pass

    if isinstance(payload, bytes):
        payload_bytes = payload
    elif msg_type == MessageType.MSG_AUDIO_UPLINK and isinstance(payload, AudioUplinkPayload):
        # Binary optimized packing:
        # sample_rate (H: uint16), channels (B: uint8), is_vpu (B: uint8), vpu_energy (f: float32) -> 8 bytes
        # followed by raw audio_data bytes
        header = struct.pack(">HBBf", payload.sample_rate, payload.channels, 1 if payload.is_vpu else 0, payload.vpu_energy)
        payload_bytes = header + payload.audio_data
    elif msg_type == MessageType.MSG_AUDIO_DOWNLINK and isinstance(payload, AudioDownlinkPayload):
        # sample_rate (H: uint16), channels (B: uint8), destination (B: 0=private_ear, 1=ambient_room), attenuation (f: float32) -> 8 bytes
        dest_val = 1 if payload.destination == AudioDestination.AMBIENT_ROOM else 0
        header = struct.pack(">HBBf", payload.sample_rate, payload.channels, dest_val, payload.attenuation_db)
        payload_bytes = header + payload.audio_data
    elif msg_type == MessageType.MSG_HUD_DRAW_BITMAP and isinstance(payload, HudDrawBitmapPayload):
        # x (H), y (H), width (H), height (H) -> 8 bytes
        header = struct.pack(">HHHH", payload.x, payload.y, payload.width, payload.height)
        payload_bytes = header + payload.bitmap_data
    else:
        # JSON serialized payloads
        if isinstance(payload, BaseModel):
            data_dict = payload.model_dump()
        else:
            data_dict = payload
        payload_bytes = json.dumps(data_dict).encode("utf-8")

    return pack_tlv(msg_type, payload_bytes, seq=seq)


def decode_message(msg_type: int, payload_bytes: bytes) -> Any:
    """Decodes raw payload bytes into the appropriate typed Pydantic model."""
    try:
        mtype = MessageType(msg_type)
    except ValueError:
        return payload_bytes

    if mtype == MessageType.MSG_AUDIO_UPLINK:
        if len(payload_bytes) >= 8:
            sample_rate, channels, is_vpu_raw, vpu_energy = struct.unpack(">HBBf", payload_bytes[:8])
            audio_data = payload_bytes[8:]
            return AudioUplinkPayload(
                sample_rate=sample_rate,
                channels=channels,
                is_vpu=bool(is_vpu_raw),
                vpu_energy=vpu_energy,
                audio_data=audio_data
            )
        else:
            # Fallback for JSON or raw
            try:
                data = json.loads(payload_bytes.decode("utf-8"))
                return AudioUplinkPayload(**data)
            except Exception:
                return AudioUplinkPayload(audio_data=payload_bytes)

    elif mtype == MessageType.MSG_AUDIO_DOWNLINK:
        if len(payload_bytes) >= 8:
            sample_rate, channels, dest_val, attenuation = struct.unpack(">HBBf", payload_bytes[:8])
            destination = AudioDestination.AMBIENT_ROOM if dest_val == 1 else AudioDestination.PRIVATE_EAR
            audio_data = payload_bytes[8:]
            return AudioDownlinkPayload(
                sample_rate=sample_rate,
                channels=channels,
                destination=destination,
                attenuation_db=attenuation,
                audio_data=audio_data
            )
        else:
            try:
                data = json.loads(payload_bytes.decode("utf-8"))
                return AudioDownlinkPayload(**data)
            except Exception:
                return AudioDownlinkPayload(audio_data=payload_bytes)

    elif mtype == MessageType.MSG_HUD_DRAW_BITMAP:
        if len(payload_bytes) >= 8:
            x, y, width, height = struct.unpack(">HHHH", payload_bytes[:8])
            bitmap_data = payload_bytes[8:]
            return HudDrawBitmapPayload(x=x, y=y, width=width, height=height, bitmap_data=bitmap_data)
        else:
            data = json.loads(payload_bytes.decode("utf-8"))
            return HudDrawBitmapPayload(**data)

    # JSON-decoded payloads
    text = payload_bytes.decode("utf-8")
    data = json.loads(text)

    if mtype == MessageType.MSG_HUD_DRAW_TEXT:
        return HudDrawTextPayload(**data)
    elif mtype == MessageType.MSG_IMU_TELEMETRY:
        return ImuTelemetryPayload(**data)
    elif mtype == MessageType.MSG_VPU_VAD_EVENT:
        return VpuVadEventPayload(**data)
    elif mtype == MessageType.MSG_SYSTEM_CONTROL:
        return SystemControlPayload(**data)
    elif mtype == MessageType.MSG_CROSS_SURFACE_ROUTING:
        return CrossSurfaceRoutingPayload(**data)
    elif mtype == MessageType.MSG_AMBIENT_DISPLAY_CONTENT:
        return AmbientDisplayPayload(**data)
    elif mtype == MessageType.MSG_HEARTBEAT:
        return HeartbeatPayload(**data)

    return data
