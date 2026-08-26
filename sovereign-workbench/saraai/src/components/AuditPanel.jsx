import React, { useState } from 'react'

export default function AuditPanel({ evidence, isOpen, onClose }) {
  const [exportNotice, setExportNotice] = useState('')

  if (!isOpen) return null

  const data = evidence || {
    hash: '#a3f9...d1',
    verified: true,
    tool: {
      name: 'RagSearchTool',
      query: '"PV-101 SOP-128"',
      latency: '42ms'
    },
    sources: [{ name: 'SOP_STD_128.md:p14', note: '(Min wall: 8.0 mm)' }],
    exports: [
      { label: 'Download .docx Report', type: 'docx' },
      { label: 'Download Audit JSONL', type: 'jsonl' }
    ]
  }

  function handleExport(label) {
    setExportNotice(`Exporting: ${label}...`)
    setTimeout(() => setExportNotice(''), 2500)
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title">
            <span>📜</span>
            <span>Audit & Evidence Details</span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Cryptographic Chain */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>🔒</span>
              <span>Cryptographic Chain</span>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-purple)' }}>
                {data.hash || '#a3f9...d1'}
              </div>
              <span className="status-badge-pass">[VERIFIED]</span>
            </div>
          </div>

          {/* Executed Tool */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>🛠️</span>
              <span>Executed Tool</span>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                Tool: <strong style={{ color: 'var(--text-highlight)' }}>{data.tool?.name || 'RagSearchTool'}</strong>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', background: 'rgba(0,0,0,0.3)', padding: '6px 8px', borderRadius: 4, fontFamily: 'var(--font-mono)' }}>
                {data.tool?.query || '"PV-101 SOP-128"'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                Latency: <span style={{ color: 'var(--text-muted)' }}>{data.tool?.latency || '42ms'}</span>
              </div>
            </div>
          </div>

          {/* Cited Sources */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>📄</span>
              <span>Cited Sources</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(data.sources || [{ name: 'SOP_STD_128.md:p14', note: '(Min wall: 8.0 mm)' }]).map((src, i) => (
                <div key={i} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-highlight)' }}>
                    {i + 1}. {src.name}
                  </div>
                  {src.note && (
                    <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 2 }}>
                      {src.note}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Export Deliverable */}
          <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>📥</span>
              <span>Export Deliverable</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button
                style={{
                  padding: '9px 12px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-highlight)',
                  fontSize: 12.5,
                  fontWeight: 500,
                  cursor: 'pointer'
                }}
                onClick={() => handleExport('.docx Report')}
              >
                [Download .docx Report]
              </button>
              <button
                style={{
                  padding: '9px 12px',
                  borderRadius: 8,
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-highlight)',
                  fontSize: 12.5,
                  fontWeight: 500,
                  cursor: 'pointer'
                }}
                onClick={() => handleExport('Audit JSONL')}
              >
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
