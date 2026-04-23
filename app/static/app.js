/*
 * nRF24 console — frontend
 *
 * Plain vanilla JS. One WebSocket to the backend. Ring-buffer packet table
 * so the DOM doesn't melt during a real capture.
 */

const MAX_ROWS = 1000;

const state = {
  mode: "idle",
  connected: false,
  channel: null,
  packetCount: 0,
  recording: false,
  channelActivity: new Map(), // ch -> count
  addresses: new Map(),       // addr -> {count, lastCh, lastPayload, lastT}
};

// Ring buffer per tab (so Scan and Sniff don't stomp on each other).
const buffers = {
  scan: [],
  sniff: [],
};

const chips = {
  conn: document.getElementById("chip-conn"),
  mode: document.getElementById("chip-mode"),
  channel: document.getElementById("chip-channel"),
  packets: document.getElementById("chip-packets"),
  recording: document.getElementById("chip-recording"),
};

// ------------------------------------------------------------- tabs --

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-pane").forEach((p) => {
      p.classList.toggle("active", p.id === `tab-${target}`);
    });
    if (target === "recordings") refreshRecordings();
  });
});

// ---------------------------------------------------------- toasts --

function toast(msg, level = "info") {
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.textContent = msg;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ---------------------------------------------------------- status --

function renderStatus() {
  chips.conn.textContent = state.connected ? "radio: ok" : "radio: ✗";
  chips.conn.className = "chip " + (state.connected ? "chip-connected" : "chip-disconnected");
  chips.mode.textContent = `mode: ${state.mode}`;
  chips.mode.className = "chip " + (state.mode !== "idle" ? `chip-${state.mode}` : "");
  chips.channel.textContent = `ch: ${state.channel ?? "—"}`;
  chips.packets.textContent = `pkts: ${state.packetCount}`;
  chips.recording.classList.toggle("chip-hidden", !state.recording);
}

// -------------------------------------------------------- heatmap --

const HEATMAP_RANGE = Array.from({ length: 82 }, (_, i) => i + 2);   // 2..83
const heatmapEl = document.getElementById("channel-heatmap");

(function initHeatmap() {
  for (const ch of HEATMAP_RANGE) {
    const cell = document.createElement("div");
    cell.className = "hm-cell";
    cell.dataset.ch = ch;
    cell.title = `ch ${ch}`;
    heatmapEl.appendChild(cell);
  }
})();

function renderHeatmap() {
  const cells = heatmapEl.children;
  for (const cell of cells) {
    const ch = Number(cell.dataset.ch);
    const count = state.channelActivity.get(ch) || 0;
    const intensity = Math.min(count / 5, 1);    // 5+ packets = full saturation
    const hue = 166; // teal-ish
    if (count > 0) {
      cell.style.background = `hsl(${hue}, 60%, ${15 + intensity * 35}%)`;
      cell.title = `ch ${ch} — ${count} packets`;
    } else {
      cell.style.background = "";
    }
    cell.classList.toggle("current", state.channel === ch);
  }
}

// --------------------------------------------------- packet table --

function pushPacket(tab, ev) {
  const buf = buffers[tab];
  buf.push(ev);
  if (buf.length > MAX_ROWS) buf.shift();

  const tbody = document.getElementById(`${tab}-tbody`);
  const row = document.createElement("tr");
  const src = ev.source || (ev.mode === "external" ? "ext" : "nRF24");
  const srcClass = src === "nRF24" ? "src-nrf24" : "src-external";
  row.innerHTML = `
    <td>${new Date(ev.t * 1000).toISOString().slice(11, 23)}</td>
    <td><span class="src-chip ${srcClass}">${src}</span></td>
    <td>${ev.ch ?? "—"}</td>
    <td>${ev.length ?? "—"}</td>
    <td>${ev.addr ?? ""}</td>
    <td>${ev.payload ?? ""}</td>
  `;
  row.addEventListener("click", () => {
    if (ev.addr) {
      document.getElementById("sniff-address").value = ev.addr;
      // Switch to sniff tab.
      document.querySelector('.tab[data-tab="sniff"]').click();
      toast(`Locked onto ${ev.addr}`, "ok");
    }
  });

  tbody.insertBefore(row, tbody.firstChild);
  while (tbody.children.length > MAX_ROWS) {
    tbody.removeChild(tbody.lastChild);
  }

  if (tab === "scan" && ev.addr) {
    const prev = state.addresses.get(ev.addr) || { count: 0 };
    state.addresses.set(ev.addr, {
      count: prev.count + 1,
      lastCh: ev.ch,
      lastPayload: ev.payload,
      lastT: ev.t,
    });
    renderAddressPanel();
  }
}

function renderAddressPanel() {
  const tbody = document.getElementById("scan-addrs-tbody");
  if (!tbody) return;
  const sorted = [...state.addresses.entries()].sort((a, b) => b[1].count - a[1].count);
  if (!sorted.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="4">—</td></tr>';
    return;
  }
  tbody.innerHTML = "";
  sorted.forEach(([addr, info], i) => {
    const row = document.createElement("tr");
    if (i === 0) row.classList.add("top-addr-row");
    row.innerHTML = `
      <td title="last payload: ${info.lastPayload || ''}">${addr}</td>
      <td>${info.count}</td>
      <td>${info.lastCh ?? "—"}</td>
      <td><button class="sniff-btn" data-addr="${addr}">Sniff →</button></td>
    `;
    tbody.appendChild(row);
  });
  tbody.querySelectorAll(".sniff-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      document.getElementById("sniff-address").value = btn.dataset.addr;
      document.querySelector('.tab[data-tab="sniff"]').click();
      toast(`Locked onto ${btn.dataset.addr}`, "ok");
    });
  });
}

