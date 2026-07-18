import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import Home from './pages/Home.jsx'
import TemplateEditor from './pages/TemplateEditor.jsx'
import FillForm from './pages/FillForm.jsx'

// ---- Toast (tiny global notifier) --------------------------------------
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  const timer = useRef(null)
  const notify = useCallback((message, kind = 'info') => {
    clearTimeout(timer.current)
    setToast({ message, kind })
    timer.current = setTimeout(() => setToast(null), 3200)
  }, [])
  return (
    <ToastCtx.Provider value={notify}>
      {children}
      {toast && <div className={`toast ${toast.kind === 'error' ? 'error' : ''}`}>{toast.message}</div>}
    </ToastCtx.Provider>
  )
}

// ---- Steps indicator ---------------------------------------------------
export function Steps({ active }) {
  const steps = ['Upload', 'Placeholders', 'Fill & export']
  return (
    <div className="steps">
      {steps.map((s, i) => (
        <span key={s} className="row" style={{ gap: '0.4rem' }}>
          {i > 0 && <span className="dot" />}
          <span className={i === active ? 'active' : ''}>{s}</span>
        </span>
      ))}
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">
            <span className="mark">§</span>
            DocSmith
          </Link>
          <span className="small faint">reflowable PDF templates</span>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/documents/:id/template" element={<TemplateEditor />} />
          <Route path="/documents/:id/fill" element={<FillForm />} />
        </Routes>
      </div>
    </ToastProvider>
  )
}
