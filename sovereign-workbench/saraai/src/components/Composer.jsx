import React, { useState, useRef, useEffect } from 'react'
import { PaperclipIcon, MicIcon, ArrowUpIcon, FileIcon, CloseIcon } from './Icons'

// ---------------------------------------------------------------------------
// Web Speech API – voice input
// ---------------------------------------------------------------------------
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

const LS_RECENT_FILES = 'sara_recent_files'

const DEFAULT_RECENT_FILES = [
  { name: 'OISD-STD-174.pdf', size: 1420000, type: 'application/pdf' },
  { name: 'MRPL_Sustainability_report_FY_2024-25.pdf', size: 4850000, type: 'application/pdf' },
  { name: 'sop_approval_note.txt', size: 12400, type: 'text/plain' },
]

function loadRecentFiles() {
  try {
    const raw = localStorage.getItem(LS_RECENT_FILES)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch (_) { /* ignore */ }
  return DEFAULT_RECENT_FILES
}

function saveRecentFile(file) {
  try {
    const existing = loadRecentFiles()
    const entry = {
      name: file.name,
      size: file.size || 1024,
      type: file.type || 'application/octet-stream',
      date: new Date().toISOString(),
    }
    const filtered = existing.filter(f => f.name !== file.name)
    const updated = [entry, ...filtered].slice(0, 8)
    localStorage.setItem(LS_RECENT_FILES, JSON.stringify(updated))
    return updated
  } catch (_) {
    return []
  }
}

/**
 * Composer
 * ========
 * Message-input bar with file attachment support & recent files drawer.
 */
export default function Composer({ onSend, onOpenHelp, disabled = false }) {
  const [text, setText] = useState('')
  const [attachedFiles, setAttachedFiles] = useState([])  // array of File objects
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const [recentFiles, setRecentFiles] = useState(() => loadRecentFiles())
  const [isListening, setIsListening] = useState(false)
  const textareaRef = useRef(null)
  const recognitionRef = useRef(null)
  const fileInputRef = useRef(null)
  const attachMenuRef = useRef(null)

  useEffect(() => {
    if (!disabled) {
      textareaRef.current?.focus()
    }
  }, [disabled])

  // Handle click outside attachment menu
  useEffect(() => {
    function handleClickOutside(e) {
      if (attachMenuRef.current && !attachMenuRef.current.contains(e.target)) {
        setShowAttachMenu(false)
      }
    }
    if (showAttachMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showAttachMenu])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey && !disabled) {
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
      // Keep actual File objects so they can be sent in multipart POST
      const newFiles = Array.from(e.target.files)
      setAttachedFiles(prev => [...prev, ...newFiles])
      newFiles.forEach(f => {
        const updated = saveRecentFile(f)
        if (updated.length > 0) setRecentFiles(updated)
      })
    }
    setShowAttachMenu(false)
    e.target.value = ''
  }

  function handleSelectRecent(rf) {
    // If the file is already attached, don't duplicate
    if (attachedFiles.some(f => f.name === rf.name)) {
      setShowAttachMenu(false)
      return
    }
    // Create a File object representing the recent file attachment
    const content = new Blob([`[Reference attachment: ${rf.name}]`], { type: rf.type || 'application/octet-stream' })
    const fileObj = new File([content], rf.name, { type: rf.type || 'application/octet-stream' })
    Object.defineProperty(fileObj, 'size', { value: rf.size || 1024, writable: false })

    setAttachedFiles(prev => [...prev, fileObj])
    const updated = saveRecentFile(rf)
    if (updated.length > 0) setRecentFiles(updated)
    setShowAttachMenu(false)
  }

  function removeFile(index) {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index))
  }

  function formatSize(bytes) {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  function submit() {
    if (disabled) return
    if (!text.trim() && attachedFiles.length === 0) return
    // Pass real File objects to parent — NOT injected label strings
    onSend(text.trim(), attachedFiles)
    setText('')
    setAttachedFiles([])
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const canSend = !disabled && (text.trim().length > 0 || attachedFiles.length > 0)

  // ---------------------------------------------------------------------------
  // Voice input — Web Speech API
  // ---------------------------------------------------------------------------
  function toggleVoiceInput() {
    if (!SpeechRecognition) {
      alert('Your browser does not support speech recognition. Try Chrome or Edge.')
      return
    }

    // Stop if already listening
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop()
      return
    }

    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = true
    recognition.continuous = false
    recognitionRef.current = recognition

    let finalTranscript = ''

    recognition.onstart = () => setIsListening(true)

    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript
        } else {
          interim += event.results[i][0].transcript
        }
      }
      // Show interim in the textarea for live feedback
      setText(prev => {
        const base = prev.replace(/\[listening….*\]$/, '').trimEnd()
        return interim
          ? base + (base ? ' ' : '') + `[listening… ${interim}]`
          : base
      })
    }

    recognition.onend = () => {
      setIsListening(false)
      recognitionRef.current = null
      // Commit the final transcript — strip any leftover [listening… …] placeholder
      setText(prev => {
        const clean = prev.replace(/\[listening….*?\]/g, '').trim()
        return finalTranscript
          ? (clean ? clean + ' ' : '') + finalTranscript
          : clean
      })
    }

    recognition.onerror = (e) => {
      console.error('Speech recognition error', e.error)
      setIsListening(false)
      recognitionRef.current = null
    }

    recognition.start()
  }

  return (
    <div className="composer-outer-wrapper">
      <div className={`composer-box ${disabled ? 'composer-disabled' : ''}`}
        style={disabled ? { opacity: 0.5, pointerEvents: 'none' } : undefined}
      >
        {/* Attached Files Preview */}
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
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  ({formatSize(file.size)})
                </span>
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
                  aria-label={`Remove ${file.name}`}
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
          placeholder={disabled ? 'Detecting hardware…' : 'Message SARA…'}
          aria-label="Message SARA"
          disabled={disabled}
        />

        <div className="composer-bottom-bar">
          <div className="composer-left-tools" style={{ position: 'relative' }} ref={attachMenuRef}>
            <button
              type="button"
              className="composer-tool-btn"
              title="Attach File or Select Recent"
              onClick={() => setShowAttachMenu(v => !v)}
              disabled={disabled}
              aria-label="Attach File or Select Recent"
              style={{ cursor: disabled ? 'not-allowed' : 'pointer' }}
            >
              <PaperclipIcon size={18} />
            </button>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.pdf,.xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv,.docx,.doc,.txt,.json"
              style={{ display: 'none' }}
              onChange={handleFileChange}
              disabled={disabled}
            />

            {/* Recent Files Popover Dropdown */}
            {showAttachMenu && (
              <div
                style={{
                  position: 'absolute',
                  bottom: 'calc(100% + 10px)',
                  left: 0,
                  zIndex: 200,
                  width: 300,
                  background: '#0d101a',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: 12,
                  padding: '10px',
                  boxShadow: '0 12px 36px rgba(0,0,0,0.8)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                {/* Upload Action */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 10px',
                    borderRadius: 8,
                    background: 'rgba(167, 139, 250, 0.12)',
                    border: '1px solid rgba(167, 139, 250, 0.3)',
                    color: 'var(--accent-purple)',
                    fontSize: 12.5,
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(167, 139, 250, 0.2)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'rgba(167, 139, 250, 0.12)'}
                >
                  <PaperclipIcon size={14} />
                  <span>Upload from Device…</span>
                </button>

                {/* Recent Files Section */}
                <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: 'var(--text-dim)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    padding: '2px 4px 6px',
                  }}>
                    Recent Files
                  </div>

                  {recentFiles.length === 0 ? (
                    <div style={{ padding: '8px', textAlign: 'center', fontSize: 11.5, color: 'var(--text-dim)' }}>
                      No recent files yet
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 180, overflowY: 'auto' }}>
                      {recentFiles.map((rf, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => handleSelectRecent(rf)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '6px 8px',
                            borderRadius: 6,
                            background: 'transparent',
                            border: 0,
                            color: 'var(--text-main)',
                            fontSize: 12,
                            cursor: 'pointer',
                            textAlign: 'left',
                            transition: 'background 0.15s ease',
                          }}
                          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)'}
                          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                          title={`Click to attach ${rf.name}`}
                        >
                          <FileIcon size={14} />
                          <div style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }}>
                              {rf.name}
                            </div>
                            <div style={{ fontSize: 10.5, color: 'var(--text-dim)' }}>
                              {formatSize(rf.size || 0)}
                            </div>
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--accent-purple)' }}>+</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="composer-right-tools">
            <button
              type="button"
              className={`composer-tool-btn${isListening ? ' mic-active' : ''}`}
              title={isListening ? 'Stop recording' : 'Voice Input'}
              onClick={toggleVoiceInput}
              disabled={disabled}
              aria-label={isListening ? 'Stop voice recording' : 'Start voice input'}
              style={isListening ? { color: '#f87171', animation: 'mic-pulse 1s ease-in-out infinite' } : undefined}
            >
              <MicIcon size={18} />
            </button>

            <button
              type="button"
              id="send-button"
              className={`btn-send-circle ${canSend ? 'active' : ''}`}
              onClick={submit}
              disabled={!canSend}
              title="Send message (Enter)"
              aria-label="Send message"
            >
              <ArrowUpIcon size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className="composer-disclaimer">
        SARA can make mistakes. Check important info. ⓘ
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
