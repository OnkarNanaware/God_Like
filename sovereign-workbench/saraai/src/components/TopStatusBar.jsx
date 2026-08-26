import React from 'react'

export default function TopStatusBar({ onOpenSettings, onOpenProfile }) {
  return (
    <header className="top-status-bar">
      <div className="status-section">
        <div className="status-brand">
          <span className="status-dot-green" />
          <span>SOVEREIGN WORKBENCH</span>
        </div>
      </div>

      <div className="status-section">
        <div className="status-airgapped">
          <span>•</span>
          <span>LOCALHOST AIR-GAPPED (0 EGRESS)</span>
        </div>
      </div>

      <div className="status-section">
        <div className="status-hardware">
          HARDWARE: <strong>NVIDIA RTX 4070 (MID-TIER)</strong>
        </div>
        <div className="status-divider" />
        <button className="top-bar-btn" onClick={onOpenSettings} title="Workbench Settings">
          ⚙ CONFIG
        </button>
        <button className="top-bar-btn" onClick={onOpenProfile} title="Operator Profile">
          👤 OPERATOR
        </button>
      </div>
    </header>
  )
}
