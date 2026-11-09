/**
 * Project PA - Ambient Screen Cast Receiver
 * Implements binary TLV parsing and ambient visual/audio presentation.
 */

// TLV Constants
const MAGIC_0 = 0x50;
const MAGIC_1 = 0x41;
const PROTOCOL_VERSION = 0x01;
const HEADER_SIZE = 12;

const MSG_AUDIO_DOWNLINK = 0x02;
const MSG_CROSS_SURFACE_ROUTING = 0x08;
const MSG_AMBIENT_DISPLAY_CONTENT = 0x09;
const MSG_HEARTBEAT = 0x0A;

// State
let ws = null;
let audioCtx = null;
let nextStartTime = 0;
let spectrumClearTimer = null;
let seqNum = 1;

// DOM Elements
const standbyView = document.getElementById("standbyView");
const activeCastView = document.getElementById("activeCastView");
const statusPill = document.getElementById("statusPill");
const contentTitle = document.getElementById("contentTitle");
const contentBody = document.getElementById("contentBody");
const spectrumCanvas = document.getElementById("spectrumCanvas");
const specCtx = spectrumCanvas.getContext("2d");
const reticle = document.getElementById("reticle");

// --- HTML Sanitization (BUG-001) ---
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

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
  view.setUint16(4, seqNum & 0xFFFF, false);
  seqNum++;
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

  return buffer;
}

