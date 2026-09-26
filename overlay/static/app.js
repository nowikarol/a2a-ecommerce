/**
 * A2A Supply Chain Visualizer Frontend
 * Real-time animated graph with flying JSON packets along edges
 */

// Node layout coordinates on SVG (viewBox 0 0 1000 680)
const NODE_COORDS = {
  P1: { x: 500, y: 100, color: "#f59e0b", name: "Producent P1" },
  H1: { x: 240, y: 310, color: "#3b82f6", name: "Hurtownia H1" },
  H2: { x: 760, y: 310, color: "#8b5cf6", name: "Hurtownia H2" },
  R1: { x: 300, y: 550, color: "#10b981", name: "Restauracja R1" },
  R2: { x: 700, y: 550, color: "#ec4899", name: "Restauracja R2" },
};

// Edge path mapping
const EDGE_PAIRS = {
  "P1-H1": "edge-P1-H1",
  "H1-P1": "edge-P1-H1",
  "P1-H2": "edge-P1-H2",
  "H2-P1": "edge-P1-H2",
  "H1-R1": "edge-H1-R1",
  "R1-H1": "edge-H1-R1",
  "H1-R2": "edge-H1-R2",
  "R2-H1": "edge-H1-R2",
  "H2-R1": "edge-H2-R1",
  "R1-H2": "edge-H2-R1",
  "H2-R2": "edge-H2-R2",
  "R2-H2": "edge-H2-R2",
};

// Message Types & Visual Attributes
const MESSAGE_META = {
  AVAILABILITY_REQUEST: {
    icon: "🔍",
    label: "Dostępność (Zapytanie)",
    color: "#06b6d4",
    bgClass: "badge-avail",
    soundFreq: 520,
  },
  AVAILABILITY_RESPONSE: {
    icon: "📦",
    label: "Dostępność (Odpowiedź)",
    color: "#06b6d4",
    bgClass: "badge-avail",
    soundFreq: 580,
  },
  CALL_FOR_PROPOSAL: {
    icon: "📑",
    label: "Zapytanie Ofertowe (CFP)",
    color: "#f97316",
    bgClass: "badge-rfq",
    soundFreq: 640,
  },
  PROPOSAL: {
    icon: "🏷️",
    label: "Oferta Cenowa",
    color: "#f59e0b",
    bgClass: "badge-prop",
    soundFreq: 700,
  },
  ACCEPT_PROPOSAL: {
    icon: "🤝",
    label: "Akceptacja Oferty",
    color: "#10b981",
    bgClass: "badge-accept",
    soundFreq: 880,
  },
  REJECT_PROPOSAL: {
    icon: "❌",
    label: "Odrzucenie",
    color: "#ef4444",
    bgClass: "badge-reject",
    soundFreq: 320,
  },
  REJECT: {
    icon: "❌",
    label: "Odrzucenie",
    color: "#ef4444",
    bgClass: "badge-reject",
    soundFreq: 320,
  },
  PROPOSAL_REJECTED: {
    icon: "❌",
    label: "Odrzucenie",
    color: "#ef4444",
    bgClass: "badge-reject",
    soundFreq: 320,
  },
  DELIVERY: {
    icon: "🚚",
    label: "Dostawa Towaru",
    color: "#a855f7",
    bgClass: "badge-delivery",
    soundFreq: 960,
  },
};

// State variables
let ws = null;
let soundEnabled = true;
let currentFlightDuration = 1800; // ms
let currentNodesData = {};
let currentModalJson = null;

// Audio Context for UI chimes
let audioCtx = null;
function playChime(freq = 600, duration = 0.12) {
  if (!soundEnabled) return;
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch (e) {
    // Ignore audio errors on autoplay restrictions
  }
}

// =============================================================================
// WebSocket Connection
// =============================================================================

