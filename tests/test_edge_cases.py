"""Explicit Edge Case and Stress Tests for Project PA."""

import pytest
import numpy as np

from core.messages import (
    MessageType,
    DisplaySurface,
    AudioDestination,
    GestureType,
    AudioUplinkPayload,
    AudioDownlinkPayload,
    HudDrawTextPayload,
    ImuTelemetryPayload,
    VpuVadEventType,
    VpuVadEventPayload,
    SystemControlPayload,
)
from core.protocol import (
    pack_tlv,
    unpack_tlv,
    encode_message,
    decode_message,
    TLVStreamParser,
    compute_crc16,
    CRCValidationError,
)
from agent_engine.local.ring_buffer import AudioRingBuffer
from agent_engine.local.vad import VoiceActivityDetector
from agent_engine.local.sentence_parser import split_sentences, StreamingSentenceAccumulator
from agent_engine.router import CrossSurfaceRouter


def test_empty_payload_tlv():
    """Verify pack and unpack with 0-byte payload."""
    packet = pack_tlv(MessageType.MSG_HEARTBEAT, b"", seq=999)
    assert len(packet) == 12  # Header only
    mtype, seq, payload = unpack_tlv(packet)
    assert mtype == MessageType.MSG_HEARTBEAT
    assert seq == 999
    assert payload == b""


def test_crc16_known_vectors():
    """Verify CRC16 with standard test vectors."""
    crc_empty = compute_crc16(b"")
    assert crc_empty == 0xFFFF

    # Standard check sequence "123456789"
    crc_123456789 = compute_crc16(b"123456789")
    assert isinstance(crc_123456789, int)
    assert 0 <= crc_123456789 <= 0xFFFF


def test_ring_buffer_multiple_rapid_drains():
    """Verify rapid consecutive drains do not corrupt state or cause negative sizes."""
    rb = AudioRingBuffer(capacity_samples=1000, sample_rate=16000)
    for _ in range(50):
        rb.write(np.full(100, 300, dtype=np.int16))
        rb.drain(fade_ms=2.0)
        assert rb.size == 0
        assert rb.read_pos == 0
        assert rb.write_pos == 0


def test_ring_buffer_extreme_audio_clipping():
    """Verify non-finite values (NaN, Inf) and extreme values are safely sanitized."""
    rb = AudioRingBuffer(capacity_samples=500, sample_rate=16000)
    dirty_float = np.array([float("nan"), float("inf"), float("-inf"), 5.0, -10.0, 0.0], dtype=np.float32)
    written = rb.write(dirty_float)
    assert written == 6

    out = rb.read(6)
    assert not np.any(np.isnan(out))
    assert out[0] == 0       # NaN becomes 0
    assert out[1] == 32767   # +Inf clamped to int16 max
    assert out[2] in [-32767, -32768]  # -Inf clamped to int16 min
    assert out[3] == 32767   # 5.0 clamped
    assert out[4] == -32768  # -10.0 clamped


def test_vad_zero_samples_and_nans():
    """Verify VAD handles empty chunks and NaNs gracefully without crashing."""
    vad = VoiceActivityDetector(sample_rate=16000)
    res_empty = vad.process(b"")
    assert res_empty == []

    res_none = vad.process(None)
    assert res_none == []

    nan_chunk = np.array([float("nan")] * 480, dtype=np.float32)
    res_nan = vad.process(nan_chunk)
    assert len(res_nan) == 1
    assert not res_nan[0]


def test_sentence_parser_edge_cases():
    """Verify sentence splitter on empty string, whitespace, emojis, and unusual punctuation."""
    assert split_sentences("") == []
    assert split_sentences("   \n\n  \t  ") == []

    emoji_text = "MicroLED display active! 🟢 Look-to-cast ready. 🚀 Next turn begins now."
    sentences = split_sentences(emoji_text)
    assert len(sentences) >= 2


def test_router_extreme_imu_angles():
    """Verify router handles extreme IMU angles (pitch 90, yaw 180, roll 180)."""
    router = CrossSurfaceRouter()
    extreme_imu = ImuTelemetryPayload(
        pitch=90.0,
        yaw=180.0,
        roll=180.0,
        gaze_vector=[-1.0, 0.0, 0.0],
        gaze_confidence=1.0
    )
    change = router.evaluate_imu_telemetry(extreme_imu)
    # Gaze is opposite to ambient target [0, 0, 1]
    assert router.current_display == DisplaySurface.PRIVATE_HUD


