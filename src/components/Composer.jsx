import React, { useState, useRef, useEffect } from 'react'

export default function Composer({ onSend }) {
  const [text, setText] = useState('')
  const inputRef = useRef()

  useEffect(() => { inputRef.current && inputRef.current.focus() }, [])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    if (!text.trim()) return
    onSend(text.trim())
    setText('')
  }

  return (
    <div className="composer compact">
      <textarea
        ref={inputRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Message Sa-Ra AI..."
        aria-label="Message input"
      />
      <div className="controls right">
        <button className="icon" aria-label="Attach">📎</button>
        <button className="icon mic" aria-label="Voice">🎤</button>
        <button className={`send ${text.trim() ? 'active' : ''}`} onClick={submit} aria-label="Send message">➤</button>
      </div>
    </div>
  )
}
