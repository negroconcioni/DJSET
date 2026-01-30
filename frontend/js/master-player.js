/**
 * Master player — Wavesurfer.js solo para la mezcla final.
 * Color de onda: $orange-xapo (#FF5C00).
 */

const WAVE_COLOR = '#FF5C00';
const PROGRESS_COLOR = '#FF5C00';
const CURSOR_COLOR = 'rgba(255, 92, 0, 0.5)';

let wavesurfer = null;
let timeInterval = null;

function formatTime(sec) {
  if (sec == null || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function stopTimeInterval() {
  if (timeInterval) {
    clearInterval(timeInterval);
    timeInterval = null;
  }
}

/**
 * Inicializa el reproductor Master con la URL del mix.
 * Requiere WaveSurfer como dependencia (inyectado desde app.js).
 * @param {object} WaveSurfer — módulo de wavesurfer.js
 * @param {string} mixUrl — URL del audio (ej. /download/{sessionId})
 * @param {object} elements — { containerId, playPauseBtnId, timeId }
 * @returns {Promise<void>} — resuelve cuando la onda está lista
 */
export async function initMasterPlayer(WaveSurfer, mixUrl, elements) {
  const { containerId, playPauseBtnId, timeId } = elements;
  const container = document.getElementById(containerId);
  const playPauseBtn = document.getElementById(playPauseBtnId);
  const timeEl = document.getElementById(timeId);

  if (!container || !playPauseBtn || !timeEl) return;

  if (wavesurfer) {
    wavesurfer.destroy();
    wavesurfer = null;
    stopTimeInterval();
  }

  function updateTime() {
    if (!wavesurfer) return;
    const current = wavesurfer.getCurrentTime();
    const duration = wavesurfer.getDuration();
    timeEl.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
  }

  wavesurfer = WaveSurfer.create({
    container: `#${containerId}`,
    waveColor: WAVE_COLOR,
    progressColor: PROGRESS_COLOR,
    cursorColor: CURSOR_COLOR,
    cursorWidth: 1,
    barWidth: 1,
    barGap: 1,
    height: 80,
    normalize: true,
  });

  wavesurfer.load(mixUrl);
  playPauseBtn.disabled = true;
  timeEl.textContent = '0:00 / 0:00';

  return new Promise((resolve) => {
    wavesurfer.on('ready', () => {
      playPauseBtn.disabled = false;
      updateTime();
      resolve();
    });

    wavesurfer.on('play', () => {
      playPauseBtn.textContent = '❚❚';
      if (!timeInterval) timeInterval = setInterval(updateTime, 250);
    });

    wavesurfer.on('pause', () => {
      playPauseBtn.textContent = '▶';
      stopTimeInterval();
    });

    wavesurfer.on('finish', () => {
      stopTimeInterval();
      playPauseBtn.textContent = '▶';
      updateTime();
    });

    wavesurfer.on('interaction', updateTime);

    playPauseBtn.textContent = '▶';
    playPauseBtn.onclick = () => {
      if (wavesurfer) wavesurfer.playPause();
    };
  });
}

/**
 * Destruye el reproductor y limpia el intervalo de tiempo.
 */
export function destroyMasterPlayer() {
  if (wavesurfer) {
    wavesurfer.destroy();
    wavesurfer = null;
  }
  stopTimeInterval();
}
