/**
 * Project PA - Wearable Eyewear MicroLED Simulator
 * Implements binary TLV framing (ADR-007) and physical eyewear emulation.
 */

// TLV Constants
const MAGIC_0 = 0x50; // 'P'
const MAGIC_1 = 0x41; // 'A'
const PROTOCOL_VERSION = 0x01;
const HEADER_SIZE = 12;

const MSG_AUDIO_UPLINK = 0x01;
const MSG_AUDIO_DOWNLINK = 0x02;
const MSG_HUD_DRAW_TEXT = 0x03;
const MSG_HUD_DRAW_BITMAP = 0x04;
const MSG_IMU_TELEMETRY = 0x05;
const MSG_VPU_VAD_EVENT = 0x06;
const MSG_SYSTEM_CONTROL = 0x07;
const MSG_CROSS_SURFACE_ROUTING = 0x08;
const MSG_AMBIENT_DISPLAY_CONTENT = 0x09;
const MSG_HEARTBEAT = 0x0A;

// State
let ws = null;
let seqNum = 1;
let isWhisperActive = false;
let audioCtx = null;
let micStream = null;
let micProcessor = null;
let isMicActive = false;

// DOM Elements
const canvas = document.getElementById("hudCanvas");
const ctx = canvas.getContext("2d");
const connDot = document.getElementById("connDot");
const connText = document.getElementById("connText");
const logBox = document.getElementById("logBox");
const pitchSlider = document.getElementById("pitchSlider");
const yawSlider = document.getElementById("yawSlider");
const rollSlider = document.getElementById("rollSlider");
const pitchVal = document.getElementById("pitchVal");
const yawVal = document.getElementById("yawVal");
const rollVal = document.getElementById("rollVal");
const whisperBtn = document.getElementById("whisperBtn");
const micToggleBtn = document.getElementById("micToggleBtn");
const earAudioBar = document.getElementById("earAudioBar");
const micAudioBar = document.getElementById("micAudioBar");
const dispRouteVal = document.getElementById("dispRouteVal");
const audioRouteVal = document.getElementById("audioRouteVal");

// --- CRC16 Calculation ---
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

// --- Binary TLV Packing ---
function packTLV(msgType, payloadUint8) {
  const payloadLen = payloadUint8 ? payloadUint8.length : 0;
  const totalLen = HEADER_SIZE + payloadLen;
  const buffer = new ArrayBuffer(totalLen);
  const view = new DataView(buffer);

  view.setUint8(0, MAGIC_0);
  view.setUint8(1, MAGIC_1);
  view.setUint8(2, PROTOCOL_VERSION);
  view.setUint8(3, msgType);
  view.setUint16(4, seqNum & 0xFFFF, false); // big-endian
  seqNum++;
  view.setUint32(6, payloadLen, false);

  // Copy payload
  const u8 = new Uint8Array(buffer);
  if (payloadLen > 0) {
    u8.set(payloadUint8, HEADER_SIZE);
  }

  // Compute CRC16 over [version (1B) + msgType (1B) + seq (2B) + payloadLen (4B)] + payload
  // Total CRC data length = 8 + payloadLen bytes
  const crcBuffer = new Uint8Array(8 + payloadLen);
  crcBuffer.set(u8.subarray(2, 10), 0);
  if (payloadLen > 0) {
    crcBuffer.set(u8.subarray(12, 12 + payloadLen), 8);
  }
  const crcView = new DataView(crcBuffer.buffer);
  const crc = computeCRC16(crcView, 0, crcBuffer.length);
  view.setUint16(10, crc, false);

  return buffer;
}

function packJSONMessage(msgType, obj) {
  const jsonStr = JSON.stringify(obj);
  const enc = new TextEncoder();
  return packTLV(msgType, enc.encode(jsonStr));
}

// --- HUD Canvas Rendering ---
function initCanvas() {
  ctx.fillStyle = "#020502";
  ctx.fillRect(0, 0, 640, 200);

  // Default welcome prompt
  drawHudText({
    x: 20,
    y: 35,
    text: "PROJECT PA // MICROLED HUD ACTIVE",
    clear_screen: true,
    font_size: 13,
  });
  drawHudText({
    x: 20,
    y: 75,
    text: "SUB-350MS EMBODIED PHYSICAL AI AGENT",
    clear_screen: false,
    font_size: 14,
  });
  drawHudText({
    x: 20,
    y: 115,
    text: "READY: VPU WHISPER ACTIVE | LOOK-TO-CAST READY",
    clear_screen: false,
    font_size: 11,
  });
}

