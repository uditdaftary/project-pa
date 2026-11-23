# Bug Report — Project PA — 2026-11-09

## Summary
- Critical: 0 open, 8 fixed
- Intermediate: 0 open, 11 fixed
- Normal: 0 open, 8 fixed
- Total: 0 open, 27 fixed

---

## 🔴 Critical

### BUG-001: Stored XSS in Ambient Screen Receiver via Unescaped Markdown HTML
- **File:** `ambient_screen/ambient.js:168`
- **Issue:** `renderAmbientContent()` injects unescaped HTML directly via `contentBody.innerHTML = formatMarkdown(data.content)`. `formatMarkdown()` only handles specific markdown syntax and fails to HTML-escape raw `<script>`, `<img src=x onerror=...>`, or other HTML tags.
- **Trigger:** Agent or external participant sending a markdown payload containing malicious HTML tags or script attributes.
- **Impact:** Arbitrary JavaScript execution in the ambient screen browser context, with access to WebSockets and local storage.
- **Suggested Fix:** Sanitize input by HTML-encoding `<` and `>` before applying markdown regexes, or use `DOMPurify.sanitize()`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Added `escapeHtml()` in `ambient_screen/ambient.js` and sanitized all dynamic markdown and card titles before regex formatting.

### BUG-002: Audio Ring Buffer Server Leak & Permanent False Barge-In Deadlock
- **File:** `agent_engine/engine.py:140`
- **Issue:** Downlink audio chunks are written to `self.ring_buffer.write(downlink.audio_data)`, but `read()` or `read_into()` is never called anywhere on the server during runtime. As a result, `ring_buffer.size` grows to capacity and `is_actively_playing()` evaluates to `True` forever.
- **Trigger:** Any agent voice downlink playback.
- **Impact:** Once the agent speaks once, `is_actively_playing()` is permanently locked to `True`, causing any subsequent ambient audio or microphone noise to trigger an immediate barge-in drain. Furthermore, `playhead_seconds` is stuck at `0.0s`.
- **Suggested Fix:** Drain the server-side ring buffer with an asynchronous real-time consumer task, or drive playback state based on client playback ACK packets over WebSocket.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Implemented autonomous 20ms `_playback_clock_task()` in `HybridAgentEngine` ticking `self.ring_buffer.read(samples_per_tick)` and resetting VAD playback active status upon completion.

### BUG-003: Inverted Routing Condition Diverting Ambient Streaming Text to HUD
- **File:** `agent_engine/engine.py:117`
- **Issue:** In `_handle_bridge_text()`, the routing condition is:
  `if recommended_surface == DisplaySurface.CAST_AMBIENT and self.router.current_display != DisplaySurface.CAST_AMBIENT:`
  When the display is already in `CAST_AMBIENT`, the condition evaluates to `False`, dropping into the `else` branch which dispatches a `HudDrawTextPayload` with `clear_screen=True`.
- **Trigger:** Streaming agent text when the display is in `CAST_AMBIENT` mode.
- **Impact:** All streaming text in ambient mode is diverted to the 640×200 MicroLED HUD instead of the ambient screen, repeatedly clearing the wearable display.
- **Suggested Fix:** Change condition to `if recommended_surface == DisplaySurface.CAST_AMBIENT or self.router.current_display == DisplaySurface.CAST_AMBIENT:`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Fixed routing condition to check `recommended_surface == DisplaySurface.CAST_AMBIENT or self.router.current_display == DisplaySurface.CAST_AMBIENT`.