function connectWebSocket() {
  const statusEl = document.getElementById("connection-status");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    statusEl.className = "connection-status connected";
    statusEl.querySelector(".status-label").textContent = "Połączono w czasie rzeczywistym";
    console.log("WebSocket connected.");
  };

  ws.onclose = () => {
    statusEl.className = "connection-status disconnected";
    statusEl.querySelector(".status-label").textContent = "Rozłączono - ponawianie...";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.warn("WebSocket error:", err);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleIncomingMessage(msg);
    } catch (e) {
      console.error("Error parsing WS message:", e);
    }
  };
}

function handleIncomingMessage(msg) {
  if (msg.type === "init") {
    currentNodesData = msg.state || {};
    updateNodesUI(currentNodesData);
    if (msg.history && msg.history.length > 0) {
      document.getElementById("feed-empty").style.display = "none";
      msg.history.forEach((evt) => appendEventCard(evt, false));
    }
  } else if (msg.type === "node_state") {
    currentNodesData = msg.data || {};
    updateNodesUI(currentNodesData);
  } else if (msg.type === "packet") {
    const eventData = msg.data;
    animatePacketAlongEdge(eventData);
    appendEventCard(eventData, true);
  }
}

// =============================================================================
// SVG Flying Packet Animation Along Curved Edges
// =============================================================================

function animatePacketAlongEdge(eventData) {
  const src = eventData.source || "R1";
  const tgt = eventData.target || "H1";
  const msgType = eventData.message_type || "CALL_FOR_PROPOSAL";
  const meta = MESSAGE_META[msgType] || {
    icon: "📄",
    label: msgType,
    color: "#38bdf8",
    bgClass: "badge-rfq",
    soundFreq: 600,
  };

  const packetsGroup = document.getElementById("packets-group");
  const edgeKey = `${src}-${tgt}`;
  const reverseKey = `${tgt}-${src}`;
  let pathId = EDGE_PAIRS[edgeKey] || EDGE_PAIRS[reverseKey];
  let isReverse = false;

  if (EDGE_PAIRS[reverseKey] && !EDGE_PAIRS[edgeKey]) {
    isReverse = true;
  } else if (pathId && pathId.startsWith(`edge-${tgt}`)) {
    isReverse = true;
  }

  const pathEl = document.getElementById(pathId);
  if (!pathEl) {
    console.warn("No path found for edge:", src, "->", tgt);
    return;
  }

  // Highlight active edge line briefly
  pathEl.classList.add("active");
  setTimeout(() => pathEl.classList.remove("active"), currentFlightDuration + 200);

  // Measure path
  const totalLength = pathEl.getTotalLength();

  // Create flying packet SVG element
  const packetG = document.createElementNS("http://www.w3.org/2000/svg", "g");
  packetG.setAttribute("class", "flying-packet");

  // Glowing Outer Circle
  const glowCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  glowCircle.setAttribute("r", "20");
  glowCircle.setAttribute("fill", meta.color);
  glowCircle.setAttribute("fill-opacity", "0.25");
  glowCircle.setAttribute("stroke", meta.color);
  glowCircle.setAttribute("stroke-width", "2");
  glowCircle.setAttribute("class", "packet-icon-bg");

  // Inner Icon Circle
  const innerCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  innerCircle.setAttribute("r", "14");
  innerCircle.setAttribute("fill", "#070a13");
  innerCircle.setAttribute("stroke", meta.color);
  innerCircle.setAttribute("stroke-width", "1.5");

  // Emoji Icon
  const iconText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  iconText.setAttribute("text-anchor", "middle");
  iconText.setAttribute("dy", "5");
  iconText.setAttribute("font-size", "14");
  iconText.textContent = meta.icon;

  // Floating Pill Badge
  const pillG = document.createElementNS("http://www.w3.org/2000/svg", "g");
  pillG.setAttribute("class", "packet-pill");
  pillG.setAttribute("transform", "translate(0, -28)");

  const itemSummary = eventData.item ? `${eventData.item.name || ''} ${eventData.item.quantity ? eventData.item.quantity + 'kg' : ''}` : '';
  const labelText = itemSummary ? `${meta.icon} ${msgType}: ${itemSummary}` : `${meta.icon} ${msgType}`;
  
  const textWidth = Math.max(labelText.length * 6.5 + 16, 80);
  const pillRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  pillRect.setAttribute("x", -textWidth / 2);
  pillRect.setAttribute("y", -10);
  pillRect.setAttribute("width", textWidth);
  pillRect.setAttribute("height", "20");
  pillRect.setAttribute("rx", "10");
  pillRect.setAttribute("fill", "#0f172a");
  pillRect.setAttribute("stroke", meta.color);
  pillRect.setAttribute("stroke-width", "1.5");

  const pillText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  pillText.setAttribute("text-anchor", "middle");
  pillText.setAttribute("dy", "4");
  pillText.setAttribute("font-size", "10");
  pillText.setAttribute("font-family", "JetBrains Mono, monospace");
  pillText.setAttribute("font-weight", "700");
  pillText.setAttribute("fill", "#fff");
  pillText.textContent = labelText;

  pillG.appendChild(pillRect);
  pillG.appendChild(pillText);

  packetG.appendChild(glowCircle);
  packetG.appendChild(innerCircle);
  packetG.appendChild(iconText);
  packetG.appendChild(pillG);

  // Clickable packet opens JSON inspector
  packetG.addEventListener("click", (e) => {
    e.stopPropagation();
    openJsonModal(eventData);
  });

  packetsGroup.appendChild(packetG);

  // Play departure sound
  playChime(meta.soundFreq, 0.1);

  // Animation Loop with easing
  const startTime = performance.now();
  const duration = currentFlightDuration;

  function step(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);

    // Ease-in-out cubic
    const eased = progress < 0.5 ? 4 * progress * progress * progress : 1 - Math.pow(-2 * progress + 2, 3) / 2;
    const dist = isReverse ? (1 - eased) * totalLength : eased * totalLength;
    const point = pathEl.getPointAtLength(dist);

    packetG.setAttribute("transform", `translate(${point.x}, ${point.y})`);

    if (progress < 1) {
      requestAnimationFrame(step);
    } else {
      // Arrival at destination node
      triggerNodeShockwave(tgt, meta.color);
      playChime(meta.soundFreq * 1.25, 0.15);

      // Fadeout packet
      packetG.style.transition = "opacity 0.25s";
      packetG.style.opacity = "0";
      setTimeout(() => {
        if (packetG.parentNode) {
          packetG.parentNode.removeChild(packetG);
        }
      }, 300);
    }
  }

  requestAnimationFrame(step);
}

