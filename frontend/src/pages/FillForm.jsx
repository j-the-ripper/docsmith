import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'
import { Steps, useToast } from '../App.jsx'
import RichTextEditor from '../components/RichTextEditor.jsx'

export default function FillForm() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [doc, setDoc] = useState(null)
  const [values, setValues] = useState({})
  const [previewUrl, setPreviewUrl] = useState(null)
  const [rendering, setRendering] = useState(false)
  const [fills, setFills] = useState([])
  const [fonts, setFonts] = useState([])
  const urlRef = useRef(null)

  useEffect(() => {
    api.getDocument(id).then((d) => {
      setDoc(d)
      const init = {}
      d.placeholders.forEach((p) => { init[p.key] = p.default_value || '' })
      setValues(init)
    }).catch((e) => toast(e.message, 'error'))
    api.listFills(id).then(setFills).catch(() => {})
    api.getFonts().then(setFonts).catch(() => {})
  }, [id])

  async function changeFont(font) {
    try {
      const updated = await api.setFont(id, font)
      setDoc(updated)
      toast(`Font: ${font}`)
      generatePreview(values) // the PDF preview is the specimen — re-render now
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  // Render a fresh preview once the template + values are ready.
  useEffect(() => { if (doc) generatePreview(values) }, [doc]) // eslint-disable-line

  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }, [])

  async function generatePreview(vals) {
    setRendering(true)
    try {
      const blob = await api.renderBlob(id, vals, false)
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
      const url = URL.createObjectURL(blob)
      urlRef.current = url
      setPreviewUrl(url)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setRendering(false)
    }
  }

  async function exportPdf() {
    try {
      const blob = await api.renderBlob(id, values, true)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${doc.name || 'document'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  async function saveDraft() {
    const name = prompt('Name this draft:', 'Draft')
    if (name === null) return
    try {
      await api.saveFill(id, name || 'Draft', values)
      const list = await api.listFills(id)
      setFills(list)
      toast('Draft saved')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  function applyDraft(fillId) {
    const f = fills.find((x) => x.id === fillId)
    if (!f) return
    const merged = {}
    doc.placeholders.forEach((p) => { merged[p.key] = f.values[p.key] ?? '' })
    setValues(merged)
    generatePreview(merged)
    toast(`Loaded “${f.name}”`)
  }

  if (!doc) return <div className="container"><div className="row muted"><span className="spinner" /> Loading…</div></div>

  if (doc.placeholders.length === 0) {
    return (
      <div className="container">
        <div className="empty">
          This document has no placeholders yet.
          <div className="mt"><button className="btn btn-primary" onClick={() => navigate(`/documents/${id}/template`)}>Go mark placeholders →</button></div>
        </div>
      </div>
    )
  }

  return (
    <div className="container container-wide">
      <div className="row-between" style={{ marginBottom: '1.25rem' }}>
        <div>
          <h1>{doc.name}</h1>
          <p className="muted">Fill each field — format values as you like. The preview reflows to fit.</p>
        </div>
        <Steps active={2} />
      </div>

      <div className="fill-grid">
        <div>
          <div className="card card-pad">
            <div className="row-between wrap" style={{ marginBottom: '0.75rem' }}>
              <h3 style={{ margin: 0 }}>Fields</h3>
              <div className="row wrap" style={{ gap: '0.4rem' }}>
                {fills.length > 0 && (
                  <select className="input btn-sm" style={{ width: 'auto' }} defaultValue=""
                    onChange={(e) => { if (e.target.value) applyDraft(e.target.value); e.target.value = '' }}>
                    <option value="">Load draft…</option>
                    {fills.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                  </select>
                )}
                <button className="btn btn-sm" onClick={saveDraft}>Save draft</button>
              </div>
            </div>

            <div className="stack">
              {doc.placeholders.map((p) => (
                <div key={p.key} className="field" style={{ marginBottom: 0 }}>
                  <label>{p.label || p.key} <span className="faint" style={{ fontWeight: 400 }}>{`{{ ${p.key} }}`}</span></label>
                  <RichTextEditor
                    value={values[p.key] || ''}
                    onChange={(html) => setValues((v) => ({ ...v, [p.key]: html }))}
                    placeholder={p.help_text || `Enter ${(p.label || p.key).toLowerCase()}…`}
                  />
                </div>
              ))}
            </div>

            {fonts.length > 0 && (
              <div className="field mt-2" style={{ marginBottom: 0 }}>
                <label>Document font <span className="faint" style={{ fontWeight: 400 }}>(applies to preview &amp; export)</span></label>
                <select className="input" value={doc.font} onChange={(e) => changeFont(e.target.value)}>
                  {fonts.map((f) => <option key={f.name} value={f.name}>{f.label}</option>)}
                </select>
              </div>
            )}

            <div className="row wrap mt-2" style={{ gap: '0.6rem' }}>
              <button className="btn btn-primary" onClick={() => generatePreview(values)} disabled={rendering}>
                {rendering ? <><span className="spinner" /> Rendering…</> : '↻ Update preview'}
              </button>
              <button className="btn" onClick={exportPdf}>⬇ Export PDF</button>
              <button className="btn btn-ghost" onClick={() => navigate(`/documents/${id}/template`)}>Edit placeholders</button>
            </div>
          </div>
        </div>

        <div className="preview-pane">
          {previewUrl ? (
            <iframe className="preview-frame" title="PDF preview" src={previewUrl} />
          ) : (
            <div className="preview-empty">{rendering ? <span className="row"><span className="spinner" /> Rendering preview…</span> : 'Preview will appear here'}</div>
          )}
        </div>
      </div>
    </div>
  )
}