### BUG-004: Float DAC Clipping (+84 dB Overdrive) in `AudioRingBuffer.read_into`
- **File:** `agent_engine/local/ring_buffer.py:205-228`
- **Issue:** When `read_into(outdata)` is called with floating-point audio buffers (`float32` or `float64`), it assigns raw `int16` values (up to 32767.0) directly into `outdata` without normalizing by `32768.0`. The same bug exists in the `fadeout_tail` assignment on line 228.
- **Trigger:** Audio output callbacks using standard floating-point audio buffers (e.g., PyAudio / SoundDevice / WebAudio).
- **Impact:** Severe acoustic distortion, extreme clipping (+84 dB digital overdrive), and potential speaker damage.
- **Suggested Fix:** Divide integer samples by `32768.0` whenever `np.issubdtype(outdata.dtype, np.floating)`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Scaled samples by `1.0 / 32768.0` in `_assign_out` when `np.issubdtype(outdata.dtype, np.floating)` for both ring buffer data and `fadeout_tail`.

### BUG-005: Unconditional IMU Gaze-Away Destroys Intentional Ambient Casts
- **File:** `agent_engine/router.py:118-122`
- **Issue:** `evaluate_imu_telemetry()` unconditionally reverts `current_display` to `DisplaySurface.PRIVATE_HUD` whenever `dot_prod < (ambient_gaze_threshold - 0.25)`. It does not distinguish whether `CAST_AMBIENT` was triggered by gaze alignment or by an explicit tool call (`set_display_surface`).
- **Trigger:** Looking away from the screen after an explicit command or tool call to cast.
- **Impact:** Looking away from the TV immediately destroys the cast session, even when the user deliberately wants a dashboard left on the TV while looking elsewhere.
- **Suggested Fix:** Maintain a `cast_origin: str` ("gaze" vs "explicit_tool"). Only revert automatically if the cast origin was "gaze".
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Introduced `RoutingOrigin` enum (`GAZE` vs `EXPLICIT_TOOL`) in `agent_engine/router.py`. Only gaze-initiated casts auto-revert upon looking away.

### BUG-006: Inoperative Acoustic Echo Suppression (AES) Causing Self-Interruption
- **File:** `agent_engine/engine.py:140` & `agent_engine/local/vad.py:94`
- **Issue:** `vad.set_playback_active(True)` is never called when agent audio playback begins. It is only called with `False` on line 179 after playback.
- **Trigger:** Any agent voice playback while the microphone is active.
- **Impact:** Acoustic Echo Suppression is completely disabled. Downlink audio playing through speakers leaks into the microphone and triggers false speech detection, immediately cutting off the agent's own voice.
- **Suggested Fix:** Call `self.vad.set_playback_active(True)` when downlink audio is dispatched to the wearable or room speaker.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Invoked `self.vad.set_playback_active(True, reference_signal=ref_samples)` upon receiving downlink audio, and sanitized `reference_signal` via `_sanitize_audio`.

### BUG-022: Raw Byte Payloads in `encode_message` Silently Stripped by `decode_message`
- **File:** `core/protocol.py:223-230` & `core/protocol.py:258-268`
- **Issue:** When a caller encodes raw `bytes` via `encode_message(MessageType.MSG_AUDIO_UPLINK, raw_bytes)`, line 223 packages `payload_bytes = payload` without an 8-byte binary header. However, `decode_message()` unconditionally assumes the first 8 bytes are `>HBBf` header fields if `len >= 8`.
- **Trigger:** Transmitting raw audio PCM bytes over TLV without wrapping in an `AudioUplinkPayload` instance.
- **Impact:** Permanent loss of the first 8 bytes (4 audio samples) of every frame, and corruption of sample rate, channel count, and VPU metadata.
- **Suggested Fix:** Always prepend the 8-byte binary header when packing raw bytes in `encode_message`, or use a distinct message flag / header structure.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Prepend standard 10-byte binary header in `encode_message()` when packaging raw bytes for audio uplink and downlink.

### BUG-027: LiveKit Bridge Audio Uplink is a Dead Stub
- **File:** `agent_engine/cloud/livekit_bridge.py:117-124`
- **Issue:** `LiveKitBridge.send_audio_frame()` contains only a `pass` statement:
  ```python
  async def send_audio_frame(self, pcm_bytes: bytes, is_vpu: bool = False, vpu_energy: float = 0.0) -> None:
      if not self.is_connected:
          return
      pass
  ```