// Trigger expanding ripple wave at target node
function triggerNodeShockwave(nodeId, color) {
  const coords = NODE_COORDS[nodeId];
  if (!coords) return;

  const svg = document.getElementById("network-svg");
  const wave = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  wave.setAttribute("cx", coords.x);
  wave.setAttribute("cy", coords.y);
  wave.setAttribute("class", "ripple-shockwave");
  wave.setAttribute("stroke", color);
  svg.appendChild(wave);

  // Remove wave after animation completes
  setTimeout(() => {
    if (wave.parentNode) {
      wave.parentNode.removeChild(wave);
    }
  }, 750);
}

// =============================================================================
// Live Events Feed UI
// =============================================================================

function appendEventCard(evt, prepend = true) {
  const feed = document.getElementById("events-feed");
  const empty = document.getElementById("feed-empty");
  if (empty) empty.style.display = "none";

  const meta = MESSAGE_META[evt.message_type] || {
    icon: "📄",
    label: evt.message_type || "UNKNOWN",
    color: "#38bdf8",
    bgClass: "badge-rfq",
  };

  const card = document.createElement("div");
  card.className = "event-card";
  card.onclick = () => openJsonModal(evt);

  const timeStr = evt.timestamp || new Date().toLocaleTimeString();

  card.innerHTML = `
    <div class="ec-header">
      <div class="ec-route">
        <span class="node-from">${evt.source || "SRC"}</span>
        <span class="arrow">➔</span>
        <span class="node-to">${evt.target || "TGT"}</span>
      </div>
      <span class="ec-time">${timeStr}</span>
    </div>
    <div class="ec-type-badge">
      <span class="badge ${meta.bgClass}">${meta.icon} ${evt.message_type || "MESSAGE"}</span>
    </div>
    <div class="ec-summary">${evt.summary || "Transmisja danych w protokole handlowym CNP"}</div>
    <div class="ec-footer">
      <span class="ec-inspect-btn">Pokaż JSON ➔</span>
    </div>
  `;

  if (prepend && feed.firstChild) {
    feed.insertBefore(card, feed.firstChild);
    if (currentSidebarMode === "chat") {
      const badge = document.getElementById("feed-count-badge");
      if (badge) {
        const count = (parseInt(badge.textContent) || 0) + 1;
        badge.textContent = count > 99 ? "99+" : count;
        badge.style.display = "inline-block";
      }
    }
  } else {
    feed.appendChild(card);
  }

  // Keep max 80 cards
  while (feed.children.length > 80) {
    feed.removeChild(feed.lastChild);
  }
}

