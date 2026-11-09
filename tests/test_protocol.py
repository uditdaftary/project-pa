"""Comprehensive Unit Tests for Core Protocol & TLV Framing."""

import pytest
import struct

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
from core.protocol import (
    MAGIC_BYTES,
    PROTOCOL_VERSION,
    HEADER_SIZE,
    pack_tlv,
    unpack_tlv,
    TLVStreamParser,
    encode_message,
    decode_message,
    compute_crc16,
    InvalidMagicError,
    CRCValidationError,
    PayloadTooLargeError,
)


def test_tlv_pack_unpack_roundtrip():
    payload = b"Hello MicroLED Eyebox!"
    msg_type = MessageType.MSG_HUD_DRAW_TEXT
    seq = 42

    packet = pack_tlv(msg_type, payload, seq=seq)
    assert len(packet) == HEADER_SIZE + len(payload)
    assert packet[:2] == MAGIC_BYTES

    unpacked_type, unpacked_seq, unpacked_payload = unpack_tlv(packet)
    assert unpacked_type == msg_type
    assert unpacked_seq == seq
    assert unpacked_payload == payload


def test_tlv_crc_validation_and_tampering():
    payload = b"Important control packet"
    packet = bytearray(pack_tlv(MessageType.MSG_SYSTEM_CONTROL, payload, seq=1))

    # Bit flip in payload
    packet[-1] ^= 0xFF

    with pytest.raises(CRCValidationError):
        unpack_tlv(bytes(packet), verify_crc=True)

    # If verify_crc is False, should unpack without error
    unpacked_type, _, unpacked_payload = unpack_tlv(bytes(packet), verify_crc=False)
    assert unpacked_type == MessageType.MSG_SYSTEM_CONTROL
    assert unpacked_payload != payload


def test_invalid_magic_bytes():
    bad_packet = b"XX\x01\x01\x00\x01\x00\x00\x00\x04\x00\x00test"
    with pytest.raises(InvalidMagicError):
        unpack_tlv(bad_packet)


def test_incomplete_packet():
    payload = b"Short payload"
    packet = pack_tlv(MessageType.MSG_HEARTBEAT, payload, seq=5)

    with pytest.raises(ValueError, match="less than header size"):
        unpack_tlv(packet[:5])

    with pytest.raises(ValueError, match="Incomplete packet"):
        unpack_tlv(packet[:-2])


def test_payload_too_large():
    too_big = b"x" * (4 * 1024 * 1024 + 1)
    with pytest.raises(PayloadTooLargeError):
        pack_tlv(MessageType.MSG_AUDIO_UPLINK, too_big)


def test_tlv_stream_parser_fragmentation():
    parser = TLVStreamParser()
    payload = b"Chunked telemetry stream"
    packet = pack_tlv(MessageType.MSG_IMU_TELEMETRY, payload, seq=100)

    # Feed 1 byte at a time
    results = []
    for i in range(len(packet)):
        chunk = packet[i:i+1]
        frames = parser.feed(chunk)
        results.extend(frames)

    assert len(results) == 1
    mtype, seq, rec_payload = results[0]
    assert mtype == MessageType.MSG_IMU_TELEMETRY
    assert seq == 100
    assert rec_payload == payload


def test_tlv_stream_parser_multiple_packets():
    parser = TLVStreamParser()
    p1 = pack_tlv(MessageType.MSG_HEARTBEAT, b"ping", seq=1)
    p2 = pack_tlv(MessageType.MSG_HEARTBEAT, b"pong", seq=2)

    frames = parser.feed(p1 + p2)
    assert len(frames) == 2
    assert frames[0] == (MessageType.MSG_HEARTBEAT, 1, b"ping")
    assert frames[1] == (MessageType.MSG_HEARTBEAT, 2, b"pong")


def test_tlv_stream_parser_resync_after_garbage():
    parser = TLVStreamParser()
    garbage = b"\xff\x00\xfe\x01GARBAGE_NOISE\xaa\xbb"
    valid_packet = pack_tlv(MessageType.MSG_SYSTEM_CONTROL, b"ok", seq=7)

    frames = parser.feed(garbage + valid_packet)
    assert len(frames) == 1
    assert frames[0] == (MessageType.MSG_SYSTEM_CONTROL, 7, b"ok")


def test_typed_audio_uplink_encoding():
    raw_pcm = b"\x00\x10\x20\x30" * 80  # 320 bytes = 160 int16 samples
    uplink = AudioUplinkPayload(
        sample_rate=16000,
        channels=1,
        is_vpu=True,
        vpu_energy=0.85,
        audio_data=raw_pcm
    )

    encoded = encode_message(MessageType.MSG_AUDIO_UPLINK, uplink, seq=10)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    assert mtype == MessageType.MSG_AUDIO_UPLINK
    assert seq == 10

    decoded: AudioUplinkPayload = decode_message(mtype, payload_bytes)
    assert isinstance(decoded, AudioUplinkPayload)
    assert decoded.sample_rate == 16000
    assert decoded.channels == 1
    assert decoded.is_vpu is True
    assert pytest.approx(decoded.vpu_energy, 0.01) == 0.85
    assert decoded.audio_data == raw_pcm


