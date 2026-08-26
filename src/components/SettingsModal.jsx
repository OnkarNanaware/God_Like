import React from 'react'

export default function SettingsModal({ onClose }) {
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal settings">
        <header>
          <h2>Settings</h2>
          <button onClick={onClose} aria-label="Close">✕</button>
        </header>
        <section>
          <h3>General</h3>
          <label><input type="checkbox" defaultChecked /> Dark appearance</label>
          <label><input type="checkbox" /> Show timestamps</label>
        </section>
        <section>
          <h3>Agent</h3>
          <label><input type="checkbox" defaultChecked /> Agent mode</label>
          <label><input type="checkbox" /> Confirm before actions</label>
        </section>
      </div>
    </div>
  )
}