// ------------------------------------------------ channels parsing --

function parseChannels(text) {
  if (!text.trim()) return null;
  const result = new Set();
  for (const part of text.split(",")) {
    const p = part.trim();
    if (!p) continue;
    if (p.includes("-")) {
      const [a, b] = p.split("-").map((x) => parseInt(x, 10));
      for (let i = a; i <= b; i++) result.add(i);
    } else {
      result.add(parseInt(p, 10));
    }
  }
  return Array.from(result).sort((a, b) => a - b);
}

// ---------------------------------------------------------- WS ----

let ws = null;

function connectWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/events`);

  ws.onopen = () => {
    renderStatus();
  };
  ws.onclose = () => {
    setTimeout(connectWs, 1500);
  };
  ws.onerror = () => { /* onclose will reconnect */ };
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    handleEvent(ev);
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case "status_snapshot":
      state.connected = ev.connected;
      state.mode = ev.mode;
      state.channel = ev.channel;
      state.packetCount = ev.packet_count;
      state.recording = (ev.recording && ev.recording.active) || false;
      renderStatus();
      break;
    case "status":
      state.connected = ev.connected ?? state.connected;
      renderStatus();
      break;
    case "mode":
      state.mode = ev.mode;
      renderStatus();
      break;
    case "channel":
      state.channel = ev.channel;
      renderStatus();
      renderHeatmap();
      break;
    case "packet":
      state.packetCount++;
      state.channelActivity.set(ev.ch, (state.channelActivity.get(ev.ch) || 0) + 1);
      renderStatus();
      renderHeatmap();
      pushPacket(ev.mode === "scan" ? "scan" : "sniff", ev);
      break;
    case "transmit_result":
      logTx(ev);
      break;
    case "recording":
      state.recording = ev.state === "started";
      renderStatus();
      toast(`Recording ${ev.state}${ev.path ? ": " + ev.path : ""}`, "ok");
      break;
    case "error":
      toast(`${ev.where}: ${ev.detail}`, "error");
      break;
    default:
      // log/unknown — ignore
  }
}

// ------------------------------------------------ scan handlers ---

document.getElementById("scan-start").addEventListener("click", async () => {
  const body = {
    channels: parseChannels(document.getElementById("scan-channels").value),
    dwell_ms: Number(document.getElementById("scan-dwell").value),
    prefix: document.getElementById("scan-prefix").value,
    scan_mode: document.getElementById("scan-mode").value,
  };
  state.channelActivity.clear();
  state.addresses.clear();
  renderAddressPanel();
  buffers.scan = [];
  document.getElementById("scan-tbody").innerHTML = "";
  if (document.getElementById("scan-record").checked) {
    await apiPost("/api/recording/start", { filename: null });
  }
  await apiPost("/api/scan/start", body);
});

document.getElementById("scan-quickdiscover").addEventListener("click", async () => {
  // Full-range scan for 15s, then auto-switch to sniff on the top address.
  state.channelActivity.clear();
  state.addresses.clear();
  renderAddressPanel();
  buffers.scan = [];
  document.getElementById("scan-tbody").innerHTML = "";

  toast("Quick discover: 15s full-range scan starting", "ok");
  const start = await apiPost("/api/scan/start", {
    channels: null, dwell_ms: 100, prefix: "",
  });
  if (!start) return;
  await new Promise((r) => setTimeout(r, 15000));
  await apiPost("/api/stop", {});

  const sorted = [...state.addresses.entries()].sort((a, b) => b[1].count - a[1].count);
  if (!sorted.length) {
    toast("No packets detected. Nothing nRF24 in range?", "warn");
    return;
  }
  const [topAddr, topInfo] = sorted[0];
  document.getElementById("sniff-address").value = topAddr;
  toast(`Top address: ${topAddr} (${topInfo.count} packets). Switched to Sniff tab.`, "ok");
  document.querySelector('.tab[data-tab="sniff"]').click();
});

document.getElementById("scan-stop").addEventListener("click", async () => {
  await apiPost("/api/stop", {});
  if (state.recording) await apiPost("/api/recording/stop", {});
});

// ----------------------------------------------- sniff handlers ---

document.getElementById("sniff-start").addEventListener("click", async () => {
  const body = {
    address: document.getElementById("sniff-address").value,
    timeout_ms: Number(document.getElementById("sniff-timeout").value),
    retries: Number(document.getElementById("sniff-retries").value),
  };
  buffers.sniff = [];
  document.getElementById("sniff-tbody").innerHTML = "";
  if (document.getElementById("sniff-record").checked) {
    await apiPost("/api/recording/start", { filename: null });
  }
  await apiPost("/api/sniff/start", body);
});

document.getElementById("sniff-stop").addEventListener("click", async () => {
  await apiPost("/api/stop", {});
  if (state.recording) await apiPost("/api/recording/stop", {});
});

// --------------------------------------------- transmit handler --

document.getElementById("tx-send").addEventListener("click", async () => {
  const body = {
    address: document.getElementById("tx-address").value,
    payload_hex: document.getElementById("tx-payload").value,
    mode: document.getElementById("tx-mode").value,
    retries: Number(document.getElementById("tx-retries").value),
  };
  await apiPost("/api/transmit", body);
});

function logTx(ev) {
  const panel = document.getElementById("tx-log");
  const line = document.createElement("div");
  line.className = ev.ok ? "ok" : "err";
  const ts = new Date(ev.t * 1000).toISOString().slice(11, 19);
  line.textContent = `[${ts}] ${ev.mode.toUpperCase()} → ${ev.addr} : ${ev.payload}  (ok=${ev.ok})`;
  panel.insertBefore(line, panel.firstChild);
}

// ------------------------------------------ recordings handler --

document.getElementById("rec-refresh").addEventListener("click", refreshRecordings);

async function refreshRecordings() {
  const res = await fetch("/api/recordings");
  const data = await res.json();
  const tbody = document.getElementById("rec-tbody");
  tbody.innerHTML = "";
  for (const r of data.recordings) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${r.name}</td>
      <td>${(r.size / 1024).toFixed(1)} KiB</td>
      <td>${new Date(r.mtime * 1000).toISOString().replace("T", " ").slice(0, 19)}</td>
    `;
    tbody.appendChild(row);
  }
}

