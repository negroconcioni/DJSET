/**
 * OPUS AI — App principal. Conecta UI, API y Master Player.
 * Sin lógica de API dentro del HTML.
 */

import * as api from './api.js';
import { initMasterPlayer, destroyMasterPlayer } from './master-player.js';

const RECENT_SESSIONS_KEY = 'opus_recent_sessions';
const RECENT_SESSIONS_MAX = 10;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const refs = {
  fileA: document.getElementById('fileA'),
  fileB: document.getElementById('fileB'),
  slotA: document.getElementById('slotA'),
  slotB: document.getElementById('slotB'),
  nameA: document.getElementById('nameA'),
  nameB: document.getElementById('nameB'),
  userPrompt: document.getElementById('userPrompt'),
  btnGenerate: document.getElementById('btnGenerate'),
  progressBar: document.getElementById('progressBar'),
  insightBody: document.getElementById('insightBody'),
  masterPlayer: document.getElementById('master-player'),
  downloadLink: document.getElementById('downloadLink'),
  masterFilename: document.getElementById('masterFilename'),
  sessionList: document.getElementById('sessionList'),
  harmonicBadgeA: document.getElementById('harmonicBadgeA'),
  harmonicBadgeB: document.getElementById('harmonicBadgeB'),
  sparklineWrapA: document.getElementById('sparklineWrapA'),
  sparklineWrapB: document.getElementById('sparklineWrapB'),
  sparklineA: document.getElementById('sparklineA'),
  sparklineB: document.getElementById('sparklineB'),
  folderZone: document.getElementById('folderZone'),
  folderInput: document.getElementById('folderInput'),
  folderName: document.getElementById('folderName'),
  progressContainer: document.getElementById('progress-container'),
  progressBarFill: document.getElementById('progressBarFill'),
  progressStatus: document.getElementById('progressStatus'),
  folderDownloadBlock: document.getElementById('folder-download-block'),
  downloadSetLink: document.getElementById('downloadSetLink'),
  downloadTracklistLink: document.getElementById('downloadTracklistLink'),
};

let sessionId = null;

// ---------------------------------------------------------------------------
// Musical Insight Terminal
// ---------------------------------------------------------------------------
function log(line, type = 'sys') {
  const div = document.createElement('div');
  div.className = `line ${type}`;
  div.textContent = line;
  refs.insightBody.appendChild(div);
  refs.insightBody.scrollTop = refs.insightBody.scrollHeight;
}

function logClear() {
  refs.insightBody.innerHTML = '';
}

// ---------------------------------------------------------------------------
// Estados: barra de progreso fina (Cargando / Procesando)
// ---------------------------------------------------------------------------
function setProgressVisible(visible) {
  refs.progressBar.setAttribute('aria-hidden', visible ? 'false' : 'true');
}

// ---------------------------------------------------------------------------
// Upload hub — slots que se iluminan en naranja al recibir archivo
// ---------------------------------------------------------------------------
async function ensureSession() {
  if (sessionId) return sessionId;
  const d = await api.createSession();
  sessionId = d.session_id;
  return sessionId;
}

function updateGenerateButton() {
  refs.btnGenerate.disabled = !refs.fileA.files?.[0] || !refs.fileB.files?.[0];
}

function energy01To110(energy) {
  if (energy == null || typeof energy !== 'number') return '—';
  const e = Math.max(0, Math.min(1, energy));
  return Math.max(1, Math.min(10, Math.round(e * 9 + 1)));
}

