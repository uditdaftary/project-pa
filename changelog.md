# Changelog: Project PA

All notable decisions, milestones, architectural transitions, and code changes are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] - 2026-11-09

### Added
- **Initial Repository Setup**: Initialized Git version control in `c:/Projects/PA`.
- **Project Governance & Memory**:
  - `memory.md`: Core system thesis, architecture decision records (ADR-001 through ADR-004), hardware topology roadmap, and open-source foundation references.
  - `agents.md`: Subagent registry defining roles, capabilities, and coordination protocols for orchestrator, software gateway, wearable OS, and research workers.
  - `changelog.md`: Continuous project journal.
- **Deep Technical Investigation Report**: Synthesized comprehensive 4-domain investigation covering:
  - JBD 0.13" MicroLED + Mitsui MR-7 diffractive waveguide optical modeling (>1,000 nits eye luminance).
  - USound Ganymede MEMS speaker + Tarvos 1.2 30Vpp Class-H boost amplifier with 20–24 dB dipole phase cancellation.
  - ST LIS25BA bone-conduction VPU for whisper-quiet and noise-immune voice input.
  - Maxim MAX77654 SIMO PMIC power tree respecting IEC 62368-1 43°C skin-contact safety ceiling.
  - End-to-end LiveKit Agents 1.x multimodal architecture achieving sub-320ms latency.
  - Scaled Bill of Materials ($149.20 at 10,000 units).

### Changed
- **Architectural Pivot (ADR-001)**: Per user directive, prioritized the **Software / Gateway / OS stack first** before hardware fabrication. Established hardware trajectory: **Developer Bench POC** first, followed by **Tier 3 Standalone Pocket Puck + Eyewear**.
- **Development Environment Selected (ADR-005)**: Selected **Dual-Platform Dev Gateway & Wearable Simulator**: Python LiveKit Agents 1.x backend + Web-based Wearable Simulator (HUD eyebox, simulated bone-conduction VPU, dipole speaker) + WebRTC Ambient Screen Receiver.
- **Hybrid Intelligence Architecture Selected (ADR-006)**: Adopted **Local-First Engine** directly adapting `C:\Projects\interactive-voice-agent` (Qwen 3.5 4B GGUF in 2.7GB VRAM, Moonshine Tiny CPU STT, PocketTTS CPU, sub-0.05ms atomic ring buffer) coupled with a **pluggable Cloud Realtime Bridge** (LiveKit Agents 1.x + Gemini Live / OpenAI Realtime) for sub-250ms native speech-to-speech and egocentric snapshot vision.
- **Unified Framing Protocol Selected (ADR-007)**: Established **Type-Length-Value (TLV) Protocol** (`0x50 0x41` magic bytes) unifying WebSocket (Simulator / Wi-Fi) and BLE GATT/L2CAP (Nordic / ESP32 hardware) with standardized message types for audio, display buffers, VPU resonance, and IMU gestures.
- **Repository Structure Adopted (ADR-008)**: Structured the workspace into `core/`, `agent_engine/`, `gateway/`, `simulator/`, `ambient_screen/`, and `tests/`.
- **Adversarial Quality & Competitive Resolution Protocol Established (ADR-009)**: Formulated 5-stage post-development pipeline: 4-agent scrutiny audit (`code-review-and-quality` + `bugs-are-annoying` -> `bugs.md`), 2 competing teams of 2 subagents formulating unified resolution proposals, Orchestrator solution synthesis, 4-agent fix execution, and GitHub issue/PR sync.
- **Implemented Full Software Stack Build Across 4 Core Streams**:
  - `core/`: Type-Length-Value (TLV) binary framing (`0x50 0x41` magic bytes, 12-byte header, CRC16 validation, streaming deserializer) and 10 typed message schemas in `core/protocol.py` and `core/messages.py`.
  - `agent_engine/`: Hybrid Agent Engine integrating `AudioRingBuffer` (sub-0.05ms atomic drain with 2ms half-cosine fadeout), `VoiceActivityDetector` (80Hz IIR high-pass, adaptive noise floor, ST LIS25BA VPU resonance fusion), `SentenceParser` (Unicode `\uE000` sentinel shielding), `CrossSurfaceRouter` (look-to-cast gaze alignment and asymmetric audio routing), and pluggable `LiveKitBridge`.
  - `gateway/`: FastAPI & WebSocket server (`gateway/server.py` and `gateway/audio_router.py`) managing `/ws/wearable`, `/ws/ambient`, and REST endpoints with binary TLV streaming dispatch.
  - `simulator/` & `ambient_screen/`: Interactive 640×200 monochrome green MicroLED HUD eyebox simulator (CRT scanlines, phosphor glow, ST LIS25BA push-to-whisper VPU trigger, 6-DoF IMU sliders) and fullscreen Ambient Screen cast receiver target.
  - `tests/`: 43 comprehensive unit and integration tests passing in 0.81s (`tests/test_protocol.py`, `tests/test_agent_engine.py`, `tests/test_gateway.py`, `tests/test_integration.py`, `tests/test_edge_cases.py`).
