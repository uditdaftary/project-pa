# Project Memory: Embodied Physical-First AI Agent Interface

**Project Codename:** Project PA (Physical Agent)  
**Repository:** `c:/Projects/PA`  
**Last Updated:** 2026-11-09  
**Status:** Software Architecture & OS/Gateway First Phase  

---

## 1. Project Thesis & Vision

Project PA creates a personalized, physical-first interface between a user and their autonomous AI agent. Unlike smartphones or laptops that trap artificial intelligence inside a 2D glass rectangle and force head-down posture, Project PA grounds the agent directly in the user's physical self through:
1. **Dynamic Visual Pipeline**: Private glanceable heads-up display (AR HUD) directly in the field of view with seamless, zero-friction handoff to ambient casting (WebRTC / Cast protocol) on traditional screens (smart TVs, monitors, tablets) for high-density visual tasks.
2. **Dynamic Acoustic Pipeline**: Private direct-to-ear dipole open-audio and bone-conduction voice pickup, with host-orchestrated runtime handoff to ambient room speakers.
3. **Physical Self Grounding**: Bone-conduction VPU for whisper-quiet voice activation immune to ambient airborne noise, 6-DoF/3-DoF IMU head micro-gestures, and look-to-cast gaze targeting.

---

## 2. Key Architecture Decisions Record (ADR)

### ADR-001: Execution Phasing — Software / Gateway / OS First
- **Decision:** Prioritize the full software stack, gateway, middleware OS, and real-time agent pipeline before entering custom hardware fabrication.
- **Hardware Follow-up:** Hardware stream begins with **Developer Bench POC** (modular off-the-shelf development boards), followed by **Tier 3 (Standalone Pocket Puck + Eyewear)** for phone-free operation.
- **Rationale:** Proving sub-350ms end-to-end latency, cross-surface visual/audio routing, and conversational reliability in software eliminates hardware rework risk and allows rapid iteration.

### ADR-002: Dynamic Cross-Surface Visual Routing
- **Private HUD Surface:** 640×200 monochrome high-contrast green HUD. Optimized for telemetry, teleprompter notes, and concise agent messages.
- **Ambient Screencast Surface:** Full-color 1080p/4K interactive React / WebRTC surface cast to external screens.
- **Trigger Mechanics:** Look-to-cast gaze alignment or agent decision via `@ai_callable` tool invocation (`set_display_surface`).

### ADR-003: Asymmetric Audio Routing & Whisper Grounding
- **Audio Uplink:** Always anchored to the wearable (dual Knowles PDM mics + ST LIS25BA bone-conduction VPU). Ensures only the wearer's vocalizations trigger the agent.
- **Audio Downlink:** Asymmetrically routed by companion host/gateway:
  - *Private Ear:* USound Ganymede MEMS speaker actuated via USound Tarvos 1.2 Class-H 30Vpp boost amplifier (20–24 dB dipole phase cancellation to eliminate bystander leakage).
  - *Ambient Room:* External Bluetooth A2DP speaker / Auracast BIS / smart speaker.

### ADR-004: Real-Time Multimodal Agent Core
- **Framework:** LiveKit Agents 1.x (`AgentSession`) with real-time speech-to-speech models (`inference.RealtimeModel` / OpenAI Realtime / Gemini Live).
- **Latency Budget:** Sub-320ms glass-to-agent conversational round-trip.

### ADR-005: Dual-Platform Dev Gateway & Wearable Simulator
- **Decision:** Build a full-stack local development and testing environment consisting of:
  1. `agent-core/`: Python LiveKit Agents 1.x backend with speech-to-speech engine and dynamic routing tools.
  2. `simulator/`: Interactive Web-based Wearable Simulator rendering the optical 640×200 green MicroLED HUD eyebox, simulating bone-conduction VPU / microphone audio input, and displaying private ear audio telemetry.
  3. `ambient-screen/`: WebRTC Ambient Screen Receiver that renders full-screen interactive React/HTML artifacts, diagrams, and media when the agent triggers ambient casting.
  4. `gateway/`: Local protocol bridge and media orchestrator managing WebRTC rooms, data channels, and asymmetric audio/display handoff.