function fillBadges(analysisA, analysisB) {
  if (analysisA) {
    const valBpmA = document.getElementById('valBpmA');
    const valKeyA = document.getElementById('valKeyA');
    const valEnergyA = document.getElementById('valEnergyA');
    if (valBpmA) { valBpmA.textContent = analysisA.bpm != null ? Math.round(analysisA.bpm) : '—'; valBpmA.classList.add('filled'); }
    if (valKeyA) { valKeyA.textContent = (analysisA.key ?? '—') + (analysisA.key_scale ? ` ${analysisA.key_scale}` : ''); valKeyA.classList.add('filled'); }
    if (valEnergyA) { valEnergyA.textContent = energy01To110(analysisA.energy); valEnergyA.classList.add('filled'); }
  }
  if (analysisB) {
    const valBpmB = document.getElementById('valBpmB');
    const valKeyB = document.getElementById('valKeyB');
    const valEnergyB = document.getElementById('valEnergyB');
    if (valBpmB) { valBpmB.textContent = analysisB.bpm != null ? Math.round(analysisB.bpm) : '—'; valBpmB.classList.add('filled'); }
    if (valKeyB) { valKeyB.textContent = (analysisB.key ?? '—') + (analysisB.key_scale ? ` ${analysisB.key_scale}` : ''); valKeyB.classList.add('filled'); }
    if (valEnergyB) { valEnergyB.textContent = energy01To110(analysisB.energy); valEnergyB.classList.add('filled'); }
  }
}

function setHarmonicBadge(visible) {
  if (refs.harmonicBadgeA) {
    refs.harmonicBadgeA.classList.toggle('is-visible', !!visible);
    refs.harmonicBadgeA.setAttribute('aria-hidden', visible ? 'false' : 'true');
  }
  if (refs.harmonicBadgeB) {
    refs.harmonicBadgeB.classList.toggle('is-visible', !!visible);
    refs.harmonicBadgeB.setAttribute('aria-hidden', visible ? 'false' : 'true');
  }
}

// ---------------------------------------------------------------------------
// Sesiones Recientes — sidebar
// ---------------------------------------------------------------------------
function getRecentSessions() {
  try {
    const raw = localStorage.getItem(RECENT_SESSIONS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.slice(0, RECENT_SESSIONS_MAX) : [];
  } catch {
    return [];
  }
}

function saveRecentSession(sessionId, name) {
  const list = getRecentSessions();
  const entry = { session_id: sessionId, name: name || `Mix ${new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}`, date: Date.now() };
  const filtered = list.filter((e) => e.session_id !== sessionId);
  filtered.unshift(entry);
  localStorage.setItem(RECENT_SESSIONS_KEY, JSON.stringify(filtered.slice(0, RECENT_SESSIONS_MAX)));
  renderSessionList();
}

function renderSessionList() {
  if (!refs.sessionList) return;
  refs.sessionList.innerHTML = '';
  const sessions = getRecentSessions();
  sessions.forEach((entry) => {
    const li = document.createElement('li');
    li.className = 'session-item';
    const name = document.createElement('span');
    name.className = 'session-name';
    name.title = entry.name;
    name.textContent = entry.name;
    const playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.className = 'btn-session-play';
    playBtn.title = 'Reproducir';
    playBtn.textContent = '▶';
    playBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      playSession(entry.session_id);
    });
    li.appendChild(name);
    li.appendChild(playBtn);
    refs.sessionList.appendChild(li);
  });
}

function playSession(sid) {
  const url = api.getDownloadUrl(sid);
  const audio = new Audio(url);
  audio.play().catch(() => {});
}

// ---------------------------------------------------------------------------
// Sparkline — energía del track (RMS por ventana)
// ---------------------------------------------------------------------------
async function drawSparkline(file, canvasEl, wrapEl) {
  if (!canvasEl || !wrapEl) return;
  wrapEl.classList.remove('is-visible');
  wrapEl.setAttribute('aria-hidden', 'true');
  if (!file) return;
  try {
    const arrayBuffer = await file.arrayBuffer();
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await audioContext.decodeAudioData(arrayBuffer);
    const channel = decoded.length > 0 ? decoded.getChannelData(0) : new Float32Array(0);
    const sampleRate = decoded.sampleRate;
    const windowSec = 0.5;
    const windowSamples = Math.floor(sampleRate * windowSec);
    const numWindows = Math.floor(channel.length / windowSamples) || 1;
    const rms = [];
    for (let i = 0; i < numWindows; i++) {
      let sum = 0;
      const start = i * windowSamples;
      const end = Math.min(start + windowSamples, channel.length);
      for (let j = start; j < end; j++) {
        sum += channel[j] * channel[j];
      }
      rms.push(Math.sqrt(sum / (end - start)) || 0);
    }
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    const w = canvasEl.width;
    const h = canvasEl.height;
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, w, h);
    if (rms.length < 2) return;
    const maxRms = Math.max(...rms, 1e-6);
    ctx.strokeStyle = '#FF5C00';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < rms.length; i++) {
      const x = (i / (rms.length - 1)) * w;
      const y = h - (rms[i] / maxRms) * (h - 2) - 1;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    wrapEl.classList.add('is-visible');
    wrapEl.setAttribute('aria-hidden', 'false');
  } catch {
    wrapEl.classList.remove('is-visible');
  }
}