// =============================================================================
// Nodes Status UI Updates
// =============================================================================

function updateNodesUI(state) {
  if (!state) return;

  // Update H1
  if (state.H1) {
    const h1Bal = state.H1.balance !== null && state.H1.balance !== undefined ? `${state.H1.balance.toFixed(2)} PLN` : "-";
    document.getElementById("badge-bal-H1").textContent = h1Bal;
    document.getElementById("stat-h1-bal").textContent = h1Bal;
    document.getElementById("stat-h1-stock").textContent = `Magazyn: ${state.H1.stock_count || 11} poz.`;
  }

  // Update H2
  if (state.H2) {
    const h2Bal = state.H2.balance !== null && state.H2.balance !== undefined ? `${state.H2.balance.toFixed(2)} PLN` : "-";
    document.getElementById("badge-bal-H2").textContent = h2Bal;
    document.getElementById("stat-h2-bal").textContent = h2Bal;
    document.getElementById("stat-h2-stock").textContent = `Magazyn: ${state.H2.stock_count || 11} poz.`;
  }

  // Update R1
  if (state.R1) {
    const r1Bal = state.R1.balance !== null && state.R1.balance !== undefined ? `${state.R1.balance.toFixed(2)} PLN` : "-";
    document.getElementById("badge-bal-R1").textContent = r1Bal;
    document.getElementById("stat-r1-bal").textContent = r1Bal;
    document.getElementById("stat-r1-stock").textContent = `Spiżarnia: ${state.R1.stock_count || 11} poz.`;
  }

  // Update R2
  if (state.R2) {
    const r2Bal = state.R2.balance !== null && state.R2.balance !== undefined ? `${state.R2.balance.toFixed(2)} PLN` : "-";
    document.getElementById("badge-bal-R2").textContent = r2Bal;
    document.getElementById("stat-r2-bal").textContent = r2Bal;
    document.getElementById("stat-r2-stock").textContent = `Magazyn: ${state.R2.stock_count || 11} poz.`;
  }

  // Update P1
  if (state.P1) {
    document.getElementById("stat-p1-stock").textContent = `Katalog: ${state.P1.stock_count || 11} surowców`;
  }
}

// =============================================================================
// Modals & Inspectors
// =============================================================================

function openJsonModal(eventData) {
  const json = eventData.raw_json || eventData;
  currentModalJson = json;

  document.getElementById("json-modal-title").textContent = `JSON: ${eventData.message_type || "Dokument"}`;
  document.getElementById("json-modal-meta").textContent = `${eventData.source || "SRC"} ➔ ${eventData.target || "TGT"} (${eventData.timestamp || ""})`;
  document.getElementById("json-code").textContent = JSON.stringify(json, null, 2);
  document.getElementById("json-modal").classList.add("open");
}