- **Adversarial Code Review & Bug Fixes (Expanded to 52 passing tests)**:
  - **Fatal CRC-16 Calculation Mismatch Fixed (`simulator/simulator.js`)**: Corrected contiguous slicing calculation in `simulator.js` which previously included header CRC bytes and truncated the payload, causing the gateway server to reject all simulator packets over WebSocket.
  - **Audio Ring Buffer 2D Callback Support (`agent_engine/local/ring_buffer.py`)**: Fixed `read_into` to safely broadcast mono narrative samples into 2D mono `(N, 1)` and stereo `(N, 2)` sounddevice/pyaudio playback callback buffers.
  - **Read-Only NumPy Array Safety**: Fixed `np.nan_to_num(..., copy=True)` in `AudioRingBuffer.write` and `VoiceActivityDetector._sanitize_audio` to prevent `ValueError: assignment destination is read-only`.
  - **Surface Route State Clobbering Fixed (`agent_engine/cloud/livekit_bridge.py` & `agent_engine/engine.py`)**: Modified AI callable tools so that updating display surface preserves current audio destination and vice versa.
  - **Live Microphone Audio Streaming Implemented (`simulator/simulator.js`)**: Connected `micToggleBtn` to Web Audio API `navigator.mediaDevices.getUserMedia`, streaming live 16kHz PCM audio packets with real-time RMS input metering.
  - **Dynamic Voice Query Intent & VAD Silence Hangover (`simulator/simulator.js` & `agent_engine/engine.py`)**: Enhanced voice simulation triggers to dispatch `MSG_SYSTEM_CONTROL` voice query intent followed by sufficient trailing silence (23 frames = 690ms) to reliably trigger VAD turn completion and multi-surface AI responses.
  - **Ambient Markdown Table Formatter Fixed (`ambient_screen/ambient.js`)**: Resolved duplicated raw table pipe markdown and generated balanced `<table><thead>...</thead><tbody>...</tbody></table>` DOM elements.
  - **Buffer Bounds Safety**: Added safety checks in `simulator.js` and `ambient.js` against truncated frame buffer allocations.
  - **Test Suite Expansion**: Added 9 new unit tests verifying 2D buffer playback, read-only arrays, non-clobbering routing, voice query intent, and Node.js-to-Python cross-language binary TLV CRC-16 CCITT compatibility (52 total passing tests in 1.21s).