- **Trigger:** Running in `livekit_mode="livekit"` with active LiveKit cloud credentials.
- **Impact:** Uplink audio is silently dropped and never forwarded to LiveKit Agents 1.x or speech models.
- **Suggested Fix:** Implement audio publishing using `LocalAudioTrack` / `rtc.AudioFrame` or LiveKit data channels.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Implemented `send_audio_frame()` in `LiveKitBridge` and wired `await self.bridge.send_audio_frame()` into `HybridAgentEngine.process_audio_uplink`.

---

## 🟡 Intermediate

### BUG-007: Binary TLV Framing Discards `codec` Field
- **File:** `core/protocol.py:229-235`
- **Issue:** `AudioUplinkPayload` and `AudioDownlinkPayload` include `codec: str = "pcm_s16le"`. Binary struct packing `>HBBf` omits this field, causing decoded payloads to always default to `"pcm_s16le"`.
- **Trigger:** Transmitting Opus or LC3 encoded audio packets.
- **Impact:** Breaks transparent audio pass-through for Opus-over-GATT (ADR-003, ADR-007).
- **Suggested Fix:** Add a 1-byte codec enum to the binary header (e.g. `0=pcm_s16le`, `1=opus`, `2=lc3`).
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Standardized on 10-byte binary header `>HBBBBf` encoding `codec_id` (`0=pcm_s16le`, `1=opus`, `2=lc3`), ensuring 22-byte 2-byte aligned WebAudio offset.

### BUG-008: CRC-16 Checksum Validation Bypassed for Zero Checksums
- **File:** `core/protocol.py:124, 176`
- **Issue:** `if verify_crc and crc != 0:` skips verification if the CRC field in the packet evaluates to `0x0000`.
- **Trigger:** Any corrupted packet with CRC bytes equal to `0x0000`.
- **Impact:** Corrupted frames bypass validation.
- **Suggested Fix:** Remove `and crc != 0` check.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Removed `and crc != 0` check from `unpack_tlv()` and `TLVStreamParser.feed()`.

### BUG-009: Binary Struct Unpack Collision on JSON Audio and Bitmap Payloads
- **File:** `core/protocol.py:259, 278, 298`
- **Issue:** `decode_message()` attempts binary struct unpack if `len >= 8` without checking if the payload is JSON formatted. JSON strings longer than 8 bytes unpack garbage values before failing.
- **Trigger:** Sending JSON-serialized audio or bitmap messages.
- **Impact:** Incorrect decoding and unexpected field values.
- **Suggested Fix:** Check the packet flags or check if payload begins with `{` before binary struct unpacking.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Added `payload_bytes.startswith(b"{")` check in `decode_message()` to parse JSON payloads safely before binary struct unpacking.

### BUG-010: Eyewear Simulator Direct Mic Output Feedback Loop
- **File:** `simulator/simulator.js:497`
- **Issue:** `micProcessor.connect(audioCtx.destination)` pipes live microphone input directly to the computer's speakers.
- **Trigger:** Clicking "Enable Mic Input" in the simulator.
- **Impact:** Immediate acoustic feedback screech and echo.
- **Suggested Fix:** Remove `micProcessor.connect(audioCtx.destination)`. The processor only needs to stream samples over WebSocket, not play locally.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Connected `micProcessor` through a muted `GainNode(0.0)` connected to `destination` to allow Web Audio processing without acoustic feedback.