def test_typed_audio_downlink_encoding():
    raw_pcm = b"\x55\xaa" * 120
    downlink = AudioDownlinkPayload(
        sample_rate=24000,
        channels=1,
        destination=AudioDestination.AMBIENT_ROOM,
        attenuation_db=-6.0,
        audio_data=raw_pcm
    )

    encoded = encode_message(MessageType.MSG_AUDIO_DOWNLINK, downlink, seq=20)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: AudioDownlinkPayload = decode_message(mtype, payload_bytes)
    assert isinstance(decoded, AudioDownlinkPayload)
    assert decoded.sample_rate == 24000
    assert decoded.destination == AudioDestination.AMBIENT_ROOM
    assert pytest.approx(decoded.attenuation_db, 0.01) == -6.0
    assert decoded.audio_data == raw_pcm


def test_typed_hud_draw_text_encoding():
    hud_cmd = HudDrawTextPayload(
        x=20,
        y=40,
        text="Project PA Active: Sub-350ms Latency",
        font_size=14,
        clear_screen=True,
        color=1,
        teleprompter_mode=True
    )

    encoded = encode_message(MessageType.MSG_HUD_DRAW_TEXT, hud_cmd, seq=30)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: HudDrawTextPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, HudDrawTextPayload)
    assert decoded.x == 20
    assert decoded.y == 40
    assert decoded.text == "Project PA Active: Sub-350ms Latency"
    assert decoded.clear_screen is True
    assert decoded.teleprompter_mode is True


def test_typed_hud_draw_bitmap_encoding():
    # 640x200 1-bit bitmap is 16,000 bytes
    dummy_bitmap = bytes([0xAA] * 16000)
    bitmap_cmd = HudDrawBitmapPayload(
        x=0,
        y=0,
        width=640,
        height=200,
        bitmap_data=dummy_bitmap
    )

    encoded = encode_message(MessageType.MSG_HUD_DRAW_BITMAP, bitmap_cmd, seq=40)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: HudDrawBitmapPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, HudDrawBitmapPayload)
    assert decoded.width == 640
    assert decoded.height == 200
    assert decoded.bitmap_data == dummy_bitmap


def test_typed_imu_telemetry_encoding():
    imu = ImuTelemetryPayload(
        pitch=12.5,
        yaw=-45.0,
        roll=3.2,
        accel_x=0.1,
        accel_y=0.2,
        accel_z=9.8,
        gesture=GestureType.LOOK_AT_AMBIENT,
        gaze_vector=[0.707, 0.0, 0.707],
        gaze_confidence=0.95
    )

    encoded = encode_message(MessageType.MSG_IMU_TELEMETRY, imu, seq=50)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: ImuTelemetryPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, ImuTelemetryPayload)
    assert decoded.pitch == 12.5
    assert decoded.gesture == GestureType.LOOK_AT_AMBIENT
    assert len(decoded.gaze_vector) == 3


def test_typed_cross_surface_routing_encoding():
    routing = CrossSurfaceRoutingPayload(
        display_surface=DisplaySurface.CAST_AMBIENT,
        audio_destination=AudioDestination.AMBIENT_ROOM,
        reason="look_to_cast_triggered",
        confidence=0.98
    )

    encoded = encode_message(MessageType.MSG_CROSS_SURFACE_ROUTING, routing, seq=60)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: CrossSurfaceRoutingPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, CrossSurfaceRoutingPayload)
    assert decoded.display_surface == DisplaySurface.CAST_AMBIENT
    assert decoded.audio_destination == AudioDestination.AMBIENT_ROOM
    assert decoded.reason == "look_to_cast_triggered"


def test_typed_vpu_vad_event_encoding():
    vpu_ev = VpuVadEventPayload(
        event_type=VpuVadEventType.WHISPER_START,
        energy_level=0.72,
        confidence=0.99,
        timestamp_ms=1600000000
    )

    encoded = encode_message(MessageType.MSG_VPU_VAD_EVENT, vpu_ev, seq=70)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: VpuVadEventPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, VpuVadEventPayload)
    assert decoded.event_type == VpuVadEventType.WHISPER_START
    assert pytest.approx(decoded.energy_level, 0.01) == 0.72