// -------------------------------------------------- API helper ---

async function apiPost(path, body) {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      toast(`${path}: ${detail.detail?.error || res.statusText}`, "error");
      return null;
    }
    return await res.json();
  } catch (e) {
    toast(`${path}: ${e.message}`, "error");
    return null;
  }
}

// ---------------------------------------------- Learn mode ---

const LEARN_LIB_KEY = "nrf24.learn.library";
const learnLibrary = JSON.parse(localStorage.getItem(LEARN_LIB_KEY) || "[]");

function saveLearnLibrary() {
  localStorage.setItem(LEARN_LIB_KEY, JSON.stringify(learnLibrary));
}

function renderLearnLibrary() {
  const el = document.getElementById("learn-library");
  if (!el) return;
  if (!learnLibrary.length) {
    el.innerHTML = '<div class="learn-empty">No captures yet. Fill in a label and click <b>Start capture</b>.</div>';
    return;
  }
  el.innerHTML = "";
  learnLibrary.slice().reverse().forEach((entry, revIdx) => {
    const idx = learnLibrary.length - 1 - revIdx;
    const card = document.createElement("div");
    card.className = "learn-card";
    const packetsStr = (entry.packets || []).map((p) =>
      `ch${String(p.ch).padStart(2, " ")}  ${p.addr}  ${p.payload}`
    ).join("\n") || "(no packets caught in window)";
    card.innerHTML = `
      <div class="learn-card-head">
        <span class="learn-card-title">${escapeHtml(entry.label)}</span>
        <span class="learn-card-meta">${new Date(entry.captured_at * 1000).toISOString().slice(11, 19)} · ${entry.packets.length} packet(s) · ±${entry.window_ms}ms</span>
      </div>
      <div class="learn-card-packets">${escapeHtml(packetsStr)}</div>
      <div class="learn-card-actions">
        <button class="btn-secondary" data-action="replay" data-idx="${idx}">Replay via Transmit</button>
        <button class="btn-secondary" data-action="export">Copy JSON</button>
        <button class="btn-secondary" data-action="delete" data-idx="${idx}">Delete</button>
      </div>
    `;
    el.appendChild(card);
  });
  el.querySelectorAll(".learn-card-actions button").forEach((btn) => {
    btn.addEventListener("click", () => handleLearnCardAction(btn));
  });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function handleLearnCardAction(btn) {
  const action = btn.dataset.action;
  if (action === "delete") {
    const idx = Number(btn.dataset.idx);
    learnLibrary.splice(idx, 1);
    saveLearnLibrary();
    renderLearnLibrary();
    return;
  }
  if (action === "export") {
    const json = JSON.stringify(learnLibrary, null, 2);
    navigator.clipboard.writeText(json).then(() => toast("Library copied to clipboard", "ok"));
    return;
  }
  if (action === "replay") {
    const idx = Number(btn.dataset.idx);
    const entry = learnLibrary[idx];
    if (!entry.packets.length) { toast("No packets to replay", "warn"); return; }
    const pkt = entry.packets[0];
    document.getElementById("tx-address").value = pkt.addr;
    document.getElementById("tx-payload").value = pkt.payload;
    document.querySelector('.tab[data-tab="transmit"]').click();
    toast(`Loaded '${entry.label}' into Transmit tab`, "ok");
  }
}

async function runLearnCapture() {
  const label = document.getElementById("learn-label").value.trim();
  if (!label) { toast("Enter a label first", "warn"); return; }
  const windowMs = Number(document.getElementById("learn-window").value);
  const countdown = Number(document.getElementById("learn-countdown").value);
  const cdEl = document.getElementById("learn-countdown-display");
  const startBtn = document.getElementById("learn-start");
  startBtn.disabled = true;

  try {
    // Kick off a full-range promiscuous scan so we catch whatever channel the device uses.
    cdEl.className = "countdown-display";
    cdEl.textContent = "arming radio…";
    await apiPost("/api/scan/start", { channels: null, dwell_ms: 50, prefix: "" });

    // Countdown
    for (let i = countdown; i >= 1; i--) {
      cdEl.textContent = `press in ${i}…`;
      await new Promise((r) => setTimeout(r, 1000));
    }
    cdEl.textContent = "PRESS NOW";
    cdEl.className = "countdown-display press";
    const pressT = Date.now() / 1000;

    // Capture window
    const extraMs = windowMs + 250;
    await new Promise((r) => setTimeout(r, extraMs));
    await apiPost("/api/stop", {});

    // Pull packets in [pressT - W, pressT + W]
    const windowS = windowMs / 1000;
    const url = `/api/recent_packets?since=${pressT - windowS}&until=${pressT + windowS}`;
    const res = await fetch(url);
    const data = await res.json();
    const packets = data.packets || [];

    const entry = {
      label,
      captured_at: pressT,
      window_ms: windowMs,
      packets,
    };
    learnLibrary.push(entry);
    saveLearnLibrary();
    renderLearnLibrary();

    cdEl.textContent = packets.length
      ? `captured ${packets.length} packet(s)`
      : "no packets in window — try again closer to the press";
    cdEl.className = "countdown-display";
    document.getElementById("learn-label").value = "";
    if (packets.length) {
      toast(`Captured '${label}': ${packets.length} packet(s)`, "ok");
    } else {
      toast("No packets in the window — get closer to the press timing", "warn");
    }
  } catch (e) {
    cdEl.textContent = `error: ${e.message}`;
    toast(`Capture failed: ${e.message}`, "error");
  } finally {
    startBtn.disabled = false;
  }
}

document.getElementById("learn-start").addEventListener("click", runLearnCapture);
document.getElementById("learn-clear").addEventListener("click", () => {
  if (learnLibrary.length === 0) return;
  if (!confirm(`Clear all ${learnLibrary.length} captured command(s)?`)) return;
  learnLibrary.length = 0;
  saveLearnLibrary();
  renderLearnLibrary();
});
renderLearnLibrary();

// ---------------------------------------------- AI assistant ---

const chatHistory = [];   // conversation history passed back to Claude
const aiMessages = document.getElementById("ai-messages");
const aiInput = document.getElementById("ai-input");
const aiSend = document.getElementById("ai-send");

async function checkAiAvailable() {
  try {
    const res = await fetch("/api/ai/available");
    const data = await res.json();
    if (!data.available) {
      document.getElementById("ai-unavailable").style.display = "block";
      document.getElementById("ai-reason").textContent = data.reason || "No API key";
      aiSend.disabled = true;
      aiInput.disabled = true;
    }
  } catch (e) { /* ignore */ }
}
checkAiAvailable();

function appendChatMsg(role, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  aiMessages.appendChild(div);
  aiMessages.scrollTop = aiMessages.scrollHeight;
  return div;
}

function appendToolStep(step) {
  const div = document.createElement("div");
  div.className = "chat-msg tool";
  if (step.error) {
    div.textContent = `🔧 ${step.tool}(${JSON.stringify(step.input || {})}) → error: ${step.error}`;
  } else {
    const resultStr = JSON.stringify(step.result);
    const compact = resultStr.length > 300 ? resultStr.slice(0, 300) + "…" : resultStr;
    div.textContent = `🔧 ${step.tool}(${JSON.stringify(step.input || {})}) → ${compact}`;
  }
  aiMessages.appendChild(div);
  aiMessages.scrollTop = aiMessages.scrollHeight;
}

async function sendChat() {
  const msg = aiInput.value.trim();
  if (!msg) return;
  aiInput.value = "";
  appendChatMsg("user", msg);
  aiSend.disabled = true;

  const spinner = document.createElement("div");
  spinner.className = "chat-msg assistant";
  spinner.innerHTML = '<span class="chat-spinner"></span>thinking…';
  aiMessages.appendChild(spinner);
  aiMessages.scrollTop = aiMessages.scrollHeight;

  try {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, history: chatHistory }),
    });
    const data = await res.json();
    spinner.remove();

    if (res.status !== 200 || data.error) {
      appendChatMsg("error", data.error || data.detail?.reason || "request failed");
    } else {
      for (const step of data.steps || []) {
        appendToolStep(step);
      }
      appendChatMsg("assistant", data.message || "(no reply)");
      if (data.history) {
        // Replace client-side history with the authoritative server copy.
        chatHistory.length = 0;
        chatHistory.push(...data.history);
      }
    }
  } catch (e) {
    spinner.remove();
    appendChatMsg("error", e.message);
  } finally {
    aiSend.disabled = false;
    aiInput.focus();
  }
}

aiSend.addEventListener("click", sendChat);
aiInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});
document.querySelectorAll(".chat-hints .hint").forEach((el) => {
  el.addEventListener("click", () => {
    aiInput.value = el.dataset.prompt;
    aiInput.focus();
  });
});

// ----------------------------------------------------- startup ---

connectWs();
renderStatus();

// Poll status every 5s as a belt-and-braces.
setInterval(async () => {
  try {
    const res = await fetch("/api/status");
    const s = await res.json();
    state.connected = s.connected;
    state.mode = s.mode;
    state.channel = s.channel;
    state.packetCount = s.packet_count;
    state.recording = s.recording?.active || false;
    renderStatus();
  } catch (e) { /* ignore */ }
}, 5000);