### BUG-011: Web Audio Downlink Playback Lacks Timeline Scheduling
- **File:** `simulator/simulator.js:310` & `ambient_screen/ambient.js:210`
- **Issue:** Audio chunks invoke `source.start(0)` immediately upon receipt. Jitter in network packet arrival causes audio chunks to overlap or play with stuttering gaps.
- **Trigger:** Streaming continuous audio chunks over WebSocket.
- **Impact:** Choppy playback and acoustic artifacts.
- **Suggested Fix:** Maintain a `nextStartTime` cursor: `nextStartTime = Math.max(audioCtx.currentTime, nextStartTime); source.start(nextStartTime); nextStartTime += buffer.duration;`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Implemented `nextStartTime` timeline scheduling in both `simulator.js` and `ambient.js`, and added playback reset on barge-in.

### BUG-012: Simulator Microphone Sends 48kHz Audio Labeled as 16kHz
- **File:** `simulator/simulator.js:451, 476`
- **Issue:** `audioCtx = new AudioContext()` runs at system native sample rate (48kHz/44.1kHz), but the packet header hardcodes `sampleRate = 16000`.
- **Trigger:** Using live microphone input in the simulator.
- **Impact:** Audio playback is pitched down 3x and plays in slow motion.
- **Suggested Fix:** Initialize `new AudioContext({ sampleRate: 16000 })` or resample in the script processor.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Explicitly initialized `AudioContext({ sampleRate: 16000 })` in `simulator.js`.

### BUG-013: Unsynchronized Concurrent `ws.send_bytes()` on Starlette WebSockets
- **File:** `gateway/audio_router.py:120-125`
- **Issue:** `ws.send_bytes()` is called concurrently across multiple asyncio tasks without synchronization locks.
- **Trigger:** High-frequency audio packets sent simultaneously with telemetry or display updates.
- **Impact:** Starlette / Uvicorn raises `RuntimeError: Cannot call "send" concurrently for a single connection`.
- **Suggested Fix:** Wrap client connections in an `asyncio.Lock()` or use an outbound message queue.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Implemented `ClientConnection` with a dedicated `asyncio.Queue` and single-task drain loop per WebSocket, selectively dropping only audio frames under backpressure.

### BUG-014: Cross-Thread Event Loop Instantiation in Synchronous REST Endpoint
- **File:** `agent_engine/engine.py:94-99` & `gateway/server.py:110`
- **Issue:** `override_route()` is declared as synchronous `def`, causing FastAPI to execute it in a separate threadpool worker. `_safe_dispatch()` creates a new disposable event loop, invoking `ws.send_bytes()` cross-thread on WebSockets bound to the main ASGI event loop.
- **Trigger:** Calling `POST /route`.
- **Impact:** Event loop conflicts and potential thread crashes.
- **Suggested Fix:** Change `override_route()` to `async def` and dispatch on the running ASGI loop.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Declared `override_route()` as `async def` in `gateway/server.py`.

### BUG-023: Simulator "Glance Away" Button Fails Due to Deadband Zone
- **File:** `simulator/simulator.js:411-416` & `agent_engine/router.py:118`
- **Issue:** The simulator's "Glance Away" button sets `yaw = 45°` (`dot_prod = cos(45°) = 0.7071`). The router's reversion condition requires `dot_prod < (0.75 - 0.25) = 0.50`. Since `0.7071 >= 0.50`, the router stays in the deadband and never reverts.
- **Trigger:** Clicking "Glanced away from screen" in the simulator.
- **Impact:** The button does nothing; the screen remains in `CAST_AMBIENT` mode.
- **Suggested Fix:** Set `yaw = 65°` in `glanceAwayBtn` (`cos(65°) = 0.4226 < 0.50`), or adjust deadband thresholds.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Updated `glanceAwayBtn` yaw to 65° in `simulator.js` (`cos(65°) = 0.4226 < 0.50`).

### BUG-025: Unhandled Background Task Exceptions in `_safe_dispatch`
- **File:** `agent_engine/engine.py:93`
- **Issue:** `loop.create_task(res)` creates background tasks without error callbacks or exception logging.
- **Trigger:** Any exception raised inside listener callbacks (e.g. disconnected socket).
- **Impact:** Silent failures and unhandled coroutine warnings.
- **Suggested Fix:** Add `task.add_done_callback(_log_task_exception)`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Added `task.add_done_callback(_log_exc)` logging uncaught exceptions with full traceback.