- **Master Fix Execution across 4 Streams — 27 Bugs Resolved (64 Passing Tests)**:
  - **Stream 1: Protocol (`core/protocol.py`, `core/messages.py`)**:
    - **BUG-007 (Codec Preservation)**: Standardized on 10-byte binary header `>HBBBBf` encoding `codec_id` (`0=pcm_s16le`, `1=opus`, `2=lc3`) with explicit 22-byte 2-byte alignment for WebAudio `Int16Array` compatibility.
    - **BUG-008 (Strict CRC-16 Validation)**: Removed `and crc != 0` check in `unpack_tlv` and `TLVStreamParser.feed`, preventing corrupted packets with zero checksums from bypassing validation.
    - **BUG-009 (JSON Struct Unpack Collision)**: Added `payload_bytes.startswith(b"{")` guard in `decode_message()` to parse JSON audio and bitmap payloads safely before binary struct unpacking.
    - **BUG-017 (HUD Text Coordinate Default)**: Set default `y = 20` in `HudDrawTextPayload` and `ctx.textBaseline = "top"` in `simulator.js` to ensure text renders within visible eyebox bounds.
    - **BUG-022 (Raw Bytes Header Alignment)**: Automatically prepended the standard 10-byte binary header when packaging raw bytes in `encode_message()` to prevent sample stripping during decoding.
  - **Stream 2: Audio & VAD (`agent_engine/local/ring_buffer.py`, `agent_engine/local/vad.py`, `agent_engine/engine.py`, `agent_engine/cloud/livekit_bridge.py`)**:
    - **BUG-002 (Server Ring Buffer Playback Clock)**: Implemented autonomous 20ms `_playback_clock_task()` in `HybridAgentEngine` ticking `self.ring_buffer.read(samples_per_tick)` and clearing VAD playback active status when audio finishes.
    - **BUG-004 (Float DAC Normalization)**: Scaled samples by `1.0 / 32768.0` in `AudioRingBuffer._assign_out` when `np.issubdtype(outdata.dtype, np.floating)` for both main buffer and `fadeout_tail`, eliminating +84 dB digital overdrive.
    - **BUG-006 (Acoustic Echo Suppression Enablement)**: Sanitized reference signal in `VoiceActivityDetector.set_playback_active()` and passed reference samples when dispatching downlink audio to prevent self-interruption.
    - **BUG-015 (Sentence Accumulator Turn Flush)**: Removed premature `flush()` call after token feeding; sentence accumulator flushes completed sentences dynamically and flushes remaining fragments only on turn completion.
    - **BUG-020 (VAD Clamping Against Fixed Threshold)**: Enforced `threshold_dbfs = max(noise + snr, _fixed_threshold_dbfs)` across `__init__`, `reset()`, and `_evaluate_frame()` to prevent false triggers in ultra-quiet rooms.
    - **BUG-027 (LiveKit Bridge Audio Uplink)**: Implemented `send_audio_frame()` in `LiveKitBridge` and wired `await self.bridge.send_audio_frame()` into `process_audio_uplink`.
  - **Stream 3: Gateway & Router (`gateway/audio_router.py`, `gateway/server.py`, `agent_engine/router.py`)**:
    - **BUG-003 (Ambient Streaming Routing Condition)**: Fixed inverted routing condition in `engine.py` to route streaming text to ambient display when `recommended == CAST_AMBIENT or current == CAST_AMBIENT`.
    - **BUG-005 (Routing Origin Distinction)**: Added `RoutingOrigin.GAZE` and `RoutingOrigin.EXPLICIT_TOOL` in `CrossSurfaceRouter`; only gaze-initiated casts revert automatically to `PRIVATE_HUD` when looking away.
    - **BUG-013 & BUG-016 (Concurrent WebSocket Queue & Safe Unregistering)**: Implemented `ClientConnection` with outbound `asyncio.Queue` and background drain task per WebSocket. Selectively drops only `MSG_AUDIO_DOWNLINK` on queue overflow. Wrapped endpoints in `try / finally` calling unregister methods with explicit closure.
    - **BUG-014 (Async REST Override Route)**: Converted `override_route()` endpoint in `gateway/server.py` to `async def` to avoid cross-thread event loop instantiation.
    - **BUG-018 (Gateway Telemetry & Latency Metrics)**: Added `record_audio_uplink` and `record_heartbeat` in `GatewayAudioRouter`, computing accurate roundtrip latency and tracking active uplink timestamps.
    - **BUG-019 (Strict CORS Regex)**: Replaced insecure wildcard CORS with `allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"`.
    - **BUG-025 (Background Task Exception Logging)**: Added task done callback logging uncaught exceptions with full traceback in `_safe_dispatch()`.
  - **Stream 4: UI & Simulator (`simulator/simulator.js`, `ambient_screen/ambient.js`, `ambient_screen/index.html`, `ambient_screen/styles.css`)**:
    - **BUG-001 (Ambient HTML Sanitization)**: Added `escapeHtml()` in `ambient.js` and sanitized all dynamic markdown and card titles against stored XSS.
    - **BUG-010 (Simulator Mic Loopback Muting)**: Routed microphone processor node through a muted `GainNode(0.0)` connected to `destination` to prevent speaker feedback screeching.
    - **BUG-011 (Web Audio Downlink Timeline Cursor)**: Implemented `nextStartTime` timeline scheduling in both `simulator.js` and `ambient.js` with playback cursor reset on barge-in.
    - **BUG-012 (16kHz AudioContext Initialization)**: Explicitly configured `AudioContext({ sampleRate: 16000 })` in `simulator.js`.
    - **BUG-021 (Ambient Visualizer Divide-by-Zero Guard)**: Guarded spectrum bar step calculation with `Math.max(1, Math.floor(len / 40))` and cancelled previous spectrum timers.
    - **BUG-023 (Glance Away Yaw Angle)**: Adjusted "Glance Away" yaw angle in `simulator.js` to 65° (`cos(65°) = 0.4226 < 0.50`) to clear the deadband threshold.
    - **BUG-024 (Client Keepalive Heartbeat Interval)**: Added 15-second keepalive `MSG_HEARTBEAT` timer in both `simulator.js` and `ambient.js`.
    - **BUG-026 (Ambient Multi-Card Dashboard Tile Rendering)**: Added `#cardsGrid` dashboard container and rendered structured card tiles in `ambient.js` with responsive styling in `styles.css`.
  - **Test Suite Expansion**: Added 12 new comprehensive tests covering floating DAC scaling, fixed VAD threshold clamping, gaze vs explicit cast preservation, streaming accumulator turn flushing, raw byte 10-byte header packing, codec preservation, zero CRC packet enforcement, JSON struct collision prevention, and HUD text coordinate defaults (64 total passing tests).
