import React, { useState } from 'react'
import { SettingsIcon, CloseIcon } from './Icons'

export default function SettingsModal({ onClose, defaultTab = 'appearance' }) {
  const [tab, setTab] = useState(defaultTab)

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              style={{
                background: tab === 'appearance' ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                color: tab === 'appearance' ? 'var(--accent-purple)' : 'var(--text-muted)',
                border: 0,
                padding: '6px 12px',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer'
              }}
              onClick={() => setTab('appearance')}
            >
              Appearance
            </button>
            <button
              style={{
                background: tab === 'agent' ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                color: tab === 'agent' ? 'var(--accent-purple)' : 'var(--text-muted)',
                border: 0,
                padding: '6px 12px',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer'
              }}
              onClick={() => setTab('agent')}
            >
              Agent Preferences
            </button>
          </div>

          <button className="modal-close" onClick={onClose} aria-label="Close">
            <CloseIcon size={16} />
          </button>
        </div>

        <div style={{ marginTop: 18 }}>
          {tab === 'appearance' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Theme & Visuals
                </div>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Cosmic Dark Atmosphere</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Planetary Horizon Glow</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Smooth Interface Transitions</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Autonomous Agent & RAG
                </div>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Auto-Router Selection (qwen2.5:14b)</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Local Air-Gapped Qdrant Vector Index</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Cryptographic Chain Audit Verification</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, color: 'var(--text-main)', cursor: 'pointer' }}>
                  <span>Show Execution Traces & Latency</span>
                  <input type="checkbox" defaultChecked style={{ accentColor: 'var(--accent-purple)', width: 16, height: 16 }} />
                </label>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