### BUG-019: Insecure CORS Wildcard Combined With `allow_credentials=True`
- **File:** `gateway/server.py:62-65`
- **Issue:** `CORSMiddleware` configured with `allow_origins=["*"]` and `allow_credentials=True`.
- **Trigger:** Browser security evaluation.
- **Impact:** Violates W3C CORS specifications and fails in strict browser environments.
- **Suggested Fix:** Remove `allow_credentials=True` or specify explicit local origin list.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Replaced wildcard origin with `allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"`.

---

## 🟢 Normal

### BUG-015: Streaming Sentence Accumulator Flushed Prematurely
- **File:** `agent_engine/engine.py:122-123`
- **Issue:** `feed()` is immediately followed by `flush()`, flushing text cards on every incoming token rather than waiting for sentence boundaries.
- **Trigger:** Streaming token generation.
- **Impact:** Defeats the purpose of the sentence accumulator.
- **Suggested Fix:** Fix `StreamingSentenceAccumulator.feed()` to properly emit complete sentences and only call `flush()` on turn completion.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Removed premature `flush()` from token feeding loop; accumulator flushes only upon turn completion.

### BUG-016: Disconnected WebSockets Discarded Without Explicit Closure
- **File:** `gateway/audio_router.py:126-127`
- **Issue:** Broken WebSockets are removed from client lists without calling `await ws.close()`.
- **Trigger:** Client network disconnection.
- **Impact:** Leaves socket resources dangling until GC.
- **Suggested Fix:** Ensure `await ws.close()` is called in a try/finally block.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Wrapped WebSocket endpoints in `try / finally` calling `unregister_wearable` / `unregister_ambient`, which explicitly closes sockets.

### BUG-017: Default `y = 0` in `HudDrawTextPayload` Renders Text Off-Screen
- **File:** `core/messages.py:81`
- **Issue:** Default `y = 0` places text baseline at the top edge of the canvas, rendering text off-screen.
- **Trigger:** Using default `y` in `HudDrawTextPayload`.
- **Impact:** Text is invisible on the HUD.
- **Suggested Fix:** Default `y = 20` or set canvas `textBaseline = "top"`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Changed default `y = 20` in `HudDrawTextPayload` and set `ctx.textBaseline = "top"` in `simulator.js`.

### BUG-018: Gateway Telemetry Latency and Uplink Variables Never Updated
- **File:** `gateway/audio_router.py:44-45`
- **Issue:** `last_uplink_ts` and `last_roundtrip_latency_ms` are initialized but never assigned.
- **Trigger:** Reading telemetry.
- **Impact:** Telemetry reports static initial values.
- **Suggested Fix:** Update timestamps upon receiving `MSG_AUDIO_UPLINK` and calculate roundtrip latency.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Implemented `record_audio_uplink` and `record_heartbeat` in `GatewayAudioRouter`, tracking timestamps and roundtrip latency.

### BUG-020: VAD Noise Floor Reset and Speech Evaluation Drop Fixed Threshold
- **File:** `agent_engine/local/vad.py:73, 110, 267`
- **Issue:** `reset()` and speech evaluation omit clamping against `_fixed_threshold_dbfs`.
- **Trigger:** Extremely quiet environments.
- **Impact:** Threshold can drop too low, causing false positive speech triggers.
- **Suggested Fix:** Ensure `threshold_dbfs = max(noise_floor_dbfs + snr_margin_db, _fixed_threshold_dbfs)`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Clamped `threshold_dbfs` against `_fixed_threshold_dbfs` across `__init__`, `reset()`, and `_evaluate_frame()`.