- **Adversarial Audit & Robustness Hardening (Expanded to 72 Passing Tests)**:
  - **Protocol & Framing Hardening (`core/protocol.py`)**:
    - Extended `encode_message()` to transparently accept `bytearray` and `memoryview` without triggering JSON serialization `TypeError`.
    - Added whitespace tolerance (`payload_bytes.lstrip().startswith(b"{")`) to prevent JSON payloads with leading spaces/newlines from triggering binary struct unpack collisions.
  - **Audio Pipeline & VAD Safety (`agent_engine/engine.py`, `agent_engine/local/vad.py`)**:
    - Fixed `_handle_bridge_audio()` to safely pass raw downlink bytes directly to VAD without calling unpadded `np.frombuffer`, preventing fatal `ValueError` crashes on odd-length or compressed frames.
    - Decoupled `_playback_clock_task()` VAD deactivation check so that when the ring buffer is drained externally (or via barge-in), Acoustic Echo Suppression state is cleanly reset to `False`.
    - Removed premature `HudDrawTextPayload(text="", clear_screen=True)` dispatch on turn completion, ensuring the user can read the final response on the HUD until the next prompt.
  - **Gateway Concurrency & Lifecycle Protection (`gateway/audio_router.py`, `gateway/server.py`)**:
    - Added drain task liveness checks and an explicit 1.0s timeout to `ClientConnection.send()`, preventing broadcast loop deadlocks if a client stalls under heavy backpressure.
    - Added `try ... finally: await engine.shutdown()` to FastAPI `lifespan` manager, ensuring background tasks and bridge connections terminate cleanly on server shutdown.
  - **Wearable Simulator & Ambient Screen Hardening (`simulator/simulator.js`, `ambient_screen/ambient.js`)**:
    - Protected `Int16Array` construction in both `simulator.js` and `ambient.js` against odd byte offsets via sliced aligned buffer fallbacks, eliminating Web Audio `RangeError`.
    - Added JSON payload detection for `MSG_HUD_DRAW_BITMAP` in `simulator.js`, preventing struct unpack collisions on JSON bitmap commands.
    - Added `MSG_HEARTBEAT` echo pong handler in `ambient.js`, dynamically computing round-trip latency and updating `#latencyMetric`.
    - Reset Web Audio timeline cursor `nextStartTime` upon switching to standby in `ambient.js` to eliminate packet jitter drift.
  - **Test Suite Expansion**: Added 8 new automated unit and integration tests covering bytearray/memoryview encoding, whitespace JSON decoding, odd-length downlink audio, autonomous playback clock VAD reset, external drain reset, ClientConnection backpressure timeouts, and lifespan teardown (72 passing tests in 2.40s).
