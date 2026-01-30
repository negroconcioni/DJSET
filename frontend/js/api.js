/**
 * FastAPI client — centraliza todas las llamadas al backend.
 * Base URL: window.location.origin (mismo host que sirve el frontend).
 */

const getBaseUrl = () => window.location.origin;

/**
 * Crea una sesión y devuelve { session_id }.
 * @returns {Promise<{ session_id: string }>}
 */
export async function createSession() {
  const r = await fetch(`${getBaseUrl()}/session`, { method: 'POST' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * Sube un archivo a un slot (a o b).
 * @param {string} sessionId
 * @param {'a'|'b'} slot
 * @param {File} file
 */
export async function uploadTrack(sessionId, slot, file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${getBaseUrl()}/upload/${sessionId}/${slot}`, {
    method: 'POST',
    body: fd,
  });
  if (!r.ok) throw new Error(await r.text());
}

/**
 * Inicia la generación de la mezcla.
 * @param {string} sessionId
 * @param {string} [userPrompt] — instrucción de estilo (opcional)
 * @returns {Promise<{ session_id: string, status: string, status_url: string, download_url: string }>}
 */
export async function generateMix(sessionId, userPrompt = '') {
  const body = userPrompt.trim() ? { user_prompt: userPrompt.trim() } : {};
  const r = await fetch(`${getBaseUrl()}/generate/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = Array.isArray(d.detail)
      ? (d.detail[0]?.msg ?? JSON.stringify(d.detail))
      : (d.detail ?? 'Error');
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return d;
}

/**
 * Consulta el estado del job de mezcla.
 * @param {string} sessionId
 * @returns {Promise<{ session_id: string, status: 'processing'|'ready'|'failed', download_url?: string, error?: string, analysis_a?: object, analysis_b?: object, strategy?: object }>}
 */
export async function getStatus(sessionId) {
  const r = await fetch(`${getBaseUrl()}/generate/${sessionId}/status`);
  return r.json().catch(() => ({}));
}

/**
 * URL para descargar el master (cuando status === 'ready').
 * @param {string} sessionId
 * @returns {string}
 */
export function getDownloadUrl(sessionId) {
  return `${getBaseUrl()}/download/${sessionId}`;
}

/**
 * Procesa una carpeta de tracks: sube archivos y arranca el pipeline del set.
 * @param {File[]} files — lista de archivos (p. ej. desde input webkitdirectory)
 * @returns {Promise<{ session_id: string, status: string, status_url: string, set_url: string, tracklist_url: string }>}
 */
export async function processFolder(files) {
  const fd = new FormData();
  files.forEach((file) => fd.append('files', file));
  const r = await fetch(`${getBaseUrl()}/process-folder`, {
    method: 'POST',
    body: fd,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = d.detail ?? d.error ?? await r.text();
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return d;
}

/**
 * Estado del job process-folder (polling).
 * @param {string} sessionId
 * @returns {Promise<{ session_id: string, status: 'processing'|'ready'|'failed', phase?: string, current_segment?: number, total_segments?: number, set_url?: string, tracklist_url?: string, error?: string }>}
 */
export async function getProcessFolderStatus(sessionId) {
  const r = await fetch(`${getBaseUrl()}/process-folder/${sessionId}/status`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