// --- Markdown Formatter ---
function formatMarkdown(text) {
  if (!text) return "";

  // Sanitize raw HTML tags to prevent XSS (BUG-001)
  let html = escapeHtml(text)
    // Code blocks
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Headers
    .replace(/^### (.*$)/gim, '<h3 style="margin: 12px 0 6px 0; color: #00f0ff;">$1</h3>')
    .replace(/^## (.*$)/gim, '<h2 style="margin: 16px 0 8px 0; color: #00f0ff;">$1</h2>')
    .replace(/^# (.*$)/gim, '<h1 style="margin: 20px 0 10px 0; color: #00f0ff;">$1</h1>');

  // Convert markdown tables cleanly
  if (html.includes("|")) {
    const lines = html.split("\n");
    const outputLines = [];
    let inTable = false;
    let isHeader = true;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith("|") && line.endsWith("|")) {
        if (line.includes("---")) {
          continue;
        }
        const cols = line.split("|").slice(1, -1);
        if (!inTable) {
          inTable = true;
          isHeader = true;
          outputLines.push("<table><thead><tr>");
        } else {
          outputLines.push("<tr>");
        }

        const tag = isHeader ? "th" : "td";
        const rowContent = cols.map(c => `<${tag}>${c.trim()}</${tag}>`).join("");
        if (isHeader) {
          outputLines.push(rowContent + "</tr></thead><tbody>");
          isHeader = false;
        } else {
          outputLines.push(rowContent + "</tr>");
        }
      } else {
        if (inTable) {
          inTable = false;
          outputLines.push("</tbody></table>");
        }
        outputLines.push(line);
      }
    }
    if (inTable) {
      outputLines.push("</tbody></table>");
    }
    html = outputLines.join("\n");
  }

  // Paragraph breaks
  html = html.replace(/\n\n+/g, '<br><br>');
  return html;
}

// --- WebSocket Connection ---
function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${location.host}/ws/ambient`;

  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    console.log("Connected to Ambient WebSocket");
  };

  ws.onclose = () => {
    console.log("Disconnected from Ambient WebSocket. Retrying in 2s...");
    setTimeout(connectWebSocket, 2000);
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
    case MSG_CROSS_SURFACE_ROUTING: {
      const jsonStr = new TextDecoder().decode(payloadBytes);
      const routing = JSON.parse(jsonStr);
      applyRouting(routing);
      break;
    }
    case MSG_AMBIENT_DISPLAY_CONTENT: {
      const jsonStr = new TextDecoder().decode(payloadBytes);
      const content = JSON.parse(jsonStr);
      renderAmbientContent(content);
      break;
    }
    case MSG_AUDIO_DOWNLINK: {
      playRoomAudio(payloadBytes);
      break;
    }
  }
}

function applyRouting(routing) {
  const isCastActive = routing.display_surface === "cast_ambient";
  if (isCastActive) {
    statusPill.className = "cast-pill";
    statusPill.innerText = "ACTIVE CAST";
    standbyView.classList.add("hidden");
    activeCastView.classList.remove("hidden");
  } else {
    statusPill.className = "cast-pill standby";
    statusPill.innerText = "STANDBY";
    standbyView.classList.remove("hidden");
    activeCastView.classList.add("hidden");
  }
}

function renderAmbientContent(data) {
  contentTitle.innerText = data.title || "Agent Response";
  contentBody.innerHTML = formatMarkdown(data.content);

  // Render cards grid tiles (BUG-026)
  const cardsGrid = document.getElementById("cardsGrid");
  if (cardsGrid) {
    cardsGrid.innerHTML = "";
    if (Array.isArray(data.cards) && data.cards.length > 0) {
      data.cards.forEach(card => {
        const tile = document.createElement("div");
        tile.className = "dashboard-tile";
        const title = escapeHtml(card.title || "");
        const body = formatMarkdown(card.body || card.content || "");
        tile.innerHTML = `<h4>${title}</h4><div class="tile-body">${body}</div>`;
        cardsGrid.appendChild(tile);
      });
      cardsGrid.classList.remove("hidden");
    } else {
      cardsGrid.classList.add("hidden");
    }
  }

  // Auto transition to active view
  statusPill.className = "cast-pill";
  statusPill.innerText = "ACTIVE CAST";
  standbyView.classList.add("hidden");
  activeCastView.classList.remove("hidden");
}

function playRoomAudio(payloadBytes) {
  if (payloadBytes.length < 8) return;
  // Binary audio header: >HBBBBf (10 bytes) or legacy >HBBf (8 bytes)
  const is10Byte = payloadBytes.length >= 10;
  const headerLen = is10Byte ? 10 : 8;
  const view = new DataView(payloadBytes.buffer, payloadBytes.byteOffset, headerLen);
  const sampleRate = view.getUint16(0, false);
  const dest = is10Byte ? view.getUint8(4) : view.getUint8(3); // 0 = private_ear, 1 = ambient_room

  if (dest !== 1) return; // Only play if targeted to ambient_room

  const pcmBytes = payloadBytes.subarray(headerLen);
  const sampleCount = Math.floor(pcmBytes.length / 2);
  if (sampleCount <= 0) return;
  const int16Samples = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, sampleCount);

  // Spectrum animation
  drawSpectrum(int16Samples);

  // Audio Context playback with timeline scheduling (BUG-011)
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
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
  nextStartTime = Math.max(audioCtx.currentTime, nextStartTime);
  source.start(nextStartTime);
  nextStartTime += audioBuffer.duration;
}

function drawSpectrum(int16Samples) {
  if (spectrumClearTimer) {
    clearTimeout(spectrumClearTimer);
    spectrumClearTimer = null;
  }

  specCtx.fillStyle = "#05080c";
  specCtx.fillRect(0, 0, 400, 48);

  specCtx.fillStyle = "#00f0ff";
  // Safe step calculation guarding against division by zero (BUG-021)
  const step = Math.max(1, Math.floor(int16Samples.length / 40));
  for (let i = 0; i < 40; i++) {
    const idx = Math.min(i * step, int16Samples.length - 1);
    const val = Math.abs(int16Samples[idx] || 0) / 32768.0;
    const barHeight = Math.max(2, val * 44);
    specCtx.fillRect(i * 10, 48 - barHeight, 7, barHeight);
  }

  spectrumClearTimer = setTimeout(() => {
    specCtx.fillStyle = "#05080c";
    specCtx.fillRect(0, 0, 400, 48);
    spectrumClearTimer = null;
  }, 250);
}

// Keepalive heartbeat timer every 15s (BUG-024)
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const hb = { timestamp_ms: Date.now(), seq: seqNum, echo: false };
    const jsonBytes = new TextEncoder().encode(JSON.stringify(hb));
    const packet = packTLV(MSG_HEARTBEAT, jsonBytes);
    ws.send(packet);
  }
}, 15000);

window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
});
