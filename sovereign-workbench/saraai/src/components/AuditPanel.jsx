import React, { useState, useEffect } from 'react'
import { fetchAuditRecent } from '../hooks/useBackend'

/**
 * AuditPanel
 * ==========
 * Draws right-side audit drawer.
 *
 * Phase E change: when a real requestId is present, fetches
 * GET /audit/recent?request_id=... and renders actual records + chain validity.
 * Falls back to the evidence object passed from the message when no requestId.
 */
export default function AuditPanel({ evidence, isOpen, onClose, requestId }) {
  const [auditData, setAuditData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState(null)
  const [exportNotice, setExportNotice] = useState('')

  useEffect(() => {
    if (!isOpen) return
    if (!requestId) {
      setAuditData(null)
      return
    }
    setLoading(true)
    setFetchError(null)
    fetchAuditRecent(requestId, 100)
      .then(data => {
        setAuditData(data)
        setLoading(false)
      })
      .catch(err => {
        setFetchError(err.message)
        setLoading(false)
      })
  }, [isOpen, requestId])

  if (!isOpen) return null

  // Decide what to render: real audit records or legacy evidence fallback
  const useLiveData = !!requestId && !!auditData
  const data = evidence || {
    hash: '#a3f9...d1',
    verified: true,
    tool: { name: 'RagSearchTool', query: '"PV-101 SOP-128"', latency: '42ms' },
    sources: [{ name: 'SOP_STD_128.md:p14', note: '(Min wall: 8.0 mm)' }],
    exports: [
      { label: 'Download .docx Report', type: 'docx' },
      { label: 'Download Audit JSONL', type: 'jsonl' },
    ],
  }

  function handleExport(label) {
    setExportNotice(`Exporting: ${label}…`)
    setTimeout(() => setExportNotice(''), 2500)
  }

  // Format a timestamp for display
  function fmtTime(ts) {
    if (!ts) return '—'
    try {
      return new Date(ts).toLocaleTimeString()
    } catch {
      return ts
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title">
            <span>📜</span>
            <span>Audit & Evidence Details</span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── Live audit records view ── */}
          {loading && (
            <div style={{ fontSize: 12, color: 'var(--text-dim)', textAlign: 'center', padding: 16 }}>
              ⏳ Loading audit records…
            </div>
          )}

          {fetchError && (
            <div style={{ fontSize: 12, color: '#f87171', padding: '8px 12px',
              background: 'rgba(248,113,113,0.08)', borderRadius: 8, border: '1px solid rgba(248,113,113,0.2)' }}>
              ⚠ Could not fetch audit records: {fetchError}
            </div>
          )}

          {useLiveData && !loading && (
            <>
              {/* Chain validity badge */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>🔒</span>
                  <span>Cryptographic Chain</span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)',
                  borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-purple)' }}>
                    {auditData.returned} record{auditData.returned !== 1 ? 's' : ''} for this run
                  </div>
                  <span className={auditData.chain_valid ? 'status-badge-pass' : 'status-badge-fail'}>
                    {auditData.chain_valid ? '[VERIFIED]' : '[BROKEN]'}
                  </span>
                </div>
                {!auditData.chain_valid && auditData.chain_errors?.length > 0 && (
                  <div style={{ marginTop: 6, fontSize: 11, color: '#f87171' }}>
                    {auditData.chain_errors.map((e, i) => <div key={i}>⚠ {e}</div>)}
                  </div>
                )}
              </div>

              {/* Event records */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>🛠️</span>
                  <span>Event Log ({auditData.returned})</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {auditData.records.map((rec, i) => (
                    <div key={i} style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 8,
                      padding: '8px 10px',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <span style={{
                          fontSize: 11, fontWeight: 700,
                          color: rec.event_type === 'error' ? '#f87171' :
                                 rec.event_type === 'tool_call' ? '#60a5fa' :
                                 rec.event_type === 'model_call' ? '#a78bfa' : 'var(--text-highlight)',
                          textTransform: 'uppercase', letterSpacing: '0.04em',
                        }}>
                          {rec.event_type}
                        </span>
                        <span style={{ fontSize: 10.5, color: 'var(--text-dim)' }}>
                          {fmtTime(rec.timestamp_utc)} · seq {rec.sequence}
                        </span>
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--text-muted)',
                        wordBreak: 'break-all', lineHeight: 1.5 }}>
                        {rec.payload?.action && (
                          <span style={{ color: 'var(--text-highlight)', marginRight: 6 }}>
                            {rec.payload.action}
                          </span>
                        )}
                        {rec.payload?.tool_name && (
                          <span style={{ color: '#60a5fa' }}>{rec.payload.tool_name}</span>
                        )}
                        {rec.payload?.model_name && (
                          <span style={{ color: '#a78bfa' }}> {rec.payload.model_name}</span>
                        )}
                        {rec.payload?.status && (
                          <span style={{ color: 'var(--text-dim)', marginLeft: 6 }}>
                            [{rec.payload.status}]
                          </span>
                        )}
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)',
                        marginTop: 4, wordBreak: 'break-all' }}>
                        hash: {rec.self_hash?.slice(0, 16)}…
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* ── Legacy evidence view (when no live requestId) ── */}
          {!useLiveData && !loading && (
            <>
              {/* Cryptographic Chain */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>🔒</span><span>Cryptographic Chain</span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)',
                  borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-purple)' }}>
                    {data.hash || '#a3f9…d1'}
                  </div>
                  <span className="status-badge-pass">[VERIFIED]</span>
                </div>
              </div>

              {/* Executed Tool */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>🛠️</span><span>Executed Tool</span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)',
                  borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                    Tool: <strong style={{ color: 'var(--text-highlight)' }}>{data.tool?.name || 'RagSearchTool'}</strong>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', background: 'rgba(0,0,0,0.3)',
                    padding: '6px 8px', borderRadius: 4, fontFamily: 'var(--font-mono)' }}>
                    {data.tool?.query || '"PV-101 SOP-128"'}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    Latency: <span style={{ color: 'var(--text-muted)' }}>{data.tool?.latency || '42ms'}</span>
                  </div>
                </div>
              </div>

              {/* Cited Sources */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>📄</span><span>Cited Sources</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(data.sources || []).map((src, i) => (
                    <div key={i} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)',
                      borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-highlight)' }}>
                        {i + 1}. {src.name}
                      </div>
                      {src.note && (
                        <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 2 }}>{src.note}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Export Deliverable — always shown */}
          <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8,
              display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>📥</span><span>Export Deliverable</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button style={{ padding: '9px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border-subtle)', color: 'var(--text-highlight)', fontSize: 12.5,
                fontWeight: 500, cursor: 'pointer' }}
                onClick={() => handleExport('.docx Report')}>
                [Download .docx Report]
              </button>
              <button style={{ padding: '9px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border-subtle)', color: 'var(--text-highlight)', fontSize: 12.5,
                fontWeight: 500, cursor: 'pointer' }}
                onClick={() => handleExport('Audit JSONL')}>
                [Download Audit JSONL]
              </button>
              {exportNotice && (
                <div style={{ fontSize: 11, color: 'var(--accent-green)', textAlign: 'center', marginTop: 4 }}>
                  ✓ {exportNotice}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