function drawHudText(cmd) {
  if (cmd.clear_screen) {
    ctx.fillStyle = "#020502";
    ctx.fillRect(0, 0, 640, 200);
  }

  ctx.fillStyle = "#00ff66";
  ctx.font = `${cmd.font_size || 14}px monospace`;
  ctx.textBaseline = "top";
  ctx.shadowColor = "rgba(0, 255, 102, 0.75)";
  ctx.shadowBlur = 6;

  ctx.fillText(cmd.text, cmd.x, cmd.y);
  ctx.shadowBlur = 0; // reset
}

function drawHudBitmap(x, y, width, height, bitmapData) {
  const imgData = ctx.createImageData(width, height);
  // 1-bit to RGBA
  let byteIdx = 0;
  let bitIdx = 7;

  for (let i = 0; i < width * height; i++) {
    const byte = bitmapData[byteIdx];
    const isPixelOn = (byte & (1 << bitIdx)) !== 0;

    const pxOffset = i * 4;
    imgData.data[pxOffset] = isPixelOn ? 0 : 2;      // R
    imgData.data[pxOffset + 1] = isPixelOn ? 255 : 5; // G
    imgData.data[pxOffset + 2] = isPixelOn ? 102 : 2; // B
    imgData.data[pxOffset + 3] = 255;                // A

    bitIdx--;
    if (bitIdx < 0) {
      bitIdx = 7;
      byteIdx++;
    }
  }

  ctx.putImageData(imgData, x, y);
}

