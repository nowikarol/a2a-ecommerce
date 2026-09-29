/**
 * A2A Trade Flow Demonstrator Frontend
 * Real-time animated graph, 5-step CNP stepper, live narrative storyline & HITL controls
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
    soundFreq: 720,
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
    label: "Odrzucenie Zamówienia",
    color: "#ef4444",
    bgClass: "badge-reject",
    soundFreq: 320,
  },
  WAITING_HUMAN_APPROVAL: {
    icon: "⚠️",
    label: "Wymagana Zgoda Człowieka",
    color: "#f59e0b",
    bgClass: "badge-prop",
    soundFreq: 440,
  },
  DELIVERY: {
    icon: "🚚",
    label: "Dostawa Towaru",
    color: "#a855f7",
    bgClass: "badge-delivery",
    soundFreq: 960,
  },
};

// Scenario presets
const SCENARIOS = {
  1: {
    title: "Scenariusz 1: Standardowy Cykl Handlu (CNP)",
    desc: "Restauracja R1 sonduje rynek u dwóch hurtowni (H1 i H2), wybiera najtańszą ofertę, zawiera kontrakt i odbiera dostawę mąki.",
    endpoint: "/api/simulate/demo-flow",
    badge: "ŚCIEŻKA SUKCESU",
  },
  2: {
    title: "Scenariusz 2: Odrzucenie i Automatyczny Fallback",
    desc: "Restauracja R1 wybiera Hurtownię H1, lecz towar zostaje wyprzedany w ułamku sekundy (Race Condition). H1 odrzuca ofertę, a agent natychmiast kupuje u drugiego dostawcy (H2).",
    endpoint: "/api/simulate/demo-reject-flow",
    badge: "ODPORNOŚĆ / FALLBACK",
  },
  3: {
    title: "Scenariusz 3: Dostawa Hurtowa od Producenta (H1 ➔ P1)",
    desc: "Hurtownia H1 staje się Kupującym i zamawia 25 kg mąki u Producenta P1 po cenie fabrycznej (2.50 PLN/kg). Demonstruje rekurencję ról w łańcuchu dostaw.",
    endpoint: "/api/simulate/h1-p1-flow",
    badge: "ŁAŃCUCH DOSTAW B2B",
  },
  4: {
    title: "Scenariusz 4: Decyzja Człowieka (Human-in-the-Loop)",
    desc: "Restauracja R2 zamawia 10 kg sera Mozzarella. Agent porównuje oferty, lecz ZATRZYMUJE zakup i oczekuje na kliknięcie autoryzacji przez człowieka w panelu.",
    endpoint: "/api/simulate/hitl-flow",
    badge: "HUMAN-IN-THE-LOOP",
  },
};

// State variables
let ws = null;
let soundEnabled = true;
let currentFlightDuration = 1800; // ms
let currentNodesData = {};
let activeScenarioId = null;
let currentStepNumber = 0;
let lastPacketJson = null;
let currentModalJson = null;

// Audio Context for UI chimes
let audioCtx = null;
function playChime(freq = 600, duration = 0.14) {
  if (!soundEnabled) return;
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.09, audioCtx.currentTime);
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
    statusEl.querySelector(".status-label").textContent = "Połączono na żywo";
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
  } else if (msg.type === "node_state") {
    currentNodesData = msg.data || {};
    updateNodesUI(currentNodesData);
  } else if (msg.type === "scenario_start") {
    handleScenarioStart(msg.data);
  } else if (msg.type === "scenario_end") {
    handleScenarioEnd(msg.data);
  } else if (msg.type === "packet") {
    const eventData = msg.data;
    handleTradePacket(eventData);
  }
}

// =============================================================================
// Scenario & Stepper State Handlers
// =============================================================================

function handleScenarioStart(data) {
  activeScenarioId = data.scenario_id;
  currentStepNumber = 0;
  recentPacketTimestamps.clear();

  // Highlight active button
  document.querySelectorAll(".scenario-card").forEach((btn) => btn.classList.remove("active"));
  const activeBtn = document.getElementById(`btn-scen-${activeScenarioId}`);
  if (activeBtn) activeBtn.classList.add("active");

  // Update Scenario Banner
  const banner = document.getElementById("scenario-banner");
  document.getElementById("banner-badge").textContent = `SCENARIUSZ ${activeScenarioId}`;
  document.getElementById("banner-time").textContent = data.timestamp || new Date().toLocaleTimeString();
  document.getElementById("banner-title").textContent = data.title;
  document.getElementById("banner-desc").textContent = data.description;

  // Reset Stepper
  updateStepper(0);

  // Reset Narrative
  document.getElementById("current-step-label").textContent = "Start Demonstracji";
  document.getElementById("narrative-headline").textContent = "Inicjalizacja Procedury CNP";
  document.getElementById("narrative-story").textContent = data.description;
  document.getElementById("narrative-rule-text").textContent = "Agenci weryfikują swoje reguły biznesowe i stany magazynowe przed wysłaniem pierwszych komunikatów w sieci.";
  document.getElementById("current-route-pill").style.display = "none";
  document.getElementById("hitl-action-box").style.display = "none";

  addStepLogEntry(data.timestamp || new Date().toLocaleTimeString(), `▶ Start: ${data.title}`);
  playChime(480, 0.2);
}

function handleScenarioEnd(data) {
  updateStepper(5);

  document.getElementById("current-step-label").textContent = "Zakończono Sukcesem";
  document.getElementById("narrative-headline").textContent = data.title;
  document.getElementById("narrative-story").textContent = data.summary;
  document.getElementById("narrative-rule-text").textContent = "Cykl handlu zbilansował bazy danych SQLite wszystkich zaangażowanych stron z zachowaniem atomowości transakcji ACID.";
  document.getElementById("hitl-action-box").style.display = "none";

  addStepLogEntry(data.timestamp || new Date().toLocaleTimeString(), `🏁 Koniec: ${data.summary}`);
  playChime(1040, 0.25);
  setTimeout(() => playChime(1320, 0.3), 150);
}

// Map to prevent duplicate animations/logs for identical packets arriving within short window
const recentPacketTimestamps = new Map();

function isDuplicatePacket(eventData) {
  const src = eventData.source || "";
  const tgt = eventData.target || "";
  const mtype = eventData.message_type || "";
  const item = (eventData.item && eventData.item.name) || "";
  const sig = `${src}->${tgt}:${mtype}:${item}`;
  const generalDelivSig = `${src}->${tgt}:DELIVERY`;
  const now = performance.now();

  const windowMs = mtype === "DELIVERY" ? 3500 : 1500;

  if (mtype === "DELIVERY" && recentPacketTimestamps.has(generalDelivSig)) {
    const prev = recentPacketTimestamps.get(generalDelivSig);
    if (now - prev < windowMs) {
      console.log(`[FRONTEND DEDUP] Ignored duplicate delivery: ${generalDelivSig}`);
      return true;
    }
  }

  if (recentPacketTimestamps.has(sig)) {
    const prev = recentPacketTimestamps.get(sig);
    if (now - prev < windowMs) {
      console.log(`[FRONTEND DEDUP] Ignored duplicate packet: ${sig}`);
      return true;
    }
  }

  recentPacketTimestamps.set(sig, now);
  if (mtype === "DELIVERY") {
    recentPacketTimestamps.set(generalDelivSig, now);
  }
  return false;
}

function handleTradePacket(eventData) {
  if (isDuplicatePacket(eventData)) {
    return;
  }

  const step = eventData.step || 1;
  currentStepNumber = step;
  updateStepper(step);

  // Update Narrative Card
  if (eventData.step_title) {
    document.getElementById("current-step-label").textContent = `KROK ${step} Z 5`;
    document.getElementById("narrative-headline").textContent = eventData.step_title;
  }
  if (eventData.narrative) {
    document.getElementById("narrative-story").textContent = eventData.narrative;
  }
  if (eventData.rule) {
    document.getElementById("narrative-rule-text").textContent = eventData.rule;
  }

  // Update Route Pill
  const routePill = document.getElementById("current-route-pill");
  if (eventData.source && eventData.target) {
    routePill.style.display = "inline-flex";
    document.getElementById("route-src").textContent = eventData.source;
    document.getElementById("route-tgt").textContent = eventData.target;
  }

  // Handle Human-in-the-Loop decision prompt
  const hitlBox = document.getElementById("hitl-action-box");
  if (eventData.requires_approval) {
    hitlBox.style.display = "flex";
    if (eventData.narrative) {
      document.getElementById("hitl-prompt-text").innerHTML = eventData.narrative;
    }
    playChime(440, 0.2);
  } else if (eventData.message_type !== "WAITING_HUMAN_APPROVAL") {
    hitlBox.style.display = "none";
  }

  // Animate packet along edge
  animatePacketAlongEdge(eventData);

  // Update Live JSON Viewer
  updateLiveJsonViewer(eventData);

  // Log Step Entry
  const timeStr = eventData.timestamp || new Date().toLocaleTimeString();
  addStepLogEntry(timeStr, `${eventData.source} ➔ ${eventData.target}: ${eventData.summary || eventData.message_type}`);
}

function updateStepper(step) {
  const fill = document.getElementById("stepper-fill");
  const percentages = { 0: "0%", 1: "15%", 2: "35%", 3: "55%", 4: "75%", 5: "100%" };
  if (fill) fill.style.width = percentages[step] || "0%";

  for (let i = 1; i <= 5; i++) {
    const node = document.getElementById(`step-node-${i}`);
    if (!node) continue;

    node.classList.remove("active", "completed");
    if (i < step) {
      node.classList.add("completed");
    } else if (i === step) {
      node.classList.add("active");
    }
  }
}

// =============================================================================
// SVG Flying Packet Animation Along Curved Edges
// =============================================================================

function animatePacketAlongEdge(eventData) {
  const src = eventData.source || "R1";
  const tgt = eventData.target || "H1";

  // If internal event (same source and target), just trigger ripple
  if (src === tgt || tgt === "OPERATOR" || tgt === "OPERATOR_UI") {
    if (NODE_COORDS[src]) triggerNodeShockwave(src, "#3b82f6");
    return;
  }

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
  const pathId = EDGE_PAIRS[edgeKey];

  if (!pathId || !packetsGroup) return;

  const pathEl = document.getElementById(pathId);
  if (!pathEl) return;

  // Highlight edge during flight
  pathEl.classList.add("highlighted");
  setTimeout(() => pathEl.classList.remove("highlighted"), currentFlightDuration + 100);

  const isReverse = edgeKey.startsWith("H1-P1") || edgeKey.startsWith("H2-P1") || edgeKey.startsWith("R1-H1") || edgeKey.startsWith("R2-H1") || edgeKey.startsWith("R1-H2") || edgeKey.startsWith("R2-H2");

  const totalLength = pathEl.getTotalLength();

  // Packet SVG Group
  const packetG = document.createElementNS("http://www.w3.org/2000/svg", "g");
  packetG.setAttribute("class", "flying-packet");
  packetG.onclick = () => openJsonModal(eventData);

  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("class", "packet-pill");
  rect.setAttribute("x", "-72");
  rect.setAttribute("y", "-20");
  rect.setAttribute("width", "144");
  rect.setAttribute("height", "40");
  rect.setAttribute("fill", "#0f172a");
  rect.setAttribute("stroke", meta.color);

  const iconText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  iconText.setAttribute("class", "packet-icon");
  iconText.setAttribute("x", "-55");
  iconText.setAttribute("y", "0");
  iconText.textContent = meta.icon;

  const labelText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  labelText.setAttribute("class", "packet-label");
  labelText.setAttribute("x", "-33");
  labelText.setAttribute("y", "-4");
  labelText.textContent = meta.label.length > 13 ? meta.label.substring(0, 12) + "…" : meta.label;

  const qtyText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  qtyText.setAttribute("class", "packet-qty");
  qtyText.setAttribute("x", "-33");
  qtyText.setAttribute("y", "10");

  let desc = "";
  if (eventData.item && eventData.item.name) {
    const qty = eventData.item.quantity ? `${eventData.item.quantity}kg` : "";
    desc = `${qty} ${eventData.item.name}`.trim();
  } else if (eventData.total_cost) {
    desc = `${eventData.total_cost} PLN`;
  } else {
    desc = eventData.summary || "";
  }
  qtyText.textContent = desc.length > 16 ? desc.substring(0, 15) + "…" : desc;

  packetG.appendChild(rect);
  packetG.appendChild(iconText);
  packetG.appendChild(labelText);
  packetG.appendChild(qtyText);
  packetsGroup.appendChild(packetG);

  playChime(meta.soundFreq, 0.12);

  // Flight Animation
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
// Live JSON Inspector & Step History
// =============================================================================

function updateLiveJsonViewer(eventData) {
  const json = eventData.raw_json || eventData;
  lastPacketJson = json;

  const viewer = document.getElementById("live-json-viewer");
  const typeBadge = document.getElementById("json-type-badge");

  if (viewer) {
    viewer.textContent = JSON.stringify(json, null, 2);
  }
  if (typeBadge) {
    typeBadge.textContent = eventData.message_type || "JSON";
  }
}

function copyCurrentJson() {
  if (lastPacketJson) {
    navigator.clipboard.writeText(JSON.stringify(lastPacketJson, null, 2));
    alert("JSON skopiowany do schowka!");
  } else {
    alert("Brak dostępnego dokumentu JSON do skopiowania.");
  }
}

function addStepLogEntry(timeStr, text) {
  const list = document.getElementById("steps-history-list");
  const empty = document.getElementById("history-empty");
  if (empty) empty.style.display = "none";

  const item = document.createElement("div");
  item.className = "shc-item";
  item.innerHTML = `
    <span class="shc-time">${timeStr}</span>
    <span class="shc-text">${escapeHtml(text)}</span>
  `;

  if (list) {
    list.insertBefore(item, list.firstChild);
    while (list.children.length > 50) {
      list.removeChild(list.lastChild);
    }
  }
}

function clearStepLog() {
  const list = document.getElementById("steps-history-list");
  if (list) {
    list.innerHTML = `<div class="shc-empty" id="history-empty">Brak zarejestrowanych kroków w bieżącej sesji.</div>`;
  }
}

// =============================================================================
// Nodes Status UI Updates
// =============================================================================

function updateNodesUI(state) {
  if (!state) return;

  function updateCard(nodeId, data, balElId, badgeElId, stockElId, labelPrefix) {
    if (!data) return;
    const card = document.getElementById(`card-${nodeId}`);

    if (data.balance !== null && data.balance !== undefined) {
      const formattedBal = `${data.balance.toFixed(2)} PLN`;
      const badge = document.getElementById(badgeElId);
      const statBal = document.getElementById(balElId);

      if (statBal && statBal.textContent !== formattedBal && statBal.textContent !== "-- PLN") {
        if (card) {
          card.classList.remove("flash-update");
          void card.offsetWidth; // trigger reflow
          card.classList.add("flash-update");
        }
      }

      if (badge) badge.textContent = formattedBal;
      if (statBal) statBal.textContent = formattedBal;
    }

    const stockEl = document.getElementById(stockElId);
    if (stockEl) {
      stockEl.textContent = `${labelPrefix}: ${data.stock_count || 11} poz.`;
    }
  }

  updateCard("H1", state.H1, "stat-h1-bal", "badge-bal-H1", "stat-h1-stock", "Magazyn");
  updateCard("H2", state.H2, "stat-h2-bal", "badge-bal-H2", "stat-h2-stock", "Magazyn");
  updateCard("R1", state.R1, "stat-r1-bal", "badge-bal-R1", "stat-r1-stock", "Spiżarnia");
  updateCard("R2", state.R2, "stat-r2-bal", "badge-bal-R2", "stat-r2-stock", "Magazyn");

  if (state.P1) {
    const p1Stock = document.getElementById("stat-p1-stock");
    if (p1Stock) p1Stock.textContent = `Katalog: ${state.P1.stock_count || 11} surowców`;
  }
}

// =============================================================================
// Actions: Trigger Scenarios, HITL Confirmation, Reset
// =============================================================================

async function triggerScenario(scenarioId) {
  const scen = SCENARIOS[scenarioId];
  if (!scen) return;

  activeScenarioId = scenarioId;

  // Visual selection
  document.querySelectorAll(".scenario-card").forEach((btn) => btn.classList.remove("active"));
  const btn = document.getElementById(`btn-scen-${scenarioId}`);
  if (btn) btn.classList.add("active");

  try {
    const res = await fetch(scen.endpoint, { method: "POST" });
    const data = await res.json();
    console.log(`Scenario ${scenarioId} started:`, data);
  } catch (e) {
    alert(`Błąd uruchomienia scenariusza ${scenarioId}: ${e.message || e}`);
  }
}

async function submitHitlDecision(decision) {
  try {
    const res = await fetch("/api/simulate/hitl-confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    const data = await res.json();
    console.log("HITL Decision submitted:", data);
    document.getElementById("hitl-action-box").style.display = "none";
  } catch (e) {
    alert(`Błąd zatwierdzenia decyzji: ${e.message || e}`);
  }
}

async function resetDemonstration() {
  try {
    await fetch("/api/simulate/reset", { method: "POST" });
    document.querySelectorAll(".scenario-card").forEach((btn) => btn.classList.remove("active"));
    activeScenarioId = null;
    updateStepper(0);

    document.getElementById("banner-badge").textContent = "GOTOWY";
    document.getElementById("banner-title").textContent = "Wybierz scenariusz u góry";
    document.getElementById("banner-desc").textContent = "Kliknij jeden z 4 kafelków scenariuszy na pasku powyżej, aby zobaczyć demonstrację przebiegu handlu agentów krok po kroku.";

    document.getElementById("current-step-label").textContent = "Oczekiwanie na start";
    document.getElementById("narrative-headline").textContent = "Wizualizacja Przebiegu Handlu";
    document.getElementById("narrative-story").textContent = "Nakładka prezentuje w czasie rzeczywistym 5-etapowy protokół negocjacji i handlu agentowego (Contract Net Protocol w standardzie MCP). Wybierz scenariusz, aby obserwować wymianę wiadomości.";
    document.getElementById("narrative-rule-text").textContent = "Protokół gwarantuje spójność ACID, zasadę milczenia wobec przegranych ofert oraz atomowe rozliczenie finansowo-magazynowe.";
    document.getElementById("current-route-pill").style.display = "none";
    document.getElementById("hitl-action-box").style.display = "none";

    clearStepLog();
  } catch (e) {
    console.warn("Reset error:", e);
  }
}

// =============================================================================
// Modals
// =============================================================================

function showNodeDetails(nodeId) {
  const node = NODE_COORDS[nodeId];
  const data = currentNodesData[nodeId];
  if (!node) return;

  document.getElementById("node-modal-title").textContent = `${node.name} (${nodeId})`;
  const container = document.getElementById("node-modal-content");

  let balHtml = data && data.balance !== null && data.balance !== undefined
    ? `<p><b>Saldo portfela:</b> <span style="color:#10b981;font-weight:700;">${data.balance.toFixed(2)} PLN</span></p>`
    : `<p><b>Rola:</b> Sprzedający (Producent P1)</p>`;
  let txHtml = data && data.transactions_count !== undefined
    ? `<p><b>Zarejestrowane transakcje w SQLite:</b> ${data.transactions_count}</p>`
    : "";

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

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// =============================================================================
// DOM Initializer
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();

  // Speed slider listener
  const speedSlider = document.getElementById("speed-slider");
  const speedVal = document.getElementById("speed-val");
  if (speedSlider) {
    speedSlider.addEventListener("input", (e) => {
      currentFlightDuration = parseInt(e.target.value);
      speedVal.textContent = `${(currentFlightDuration / 1000).toFixed(1)}s`;
    });
  }

  // Sound toggle listener
  const soundBtn = document.getElementById("btn-sound");
  const soundIcon = document.getElementById("sound-icon");
  if (soundBtn) {
    soundBtn.addEventListener("click", () => {
      soundEnabled = !soundEnabled;
      soundIcon.textContent = soundEnabled ? "🔊" : "🔇";
    });
  }

  // Node Clicking on SVG
  document.querySelectorAll(".graph-node").forEach((el) => {
    el.addEventListener("click", () => {
      const nid = el.getAttribute("data-node");
      showNodeDetails(nid);
    });
  });

  // Close modals on clicking backdrop
  window.addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-backdrop")) {
      e.target.classList.remove("open");
    }
  });
});
