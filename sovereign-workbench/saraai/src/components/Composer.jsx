import React, { useState, useRef, useEffect } from 'react'
import { PaperclipIcon, MicIcon, ArrowUpIcon, FileIcon, CloseIcon } from './Icons'

// ---------------------------------------------------------------------------
// Web Speech API – voice input
// ---------------------------------------------------------------------------
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

/**
 * Composer
 * ========
 * Message-input bar with file attachment support.
 *
 * Change from Phase D mock:
 *   onSend(text, files) now receives real File objects (not name labels).
 *   The parent (App.jsx) passes them through to submitGoal() as multipart.
 */
export default function Composer({ onSend, onOpenHelp, disabled = false }) {
  const [text, setText] = useState('')
  const [attachedFiles, setAttachedFiles] = useState([])  // array of File objects
  const [isListening, setIsListening] = useState(false)
  const textareaRef = useRef(null)
  const recognitionRef = useRef(null)

  useEffect(() => {
    if (!disabled) {
      textareaRef.current?.focus()
    }
  }, [disabled])

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
    }
    // Reset input so the same file can be re-attached if removed and re-added
    e.target.value = ''
  }

  function removeFile(index) {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index))
  }

  function formatSize(bytes) {
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
          placeholder={disabled ? 'Detecting hardware…' : 'Message Sa-Ra AI…'}
          aria-label="Message Sa-Ra AI"
          disabled={disabled}
        />

        <div className="composer-bottom-bar">
          <div className="composer-left-tools">
            <label className="composer-tool-btn" title="Attach File (image, PDF, or spreadsheet)"
              style={{ cursor: disabled ? 'not-allowed' : 'pointer' }}>
              <PaperclipIcon size={18} />
              <input
                type="file"
                multiple
                accept="image/*,.pdf,.xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv"
                style={{ display: 'none' }}
                onChange={handleFileChange}
                disabled={disabled}
              />
            </label>
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