function handleFileChange(slot, fileInput, nameEl, slotEl) {
  const file = fileInput.files?.[0];
  const sparkCanvas = slot === 'a' ? refs.sparklineA : refs.sparklineB;
  const sparkWrap = slot === 'a' ? refs.sparklineWrapA : refs.sparklineWrapB;
  if (file) {
    nameEl.textContent = file.name;
    slotEl.classList.add('has-file');
    ensureSession()
      .then((sid) => api.uploadTrack(sid, slot, file))
      .then(() => log('> System: Track uploaded.'))
      .catch((err) => {
        nameEl.textContent = 'Error';
        log(`> Error: ${err.message}`, 'err');
      })
      .finally(updateGenerateButton);
    drawSparkline(file, sparkCanvas, sparkWrap);
  } else {
    nameEl.textContent = 'Elegir archivo';
    slotEl.classList.remove('has-file');
    if (sparkWrap) {
      sparkWrap.classList.remove('is-visible');
      sparkWrap.setAttribute('aria-hidden', 'true');
    }
    if (sparkCanvas) {
      const ctx = sparkCanvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, sparkCanvas.width, sparkCanvas.height);
    }
    const suf = slot === 'a' ? 'A' : 'B';
    const vB = document.getElementById(`valBpm${suf}`);
    const vK = document.getElementById(`valKey${suf}`);
    const vE = document.getElementById(`valEnergy${suf}`);
    if (vB) { vB.textContent = '—'; vB.classList.remove('filled'); }
    if (vK) { vK.textContent = '—'; vK.classList.remove('filled'); }
    if (vE) { vE.textContent = '—'; vE.classList.remove('filled'); }
    setHarmonicBadge(false);
    updateGenerateButton();
  }
}

