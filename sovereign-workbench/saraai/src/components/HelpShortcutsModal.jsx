import React, { useState } from 'react'
import { KeyboardIcon, HelpIcon, CloseIcon } from './Icons'

export default function HelpShortcutsModal({ isOpen, defaultTab = 'shortcuts', onClose }) {
  const [activeTab, setActiveTab] = useState(defaultTab)

  if (!isOpen) return null

  const shortcuts = [
    { key: 'Enter', desc: 'Send message' },
    { key: 'Shift + Enter', desc: 'New line in message composer' },
    { key: 'Ctrl + K / Cmd + K', desc: 'Focus conversation search' },
    { key: 'Ctrl + Shift + O', desc: 'Start a new conversation' },
    { key: 'Ctrl + Shift + S', desc: 'Toggle sidebar open / closed' },
    { key: 'Esc', desc: 'Close open drawers & modals' }
  ]

  const faqs = [
    {
      q: 'What is Sa-Ra AI?',
      a: 'Sa-Ra AI is an air-gapped sovereign AI assistant equipped with local vector search (Qdrant), autonomous multi-step agent routers, and cryptographic audit trail verification.'
    },
    {
      q: 'How does Local RAG search work?',
      a: 'When you ask questions referencing SOPs or MRPL reports, Sa-Ra AI queries the local vector index, retrieves the most relevant passage chunks, and cites exact sections and page numbers.'
    },
    {
      q: 'What is the Cryptographic Chain & Audit Trail?',
      a: 'Every agent step, retrieved document, and tool execution is hashed with SHA-256 to ensure complete air-gapped traceability and tamper-proof verification.'
    },
    {
      q: 'How do I ingest custom SOPs and documents?',
      a: 'Open the Knowledge Base drawer using the folder icon or header button, then drag and drop your PDF/Doc files into the ingestion target zone.'
    }
  ]

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" style={{ width: 500 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              style={{
                background: activeTab === 'shortcuts' ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                color: activeTab === 'shortcuts' ? 'var(--accent-purple)' : 'var(--text-muted)',
                border: 0,
                padding: '6px 12px',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}
              onClick={() => setActiveTab('shortcuts')}
            >
              <KeyboardIcon size={15} />
              <span>Keyboard Shortcuts</span>
            </button>
            <button
              style={{
                background: activeTab === 'faq' ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                color: activeTab === 'faq' ? 'var(--accent-purple)' : 'var(--text-muted)',
                border: 0,
                padding: '6px 12px',
                borderRadius: 6,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}
              onClick={() => setActiveTab('faq')}
            >
              <HelpIcon size={15} />
              <span>Help & FAQ</span>
            </button>
          </div>

          <button className="modal-close" onClick={onClose} aria-label="Close">
            <CloseIcon size={16} />
          </button>
        </div>

        <div style={{ marginTop: 16, maxHeight: 380, overflowY: 'auto' }}>
          {activeTab === 'shortcuts' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {shortcuts.map((sc, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border-subtle)'
                  }}
                >
                  <span style={{ fontSize: 13, color: 'var(--text-main)' }}>{sc.desc}</span>
                  <span
                    style={{
                      fontFamily: 'var(--font-sans)',
                      fontSize: 11.5,
                      fontWeight: 600,
                      color: 'var(--text-highlight)',
                      background: 'rgba(255, 255, 255, 0.08)',
                      padding: '3px 8px',
                      borderRadius: 4,
                      border: '1px solid rgba(255, 255, 255, 0.1)'
                    }}
                  >
                    {sc.key}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {faqs.map((faq, i) => (
                <div
                  key={i}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 8,
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border-subtle)'
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-highlight)', marginBottom: 4 }}>
                    {faq.q}
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.55 }}>
                    {faq.a}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