function closeJsonModal() {
  document.getElementById("json-modal").classList.remove("open");
}

function copyJsonToClipboard() {
  if (currentModalJson) {
    navigator.clipboard.writeText(JSON.stringify(currentModalJson, null, 2));
    alert("JSON skopiowany do schowka!");
  }
}

function showNodeDetails(nodeId) {
  const node = NODE_COORDS[nodeId];
  const data = currentNodesData[nodeId];
  if (!node) return;

  document.getElementById("node-modal-title").textContent = `${node.name} (${nodeId})`;
  const container = document.getElementById("node-modal-content");

  let balHtml = data && data.balance !== null && data.balance !== undefined ? `<p><b>Saldo portfela:</b> <span style="color:#10b981;font-weight:700;">${data.balance.toFixed(2)} PLN</span></p>` : `<p><b>Rola:</b> Sprzedający (Producent P1)</p>`;
  let txHtml = data && data.transactions_count !== undefined ? `<p><b>Zarejestrowane transakcje w bazie:</b> ${data.transactions_count}</p>` : "";

  let stockTable = "";
  if (data && data.stock && data.stock.length > 0) {
    stockTable = `
      <h4 style="margin-top:16px;margin-bottom:8px;font-size:13px;color:#94a3b8;">Stan magazynowy (${data.stock.length} pozycji):</h4>
      <table class="detail-table">
        <thead>
          <tr>
            <th>Produkt</th>
            <th>Ilość</th>
            <th>Cena jedn.</th>
          </tr>
        </thead>
        <tbody>
          ${data.stock.map(item => `
            <tr>
              <td><b>${item.name}</b></td>
              <td>${item.quantity} ${item.unit || 'kg'}</td>
              <td>${item.price !== undefined ? item.price.toFixed(2) + ' PLN' : '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  container.innerHTML = `
    <div style="font-size: 13px; line-height: 1.6;">
      <p><b>Status:</b> <span style="color:#10b981;">ONLINE</span></p>
      ${balHtml}
      ${txHtml}
      ${stockTable}
    </div>
  `;

  document.getElementById("node-modal").classList.add("open");
}

function closeNodeModal() {
  document.getElementById("node-modal").classList.remove("open");
}

// =============================================================================
// Interactive Chat Console & Sidebar State
// =============================================================================

let currentSidebarMode = "chat"; // 'chat' | 'feed' | 'split'
let currentChatTarget = "R2";
let isChatSending = false;

const AGENT_META = {
  R2: { name: "Restauracja 2", icon: "🍝", color: "#ec4899", class: "agent-R2" },
  R1: { name: "Restauracja 1", icon: "🍕", color: "#10b981", class: "agent-R1" },
  H1: { name: "Hurtownia 1", icon: "🏢", color: "#3b82f6", class: "agent-H1" },
  H2: { name: "Hurtownia 2", icon: "🏬", color: "#8b5cf6", class: "agent-H2" },
};

const QUICK_CHIPS_BY_AGENT = {
  R2: [
    { text: "Tak, potwierdzam zakup", label: "✅ Tak, potwierdzam zakup", type: "confirm", autoSend: true },
    { text: "Nie, anuluj", label: "❌ Nie, anuluj", type: "cancel", autoSend: true },
    { text: "Przygotuj 5x Pizza Margherita", label: "🍕 Przygotuj 5x Pizza", type: "action", autoSend: false },
    { text: "Sprawdź stan mąki w magazynie", label: "📦 Stan mąki", type: "action", autoSend: false },
    { text: "Kup 10 kg mąki w hurtowniach", label: "🌾 Kup 10kg mąki", type: "action", autoSend: false },
  ],
  R1: [
    { text: "Przygotuj 2x Pizza Margherita Classica", label: "🍕 Przygotuj 2x Pizza (Autonomicznie)", type: "action", autoSend: false },
    { text: "Sprawdź stan zapasów w spiżarni", label: "📦 Stan spiżarni", type: "action", autoSend: false },
    { text: "Przeprowadź audyt zapasów i uzupełnij braki", label: "🔄 Audyt i auto-zakup", type: "action", autoSend: false },
  ],
  H1: [
    { text: "Jaki masz aktualny stan magazynu?", label: "📦 Stan magazynu", type: "action", autoSend: false },
    { text: "Kup 25 kg mąki u Producenta P1", label: "🌾 Zaopatrzenie u Producenta P1", type: "action", autoSend: false },
    { text: "Podaj cennik produktów", label: "🏷️ Cennik", type: "action", autoSend: false },
  ],
  H2: [
    { text: "Jaki masz aktualny stan magazynu?", label: "📦 Stan magazynu", type: "action", autoSend: false },
    { text: "Podaj aktualny cennik produktów", label: "🏷️ Cennik", type: "action", autoSend: false },
  ],
};

const chatHistories = {
  R2: [
    {
      sender: "agent",
      target: "R2",
      text: "👋 Cześć! Jestem agentem Restauracji 2 (R2).\nMożesz zlecić mi przygotowanie potraw (np. 'Przygotuj 5x Pizza Margherita') lub sprawdzenie zapasów.\n\n⚠️ PAMIĘTAJ: W R2 ZAWSZE wymagam akceptacji ze strony człowieka przed zakupem! Po zebraniu ofert hurtowni zatrzymam się i zapytam Cię o potwierdzenie transakcji – możesz odpisać w czacie lub kliknąć zielony przycisk szybkiego potwierdzenia poniżej.",
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ],
  R1: [
    {
      sender: "agent",
      target: "R1",
      text: "👋 Cześć! Jestem agentem Restauracji 1 (R1).\nMożesz zlecić mi przygotowanie potraw (np. 'Przygotuj 2x Pizza Margherita Classica'). Działam w pełni autonomicznie – w razie braków w spiżarni samodzielnie przeprowadzam procedurę CNP i zamawiam składniki bez konieczności pytania człowieka o zgodę.",
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ],
  H1: [
    {
      sender: "agent",
      target: "H1",
      text: "👋 Cześć! Jestem Hurtownią 1 (H1).\nMożesz sprawdzić moje stany magazynowe, cennik lub zlecić uzupełnienie zapasów u Producenta P1.",
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ],
  H2: [
    {
      sender: "agent",
      target: "H2",
      text: "👋 Cześć! Jestem Hurtownią 2 (H2).\nMożesz sprawdzić moje stany magazynowe, cennik lub zapytać o oferty hurtowe.",
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ],
};

function switchSidebarTab(mode) {
  currentSidebarMode = mode;
  const sidebar = document.getElementById("app-sidebar");
  if (!sidebar) return;

  sidebar.className = `sidebar mode-${mode}`;

  document.querySelectorAll(".sb-tab").forEach((tab) => tab.classList.remove("active"));
  const activeTabBtn = document.getElementById(`tab-btn-${mode}`);
  if (activeTabBtn) activeTabBtn.classList.add("active");

  if (mode === "feed" || mode === "split") {
    const badge = document.getElementById("feed-count-badge");
    if (badge) {
      badge.textContent = "0";
      badge.style.display = "none";
    }
  }

  if (mode === "chat" || mode === "split") {
    updateQuickChips(currentChatTarget);
    renderChatThread();
    setTimeout(() => {
      const input = document.getElementById("side-chat-input");
      if (input) input.focus();
    }, 100);
  }
}

function onChatTargetChange(target) {
  currentChatTarget = target;
  updateQuickChips(target);
  renderChatThread();
}

function updateQuickChips(target) {
  const container = document.getElementById("chat-quick-chips");
  if (!container) return;

  const chips = QUICK_CHIPS_BY_AGENT[target] || QUICK_CHIPS_BY_AGENT.R2;
  container.innerHTML = chips
    .map((c) => {
      const fn = c.autoSend ? `quickSendChat('${escapeHtml(c.text)}')` : `quickFillChat('${escapeHtml(c.text)}')`;
      const cls = c.type === "confirm" ? "chip-confirm" : (c.type === "cancel" ? "chip-cancel" : "chip-action");
      return `<button class="quick-chip ${cls}" onclick="${fn}">${c.label}</button>`;
    })
    .join("");
}

function renderChatThread() {
  const thread = document.getElementById("chat-thread");
  if (!thread) return;

  const msgs = chatHistories[currentChatTarget] || [];
  thread.innerHTML = msgs
    .map((msg) => {
      const isUser = msg.sender === "user";
      const meta = AGENT_META[currentChatTarget] || { name: currentChatTarget, icon: "🤖", class: "" };
      const avatar = isUser ? "👤" : meta.icon;
      const senderName = isUser ? "Ty (Orkiestrator)" : `${meta.name} (${currentChatTarget})`;
      const agentClass = isUser ? "" : meta.class;

      return `
      <div class="chat-msg ${isUser ? "user" : "agent"} ${agentClass}">
        <div class="chat-avatar">${avatar}</div>
        <div class="chat-bubble-container">
          <span class="chat-sender-name">${senderName}</span>
          <div class="chat-bubble">${escapeHtml(msg.text)}</div>
          <span class="chat-time">${msg.time}</span>
        </div>
      </div>
    `;
    })
    .join("");

  thread.scrollTop = thread.scrollHeight;
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function quickFillChat(text) {
  const input = document.getElementById("side-chat-input");
  if (input) {
    input.value = text;
    input.focus();
  }
}

function quickSendChat(text) {
  const input = document.getElementById("side-chat-input");
  if (input) {
    input.value = text;
    submitSideChat();
  }
}

function clearCurrentChat() {
  chatHistories[currentChatTarget] = [
    {
      sender: "agent",
      target: currentChatTarget,
      text: `Wątek z ${AGENT_META[currentChatTarget]?.name || currentChatTarget} został zresetowany. W czym mogę pomóc?`,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ];
  renderChatThread();
}

async function submitSideChat() {
  if (isChatSending) return;
  const input = document.getElementById("side-chat-input");
  if (!input) return;

  const prompt = input.value.trim();
  if (!prompt) return;

  const target = currentChatTarget;
  const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // Add user message
  if (!chatHistories[target]) chatHistories[target] = [];
  chatHistories[target].push({
    sender: "user",
    text: prompt,
    time: nowTime,
  });

  input.value = "";
  renderChatThread();

  // Show typing indicator
  isChatSending = true;
  const sendBtn = document.getElementById("btn-side-send-chat");
  const typingIndicator = document.getElementById("chat-typing-indicator");
  const typingAgentName = document.getElementById("typing-agent-name");

  if (sendBtn) sendBtn.disabled = true;
  if (typingAgentName) typingAgentName.textContent = AGENT_META[target]?.name || target;
  if (typingIndicator) typingIndicator.style.display = "block";

  const thread = document.getElementById("chat-thread");
  if (thread) thread.scrollTop = thread.scrollHeight;

  try {
    const res = await fetch("/api/trigger/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, prompt }),
    });

    const data = await res.json();
    const ansText = data.response || data.odpowiedz || (data.status === "error" ? `Błąd: ${data.detail || "Nieznany błąd"}` : JSON.stringify(data, null, 2));

    const replyTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    chatHistories[target].push({
      sender: "agent",
      target: target,
      text: ansText,
      time: replyTime,
    });

    playChime(640, 0.15);
  } catch (e) {
    const replyTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    chatHistories[target].push({
      sender: "agent",
      target: target,
      text: `⚠️ Błąd połączenia z agentem: ${e.message || e}`,
      time: replyTime,
    });
  } finally {
    isChatSending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (typingIndicator) typingIndicator.style.display = "none";
    renderChatThread();
    if (input) input.focus();
  }
}

// =============================================================================
// Action Button Handlers (Demo, CNP Flows, Sound, Reset)
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
  updateQuickChips(currentChatTarget);
  renderChatThread();

  // Speed Slider
  const speedSlider = document.getElementById("speed-slider");
  const speedVal = document.getElementById("speed-val");
  if (speedSlider) {
    speedSlider.addEventListener("input", (e) => {
      currentFlightDuration = parseInt(e.target.value);
      speedVal.textContent = `${(currentFlightDuration / 1000).toFixed(1)}s`;
    });
  }

  // Sound Toggle
  const soundBtn = document.getElementById("btn-sound");
  const soundIcon = document.getElementById("sound-icon");
  if (soundBtn) {
    soundBtn.addEventListener("click", () => {
      soundEnabled = !soundEnabled;
      soundIcon.textContent = soundEnabled ? "🔊" : "🔇";
    });
  }

  // Clear Feed
  const btnClearFeed = document.getElementById("btn-clear-feed");
  if (btnClearFeed) {
    btnClearFeed.addEventListener("click", () => {
      document.getElementById("events-feed").innerHTML = `
        <div class="empty-state" id="feed-empty">
          <p>Oczekiwanie na pierwsze pakiety JSON...</p>
          <small>Użyj przycisków CNP u góry lub czatuj z agentami, aby zobaczyć przelatujące piktogramy.</small>
        </div>
      `;
    });
  }

  // Node Clicking on SVG
  document.querySelectorAll(".graph-node").forEach((el) => {
    el.addEventListener("click", () => {
      const nid = el.getAttribute("data-node");
      showNodeDetails(nid);
    });
  });

  // Demo CNP Flow (Path A: Success R1 -> H1)
  const btnDemo = document.getElementById("btn-demo");
  if (btnDemo) {
    btnDemo.addEventListener("click", async () => {
      btnDemo.disabled = true;
      try {
        await fetch("/api/simulate/demo-flow", { method: "POST" });
      } catch (e) {
        alert("Błąd symulacji CNP Sukces: " + e);
      } finally {
        setTimeout(() => (btnDemo.disabled = false), 3000);
      }
    });
  }

  // Demo CNP Reject & Fallback Flow (Path B: H1 Rejects -> Fallback to H2)
  const btnDemoReject = document.getElementById("btn-demo-reject");
  if (btnDemoReject) {
    btnDemoReject.addEventListener("click", async () => {
      btnDemoReject.disabled = true;
      try {
        await fetch("/api/simulate/demo-reject-flow", { method: "POST" });
      } catch (e) {
        alert("Błąd symulacji CNP Odrzucenie i Fallback: " + e);
      } finally {
        setTimeout(() => (btnDemoReject.disabled = false), 3000);
      }
    });
  }

  // H1 Buy from P1 Button (CNP Flow: Wholesaler H1 -> Producer P1)
  const btnH1Buy = document.getElementById("btn-h1-buy");
  if (btnH1Buy) {
    btnH1Buy.addEventListener("click", async () => {
      btnH1Buy.disabled = true;
      try {
        await fetch("/api/simulate/h1-p1-flow", { method: "POST" });
      } catch (e) {
        alert("Błąd symulacji H1 -> P1: " + e);
      } finally {
        setTimeout(() => (btnH1Buy.disabled = false), 3000);
      }
    });
  }

  // Header Chat Toggle Button (switches sidebar tab to chat or split)
  const btnToggleChat = document.getElementById("btn-toggle-chat");
  if (btnToggleChat) {
    btnToggleChat.addEventListener("click", () => {
      if (currentSidebarMode === "chat") {
        switchSidebarTab("split");
      } else {
        switchSidebarTab("chat");
      }
    });
  }

  // Chat Input Keyboard Listener (Enter = submit, Shift+Enter = newline)
  const sideInput = document.getElementById("side-chat-input");
  if (sideInput) {
    sideInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitSideChat();
      }
    });
  }

  // Close modals on clicking backdrop
  window.addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) {
      e.target.classList.remove("open");
    }
  });
});
