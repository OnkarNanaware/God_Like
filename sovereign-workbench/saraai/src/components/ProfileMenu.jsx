import React from 'react'
import { FolderIcon, SettingsIcon, KeyboardIcon, HelpIcon, SparkleIcon, CloseIcon } from './Icons'

export default function ProfileMenu({
  onClose,
  onOpenSettings,
  onOpenKnowledgeBase,
  onOpenUpgrade,
  onOpenHelpShortcuts
}) {
  return (
    <div className="profile-popover" role="menu">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}>
        <div className="avatar-circle">U</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-highlight)' }}>User</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            user@example.com
          </div>
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
          <FolderIcon size={15} />
          <span>Knowledge Base & SOPs</span>
        </button>

        <button
          className="sidebar-link"
          onClick={() => {
            onClose()
            onOpenSettings()
          }}
        >
          <SettingsIcon size={15} />
          <span>Settings</span>
        </button>

        <button
          className="sidebar-link"
          onClick={() => {
            onClose()
            onOpenHelpShortcuts('shortcuts')
          }}
        >
          <KeyboardIcon size={15} />
          <span>Keyboard shortcuts</span>
        </button>

        <button
          className="sidebar-link"
          onClick={() => {
            onClose()
            onOpenHelpShortcuts('faq')
          }}
        >
          <HelpIcon size={15} />
          <span>Help & FAQ</span>
        </button>

        <button
          className="sidebar-link"
          style={{ color: 'var(--accent-purple)' }}
          onClick={() => {
            onClose()
            onOpenUpgrade()
          }}
        >
          <SparkleIcon size={15} />
          <span>Upgrade to Pro</span>
        </button>

        <button
          className="sidebar-link"
          style={{ color: '#f87171', borderTop: '1px solid var(--border-subtle)', marginTop: 4, paddingTop: 6 }}
          onClick={onClose}
        >
          <CloseIcon size={13} />
          <span>Close Menu</span>
        </button>
      </div>
    </div>
  )
}