// ---------------------------------------------------------------------------
// Generate mix — polling y mostrar Master con fade-in
// ---------------------------------------------------------------------------
async function runGenerate() {
  if (!sessionId) await ensureSession();
  refs.btnGenerate.disabled = true;
  refs.masterPlayer.classList.remove('is-visible');
  refs.masterPlayer.setAttribute('aria-hidden', 'true');
  logClear();
  log('> System: Analyzing...');
  setProgressVisible(true);

  try {
    const userPrompt = (refs.userPrompt?.value ?? '').trim();
    await api.generateMix(sessionId, userPrompt);
    log('> System: Mix in progress...');

    let st = await api.getStatus(sessionId);
    while (st.status === 'processing') {
      await new Promise((r) => setTimeout(r, 2000));
      st = await api.getStatus(sessionId);
    }

    setProgressVisible(false);

    if (st.status === 'failed') {
      log(`> Error: ${st.error ?? 'Generation failed'}`, 'err');
      return;
    }

    const a = st.analysis_a ?? {};
    const b = st.analysis_b ?? {};
    const s = st.strategy ?? {};
    fillBadges(a, b);

    const harmonicDist = s.harmonic_distance;
    const isHarmonicMatch = harmonicDist !== undefined && harmonicDist !== null && harmonicDist <= 1;
    setHarmonicBadge(isHarmonicMatch);

    const keyA = (a.key ?? '—') + (a.key_scale ? ` ${a.key_scale}` : '') + (a.key_camelot ? ` (${a.key_camelot})` : '');
    const keyB = (b.key ?? '—') + (b.key_scale ? ` ${b.key_scale}` : '') + (b.key_camelot ? ` (${b.key_camelot})` : '');
    log(`> Keys: A = ${keyA}  |  B = ${keyB}`, 'key');

    const comment = (s.dj_comment ?? '').trim();
    const reasoning = (s.reasoning ?? '').trim();
    log('> System: Mix ready.');
    if (comment) log(`> DJ: ${comment}`, 'dj');
    if (reasoning) log(`> Reasoning: ${reasoning}`, 'reason');

    const mixName = (refs.nameA?.textContent && refs.nameB?.textContent)
      ? `${refs.nameA.textContent} + ${refs.nameB.textContent}`.slice(0, 40)
      : `Mix ${new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}`;
    saveRecentSession(sessionId, mixName);

    const mixUrl = api.getDownloadUrl(sessionId);
    refs.downloadLink.href = mixUrl;
    refs.masterFilename.textContent = 'automix_master.wav';

    const WaveSurfer = await import('https://unpkg.com/wavesurfer.js@7/dist/wavesurfer.esm.js').then((m) => m.default);
    await initMasterPlayer(WaveSurfer, mixUrl, {
      containerId: 'waveformMaster',
      playPauseBtnId: 'btnPlayPause',
      timeId: 'masterTime',
    });

    refs.masterPlayer.setAttribute('aria-hidden', 'false');
    refs.masterPlayer.classList.add('is-visible');
  } catch (err) {
    setProgressVisible(false);
    log(`> Error: ${err.message}`, 'err');
  } finally {
    refs.btnGenerate.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Folder / Crate — process-folder + polling + progress + deck pulse
// ---------------------------------------------------------------------------
const AUDIO_EXT = new Set(['.wav', '.mp3', '.flac', '.ogg', '.m4a']);

function getStatusMessage(phase, current, total) {
  switch (phase) {
    case 'analyzing':
      return 'Analizando armonía y BPM de los tracks...';
    case 'sequencing':
      return 'Calculando secuencia óptima (Opus Engine)...';
    case 'rendering':
      if (total != null && total > 0 && current != null) {
        return `Mezclando Track ${current} de ${total} (Applying Bass-Swap)...`;
      }
      return 'Mezclando tracks (Applying Bass-Swap)...';
    case 'finalizing':
      return 'Masterizando set final (Loudness Pro)...';
    default:
      return 'Procesando...';
  }
}

function getProgressPercent(phase, current, total) {
  if (total != null && total > 0 && current != null) {
    if (phase === 'rendering') {
      return 20 + Math.round((current / total) * 60);
    }
    if (phase === 'finalizing') return 90;
  }
  switch (phase) {
    case 'analyzing': return 5;
    case 'sequencing': return 15;
    case 'rendering': return 25;
    case 'finalizing': return 90;
    default: return 10;
  }
}

function setDeckPulse(on) {
  refs.slotA?.classList.toggle('deck-pulse', !!on);
  refs.slotB?.classList.toggle('deck-pulse', !!on);
}

function showProgressContainer(show) {
  if (refs.progressContainer) {
    refs.progressContainer.classList.toggle('is-hidden', !show);
    refs.progressContainer.setAttribute('aria-hidden', show ? 'true' : 'false');
  }
}

function showFolderDownloadBlock(show, setUrl, tracklistUrl) {
  if (!refs.folderDownloadBlock) return;
  refs.folderDownloadBlock.classList.toggle('is-hidden', !show);
  if (show && refs.downloadSetLink && setUrl) {
    refs.downloadSetLink.href = setUrl.startsWith('http') ? setUrl : window.location.origin + setUrl;
  }
  if (show && refs.downloadTracklistLink && tracklistUrl) {
    refs.downloadTracklistLink.href = tracklistUrl.startsWith('http') ? tracklistUrl : window.location.origin + tracklistUrl;
  }
}

function connectSocketAndJoin(sessionId, onProgress) {
  if (typeof window === 'undefined' || !window.io) return null;
  try {
    const socket = window.io(window.location.origin, { path: '/socket.io', transports: ['websocket', 'polling'] });
    socket.emit('join_session', { session_id: sessionId });
    socket.on('progress', (data) => {
      if (data && onProgress) onProgress(data);
    });
    return socket;
  } catch (e) {
    return null;
  }
}

async function runProcessFolder(files) {
  const list = Array.from(files || []).filter((f) => {
    const ext = (f.name || '').toLowerCase().replace(/^.*\./, '');
    return AUDIO_EXT.has('.' + ext);
  });
  if (list.length < 2) {
    log('> Error: Necesitás al menos 2 archivos de audio en la carpeta.', 'err');
    return;
  }
  refs.folderZone?.classList.add('has-folder');
  refs.folderName.textContent = `${list.length} archivos`;
  showFolderDownloadBlock(false);
  showProgressContainer(true);
  setDeckPulse(true);
  refs.progressBarFill.style.width = '0%';
  refs.progressStatus.textContent = 'Subiendo carpeta...';

  let socket = null;
  try {
    const d = await api.processFolder(list);
    const folderSessionId = d.session_id;
    refs.progressStatus.textContent = getStatusMessage('analyzing');
    refs.progressBarFill.style.width = '5%';

    socket = connectSocketAndJoin(folderSessionId, (data) => {
      const phase = data.phase || 'analyzing';
      const msg = data.message || getStatusMessage(phase, data.current_segment, data.total_segments);
      const pct = getProgressPercent(phase, data.current_segment, data.total_segments);
      refs.progressStatus.textContent = msg;
      refs.progressBarFill.style.width = pct + '%';
    });

    const pollInterval = 2000;
    let st = await api.getProcessFolderStatus(folderSessionId);

    while (st.status === 'processing') {
      await new Promise((r) => setTimeout(r, pollInterval));
      st = await api.getProcessFolderStatus(folderSessionId);
      const phase = st.phase || 'analyzing';
      const msg = getStatusMessage(phase, st.current_segment, st.total_segments);
      const pct = getProgressPercent(phase, st.current_segment, st.total_segments);
      refs.progressStatus.textContent = msg;
      refs.progressBarFill.style.width = pct + '%';
    }

    setDeckPulse(false);
    showProgressContainer(false);
    refs.progressBarFill.style.width = '0%';
    if (socket) socket.disconnect();

    if (st.status === 'failed') {
      log(`> Error (carpeta): ${st.error ?? 'Proceso fallido'}`, 'err');
      return;
    }

    refs.progressStatus.textContent = 'Listo.';
    const setUrl = st.set_url ?? `/process-folder/${folderSessionId}/set`;
    const tracklistUrl = st.tracklist_url ?? `/process-folder/${folderSessionId}/tracklist`;
    showFolderDownloadBlock(true, setUrl, tracklistUrl);
    log('> System: Set listo. Descargá el WAV y el tracklist.');
  } catch (err) {
    setDeckPulse(false);
    showProgressContainer(false);
    if (socket) socket.disconnect();
    log(`> Error: ${err.message}`, 'err');
  }
}

function handleFolderChange() {
  const input = refs.folderInput;
  if (!input?.files?.length) return;
  runProcessFolder(input.files);
}

// ---------------------------------------------------------------------------
// Inicialización
// ---------------------------------------------------------------------------
function init() {
  log('> System: Ready. Upload Song A and B, then Generate mix. Or upload a folder / crate.');

  renderSessionList();

  refs.slotA.addEventListener('click', () => refs.fileA.click());
  refs.slotB.addEventListener('click', () => refs.fileB.click());

  refs.fileA.addEventListener('change', () => handleFileChange('a', refs.fileA, refs.nameA, refs.slotA));
  refs.fileB.addEventListener('change', () => handleFileChange('b', refs.fileB, refs.nameB, refs.slotB));

  if (refs.folderZone) {
    refs.folderZone.addEventListener('click', () => refs.folderInput?.click());
  }
  refs.folderInput?.addEventListener('change', handleFolderChange);

  refs.btnGenerate.addEventListener('click', runGenerate);

  setProgressVisible(false);
  showProgressContainer(false);
  showFolderDownloadBlock(false);
}

init();