- **Rationale:** Enables instant, zero-hardware end-to-end verification of the physical interface, conversational latency, and cross-surface handoff.

### ADR-006: Hybrid Agent Intelligence Engine (Local-First + Pluggable Cloud Bridge)
- **Decision:** Adopt a hybrid multi-tier intelligence architecture:
  1. **Local-First Baseline Engine ($0.00 operational cost)**: Derived directly from the proven stack in `C:\Projects\interactive-voice-agent`:
     - `audio/`: Sub-0.05ms atomic ring buffer with 2ms half-cosine micro-fadeout (click-free barge-in).
     - `vad/`: 80Hz IIR high-pass filter + DC blocker + dual-rate EMA adaptive noise floor estimator.
     - `stt/`: Sherpa-ONNX / Moonshine Tiny running on CPU (~210ms latency, 0 MB VRAM).
     - `llm/`: Local llama.cpp / Qwen 3.5 4B GGUF running in 2.7 GB VRAM (fits comfortably in 4 GB RTX 3050 Laptop GPU with 1.3 GB headroom).
     - `tts/`: PocketTTS running on CPU (~140ms chunk synthesis, 0 MB VRAM).
     - `parser/`: Sentence boundary tokenizer with Unicode `\uE000` sentinel shielding for streaming text cards to the 640×200 HUD.
  2. **Pluggable Cloud Multimodal Bridge**: LiveKit Agents 1.x `AgentSession` connecting to Google Gemini Live / OpenAI Realtime for sub-250ms native speech-to-speech and egocentric visual perception when cloud connectivity is active.
- **Rationale:** Guarantees 100% offline development, zero API cost during prototyping, and seamless escalation to cutting-edge multimodal vision models.

### ADR-007: Unified Binary/JSON Packet Framing Protocol
- **Decision:** Standardize on a unified Type-Length-Value (TLV) packet framing protocol sharing identical schemas across WebSocket (Simulator / Wi-Fi) and BLE GATT/L2CAP (future Nordic nRF5340 / ESP32 hardware):
  - Magic Bytes: `0x50` ('P'), `0x41` ('A')
  - Message Types:
    - `0x01` (`MSG_AUDIO_UPLINK`): 16kHz Opus/PCM frames from VPU + Knowles mic.
    - `0x02` (`MSG_AUDIO_DOWNLINK`): Audio output chunks to USound MEMS / Tarvos 1.2 amp.
    - `0x03` (`MSG_HUD_DRAW_TEXT`): Text layout commands (x, y, text, font, clear_flag).
    - `0x04` (`MSG_HUD_DRAW_BITMAP`): 1-bit monochrome 640×200 MicroLED display buffer tiles.
    - `0x05` (`MSG_IMU_TELEMETRY`): 6-DoF pitch, yaw, roll, nod/shake gestures, gaze vector.
    - `0x06` (`MSG_VPU_VAD_EVENT`): Bone-conduction vocal cord resonance trigger (whisper detection).
    - `0x07` (`MSG_SYSTEM_CONTROL`): Battery %, brightness, thermal telemetry, sleep/wake states.
    - `0x08` (`MSG_CROSS_SURFACE_ROUTING`): Display (`private_hud` / `cast_ambient`) and Audio (`private_ear` / `ambient_room`) destinations.
- **Rationale:** Ensures complete parity between software simulator and physical embedded hardware. Firmware drivers and UI layouts developed on the simulator run on hardware with zero protocol translation.

### ADR-008: Modular Monorepo Architecture
- **Decision:** Organize the software stack within a unified, cleanly decoupled monorepo:
  - `core/`: Shared protocol definitions, TLV binary packet packing/unpacking, typed schemas.
  - `agent_engine/`: Hybrid AI agent core (`local/` adapting `interactive-voice-agent` + `cloud/` LiveKit bridge).
  - `gateway/`: FastAPI + WebSocket/WebRTC media orchestrator and surface dispatcher.
  - `simulator/`: Optical 640×200 green MicroLED HUD eyebox, bone-conduction VPU simulation, and private ear telemetry.
  - `ambient_screen/`: Cast target receiver rendering rich full-screen React/Markdown artifacts.
  - `tests/`: Comprehensive unit tests for protocol serialization, audio routing, and latency benchmarks.
