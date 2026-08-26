import React from 'react'

export default function AgentActivity({ trace, isLive = false }) {
  const routerText = trace?.router || 'Selected qwen2.5:14b (Modality: Text + RAG)'
  const steps = trace?.steps || [
    { id: 1, action: "Queried Qdrant collection: 'synthetic_sops'", done: true },
    { id: 2, action: "Retrieved SOP_STD_128.md §4.2 (Score: 0.91)", done: true }
  ]

  return (
    <div className="agentic-detail-card">
      <div className="detail-card-header">
        <span>🧠</span>
        <span>Agent Execution Trace</span>
      </div>

      <div className="trace-step-item router">
        <span>Router:</span>
        <span style={{ color: 'var(--accent-purple)' }}>{routerText}</span>
      </div>

      {steps.map((s, idx) => (
        <div key={s.id || idx} className="trace-step-item">
          <span>Step {idx + 1}:</span>
          <span>{s.action}</span>
        </div>
      ))}

      {isLive && (
        <div className="trace-step-item" style={{ color: 'var(--accent-purple)', marginTop: 4 }}>
          <span>⏳</span>
          <span>Synthesizing agent response...</span>
        </div>
      )}
    </div>
  )
}