### BUG-021: Ambient Visualizer Division by Zero for Chunks Under 40 Samples
- **File:** `ambient_screen/ambient.js:218-228`
- **Issue:** `Math.floor(len / 40)` yields 0 if `len < 40`, and overlapping `setTimeout` timers cause visualizer flickering.
- **Trigger:** Small audio chunks.
- **Impact:** Visualizer glitches and flickering.
- **Suggested Fix:** Ensure `step = Math.max(1, Math.floor(len / 40))` and cancel pending timers.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Guarded step calculation with `Math.max(1, Math.floor(len / 40))` and cancelled previous spectrum timeout timers.

### BUG-024: Complete Absence of Client-Side Heartbeat Keepalive Timers
- **File:** `simulator/simulator.js:21` & `ambient_screen/ambient.js:15`
- **Issue:** `MSG_HEARTBEAT` handlers exist, but neither client sends heartbeat pings periodically.
- **Trigger:** Idle connection.
- **Impact:** Connections may be silently dropped by NAT or reverse proxies.
- **Suggested Fix:** Add `setInterval(() => sendHeartbeat(), 15000)`.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Added 15-second keepalive `MSG_HEARTBEAT` interval in both `simulator.js` and `ambient.js`.

### BUG-026: Ambient Receiver UI Completely Discards `cards` Metadata Array
- **File:** `ambient_screen/ambient.js:140-144`
- **Issue:** `AmbientDisplayPayload.cards` is discarded; only `title` and `content` are rendered.
- **Trigger:** Sending multi-card dashboards.
- **Impact:** Structured cards layout is lost.
- **Suggested Fix:** Iterate over `data.cards` and render card elements in the ambient UI.
- **Status:** ✅ Resolved (2026-11-09)
- **Resolution:** Added `#cardsGrid` dashboard container and rendered structured card tiles in `ambient_screen/ambient.js`.

---

## ✅ Resolved