- **Rationale:** Minimizes multi-repo dependency drift, enables single-command startup, and guarantees protocol synchronization.

### ADR-009: Post-Sprint Multi-Team Adversarial Review & Competitive Resolution Protocol
- **Trigger:** Initiates automatically upon completion of the initial software development sprint.
- **Phase 1: Deep Scrutiny (Reviewer Team - max 4 subagents)**:
  - Guided by `/code-review-and-quality` (5-axis audit: Correctness, Readability, Architecture, Security, Performance) and `/bugs-are-annoying` (adversarial bug hunter across 14 bug taxonomies).
  - Outputs formal `bugs.md` with exact `file:line` references, triggers, impacts, and severity tiers (🔴 Critical, 🟡 Intermediate, 🟢 Normal).
- **Phase 2: Competitive Solution Synthesis (2 Independent Teams of 2 Subagents)**:
  - **Team Alpha** (2 agents) and **Team Beta** (2 agents) independently analyze the review findings.
  - Agents within each team debate and synthesize a united, cohesive architectural resolution strategy.
- **Phase 3: Orchestrator Evaluation & Selection**:
  - The Sole Orchestrator compares Team Alpha vs. Team Beta proposals, selects the superior technical fixes based on correctness, minimal blast radius, and performance, and formulates the Master Fix Plan.
- **Phase 4: Multi-Agent Fix Deployment & Verification**:
  - Deploy a specialized 4-agent fix team to apply the selected solutions, verify zero regressions via test suites, and update `bugs.md` with ✅ Resolved status.
- **Phase 5: GitHub Tracking**:
  - Post all identified issues and review comments directly to GitHub issues and pull requests via `gh` CLI.

---

## 3. Hardware Roadmap & Strategy

### Phase 1: Bench POC
- **Compute:** Seeed Studio XIAO BLE Sense (Nordic nRF52840) or ESP32-S3.
- **Audio:** USound Ganymede MEMS Speaker + Tarvos 1.2 Evaluation Board; ST LIS25BA VPU on breakout.
- **Display:** Brilliant Labs Monocle geometric prism module or 640×400 SPI micro-OLED.
- **Protocol:** Omi-style Opus-over-GATT (16kHz 16-bit mono) + WebRTC data channel.

### Phase 2: Standalone Pocket Puck + Eyewear (Tier 3)
- **Eyewear:** Ultra-lightweight (<38g) frame containing only micro-optics (JBD 0.13" MicroLED + Mitsui MR-7 SRG Waveguide), USound MEMS speakers, dual mics + VPU, and a thin micro-coax tether or ultra-low-power short-range link.
- **Pocket Puck:** Independent battery (4,000–5,000 mAh), 5G cellular modem, high-performance edge compute (Snapdragon 8 Gen 3 / Rockchip RK3588), Wi-Fi 7, and full-day 18+ hour continuous runtime with zero thermal dissipation on the head.

---

## 4. Open-Source Ecosystem Foundations

1. **[`Mentra-Community/SmartGlassesManager`](https://github.com/Mentra-Community/SmartGlassesManager)**:
   - Android foreground service maintaining resilient single-master BLE sockets, multiplexing UI cards and voice data to multiple smart glasses platforms.
2. **[`brilliantlabsAR/frame-codebase`](https://github.com/brilliantlabsAR/frame-codebase)**:
   - Ultra-low-power bare-metal Nordic architecture with embedded Lua interpreter, driving FPGA hardware-accelerated JPEG compression and display buffers.
3. **[`BasedHardware/omi`](https://github.com/BasedHardware/omi)**:
   - Proven Opus-over-GATT audio transport on nRF52840 bypassing mobile OS LE Audio developer restrictions.
4. **LiveKit Agents 1.x**:
   - WebRTC media routing, speech-to-speech agent session orchestration, and bidirectional data channels.