def test_encode_message_from_dict_payload():
    """Verify encode_message converts raw dict payloads without TypeError on bytes."""
    # 1. Audio uplink dict with raw bytes
    dict_payload = {
        "sample_rate": 16000,
        "channels": 1,
        "is_vpu": True,
        "vpu_energy": 0.8,
        "audio_data": b"\x01\x02\x03\x04"
    }
    encoded = encode_message(MessageType.MSG_AUDIO_UPLINK, dict_payload, seq=80)
    mtype, seq, payload_bytes = unpack_tlv(encoded)
    decoded: AudioUplinkPayload = decode_message(mtype, payload_bytes)
    assert isinstance(decoded, AudioUplinkPayload)
    assert decoded.audio_data == b"\x01\x02\x03\x04"

    # 2. Audio downlink dict
    downlink_dict = {
        "sample_rate": 24000,
        "channels": 1,
        "destination": AudioDestination.AMBIENT_ROOM,
        "audio_data": b"\x05\x06"
    }
    encoded_dl = encode_message(MessageType.MSG_AUDIO_DOWNLINK, downlink_dict, seq=81)
    mtype_dl, _, pbytes_dl = unpack_tlv(encoded_dl)
    decoded_dl: AudioDownlinkPayload = decode_message(mtype_dl, pbytes_dl)
    assert decoded_dl.destination == AudioDestination.AMBIENT_ROOM


def test_stream_parser_crc_mismatch_resync():
    """Verify TLVStreamParser safely recovers when a corrupted frame with valid magic bytes is fed."""
    parser = TLVStreamParser(verify_crc=True)

    # Corrupt packet: valid magic + valid header length, but invalid CRC
    corrupt_packet = bytearray(pack_tlv(MessageType.MSG_HEARTBEAT, b"corrupted", seq=1))
    corrupt_packet[-1] ^= 0xFF  # Corrupt the payload without updating CRC

    # Valid packet immediately following
    valid_packet = pack_tlv(MessageType.MSG_HEARTBEAT, b"valid_recovery", seq=2)

    # Feed both
    frames = parser.feed(bytes(corrupt_packet) + valid_packet)
    assert len(frames) == 1
    assert frames[0] == (MessageType.MSG_HEARTBEAT, 2, b"valid_recovery")


def test_raw_bytes_audio_encoding_and_header_alignment():
    """Verify BUG-022 and BUG-007: raw bytes get 10-byte header and 22-byte offset alignment."""
    raw_audio = b"\x12\x34\x56\x78" * 40
    packet = encode_message(MessageType.MSG_AUDIO_UPLINK, raw_audio, seq=90)
    mtype, seq, payload_bytes = unpack_tlv(packet)
    decoded: AudioUplinkPayload = decode_message(mtype, payload_bytes)

    assert isinstance(decoded, AudioUplinkPayload)
    assert decoded.audio_data == raw_audio  # Full raw audio preserved, not truncated
    assert decoded.sample_rate == 16000
    assert decoded.channels == 1
    assert decoded.codec == "pcm_s16le"


def test_codec_preservation_opus_lc3():
    """Verify BUG-007: opus and lc3 codecs are preserved across binary TLV encoding."""
    for codec_name in ["opus", "lc3", "pcm_s16le"]:
        uplink = AudioUplinkPayload(
            sample_rate=16000,
            channels=1,
            codec=codec_name,
            audio_data=b"\xaa\xbb" * 20,
        )
        packet = encode_message(MessageType.MSG_AUDIO_UPLINK, uplink, seq=91)
        mtype, _, payload_bytes = unpack_tlv(packet)
        decoded: AudioUplinkPayload = decode_message(mtype, payload_bytes)
        assert decoded.codec == codec_name


def test_zero_crc_packet_validation_enforced():
    """Verify BUG-008: A frame with CRC 0x0000 that is invalid raises CRCValidationError."""
    payload = b"test_payload"
    packet = bytearray(pack_tlv(MessageType.MSG_HEARTBEAT, payload, seq=1))
    # Overwrite CRC in header (offset 10..12) with 0x0000
    packet[10] = 0
    packet[11] = 0

    with pytest.raises(CRCValidationError):
        unpack_tlv(bytes(packet), verify_crc=True)


def test_json_payload_in_audio_and_bitmap():
    """Verify BUG-009: JSON-encoded payload decoded correctly for audio and bitmap."""
    import json
    json_bytes = json.dumps({"sample_rate": 16000, "channels": 1, "codec": "opus", "audio_data": ""}).encode("utf-8")
    decoded = decode_message(MessageType.MSG_AUDIO_UPLINK, json_bytes)
    assert isinstance(decoded, AudioUplinkPayload)
    assert decoded.codec == "opus"

    json_bmp = json.dumps({"x": 5, "y": 10, "width": 100, "height": 50, "bitmap_data": ""}).encode("utf-8")
    decoded_bmp = decode_message(MessageType.MSG_HUD_DRAW_BITMAP, json_bmp)
    assert isinstance(decoded_bmp, HudDrawBitmapPayload)
    assert decoded_bmp.x == 5
    assert decoded_bmp.y == 10


def test_hud_draw_text_default_y_coord():
    """Verify BUG-017: Default y coordinate in HudDrawTextPayload is 20, not 0."""
    payload = HudDrawTextPayload(text="MicroLED")
    assert payload.y == 20

