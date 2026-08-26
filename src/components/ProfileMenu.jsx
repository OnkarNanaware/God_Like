import React from 'react'

export default function ProfileMenu({ onClose, onOpenSettings, onOpenKnowledgeBase }) {
  return (
    <div className="profile-popover" role="menu">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}>
        <div className="avatar-circle">U</div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-highlight)' }}>User</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>user@example.com</div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 6 }}>
        <button
          className="sidebar-link"
          onClick={() => {
            onClose()
            onOpenKnowledgeBase()
          }}
        >
          <span>📁</span>
          <span>Knowledge Base & SOPs</span>
        </button>
        <button
          className="sidebar-link"
          onClick={() => {
            onClose()
            onOpenSettings()
          }}
        >
          <span>⚙</span>
          <span>Settings</span>
        </button>
        <button
          className="sidebar-link"
          onClick={() => {
            alert('Viewing subscription: Sa-Ra AI Pro Plan')
            onClose()
          }}
        >
          <span>✨</span>
          <span>Upgrade to Pro</span>
        </button>
        <button
          className="sidebar-link"
          style={{ color: '#f87171', borderTop: '1px solid var(--border-subtle)', marginTop: 4, paddingTop: 6 }}
          onClick={onClose}
        >
          <span>✕</span>
          <span>Close Menu</span>
        </button>
      </div>
    </div>
  )
}
