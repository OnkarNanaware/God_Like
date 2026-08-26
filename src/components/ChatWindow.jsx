import React, { useState, useRef, useEffect } from 'react'
import AgentActivity from './AgentActivity'
import EmptyState from './EmptyState'

function MessageItem({ msg, onOpenAudit }) {
  const [showTrace, setShowTrace] = useState(false)
  const [showSources, setShowSources] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="chat-message-row user">
        <div className="message-bubble-user">
          {msg.text}
        </div>
      </div>
    )
  }

  return (
    <div className="chat-message-row agent">
      <div className="agent-avatar-badge">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2Z" fill="#a78bfa" />
        </svg>
      </div>

      <div className="message-bubble-agent">
        <div className="findings-text">
          {formatMessageContent(msg.text)}
        </div>

        {/* Expandable Agentic Features Bar */}
        {(msg.trace || msg.evidence) && (
          <div className="agentic-actions-row">
            {msg.trace && (
              <button
                type="button"
                className={`agentic-pill-btn ${showTrace ? 'expanded' : ''}`}
                onClick={() => setShowTrace(v => !v)}
              >
                <span>🧠</span>
                <span>Agent activity ({msg.trace.steps?.length || 2} steps)</span>
                <span style={{ fontSize: 10 }}>{showTrace ? '▲' : '▼'}</span>
              </button>
            )}

            {msg.evidence?.sources && (
              <button
                type="button"
                className={`agentic-pill-btn ${showSources ? 'expanded' : ''}`}
                onClick={() => setShowSources(v => !v)}
              >
                <span>📄</span>
                <span>Sources ({msg.evidence.sources.length})</span>
                <span style={{ fontSize: 10 }}>{showSources ? '▲' : '▼'}</span>
              </button>
            )}

            {msg.evidence && (
              <button
                type="button"
                className="agentic-pill-btn"
                onClick={() => onOpenAudit && onOpenAudit(msg.evidence)}
              >
                <span>🔒</span>
                <span>Audit & evidence</span>
                <span style={{ fontSize: 10 }}>↗</span>
              </button>
            )}
          </div>
        )}

        {/* Inline Expanded Agent Activity */}
        {showTrace && msg.trace && (
          <AgentActivity trace={msg.trace} />
        )}

        {/* Inline Expanded Sources */}
        {showSources && msg.evidence?.sources && (
          <div className="agentic-detail-card">
            <div className="detail-card-header">
              <span>📄</span>
              <span>Cited Documents</span>
            </div>
            {msg.evidence.sources.map((src, i) => (
              <div key={i} style={{ padding: '4px 0', fontSize: 12.5, color: 'var(--text-muted)' }}>
                <strong style={{ color: 'var(--text-highlight)' }}>{i + 1}. {src.name}</strong>
                {src.note && <div style={{ color: 'var(--text-dim)', fontSize: 11.5 }}>{src.note}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function formatMessageContent(text) {
  if (!text) return null
  const lines = text.split('\n')

  return lines.map((line, idx) => {
    const trimmed = line.trim()
    if (!trimmed) return <div key={idx} style={{ height: 8 }} />

    if (trimmed.startsWith('•')) {
      const content = trimmed.substring(1).trim()
      return (
        <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '4px 0' }}>
          <span style={{ color: 'var(--accent-purple)' }}>•</span>
          <div>{renderStyledTokens(content)}</div>
        </div>
      )
    }

    return <p key={idx}>{renderStyledTokens(trimmed)}</p>
  })
}

function renderStyledTokens(str) {
  const parts = []
  const regex = /(\*\*.*?\*\*|\bPASS\b|\bFAIL\b|\bON TRACK\b)/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(str)) !== null) {
    if (match.index > lastIndex) {
      parts.push(str.substring(lastIndex, match.index))
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(
        <strong key={match.index} style={{ color: 'var(--text-highlight)' }}>
          {token.slice(2, -2)}
        </strong>
      )
    } else if (token === 'PASS' || token === 'ON TRACK') {
      parts.push(
        <span key={match.index} className="status-badge-pass">
          {token}
        </span>
      )
    } else if (token === 'FAIL') {
      parts.push(
        <span key={match.index} className="status-badge-fail">
          {token}
        </span>
      )
    }
    lastIndex = regex.lastIndex
  }

  if (lastIndex < str.length) {
    parts.push(str.substring(lastIndex))
  }

  return parts.length > 0 ? parts : str
}

export default function ChatWindow({
  conversation,
  onSendCustom,
  onOpenAudit
}) {
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [conversation?.messages])

  const messages = conversation?.messages || []

  return (
    <div className="main-content-scroll" ref={scrollRef}>
      {messages.length === 0 ? (
        <EmptyState onSelectSuggestion={onSendCustom} />
      ) : (
        <div className="chat-conversation-container">
          {messages.map(m => (
            <MessageItem key={m.id} msg={m} onOpenAudit={onOpenAudit} />
          ))}
        </div>
      )}
    </div>
  )
}