// --- WebSocket Connection ---
function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${location.host}/ws/wearable`;

  appendLog(`Connecting to ${wsUrl}...`, "system");
  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    connDot.classList.add("connected");
    connText.innerText = "ONLINE (WS/TLV)";
    appendLog("Connected to Project PA Gateway", "system");

    // Send initial IMU telemetry
    sendIMUTelemetry();
  };

  ws.onclose = () => {
    connDot.classList.remove("connected");
    connText.innerText = "OFFLINE";
    appendLog("Disconnected from Gateway. Reconnecting in 2s...", "system");
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error("WS Error:", err);
  };

  ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      handleIncomingPacket(event.data);
    }
  };
}

function handleIncomingPacket(buffer) {
  if (buffer.byteLength < HEADER_SIZE) return;
  const view = new DataView(buffer);

  const magic0 = view.getUint8(0);
  const magic1 = view.getUint8(1);
  if (magic0 !== MAGIC_0 || magic1 !== MAGIC_1) return;

  const msgType = view.getUint8(3);
  const payloadLen = view.getUint32(6, false);
  if (buffer.byteLength < HEADER_SIZE + payloadLen) return;
  const payloadBytes = new Uint8Array(buffer, HEADER_SIZE, payloadLen);

  switch (msgType) {
    case MSG_HUD_DRAW_TEXT: {
      const jsonStr = new TextDecoder().decode(payloadBytes);
      const cmd = JSON.parse(jsonStr);
      drawHudText(cmd);
      appendLog(`HUD: "${cmd.text}"`, "hud");
      break;
    }
    case MSG_HUD_DRAW_BITMAP: {
      if (payloadBytes.length > 0 && payloadBytes[0] === 0x7B) {
        try {
          const jsonStr = new TextDecoder().decode(payloadBytes);
          const cmd = JSON.parse(jsonStr);
          const rawBmp = cmd.bitmap_data ? new TextEncoder().encode(cmd.bitmap_data) : new Uint8Array(0);
          drawHudBitmap(cmd.x || 0, cmd.y || 0, cmd.width || 640, cmd.height || 200, rawBmp);
          appendLog(`HUD BITMAP [${cmd.width || 640}x${cmd.height || 200}]`, "hud");
          break;
        } catch (e) {}
      }
      if (payloadBytes.byteLength >= 8) {
        const bView = new DataView(payloadBytes.buffer, payloadBytes.byteOffset, 8);
        const x = bView.getUint16(0, false);
        const y = bView.getUint16(2, false);
        const w = bView.getUint16(4, false);
        const h = bView.getUint16(6, false);
        const bmp = payloadBytes.subarray(8);
        drawHudBitmap(x, y, w, h, bmp);
        appendLog(`HUD BITMAP [${w}x${h}]`, "hud");
      }
      break;
    }
    case MSG_AUDIO_DOWNLINK: {
      playAudioDownlink(payloadBytes);
      break;
    }
    case MSG_CROSS_SURFACE_ROUTING: {
      const jsonStr = new TextDecoder().decode(payloadBytes);
      const routing = JSON.parse(jsonStr);
      dispRouteVal.innerText = routing.display_surface.toUpperCase();
      audioRouteVal.innerText = routing.audio_destination.toUpperCase();
      appendLog(`SURFACE ROUTE: ${routing.display_surface} / ${routing.audio_destination} (${routing.reason})`, "route");
      break;
    }
    case MSG_HEARTBEAT: {
      try {
        const jsonStr = new TextDecoder().decode(payloadBytes);
        const hb = JSON.parse(jsonStr);
        if (hb.echo && hb.timestamp_ms) {
          const rtt = Math.max(0, Date.now() - hb.timestamp_ms);
          appendLog(`HEARTBEAT ECHO PONG (${rtt}ms RTT)`, "system");
        } else {
          appendLog("HEARTBEAT ECHO PONG", "system");
        }
      } catch (e) {
        appendLog("HEARTBEAT ECHO PONG", "system");
      }
      break;
    }
  }
}

// --- Audio Playback (USound Ganymede MEMS Private Ear) ---
let downlinkNextStartTime = 0;

function resetDownlinkPlayback() {
  if (audioCtx) {
    downlinkNextStartTime = audioCtx.currentTime;
  }
}

function playAudioDownlink(payloadBytes) {
  if (payloadBytes.length < 8) return;
  const is10Byte = payloadBytes.length >= 10;
  const headerLen = is10Byte ? 10 : 8;
  const view = new DataView(payloadBytes.buffer, payloadBytes.byteOffset, headerLen);
  const sampleRate = view.getUint16(0, false);
  const channels = view.getUint8(2);
  const dest = is10Byte ? view.getUint8(4) : view.getUint8(3); // 0 = private_ear, 1 = ambient_room

  if (dest !== 0) return; // Only play if routed to private ear

  const pcmBytes = payloadBytes.subarray(headerLen);
  const sampleCount = Math.floor(pcmBytes.length / 2);
  if (sampleCount <= 0) return;

  let int16Samples;
  if (pcmBytes.byteOffset % 2 === 0) {
    int16Samples = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, sampleCount);
  } else {
    int16Samples = new Int16Array(pcmBytes.slice().buffer, 0, sampleCount);
  }

  // Meter animation
  let sumSquare = 0;
  for (let i = 0; i < int16Samples.length; i++) {
    sumSquare += int16Samples[i] * int16Samples[i];
  }
  const rms = Math.sqrt(sumSquare / int16Samples.length);
  const pct = Math.min(100, Math.round((rms / 16000) * 100));
  earAudioBar.style.width = `${pct}%`;
  setTimeout(() => { earAudioBar.style.width = "0%"; }, 200);

  // Audio Context playback with timeline scheduling (BUG-011)
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }

  const audioBuffer = audioCtx.createBuffer(1, int16Samples.length, sampleRate || 24000);
  const floatData = audioBuffer.getChannelData(0);
  for (let i = 0; i < int16Samples.length; i++) {
    floatData[i] = int16Samples[i] / 32768.0;
  }

  const source = audioCtx.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(audioCtx.destination);
  downlinkNextStartTime = Math.max(audioCtx.currentTime, downlinkNextStartTime);
  source.start(downlinkNextStartTime);
  downlinkNextStartTime += audioBuffer.duration;

  appendLog(`USound MEMS Downlink: ${int16Samples.length} samples (${sampleRate}Hz)`, "hud");
}

// --- IMU Telemetry Dispatch ---
function sendIMUTelemetry(gesture = "none") {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const pitch = parseFloat(pitchSlider.value);
  const yaw = parseFloat(yawSlider.value);
  const roll = parseFloat(rollSlider.value);

  // Calculate gaze vector [gx, gy, gz] from yaw and pitch (in radians)
  const yawRad = (yaw * Math.PI) / 180.0;
  const pitchRad = (pitch * Math.PI) / 180.0;
  const gx = Math.sin(yawRad) * Math.cos(pitchRad);
  const gy = -Math.sin(pitchRad);
  const gz = Math.cos(yawRad) * Math.cos(pitchRad);

  const payload = {
    pitch,
    yaw,
    roll,
    accel_x: 0.0,
    accel_y: 0.0,
    accel_z: 9.81,
    gesture,
    gaze_vector: [gx, gy, gz],
    gaze_confidence: 0.95,
  };

  const packet = packJSONMessage(MSG_IMU_TELEMETRY, payload);
  ws.send(packet);
}

// --- Bone-Conduction VPU Whisper Dispatch ---
function setWhisperState(active) {
  isWhisperActive = active;
  if (active) {
    whisperBtn.classList.add("active");
    whisperBtn.innerText = "WHISPER ACTIVE (VPU DETECTED)";
    appendLog("ST LIS25BA VPU: Whisper Acoustic Resonance Engaged", "vpu");
  } else {
    whisperBtn.classList.remove("active");
    whisperBtn.innerText = "HOLD TO WHISPER (VPU TRIGGER)";
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const payload = {
    event_type: active ? "whisper_start" : "whisper_stop",
    energy_level: active ? 0.88 : 0.0,
    confidence: 0.98,
    timestamp_ms: Date.now(),
  };

  const packet = packJSONMessage(MSG_VPU_VAD_EVENT, payload);
  ws.send(packet);
}

// --- Logging Helper ---
function appendLog(msg, cls = "") {
  const line = document.createElement("div");
  line.className = `log-entry ${cls}`;
  const time = new Date().toLocaleTimeString().split(" ")[0];
  line.innerText = `[${time}] ${msg}`;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}

// --- Event Listeners ---
pitchSlider.addEventListener("input", () => {
  pitchVal.innerText = `${pitchSlider.value}°`;
  sendIMUTelemetry();
});
yawSlider.addEventListener("input", () => {
  yawVal.innerText = `${yawSlider.value}°`;
  sendIMUTelemetry();
});
rollSlider.addEventListener("input", () => {
  rollVal.innerText = `${rollSlider.value}°`;
  sendIMUTelemetry();
});

whisperBtn.addEventListener("mousedown", () => setWhisperState(true));
whisperBtn.addEventListener("mouseup", () => setWhisperState(false));
whisperBtn.addEventListener("touchstart", (e) => { e.preventDefault(); setWhisperState(true); });
whisperBtn.addEventListener("touchend", (e) => { e.preventDefault(); setWhisperState(false); });

document.getElementById("lookCastBtn").addEventListener("click", () => {
  pitchSlider.value = 0;
  yawSlider.value = 0;
  rollSlider.value = 0;
  pitchVal.innerText = "0°";
  yawVal.innerText = "0°";
  rollVal.innerText = "0°";
  sendIMUTelemetry("look_at_ambient");
  appendLog("Look-to-cast gaze trigger emitted", "route");
});

document.getElementById("glanceAwayBtn").addEventListener("click", () => {
  yawSlider.value = 65;
  yawVal.innerText = "65°";
  sendIMUTelemetry("none");
  appendLog("Glanced away from screen", "route");
});

document.getElementById("nodBtn").addEventListener("click", () => {
  sendIMUTelemetry("nod");
  appendLog("Gesture: NOD", "system");
});

document.getElementById("shakeBtn").addEventListener("click", () => {
  sendIMUTelemetry("shake");
  appendLog("Gesture: SHAKE", "system");
});

document.getElementById("clearHudBtn").addEventListener("click", () => {
  drawHudText({ text: "", clear_screen: true });
});

// --- Microphone Audio Streaming ---
async function toggleMicrophone() {
  if (isMicActive) {
    if (micStream) {
      micStream.getTracks().forEach(t => t.stop());
      micStream = null;
    }
    if (micProcessor) {
      micProcessor.disconnect();
      micProcessor = null;
    }
    isMicActive = false;
    micToggleBtn.innerText = "Enable Mic Input";
    micToggleBtn.classList.remove("active");
    micAudioBar.style.width = "0%";
    appendLog("Microphone streaming stopped", "vpu");
  } else {
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      }
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: false,
        }
      });

      const source = audioCtx.createMediaStreamSource(micStream);
      micProcessor = audioCtx.createScriptProcessor(1024, 1, 1);

      micProcessor.onaudioprocess = (e) => {
        if (!isMicActive || !ws || ws.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);

        let sumSq = 0;
        // 10-byte audio header: sample_rate (H), channels (B), codec_id (B), is_vpu (B), reserved (B), vpu_energy (f)
        const pcmBuffer = new ArrayBuffer(10 + inputData.length * 2);
        const pcmView = new DataView(pcmBuffer);
        pcmView.setUint16(0, 16000, false);
        pcmView.setUint8(2, 1);
        pcmView.setUint8(3, 0); // codec_id: 0 = pcm_s16le
        pcmView.setUint8(4, isWhisperActive ? 1 : 0);
        pcmView.setUint8(5, 0);
        pcmView.setFloat32(6, isWhisperActive ? 0.9 : 0.05, false);

        const int16 = new Int16Array(pcmBuffer, 10, inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          sumSq += s * s;
        }

        const rms = Math.sqrt(sumSq / inputData.length);
        const pct = Math.min(100, Math.round(rms * 250));
        micAudioBar.style.width = `${pct}%`;

        if (rms > 0.04) {
          resetDownlinkPlayback();
        }

        const packet = packTLV(MSG_AUDIO_UPLINK, new Uint8Array(pcmBuffer));
        ws.send(packet);
      };

      source.connect(micProcessor);
      // Mute mic output to local destination to eliminate feedback screech (BUG-010)
      const muteGain = audioCtx.createGain();
      muteGain.gain.value = 0.0;
      micProcessor.connect(muteGain);
      muteGain.connect(audioCtx.destination);

      isMicActive = true;
      micToggleBtn.innerText = "Stop Mic Input";
      micToggleBtn.classList.add("active");
      appendLog("16kHz Knowles PDM Mic Streaming Active", "vpu");
    } catch (err) {
      appendLog(`Mic Error: ${err.message}`, "system");
      console.error(err);
    }
  }
}

// Voice simulation triggers
function sendSimulatedAudio(textPrompt) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  resetDownlinkPlayback();

  // 1. Notify gateway of intended voice query prompt
  const ctrlPayload = {
    command: "voice_query",
    voice_query: textPrompt,
  };
  ws.send(packJSONMessage(MSG_SYSTEM_CONTROL, ctrlPayload));

  // 2. Generate speech burst (1920 samples = 4 frames of 16kHz speech) with 10-byte header
  const speechSamples = 1920;
  const pcmBuffer = new ArrayBuffer(10 + speechSamples * 2);
  const pcmView = new DataView(pcmBuffer);
  pcmView.setUint16(0, 16000, false);
  pcmView.setUint8(2, 1); // channels
  pcmView.setUint8(3, 0); // codec_id
  pcmView.setUint8(4, isWhisperActive ? 1 : 0); // is_vpu
  pcmView.setUint8(5, 0);
  pcmView.setFloat32(6, isWhisperActive ? 0.9 : 0.1, false);

  const int16 = new Int16Array(pcmBuffer, 10, speechSamples);
  for (let i = 0; i < speechSamples; i++) {
    int16[i] = Math.sin(i * 0.1) * (isWhisperActive ? 8000 : 20000);
  }

  const speechPacket = packTLV(MSG_AUDIO_UPLINK, new Uint8Array(pcmBuffer));
  ws.send(speechPacket);

  // 3. Send trailing silence (23 frames = 11040 samples) to trigger VAD turn completion
  const silenceSamples = 11040;
  const silBuffer = new ArrayBuffer(10 + silenceSamples * 2);
  const silView = new DataView(silBuffer);
  silView.setUint16(0, 16000, false);
  silView.setUint8(2, 1);
  silView.setUint8(3, 0);
  silView.setUint8(4, 0);
  silView.setUint8(5, 0);
  silView.setFloat32(6, 0.0, false);
  const silencePacket = packTLV(MSG_AUDIO_UPLINK, new Uint8Array(silBuffer));
  ws.send(silencePacket);

  appendLog(`Uplink: "${textPrompt}" sent (VAD turn triggered)`, "vpu");
}

micToggleBtn.addEventListener("click", toggleMicrophone);

document.getElementById("testPromptBtn1").addEventListener("click", () => {
  sendSimulatedAudio("Show metrics on screen");
});
document.getElementById("testPromptBtn2").addEventListener("click", () => {
  sendSimulatedAudio("Switch back to HUD");
});
document.getElementById("testPromptBtn3").addEventListener("click", () => {
  sendSimulatedAudio("Route audio to room");
});
document.getElementById("testPromptBtn4").addEventListener("click", () => {
  sendSimulatedAudio("What is the system status?");
});

// Keepalive heartbeat timer every 15s (BUG-024)
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const hb = { timestamp_ms: Date.now(), seq: seqNum, echo: false };
    const packet = packJSONMessage(MSG_HEARTBEAT, hb);
    ws.send(packet);
  }
}, 15000);

// Init
window.addEventListener("DOMContentLoaded", () => {
  initCanvas();
  connectWebSocket();
});
