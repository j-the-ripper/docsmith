import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { Steps, useToast } from '../App.jsx'

function fmtDate(s) {
  try { return new Date(s).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return '' }
}

export default function Home() {
  const [docs, setDocs] = useState(null)
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const inputRef = useRef(null)
  const navigate = useNavigate()
  const toast = useToast()

  const load = () => api.listDocuments().then(setDocs).catch((e) => toast(e.message, 'error'))
  useEffect(() => { load() }, [])

  async function upload(file) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) return toast('Please choose a PDF file', 'error')
    setBusy(true)
    try {
      const doc = await api.uploadDocument(file)
      toast('Uploaded — extracting text…')
      navigate(`/documents/${doc.id}/template`)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function remove(e, id) {
    e.stopPropagation()
    if (!confirm('Delete this document and its template?')) return
    try { await api.deleteDocument(id); load() }
    catch (err) { toast(err.message, 'error') }
  }

  return (
    <div className="container">
      <div className="row-between" style={{ marginBottom: '1.5rem' }}>
        <div>
          <h1>Turn a PDF into a fill-in template</h1>
          <p className="muted" style={{ maxWidth: 560 }}>
            Upload a document, mark the parts that change as placeholders, then fill and export
            clean PDFs — long values reflow the text instead of overflowing.
          </p>
        </div>
        <Steps active={0} />
      </div>

      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files?.[0]) }}
      >
        {busy ? (
          <div className="row" style={{ justifyContent: 'center' }}><span className="spinner" /> Uploading &amp; extracting…</div>
        ) : (
          <>
            <div className="big">📄</div>
            <div style={{ fontWeight: 600, fontSize: '1.1rem' }}>Drop a PDF here, or click to browse</div>
            <div className="hint">We extract the text so you can mark placeholders. Legacy-font pages can be OCR&rsquo;d next.</div>
          </>
        )}
        <input ref={inputRef} type="file" accept="application/pdf" hidden
          onChange={(e) => upload(e.target.files?.[0])} />
      </div>

      <h2 className="mt-2">Your documents</h2>
      {docs === null && <div className="row muted"><span className="spinner" /> Loading…</div>}
      {docs && docs.length === 0 && <div className="empty">No documents yet — upload one above to get started.</div>}
      {docs && docs.length > 0 && (
        <div className="doc-list">
          {docs.map((d) => (
            <div key={d.id} className="card doc-card"
              onClick={() => navigate(`/documents/${d.id}/${d.status === 'template_ready' ? 'fill' : 'template'}`)}>
              <div className="row-between">
                <div className="name">{d.name}</div>
                <span className={`badge ${d.status}`}>
                  {d.status === 'template_ready' ? 'ready' : d.status === 'processing' ? 'OCR…' : 'draft'}
                </span>
              </div>
              <div className="meta">{d.page_count} page{d.page_count === 1 ? '' : 's'} · {fmtDate(d.created_at)}</div>
              <div className="row" style={{ marginTop: '0.8rem', justifyContent: 'flex-end' }}>
                <button className="btn btn-danger btn-sm" onClick={(e) => remove(e, d.id)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
