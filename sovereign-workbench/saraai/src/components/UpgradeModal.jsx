import React from 'react'
import { SparkleIcon, CheckIcon, CloseIcon } from './Icons'

export default function UpgradeModal({ isOpen, onClose }) {
  if (!isOpen) return null

  const features = [
    'Unlimited High-Speed Air-Gapped Local Inference',
    'Advanced Qdrant Vector Collection Indexing & Hybrid Search',
    'Autonomous Multi-Step Agent Tracing & Tool Execution',
    'SHA-256 Cryptographic Chain & Full Audit Trail Exports',
    'Priority Local GPU Acceleration (CUDA / FlashAttention-2)',
    'Multi-Document Cross-Referencing & Batch Ingestion'
  ]

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog upgrade-dialog" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--accent-purple)' }}><SparkleIcon size={18} /></span>
            <span>Upgrade to SARA Pro</span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <CloseIcon size={16} />
          </button>
        </div>

        <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: 'rgba(167, 139, 250, 0.08)', border: '1px solid var(--border-accent)', borderRadius: 10, padding: '14px 16px', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-highlight)' }}>Pro Operator Plan</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>For engineers & local AI investigation workloads</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent-purple)' }}>$20<span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-muted)' }}>/mo</span></div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {features.map((feat, idx) => (
              <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: 'var(--text-main)' }}>
                <span style={{ width: 18, height: 18, borderRadius: 999, background: 'rgba(52, 211, 153, 0.15)', color: 'var(--accent-green)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <CheckIcon size={11} />
                </span>
                <span>{feat}</span>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 10, paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <button
              style={{
                flex: 1,
                padding: '10px 16px',
                borderRadius: 8,
                background: 'var(--button-gradient)',
                border: 0,
                color: '#ffffff',
                fontWeight: 600,
                fontSize: 13.5,
                cursor: 'pointer',
                boxShadow: '0 4px 16px rgba(123, 91, 255, 0.35)'
              }}
              onClick={() => {
                alert('Pro Plan Activated! High-speed RAG and GPU acceleration enabled.')
                onClose()
              }}
            >
              Upgrade Now
            </button>
            <button
              style={{
                padding: '10px 16px',
                borderRadius: 8,
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-muted)',
                fontWeight: 500,
                fontSize: 13,
                cursor: 'pointer'
              }}
              onClick={onClose}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
