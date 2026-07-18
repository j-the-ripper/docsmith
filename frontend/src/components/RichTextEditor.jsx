import { useEffect, useRef } from 'react'

// Dependency-light rich-text box. Produces exactly the inline HTML the backend
// allow-lists (<b>/<i>/<u>/<s> and styled <span>), so values keep their
// formatting through sanitisation and into the WeasyPrint render.
//
// Uncontrolled by design: we seed innerHTML once and read it back on input,
// so React never fights the caret.

const FONT_SIZES = [
  { label: 'Size', value: '' },
  { label: 'Small', value: '0.85em' },
  { label: 'Normal', value: '1em' },
  { label: 'Large', value: '1.3em' },
  { label: 'X-Large', value: '1.7em' },
]

const COLORS = ['#201d18', '#c96442', '#3f7d54', '#2f6b9a', '#8a2f8a']

function applyInlineStyle(prop, val) {
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return
  const range = sel.getRangeAt(0)
  const span = document.createElement('span')
  span.style[prop] = val
  try {
    range.surroundContents(span)
  } catch {
    // Selection crosses element boundaries — extract then wrap.
    span.appendChild(range.extractContents())
    range.insertNode(span)
  }
  sel.removeAllRanges()
}

export default function RichTextEditor({ value, onChange, placeholder }) {
  const ref = useRef(null)

  // Seed content once (and when an external load replaces it while unfocused).
  useEffect(() => {
    const el = ref.current
    if (el && document.activeElement !== el && el.innerHTML !== (value || '')) {
      el.innerHTML = value || ''
    }
  }, [value])

  const emit = () => onChange(ref.current.innerHTML)

  const cmd = (command) => {
    document.execCommand(command, false, null)
    ref.current.focus()
    emit()
  }

  const size = (v) => {
    if (v) applyInlineStyle('fontSize', v)
    emit()
  }

  const color = (c) => {
    applyInlineStyle('color', c)
    emit()
  }

  return (
    <div className="rte">
      <div className="rte-toolbar" onMouseDown={(e) => e.preventDefault()}>
        <button type="button" className="rte-btn" title="Bold" onClick={() => cmd('bold')}><b>B</b></button>
        <button type="button" className="rte-btn" title="Italic" onClick={() => cmd('italic')}><i>I</i></button>
        <button type="button" className="rte-btn" title="Underline" onClick={() => cmd('underline')}><u>U</u></button>
        <button type="button" className="rte-btn" title="Strikethrough" onClick={() => cmd('strikeThrough')}><s>S</s></button>
        <select className="rte-select" defaultValue="" onChange={(e) => { size(e.target.value); e.target.value = '' }}>
          {FONT_SIZES.map((s) => <option key={s.label} value={s.value}>{s.label}</option>)}
        </select>
        <span className="row" style={{ gap: 2, marginLeft: 4 }}>
          {COLORS.map((c) => (
            <button key={c} type="button" className="rte-btn" title={`Colour ${c}`} onClick={() => color(c)}
              style={{ color: c, fontWeight: 700 }}>A</button>
          ))}
        </span>
      </div>
      <div
        ref={ref}
        className="rte-body"
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder || 'Type a value…'}
        onInput={emit}
      />
    </div>
  )
}
