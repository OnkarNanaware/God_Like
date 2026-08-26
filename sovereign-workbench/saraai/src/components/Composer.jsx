import React, { useState, useRef, useEffect } from 'react'
import { PaperclipIcon, MicIcon, ArrowUpIcon, FileIcon, CloseIcon } from './Icons'

export default function Composer({ onSend, onOpenHelp }) {
  const [text, setText] = useState('')
  const [attachedFiles, setAttachedFiles] = useState([])
  const textareaRef = useRef(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function handleInput(e) {
    setText(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px'
    }
  }

  function handleFileChange(e) {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files).map(f => ({
        name: f.name,
        size: (f.size / (1024 * 1024)).toFixed(1) + ' MB'
      }))
      setAttachedFiles(prev => [...prev, ...newFiles])
    }
  }

  function removeFile(index) {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index))
  }

  function submit() {
    if (!text.trim() && attachedFiles.length === 0) return
    const fileLabels = attachedFiles.map(f => `[Attached: ${f.name}]`).join(' ')
    const fullText = fileLabels ? `${text} ${fileLabels}`.trim() : text.trim()
    onSend(fullText)
    setText('')
    setAttachedFiles([])
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  return (
    <div className="composer-outer-wrapper">
      <div className="composer-box">
        {/* Attached Files Preview (Stitch Screen 12) */}
        {attachedFiles.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, paddingBottom: 6 }}>
            {attachedFiles.map((file, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  background: 'rgba(167, 139, 250, 0.1)',
                  border: '1px solid var(--border-accent)',
                  borderRadius: 8,
                  padding: '4px 10px',
                  fontSize: 12,
                  color: 'var(--text-highlight)'
                }}
              >
                <FileIcon size={14} />
                <span style={{ fontWeight: 500 }}>{file.name}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({file.size})</span>
                <button
                  type="button"
                  style={{
                    background: 'transparent',
                    border: 0,
                    color: 'var(--text-dim)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    padding: 2
                  }}
                  onClick={() => removeFile(idx)}
                >
                  <CloseIcon size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          className="composer-textarea"
          rows={1}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Message Sa-Ra AI..."
          aria-label="Message Sa-Ra AI"
        />

        <div className="composer-bottom-bar">
          <div className="composer-left-tools">
            <label className="composer-tool-btn" title="Attach File" style={{ cursor: 'pointer' }}>
              <PaperclipIcon size={18} />
              <input
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
            </label>
          </div>

          <div className="composer-right-tools">
            <button
              type="button"
              className="composer-tool-btn"
              title="Voice Input"
              onClick={() => alert('Voice input activated (listening...)')}
            >
              <MicIcon size={18} />
            </button>

            <button
              type="button"
              className={`btn-send-circle ${(text.trim() || attachedFiles.length > 0) ? 'active' : ''}`}
              onClick={submit}
              disabled={!text.trim() && attachedFiles.length === 0}
              title="Send message"
              aria-label="Send message"
            >
              <ArrowUpIcon size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className="composer-disclaimer">
        Sa-Ra AI can make mistakes. Check important info. ⓘ
      </div>

      <button
        className="floating-help-btn"
        title="Help & Feedback"
        onClick={onOpenHelp}
      >
        ?
      </button>
    </div>
  )
}
