/**
 * Admin — The Lab: same Opus/Xapo aesthetic, training UI.
 * Load/save config, DEBUG CONSOLE with raw JSON, POST /admin/update-config.
 */

const API = window.location.origin;

const systemPromptEl = document.getElementById("systemPrompt");
const bpmSensitivityEl = document.getElementById("bpmSensitivity");
const bpmSensitivityVal = document.getElementById("bpmSensitivityVal");
const harmonicPriorityEl = document.getElementById("harmonicPriority");
const harmonicPriorityVal = document.getElementById("harmonicPriorityVal");
const bassSwapIntensityEl = document.getElementById("bassSwapIntensity");
const bassSwapIntensityVal = document.getElementById("bassSwapIntensityVal");
const defaultBarsEl = document.getElementById("defaultBars");
const allowInstrumentsAiEl = document.getElementById("allowInstrumentsAi");
const allowVocalsAiEl = document.getElementById("allowVocalsAi");
const debugBodyEl = document.getElementById("debugBody");
const btnSaveTrain = document.getElementById("btnSaveTrain");
const statusMsg = document.getElementById("statusMsg");

const MAX_DEBUG_LINES = 80;

/** Presets from server (keep on save so we don't wipe them). */
let presets = [];

function setStatus(msg, isError = false) {
  statusMsg.textContent = msg;
  statusMsg.className = "admin-status-msg" + (msg ? (isError ? " err" : " ok") : "");
}

function debugLog(text, type = "in") {
  const line = document.createElement("div");
  line.className = "line " + type;
  line.textContent = text;
  debugBodyEl.appendChild(line);
  while (debugBodyEl.children.length > MAX_DEBUG_LINES) {
    debugBodyEl.removeChild(debugBodyEl.firstChild);
  }
  debugBodyEl.scrollTop = debugBodyEl.scrollHeight;
}

function debugJson(label, obj, type = "out") {
  try {
    const str = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    debugLog(label + "\n" + str, type);
  } catch (e) {
    debugLog(label + " (serialize error: " + e.message + ")", "err");
  }
}

// mix_sensitivity: 0 = BPM, 1 = harmony. UI: BPM Sensitivity = 1 - mix_sensitivity, Harmonic Priority = mix_sensitivity
function syncSlidersFromMixSensitivity(mixSensitivity) {
  const s = Math.max(0, Math.min(1, parseFloat(mixSensitivity) || 0.5));
  harmonicPriorityEl.value = s;
  harmonicPriorityVal.textContent = s;
  bpmSensitivityEl.value = 1 - s;
  bpmSensitivityVal.textContent = (1 - s).toFixed(2);
}

function getMixSensitivityFromSliders() {
  return parseFloat(harmonicPriorityEl.value) || 0.5;
}

async function loadConfig() {
  setStatus("");
  debugLog("[LOAD] GET /admin/config", "in");
  try {
    const r = await fetch(API + "/admin/config");
    if (!r.ok) throw new Error(r.statusText);
    const data = await r.json();
    debugJson("[LOAD] Response", data, "out");

    systemPromptEl.value = data.system_prompt ?? "";
    syncSlidersFromMixSensitivity(data.mix_sensitivity);
    presets = Array.isArray(data.presets) ? data.presets : [];
    const bars = parseInt(data.default_bars, 10);
    if ([16, 32, 64].includes(bars)) {
      const radio = defaultBarsEl.querySelector(`input[value="${bars}"]`);
      if (radio) radio.checked = true;
    }
    const bass = parseFloat(data.bass_swap_intensity);
    if (!Number.isNaN(bass)) {
      bassSwapIntensityEl.value = bass;
      bassSwapIntensityVal.textContent = bass;
    }
    if (allowInstrumentsAiEl) allowInstrumentsAiEl.checked = !!data.allow_instruments_ai;
    if (allowVocalsAiEl) allowVocalsAiEl.checked = !!data.allow_vocals_ai;
    setStatus("");
  } catch (e) {
    setStatus("Error al cargar: " + e.message, true);
    debugLog("[LOAD] Error: " + e.message, "err");
  }
}

async function saveConfig() {
  const barsRadio = defaultBarsEl.querySelector("input:checked");
  const defaultBars = barsRadio ? parseInt(barsRadio.value, 10) : 32;

  const body = {
    system_prompt: systemPromptEl.value,
    mix_sensitivity: getMixSensitivityFromSliders(),
    default_bars: [16, 32, 64].includes(defaultBars) ? defaultBars : 32,
    bass_swap_intensity: parseFloat(bassSwapIntensityEl.value) || 0.5,
    presets,
    allow_instruments_ai: allowInstrumentsAiEl ? allowInstrumentsAiEl.checked : false,
    allow_vocals_ai: allowVocalsAiEl ? allowVocalsAiEl.checked : false,
  };

  debugLog("[SAVE] POST /admin/update-config", "in");
  debugJson("[SAVE] Request body", body, "out");

  btnSaveTrain.disabled = true;
  setStatus("Guardando…");
  try {
    const r = await fetch(API + "/admin/update-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const text = await r.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    debugJson("[SAVE] Response", data, r.ok ? "out" : "err");

    if (!r.ok) throw new Error(data.detail || data.raw || text || r.statusText);

    syncSlidersFromMixSensitivity(data.mix_sensitivity);
    setStatus("Configuración guardada. Se aplica en tiempo real.");
  } catch (e) {
    setStatus("Error: " + e.message, true);
    debugLog("[SAVE] Error: " + e.message, "err");
  } finally {
    btnSaveTrain.disabled = false;
  }
}

bpmSensitivityEl.addEventListener("input", () => {
  const v = parseFloat(bpmSensitivityEl.value) || 0;
  bpmSensitivityVal.textContent = v.toFixed(2);
  harmonicPriorityEl.value = (1 - v).toFixed(2);
  harmonicPriorityVal.textContent = (1 - v).toFixed(2);
});
harmonicPriorityEl.addEventListener("input", () => {
  const v = parseFloat(harmonicPriorityEl.value) || 0;
  harmonicPriorityVal.textContent = v.toFixed(2);
  bpmSensitivityEl.value = (1 - v).toFixed(2);
  bpmSensitivityVal.textContent = (1 - v).toFixed(2);
});
bassSwapIntensityEl.addEventListener("input", () => {
  bassSwapIntensityVal.textContent = bassSwapIntensityEl.value;
});

btnSaveTrain.addEventListener("click", saveConfig);

loadConfig();
