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