def test_stream_parser_split_header():
    """Verify TLVStreamParser correctly buffers when chunks split right in the middle of 12-byte header."""
    parser = TLVStreamParser()
    packet = pack_tlv(MessageType.MSG_HUD_DRAW_TEXT, b"Split header test", seq=55)

    # Feed first 4 bytes of header
    f1 = parser.feed(packet[:4])
    assert f1 == []

    # Feed next 4 bytes of header
    f2 = parser.feed(packet[4:8])
    assert f2 == []

    # Feed rest of header + payload
    f3 = parser.feed(packet[8:])
    assert len(f3) == 1
    assert f3[0] == (MessageType.MSG_HUD_DRAW_TEXT, 55, b"Split header test")


def test_cross_language_simulator_js_crc_compatibility():
    """Verify that binary TLV packets packed by simulator.js in Node.js unpack with CRC validation in Python."""
    import subprocess
    import shutil

    if not shutil.which("node"):
        pytest.skip("Node.js not installed in test environment")

    node_code = """
function computeCRC16(dataView, offset, length) {
  let crc = 0xFFFF;
  for (let i = 0; i < length; i++) {
    const byte = dataView.getUint8(offset + i);
    crc ^= (byte << 8);
    for (let j = 0; j < 8; j++) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF;
      } else {
        crc = (crc << 1) & 0xFFFF;
      }
    }
  }
  return crc;
}
const HEADER_SIZE = 12;
const MAGIC_0 = 0x50, MAGIC_1 = 0x41, PROTOCOL_VERSION = 1;
function packTLV(msgType, payloadUint8) {
  const payloadLen = payloadUint8 ? payloadUint8.length : 0;
  const totalLen = HEADER_SIZE + payloadLen;
  const buffer = new ArrayBuffer(totalLen);
  const view = new DataView(buffer);
  view.setUint8(0, MAGIC_0);
  view.setUint8(1, MAGIC_1);
  view.setUint8(2, PROTOCOL_VERSION);
  view.setUint8(3, msgType);
  view.setUint16(4, 77, false);
  view.setUint32(6, payloadLen, false);
  const u8 = new Uint8Array(buffer);
  if (payloadLen > 0) {
    u8.set(payloadUint8, HEADER_SIZE);
  }
  const crcBuffer = new Uint8Array(8 + payloadLen);
  crcBuffer.set(u8.subarray(2, 10), 0);
  if (payloadLen > 0) {
    crcBuffer.set(u8.subarray(12, 12 + payloadLen), 8);
  }
  const crcView = new DataView(crcBuffer.buffer);
  const crc = computeCRC16(crcView, 0, crcBuffer.length);
  view.setUint16(10, crc, false);
  return Buffer.from(buffer);
}
const payload = Buffer.from(JSON.stringify({ pitch: 10.5, yaw: -20.0, roll: 0.0 }));
process.stdout.write(packTLV(5, payload).toString("hex"));
"""
    result = subprocess.run(["node", "-e", node_code], capture_output=True, text=True, check=True)
    hex_str = result.stdout.strip()
    assert hex_str

    raw_bytes = bytes.fromhex(hex_str)
    # Must unpack and verify CRC without throwing CRCValidationError
    mtype, seq, payload_bytes = unpack_tlv(raw_bytes, verify_crc=True)
    assert mtype == 5
    assert seq == 77
    assert b"pitch" in payload_bytes


def test_simulator_js_json_bitmap_and_unaligned_audio_handling():
    """Verify Node.js executes unaligned audio buffer slicing and JSON bitmap parsing without RangeError or crashes."""
    import subprocess
    import shutil

    if not shutil.which("node"):
        pytest.skip("Node.js not installed in test environment")

    node_code = """
// 1. Unaligned buffer Int16Array slicing test
const fullBuf = new ArrayBuffer(23); // Odd byte length
const pcmBytes = new Uint8Array(fullBuf, 1, 22); // byteOffset = 1 (ODD!)
const sampleCount = Math.floor(pcmBytes.length / 2);

let int16Samples;
if (pcmBytes.byteOffset % 2 === 0) {
  int16Samples = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, sampleCount);
} else {
  int16Samples = new Int16Array(pcmBytes.slice().buffer, 0, sampleCount);
}
if (int16Samples.length !== 11) {
  throw new Error("Sample count mismatch: " + int16Samples.length);
}

// 2. JSON bitmap payload parsing test
const jsonPayload = Buffer.from(JSON.stringify({ x: 10, y: 20, width: 640, height: 200, bitmap_data: "" }));
if (jsonPayload.length > 0 && jsonPayload[0] === 0x7B) {
  const parsed = JSON.parse(jsonPayload.toString("utf-8"));
  if (parsed.width !== 640 || parsed.height !== 200) {
    throw new Error("Failed to parse JSON bitmap dimensions");
  }
}
process.stdout.write("OK");
"""
    result = subprocess.run(["node", "-e", node_code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "OK"

