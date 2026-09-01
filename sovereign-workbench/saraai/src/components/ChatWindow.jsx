import React, { useState, useRef, useEffect } from 'react'
import AgentActivity from './AgentActivity'
import EmptyState from './EmptyState'
import { AlertIcon } from './Icons'
import { artifactDownloadUrl } from '../hooks/useBackend'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
      parts.push(<span key={match.index} className="status-badge-pass">{token}</span>)
    } else if (token === 'FAIL') {
      parts.push(<span key={match.index} className="status-badge-fail">{token}</span>)
    }
    lastIndex = regex.lastIndex
  }

  if (lastIndex < str.length) {
    parts.push(str.substring(lastIndex))
  }

  return parts.length > 0 ? parts : str
}

// ---------------------------------------------------------------------------
// Live step-trace panel (shown while streaming, before completion)
// ---------------------------------------------------------------------------

function LiveStepTrace({ steps, currentTool }) {
  return (
    <div className="agentic-detail-card" style={{ marginTop: 8 }}>
      <div className="detail-card-header">
        <span>🧠</span>
        <span>Agent Execution — Live</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--accent-purple)' }}>
          {currentTool ? `⚡ ${currentTool}` : '⏳ Planning…'}
        </span>
      </div>
      {steps.map((s, idx) => (
        <div key={idx} className="trace-step-item" style={{
          opacity: s.done ? 1 : 0.7,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
        }}>
          <span style={{
            fontSize: 10,
            color: s.success === false ? '#f87171' : s.done ? '#34d399' : 'var(--accent-purple)',
            marginTop: 2,
            flexShrink: 0,
          }}>
            {s.success === false ? '✗' : s.done ? '✓' : '⟳'}
          </span>
          <div style={{ flex: 1 }}>
            <span style={{ fontWeight: 600, color: 'var(--text-highlight)' }}>
              {s.tool_name}
            </span>
            {s.description && (
              <span style={{ color: 'var(--text-dim)', fontSize: 11.5, marginLeft: 6 }}>
                — {s.description}
              </span>
            )}
            {s.error && (
              <div style={{ color: '#f87171', fontSize: 11, marginTop: 2 }}>
                {s.error}
              </div>
            )}
          </div>
          {s.attempt > 1 && (
            <span style={{ fontSize: 10, color: '#fbbf24' }}>retry #{s.attempt}</span>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline citations panel
// ---------------------------------------------------------------------------

function CitationsPanel({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{
        fontSize: 11.5, fontWeight: 600, color: 'var(--text-highlight)',
        marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4,
      }}>
        📄 Sources
      </div>
      {sources.map((src, i) => (
        <div key={i} style={{
          padding: '5px 0',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          fontSize: 12,
          display: 'flex',
          gap: 8,
          alignItems: 'flex-start',
        }}>
          <span style={{ color: 'var(--text-dim)', minWidth: 18 }}>{i + 1}.</span>
          <div>
            <span style={{ fontWeight: 600, color: 'var(--text-highlight)' }}>
              {src.name}
            </span>
            {src.page_number != null && (
              <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 4 }}>
                p.{src.page_number}
              </span>
            )}
            {src.score != null && (
              <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 6 }}>
                (score: {src.score.toFixed(3)})
              </span>
            )}
            {src.note && (
              <div style={{ color: 'var(--text-dim)', fontSize: 11.5, marginTop: 2 }}>
                {src.note}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Artifact download buttons (replaces OutputFiles)
// ---------------------------------------------------------------------------

function formatBytes(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function artifactIcon(artifactType) {
  if (artifactType === 'docx') return '📄'
  if (artifactType === 'pptx') return '📊'
  if (artifactType === 'xlsx') return '📈'
  return '📎'
}

function ArtifactDownloads({ artifacts }) {
  if (!artifacts || artifacts.length === 0) return null

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{
        fontSize: 11.5, fontWeight: 600, color: 'var(--text-highlight)',
        marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4,
      }}>
        📥 Generated Files
      </div>
      {artifacts.map((artifact) => {
        const url = artifactDownloadUrl(artifact.artifact_id)
        return (
          <a
            key={artifact.artifact_id}
            href={url}
            download={artifact.filename}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '7px 10px',
              marginBottom: 4,
              background: 'rgba(167,139,250,0.08)',
              border: '1px solid var(--border-accent)',
              borderRadius: 8,
              fontSize: 12.5,
              color: 'var(--accent-purple)',
              textDecoration: 'none',
              fontWeight: 500,
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(167,139,250,0.16)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(167,139,250,0.08)'}
          >
            <span>{artifactIcon(artifact.artifact_type)}</span>
            <span style={{ flex: 1 }}>Download {artifact.filename}</span>
            {artifact.size_bytes != null && (
              <span style={{ fontSize: 10.5, color: 'var(--text-dim)', marginRight: 4 }}>
                {formatBytes(artifact.size_bytes)}
              </span>
            )}
            <span style={{ fontSize: 10 }}>↓</span>
          </a>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single message renderer
// ---------------------------------------------------------------------------

function MessageItem({ msg, onOpenAudit, onRetry }) {
  const [showTrace, setShowTrace] = useState(false)
  const [showSources, setShowSources] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="chat-message-row user">
        <div className="message-bubble-user">
          {msg.text}
          {msg.files && msg.files.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11.5, color: 'rgba(255,255,255,0.5)' }}>
              {msg.files.map((f, i) => <span key={i}>📎 {f} </span>)}
            </div>
          )}
        </div>
      </div>
    )
  }

  // Error state
  if (msg.isError) {
    return (
      <div className="chat-message-row agent">
        <div className="agent-avatar-badge" style={{ background: 'linear-gradient(135deg, #f87171, #ef4444)' }}>
          <AlertIcon size={16} />
        </div>
        <div className="message-bubble-agent" style={{ borderColor: 'rgba(248, 113, 113, 0.3)' }}>
          <div style={{ color: '#f87171', fontWeight: 600, fontSize: 13.5, marginBottom: 4 }}>
            Orchestrator Error
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            {msg.text || 'The agent run failed. Check the audit log for details.'}
          </div>
          {onRetry && (
            <button
              type="button"
              style={{
                marginTop: 10,
                background: 'rgba(248, 113, 113, 0.12)',
                border: '1px solid rgba(248, 113, 113, 0.3)',
                color: '#f87171',
                padding: '5px 12px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer'
              }}
              onClick={() => onRetry(msg.retryQuery)}
            >
              ↻ Retry
            </button>
          )}
        </div>
      </div>
    )
  }

  // Streaming-in-progress state — show live step trace
  if (msg.isStreaming) {
    return (
      <div className="chat-message-row agent">
        <div className="agent-avatar-badge">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2Z" fill="#a78bfa" />
          </svg>
        </div>
        <div className="message-bubble-agent">
          <LiveStepTrace
            steps={msg.streamingSteps || []}
            currentTool={msg.currentTool}
          />
        </div>
      </div>
    )
  }

  // Completed assistant message
  const hasSources = msg.sources && msg.sources.length > 0
  const hasFiles = msg.outputFiles && msg.outputFiles.length > 0
  const hasTrace = msg.trace

  return (
    <div className="chat-message-row agent">
      <div className="agent-avatar-badge">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2Z" fill="#a78bfa" />
        </svg>
      </div>

      <div className="message-bubble-agent">
        <div className="findings-text">
          {formatMessageContent(msg.text)}
        </div>

        {/* Inline citations — always visible when RAG-grounded */}
        <CitationsPanel sources={msg.sources} />

        {/* Inline file download links */}
        <ArtifactDownloads artifacts={msg.artifacts} />

        {/* Agentic actions row */}
        {(hasTrace || hasSources || msg.evidence) && (
          <div className="agentic-actions-row">
            {hasTrace && (
              <button
                type="button"
                className={`agentic-pill-btn ${showTrace ? 'expanded' : ''}`}
                onClick={() => setShowTrace(v => !v)}
              >
                <span>🧠</span>
                <span>Agent activity ({msg.trace?.steps?.length || 0} steps)</span>
                <span style={{ fontSize: 10 }}>{showTrace ? '▲' : '▼'}</span>
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

        {showTrace && hasTrace && (
          <AgentActivity trace={msg.trace} />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ChatWindow
// ---------------------------------------------------------------------------

export default function ChatWindow({
  conversation,
  onSendCustom,
  onOpenAudit,
  isGenerating = false,
}) {
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [conversation?.messages, isGenerating])

  const messages = conversation?.messages || []

  return (
    <div className="main-content-scroll" ref={scrollRef}>
      {messages.length === 0 ? (
        <EmptyState onSelectSuggestion={onSendCustom} />
      ) : (
        <div className="chat-conversation-container">
          {messages.map(m => (
            <MessageItem
              key={m.id}
              msg={m}
              onOpenAudit={onOpenAudit}
              onRetry={onSendCustom}
            />
          ))}

          {/* Fallback spinner for edge case where streaming hasn't attached yet */}
          {isGenerating && messages.length > 0 && !messages[messages.length - 1]?.isStreaming && (
            <div className="chat-message-row agent">
              <div className="agent-avatar-badge">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2Z" fill="#a78bfa" />
                </svg>
              </div>
              <div className="message-bubble-agent">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--accent-purple)' }}>
                  <span className="streaming-dots">Connecting to agent</span>
                  <span className="streaming-cursor">▊</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
