// Thin fetch wrapper around the DocSmith API. Same-origin: Caddy (prod) or the
// Vite dev proxy (dev) forwards /api to FastAPI.
const BASE = '/api'

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res
}

export const api = {
  listDocuments: () => req('/documents').then((r) => r.json()),
  getDocument: (id) => req(`/documents/${id}`).then((r) => r.json()),

  uploadDocument: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return req('/documents', { method: 'POST', body: fd }).then((r) => r.json())
  },

  ocrPage: (id, page) =>
    req(`/documents/${id}/pages/${page}/ocr`, { method: 'POST' }).then((r) => r.json()),

  ocrAll: (id) => req(`/documents/${id}/ocr`, { method: 'POST' }).then((r) => r.json()),

  getFonts: () => req('/fonts').then((r) => r.json()),

  setFont: (id, font) =>
    req(`/documents/${id}/font`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ font }),
    }).then((r) => r.json()),

  saveTemplate: (id, payload) =>
    req(`/documents/${id}/template`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then((r) => r.json()),

  deleteDocument: (id) => req(`/documents/${id}`, { method: 'DELETE' }),

  renderBlob: (id, values, download = false) =>
    req(`/documents/${id}/render?download=${download}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    }).then((r) => r.blob()),

  saveFill: (id, name, values) =>
    req(`/documents/${id}/fills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, values }),
    }).then((r) => r.json()),

  listFills: (id) => req(`/documents/${id}/fills`).then((r) => r.json()),
}