| Bug ID | Severity | File | Stream | Summary | Resolved At |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BUG-001** | 🔴 Critical | `ambient_screen/ambient.js` | Stream 4 (UI) | Added `escapeHtml()` and sanitized markdown/card titles against stored XSS | 2026-11-09 18:15 UTC |
| **BUG-002** | 🔴 Critical | `agent_engine/engine.py` | Stream 2 (Audio) | Implemented autonomous 20ms playback clock task draining ring buffer | 2026-11-09 18:10 UTC |
| **BUG-003** | 🔴 Critical | `agent_engine/engine.py` | Stream 3 (Gateway) | Fixed inverted content routing condition for ambient streaming text | 2026-11-09 18:10 UTC |
| **BUG-004** | 🔴 Critical | `agent_engine/local/ring_buffer.py` | Stream 2 (Audio) | Scaled float samples by `1.0 / 32768.0` preventing +84 dB digital overdrive | 2026-11-09 18:08 UTC |
| **BUG-005** | 🔴 Critical | `agent_engine/router.py` | Stream 3 (Gateway) | Added `RoutingOrigin` protecting intentional tool casts from gaze glance-away | 2026-11-09 18:10 UTC |
| **BUG-006** | 🔴 Critical | `agent_engine/local/vad.py` | Stream 2 (Audio) | Sanitized reference audio and enabled AES during agent playback | 2026-11-09 18:09 UTC |
| **BUG-007** | 🟡 Intermediate | `core/protocol.py` | Stream 1 (Protocol) | Standardized 10-byte aligned header `>HBBBBf` encoding `codec_id` | 2026-11-09 18:07 UTC |
| **BUG-008** | 🟡 Intermediate | `core/protocol.py` | Stream 1 (Protocol) | Removed `and crc != 0` check to enforce strict CRC verification | 2026-11-09 18:07 UTC |
| **BUG-009** | 🟡 Intermediate | `core/protocol.py` | Stream 1 (Protocol) | Added `payload_bytes.startswith(b"{")` check before binary struct unpack | 2026-11-09 18:07 UTC |
| **BUG-010** | 🟡 Intermediate | `simulator/simulator.js` | Stream 4 (UI) | Muted mic processor output node to eliminate speaker feedback screech | 2026-11-09 18:18 UTC |
| **BUG-011** | 🟡 Intermediate | `simulator/simulator.js` | Stream 4 (UI) | Scheduled Web Audio playback on timeline cursor and reset on barge-in | 2026-11-09 18:18 UTC |
| **BUG-012** | 🟡 Intermediate | `simulator/simulator.js` | Stream 4 (UI) | Configured AudioContext with explicit 16kHz sample rate | 2026-11-09 18:18 UTC |
| **BUG-013** | 🟡 Intermediate | `gateway/audio_router.py` | Stream 3 (Gateway) | Implemented `ClientConnection` outbound queue protecting concurrent sends | 2026-11-09 18:14 UTC |
| **BUG-014** | 🟡 Intermediate | `gateway/server.py` | Stream 3 (Gateway) | Changed `override_route()` endpoint to `async def` | 2026-11-09 18:14 UTC |
| **BUG-015** | 🟢 Normal | `agent_engine/engine.py` | Stream 2 (Audio) | Removed premature `flush()` from token feeding loop | 2026-11-09 18:10 UTC |
| **BUG-016** | 🟢 Normal | `gateway/audio_router.py` | Stream 3 (Gateway) | Added `try / finally` unregistering with explicit WebSocket closure | 2026-11-09 18:14 UTC |
| **BUG-017** | 🟢 Normal | `core/messages.py` | Stream 1 (Protocol) | Updated `HudDrawTextPayload` default `y = 20` and canvas `textBaseline = "top"` | 2026-11-09 18:06 UTC |
| **BUG-018** | 🟢 Normal | `gateway/audio_router.py` | Stream 3 (Gateway) | Tracked `last_uplink_ts` and computed heartbeat round-trip latency | 2026-11-09 18:14 UTC |
| **BUG-019** | 🟡 Intermediate | `gateway/server.py` | Stream 3 (Gateway) | Replaced wildcard CORS with strict localhost/127.0.0.1 regex | 2026-11-09 18:14 UTC |
| **BUG-020** | 🟢 Normal | `agent_engine/local/vad.py` | Stream 2 (Audio) | Enforced `_fixed_threshold_dbfs` clamping in `__init__`, `reset()`, and eval | 2026-11-09 18:09 UTC |
| **BUG-021** | 🟢 Normal | `ambient_screen/ambient.js` | Stream 4 (UI) | Guarded visualizer step against division by zero and cleared timers | 2026-11-09 18:16 UTC |
| **BUG-022** | 🔴 Critical | `core/protocol.py` | Stream 1 (Protocol) | Automatically prepended 10-byte header when encoding raw bytes | 2026-11-09 18:07 UTC |
| **BUG-023** | 🟡 Intermediate | `simulator/simulator.js` | Stream 4 (UI) | Adjusted "Glance Away" yaw to 65° to exceed deadband threshold | 2026-11-09 18:18 UTC |
| **BUG-024** | 🟢 Normal | `simulator/simulator.js` | Stream 4 (UI) | Added 15s keepalive heartbeat interval to both simulator and ambient screen | 2026-11-09 18:18 UTC |
| **BUG-025** | 🟡 Intermediate | `agent_engine/engine.py` | Stream 3 (Gateway) | Added done callback logging exceptions in `_safe_dispatch()` | 2026-11-09 18:10 UTC |
| **BUG-026** | 🟢 Normal | `ambient_screen/ambient.js` | Stream 4 (UI) | Rendered `data.cards` into `#cardsGrid` dashboard tiles | 2026-11-09 18:16 UTC |
| **BUG-027** | 🔴 Critical | `agent_engine/cloud/livekit_bridge.py` | Stream 2 (Audio) | Implemented `send_audio_frame()` in `LiveKitBridge` and wired into uplink flow | 2026-11-09 18:09 UTC |