- **Gateway CLI Entrypoint & Clean Module Import (73 Passing Tests)**:
  - Added `if __name__ == "__main__":` entrypoint to [`gateway/server.py`](file:///c:/Projects/PA/gateway/server.py) invoking `uvicorn.run(...)` on configurable `PA_GATEWAY_HOST` and `PA_GATEWAY_PORT`.
  - Removed premature `from gateway.server import ...` from [`gateway/__init__.py`](file:///c:/Projects/PA/gateway/__init__.py), eliminating `<frozen runpy>:128: RuntimeWarning: 'gateway.server' found in sys.modules` and preventing auto-exit on startup.
  - Added `@app.get("/")` root redirect to `/simulator/` and regression test `test_root_redirect` in [`tests/test_gateway.py`](file:///c:/Projects/PA/tests/test_gateway.py).
- **Dual-Surface Real-Time Agent Turnaround, Eyebox Text Wrap & Ambient Mirror (74 Passing Tests)**:
  - **HUD Overlap Elimination**: Built multi-line auto-scrolling terminal engine with 590px word wrapping and clean line vertical layout (`y=32, 54, 76, 98, 120, 142`), eliminating text overlapping on the 640x200 MicroLED canvas.
  - **Live Ambient Screen Mirror in Simulator**: Embedded real-time Ambient Screen companion panel in [`simulator/index.html`](file:///c:/Projects/PA/simulator/index.html) and dual-broadcast `MSG_AMBIENT_DISPLAY_CONTENT` in [`gateway/audio_router.py`](file:///c:/Projects/PA/gateway/audio_router.py) so ambient mode works directly inside the simulator page.
  - **Gaze Anchor Real-World Neutral Default**: Initialized simulator `yaw` to 50° (real-world view / `PRIVATE_HUD`), requiring deliberate 0° gaze alignment or clicking "LOOK AT SCREEN (CAST)" to hand off to ambient mode.
  - **Interactive Dialogue Input**: Added text query input box allowing direct prompt submission alongside mic and simulated voice buttons.
  - **VAD Turn Completion Flush**: Fixed turn-completion flush in [`agent_engine/cloud/livekit_bridge.py`](file:///c:/Projects/PA/agent_engine/cloud/livekit_bridge.py) calling `on_text_output("")` and added two-tone audio chime (D5+A5).
  - **Mic Sensitivity Tuning**: Adjusted VAD baseline energy threshold to 120.0 (`-48.7 dBFS`) in [`agent_engine/local/vad.py`](file:///c:/Projects/PA/agent_engine/local/vad.py).
- **Voice Agent Coexistence & Dedicated Gateway Port (75 Passing Tests)**:
  - **Dedicated Port Default (8080)**: Configured Project PA to run on port `8080` by default with smart auto-binding (`find_available_port(8080)`), completely isolating it from `interactive-voice-agent` on port `8000` and enabling both servers to run simultaneously.
  - **`/ws` Coexistence Handler**: Added fallback WebSocket route `@app.websocket("/ws")` in [`gateway/server.py`](file:///c:/Projects/PA/gateway/server.py) accepting both binary TLV frames and voice agent JSON handshakes without returning `403 Forbidden`.
  - **Added Regression Test**: Added `test_websocket_coexistence_endpoint` in [`tests/test_gateway.py`](file:///c:/Projects/PA/tests/test_gateway.py).





