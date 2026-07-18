import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'
import { Steps, useToast } from '../App.jsx'

// key <- arbitrary text, coerced to a valid jinja identifier (snake_case).
function slugKey(text) {
  let k = (text || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
  if (k && /^[0-9]/.test(k)) k = '_' + k
  return k
}

const titleCase = (k) => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

// {{ key }} -> highlighted, non-editable token span (for re-opening a saved template).
function tokensToSpans(html) {
  return (html || '').replace(
    /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g,
    (_m, key) => `<span class="ph-token" data-key="${key}" contenteditable="false">{{ ${key} }}</span>`,
  )
}

export default function TemplateEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [doc, setDoc] = useState(null)
  const [placeholders, setPlaceholders] = useState([]) // [{key, label}]
  const [keyInput, setKeyInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [ocrBusy, setOcrBusy] = useState(null)
  const [showOriginal, setShowOriginal] = useState(true)

  const wrapRef = useRef(null)
  const sectionRefs = useRef([])
  const labelsRef = useRef({}) // preserve edited labels across DOM rescans
  const seededRef = useRef(false)

  const processing = doc?.status === 'processing'
  const editMode = doc?.template_html ? 'template' : 'pages'

  useEffect(() => {
    api.getDocument(id).then(setDoc).catch((e) => toast(e.message, 'error'))
  }, [id])

  // While background OCR runs, poll for progress until the doc unblocks.
  useEffect(() => {
    if (!processing) return
    const t = setInterval(() => api.getDocument(id).then(setDoc).catch(() => {}), 1500)
    return () => clearInterval(t)
  }, [processing, id])

  // Seed the editable canvas(es) once the content is ready (not mid-OCR).
  useEffect(() => {
    if (!doc || processing || seededRef.current) return
    seededRef.current = true
    if (editMode === 'template') {
      if (sectionRefs.current[0]) sectionRefs.current[0].innerHTML = tokensToSpans(doc.template_html)
    } else {
      doc.pages.forEach((p, i) => {
        if (sectionRefs.current[i]) sectionRefs.current[i].innerHTML = p.html || '<p></p>'
      })
    }
    refreshPlaceholders()
  }, [doc, processing])

  function refreshPlaceholders() {
    const counts = new Map()
    wrapRef.current?.querySelectorAll('.ph-token').forEach((tok) => {
      const key = tok.getAttribute('data-key')
      if (key) counts.set(key, (counts.get(key) || 0) + 1)
    })
    setPlaceholders(
      Array.from(counts, ([key, count]) => ({ key, count, label: labelsRef.current[key] || titleCase(key) })),
    )
  }

  function onSelect() {
    if (keyInput) return
    const sel = window.getSelection()
    if (sel && !sel.isCollapsed && wrapRef.current?.contains(sel.anchorNode)) {
      setKeyInput(slugKey(sel.toString()))
    }
  }

  // Replace the current canvas selection with a {{ key }} token. Shared by the
  // Insert button (new keys) and the sidebar stamps (reusing existing keys).
  function insertTokenAtSelection(key) {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      toast('Select some text in the document first', 'error')
      return false
    }
    const range = sel.getRangeAt(0)
    if (!wrapRef.current?.contains(range.commonAncestorContainer)) {
      toast('Select text inside the document', 'error')
      return false
    }
    const span = document.createElement('span')
    span.className = 'ph-token'
    span.setAttribute('data-key', key)
    span.setAttribute('contenteditable', 'false')
    span.textContent = `{{ ${key} }}`
    range.deleteContents()
    range.insertNode(span)
    sel.removeAllRanges()
    labelsRef.current[key] = labelsRef.current[key] || titleCase(key)
    refreshPlaceholders()
    return true
  }

  function makePlaceholder() {
    const key = slugKey(keyInput)
    if (!key) return toast('Name the placeholder (letters, digits, _)', 'error')
    if (insertTokenAtSelection(key)) setKeyInput('')
  }

  function stampPlaceholder(key) {
    if (insertTokenAtSelection(key)) toast(`Stamped {{ ${key} }}`)
  }

  function removePlaceholder(key) {
    wrapRef.current?.querySelectorAll(`.ph-token[data-key="${key}"]`).forEach((tok) => {
      tok.replaceWith(document.createTextNode(key.replace(/_/g, ' ')))
    })
    delete labelsRef.current[key]
    refreshPlaceholders()
  }

  function setLabel(key, label) {
    labelsRef.current[key] = label
    setPlaceholders((ps) => ps.map((p) => (p.key === key ? { ...p, label } : p)))
  }

  async function runOcr(pageNumber, i) {
    setOcrBusy(pageNumber)
    try {
      const updated = await api.ocrPage(id, pageNumber)
      const page = updated.pages.find((p) => p.page_number === pageNumber)
      if (page && sectionRefs.current[i]) sectionRefs.current[i].innerHTML = page.html || '<p></p>'
      setDoc(updated)
      refreshPlaceholders()
      toast(`Page ${pageNumber} re-read with OCR`)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setOcrBusy(null)
    }
  }

  async function ocrAll() {
    if (!confirm('Re-read gibberish/scanned pages with OCR? This replaces the text of those pages — and resets any saved template built from them.')) return
    try {
      const updated = await api.ocrAll(id)
      if (updated.status === 'processing') {
        seededRef.current = false // re-seed canvases when OCR finishes
        toast('Recovering text with OCR…')
      } else {
        toast('All pages already look like readable text')
      }
      setDoc(updated)
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  // --- formatting (execCommand keeps the browser's native undo stack) ---
  function selectionInCanvas() {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0 || !wrapRef.current?.contains(sel.anchorNode)) {
      toast('Click into the document text first', 'error')
      return false
    }
    return true
  }

  function fmt(command) {
    if (!selectionInCanvas()) return
    document.execCommand(command, false, null)
  }

  function toggleHeading() {
    if (!selectionInCanvas()) return
    const node = window.getSelection().anchorNode
    const block = (node instanceof Element ? node : node.parentElement)?.closest('h1,h2,h3')
    document.execCommand('formatBlock', false, block ? 'p' : 'h2')
  }

  function toggleCenter() {
    if (!selectionInCanvas()) return
    const centered = document.queryCommandState('justifyCenter')
    document.execCommand(centered ? 'justifyLeft' : 'justifyCenter', false, null)
  }

  function serializeSection(el) {
    const clone = el.cloneNode(true)
    clone.querySelectorAll('.ph-token').forEach((tok) => {
      tok.replaceWith(document.createTextNode(`{{ ${tok.getAttribute('data-key')} }}`))
    })
    return clone.innerHTML.trim()
  }

  async function commit() {
    if (processing) return
    if (placeholders.length === 0 && !confirm('No placeholders marked yet — save the template anyway?')) return
    const sections = sectionRefs.current.filter(Boolean).map(serializeSection)
    const template_html = sections.join('\n<div class="pagebreak"></div>\n')
    setSaving(true)
    try {
      await api.saveTemplate(id, {
        template_html,
        placeholders: placeholders.map((p, order) => ({ key: p.key, label: p.label, order })),
      })
      toast('Template saved')
      navigate(`/documents/${id}/fill`)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (!doc) return <div className="container"><div className="row muted"><span className="spinner" /> Loading…</div></div>

  const sections = editMode === 'template' ? [{ page_number: 1, method: 'template' }] : doc.pages
  const pct = doc.ocr_total ? Math.round((doc.ocr_done / doc.ocr_total) * 100) : 0
  const sideBySide = showOriginal && editMode === 'pages'

  return (
    <div className="container container-wide">
      <div className="row-between" style={{ marginBottom: '1.25rem' }}>
        <div>
          <h1>{doc.name}</h1>
          <p className="muted">Select any text and turn it into a placeholder — then stamp the same key anywhere with one click.</p>
        </div>
        <Steps active={1} />
      </div>

      {processing ? (
        <div className="card card-pad center">
          <h3>Recovering Gujarati text with OCR…</h3>
          <p className="muted small" style={{ margin: '0.25rem 0 0' }}>
            This PDF uses a legacy (non-Unicode) font, so its text layer is gibberish.
            Each flagged page is re-read from the page image instead.
          </p>
          <div className="progress"><div className="progress-fill" style={{ width: `${pct}%` }} /></div>
          <p className="muted small">{doc.ocr_done} of {doc.ocr_total} pages · roughly 10–30s per page</p>
          <div className="thumb-grid">
            {doc.pages.map((p) => (
              <img key={p.page_number} className="page-img" loading="lazy" alt={`Page ${p.page_number}`}
                src={`/api/documents/${id}/pages/${p.page_number}/image`} />
            ))}
          </div>
        </div>
      ) : (
        <div className="editor-grid">
          <div>
            <div className="editor-toolbar card" onMouseDown={(e) => e.preventDefault() /* keep the canvas selection */}>
              <button className="rte-btn" title="Bold (⌘B)" onClick={() => fmt('bold')}><b>B</b></button>
              <button className="rte-btn" title="Italic (⌘I)" onClick={() => fmt('italic')}><i>I</i></button>
              <button className="rte-btn" title="Underline (⌘U)" onClick={() => fmt('underline')}><u>U</u></button>
              <span className="tb-sep" />
              <button className="rte-btn" title="Heading — larger & bold" onClick={toggleHeading} style={{ width: 'auto', padding: '0 8px', fontWeight: 700 }}>H</button>
              <button className="rte-btn" title="Center line" onClick={toggleCenter}>≡</button>
              {editMode === 'pages' && (
                <>
                  <span className="tb-sep" />
                  <button className="btn btn-sm btn-ghost" onClick={() => setShowOriginal((s) => !s)}>
                    {showOriginal ? 'Hide original' : 'Show original'}
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={ocrAll}>↻ OCR all</button>
                </>
              )}
              <span className="small faint" style={{ marginLeft: 'auto' }}>match bold/size against the original</span>
            </div>
            <div ref={wrapRef} onMouseUp={onSelect} onKeyUp={onSelect}>
              {sections.map((p, i) => (
                <div key={p.page_number} style={{ marginBottom: '1.25rem' }}>
                  {editMode === 'pages' && (
                    <div className="row-between small muted" style={{ marginBottom: '0.4rem' }}>
                      <span>Page {p.page_number} · <span className="faint">{p.method === 'ocr' ? 'OCR' : 'text layer'}</span></span>
                      <button className="btn btn-sm btn-ghost" disabled={ocrBusy === p.page_number}
                        onClick={() => runOcr(p.page_number, i)}>
                        {ocrBusy === p.page_number ? <><span className="spinner" /> OCR…</> : '↻ Re-read with OCR'}
                      </button>
                    </div>
                  )}
                  <div className={`page-row ${sideBySide ? '' : 'no-original'}`}>
                    {sideBySide && (
                      <img className="page-img" loading="lazy" alt={`Original page ${p.page_number}`}
                        src={`/api/documents/${id}/pages/${p.page_number}/image`} />
                    )}
                    <div
                      ref={(el) => (sectionRefs.current[i] = el)}
                      className="doc-canvas"
                      contentEditable
                      suppressContentEditableWarning
                      spellCheck={false}
                    />
                  </div>
                </div>
              ))}
            </div>
            <p className="hint">
              Gibberish (legacy-font) pages are re-read with OCR automatically. Proofread numbers, dates and
              PAN codes against the original on the left — OCR can misread digits. Tables may need hand-tidying.
            </p>
          </div>

          <aside className="sidebar">
            <div className="card card-pad">
              <h3>Add placeholder</h3>
              <p className="hint" style={{ marginTop: 0 }}>Select text on the left, adjust the name, then insert.</p>
              <div className="row" style={{ gap: '0.5rem' }}>
                <input className="input" placeholder="seller_name" value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && makePlaceholder()} />
                <button className="btn btn-primary" onMouseDown={(e) => e.preventDefault()} onClick={makePlaceholder}>Insert</button>
              </div>
            </div>

            <div className="card card-pad">
              <div className="row-between"><h3 style={{ margin: 0 }}>Placeholders</h3><span className="badge extracted">{placeholders.length}</span></div>
              <p className="hint" style={{ marginTop: '0.35rem' }}>
                To reuse a key: select text on the left, then <b>click the key below</b> to stamp it there — no retyping.
              </p>
              {placeholders.length === 0 && <p className="hint">None yet.</p>}
              <div className="stack" style={{ marginTop: '0.5rem' }}>
                {placeholders.map((p) => (
                  <div key={p.key} className="ph-item">
                    <div className="grow">
                      <button type="button" className="ph-stamp" title={`Stamp {{ ${p.key} }} onto the selected text`}
                        onMouseDown={(e) => e.preventDefault() /* keep the canvas selection alive */}
                        onClick={() => stampPlaceholder(p.key)}>
                        <span className="key">{`{{ ${p.key} }}`}</span>
                        <span className="ph-count">×{p.count}</span>
                        <span className="ph-stamp-hint">stamp</span>
                      </button>
                      <input className="input" style={{ marginTop: 4, padding: '0.25rem 0.4rem', fontSize: '0.82rem' }}
                        value={p.label} onChange={(e) => setLabel(p.key, e.target.value)} placeholder="Field label" />
                    </div>
                    <button className="rte-btn" title="Remove all uses" onClick={() => removePlaceholder(p.key)}>✕</button>
                  </div>
                ))}
              </div>
            </div>

            <button className="btn btn-primary" style={{ justifyContent: 'center' }} onClick={commit} disabled={saving || processing}>
              {saving ? <><span className="spinner" /> Saving…</> : 'Save template & continue →'}
            </button>
            <button className="btn btn-ghost" style={{ justifyContent: 'center' }} onClick={() => navigate('/')}>Back to documents</button>
          </aside>
        </div>
      )}
    </div>
  )
}
