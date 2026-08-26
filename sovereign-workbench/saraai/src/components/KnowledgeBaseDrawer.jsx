import React, { useState } from 'react'

export default function KnowledgeBaseDrawer({ isOpen, onClose }) {
  const [selectedDoc, setSelectedDoc] = useState('SOP-128 (PV)')
  const [ingestStatus, setIngestStatus] = useState('')

  if (!isOpen) return null

  function handleDrop(e) {
    e.preventDefault()
    setIngestStatus('Ingesting document into local vector index...')
    setTimeout(() => {
      setIngestStatus('Document successfully indexed in Qdrant.')
      setTimeout(() => setIngestStatus(''), 3000)
    }, 1200)
  }

  function handleFileSelect(e) {
    if (e.target.files && e.target.files[0]) {
      setIngestStatus(`Ingesting ${e.target.files[0].name}...`)
      setTimeout(() => {
        setIngestStatus('Document indexed in Qdrant collection.')
        setTimeout(() => setIngestStatus(''), 3000)
      }, 1200)
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title">
            <span>📁</span>
            <span>Knowledge Base & SOPs</span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 18 }}>
          {/* MRPL Reports */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>▶</span>
              <span>MRPL Reports</span>
            </div>
            <ul style={{ listStyle: 'none', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <li
                style={{
                  fontSize: 13,
                  color: selectedDoc === "Annual '24" ? 'var(--accent-purple)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: selectedDoc === "Annual '24" ? 'rgba(167, 139, 250, 0.1)' : 'transparent'
                }}
                onClick={() => setSelectedDoc("Annual '24")}
              >
                • Annual '24
              </li>
              <li
                style={{
                  fontSize: 13,
                  color: selectedDoc === "Sust. '24" ? 'var(--accent-purple)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: selectedDoc === "Sust. '24" ? 'rgba(167, 139, 250, 0.1)' : 'transparent'
                }}
                onClick={() => setSelectedDoc("Sust. '24")}
              >
                • Sust. '24
              </li>
            </ul>
          </div>

          {/* Synthetic SOPs */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>▶</span>
              <span>Synthetic SOPs</span>
            </div>
            <ul style={{ listStyle: 'none', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <li
                style={{
                  fontSize: 13,
                  color: selectedDoc === 'SOP-128 (PV)' ? 'var(--accent-purple)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: selectedDoc === 'SOP-128 (PV)' ? 'rgba(167, 139, 250, 0.1)' : 'transparent'
                }}
                onClick={() => setSelectedDoc('SOP-128 (PV)')}
              >
                • SOP-128 (PV)
              </li>
              <li
                style={{
                  fontSize: 13,
                  color: selectedDoc === 'SOP-129 (TK)' ? 'var(--accent-purple)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: selectedDoc === 'SOP-129 (TK)' ? 'rgba(167, 139, 250, 0.1)' : 'transparent'
                }}
                onClick={() => setSelectedDoc('SOP-129 (TK)')}
              >
                • SOP-129 (TK)
              </li>
            </ul>
          </div>

          {/* Ingest Actions */}
          <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <label
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                padding: '9px 12px',
                borderRadius: 8,
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-highlight)',
                fontSize: 13,
                fontWeight: 500,
                cursor: 'pointer'
              }}
            >
              <span>＋ Ingest File</span>
              <input
                type="file"
                style={{ display: 'none' }}
                onChange={handleFileSelect}
                accept=".pdf,.doc,.docx,.md,.txt,.json,.jsonl"
              />
            </label>

            <div
              style={{
                marginTop: 10,
                border: '1px dashed var(--border-medium)',
                borderRadius: 8,
                padding: '16px 12px',
                textAlign: 'center',
                fontSize: 12,
                color: 'var(--text-dim)',
                background: 'rgba(255, 255, 255, 0.02)',
                cursor: 'pointer'
              }}
              onDragOver={e => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => document.querySelector('.drawer-panel input[type="file"]')?.click()}
            >
              [Drop PDF/Doc here to index]
            </div>

            {ingestStatus && (
              <div style={{ fontSize: 11, color: 'var(--accent-green)', marginTop: 8, textAlign: 'center' }}>
                ✓ {ingestStatus}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
