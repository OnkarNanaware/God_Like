import React from 'react'

export default function SettingsModal({ onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">Settings</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>
              General
            </div>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
              <span>Dark Cosmic Theme</span>
              <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)' }} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
              <span>Show Thinking & Execution Traces</span>
              <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)' }} />
            </label>
          </div>

          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>
              Local Agent & RAG
            </div>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
              <span>Autonomous Router (qwen2.5:14b)</span>
              <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)' }} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
              <span>Air-Gapped Local Vector Store (Qdrant)</span>
              <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)' }} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
              <span>Cryptographic Chain Audit Verification</span>
              <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)' }} />
            </label>
          </div>
        </div>
      </div>
    </div>
  )
}
