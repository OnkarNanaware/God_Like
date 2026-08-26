import React, { useState, useRef, useEffect } from 'react'
import { PaperclipIcon, MicIcon, ArrowUpIcon } from './Icons'

export default function Composer({ onSend }) {
  const [text, setText] = useState('')
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

  function submit() {
    if (!text.trim()) return
    onSend(text.trim())
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  return (
    <div className="composer-outer-wrapper">
      <div className="composer-box">
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
                style={{ display: 'none' }}
                onChange={e => {
                  if (e.target.files && e.target.files[0]) {
                    setText(prev => (prev ? `${prev} [Attached: ${e.target.files[0].name}]` : `[Attached: ${e.target.files[0].name}] `))
                  }
                }}
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
              className={`btn-send-circle ${text.trim() ? 'active' : ''}`}
              onClick={submit}
              disabled={!text.trim()}
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

      <button className="floating-help-btn" title="Help & Feedback" onClick={() => alert('Sa-Ra AI Support & Documentation')}>
        ?
      </button>
    </div>
  )
}
