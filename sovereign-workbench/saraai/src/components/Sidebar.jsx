import React, { useState, useMemo } from 'react'
import {
  LogoIcon,
  PlusIcon,
  SearchIcon,
  ChatBubbleIcon,
  SettingsIcon,
  KeyboardIcon,
  HelpIcon,
  TrashIcon
} from './Icons'

export default function Sidebar({
  open = true,
  conversations = [],
  activeId,
  onSelect,
  onNewChat,
  onOpenSettings,
  onOpenProfile,
  onClearHistory
}) {
  const [searchQuery, setSearchQuery] = useState('')

  const grouped = useMemo(() => {
    const today = []
    const yesterday = []
    const older = []
    const now = new Date()

    conversations.forEach(c => {
      if (c.group === 'Today') {
        today.push(c)
      } else if (c.group === 'Yesterday') {
        yesterday.push(c)
      } else if (c.group === 'Previous 7 days') {
        older.push(c)
      } else {
        const d = new Date(c.createdAt || Date.now())
        const diffDays = (now - d) / (1000 * 60 * 60 * 24)
        if (diffDays < 1) today.push(c)
        else if (diffDays < 2) yesterday.push(c)
        else older.push(c)
      }
    })

    return { today, yesterday, older }
  }, [conversations])

  const filterList = list => {
    if (!searchQuery.trim()) return list
    const q = searchQuery.toLowerCase()
    return list.filter(c => c.title.toLowerCase().includes(q))
  }

  const todayList = filterList(grouped.today)
  const yesterdayList = filterList(grouped.yesterday)
  const olderList = filterList(grouped.older)

  return (
    <aside className={`sidebar ${open ? 'open' : 'closed'}`} aria-label="Sidebar">
      {/* Brand Header - Clean without extra pencil icon */}
      <div className="sidebar-header">
        <div className="brand-wrapper" onClick={() => onSelect(conversations[0]?.id)}>
          <LogoIcon size={22} />
          <span className="brand-title">SARA</span>
        </div>
      </div>

      {/* Action Row */}
      <div className="sidebar-new-chat-row">
        <button className="btn-new-chat" onClick={onNewChat}>
          <PlusIcon size={14} />
          <span>New chat</span>
        </button>
      </div>

      {/* Search Bar */}
      <div className="sidebar-search">
        <span className="sidebar-search-icon">
          <SearchIcon size={13} />
        </span>
        <input
          type="text"
          placeholder="Search chats..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
      </div>

      {/* History List */}
      <div className="sidebar-history">
        {todayList.length > 0 && (
          <div className="history-group">
            <div className="history-group-title">Today</div>
            {todayList.map(c => (
              <button
                key={c.id}
                className={`history-item ${c.id === activeId ? 'active' : ''}`}
                onClick={() => onSelect(c.id)}
              >
                <div className="history-item-left">
                  <span className="history-item-icon">
                    <ChatBubbleIcon size={14} />
                  </span>
                  <span className="history-item-title">{c.title}</span>
                </div>
                <span className="history-item-dots">⋯</span>
              </button>
            ))}
          </div>
        )}

        {yesterdayList.length > 0 && (
          <div className="history-group">
            <div className="history-group-title">Yesterday</div>
            {yesterdayList.map(c => (
              <button
                key={c.id}
                className={`history-item ${c.id === activeId ? 'active' : ''}`}
                onClick={() => onSelect(c.id)}
              >
                <div className="history-item-left">
                  <span className="history-item-icon">
                    <ChatBubbleIcon size={14} />
                  </span>
                  <span className="history-item-title">{c.title}</span>
                </div>
                <span className="history-item-dots">⋯</span>
              </button>
            ))}
          </div>
        )}

        {olderList.length > 0 && (
          <div className="history-group">
            <div className="history-group-title">Previous 7 days</div>
            {olderList.map(c => (
              <button
                key={c.id}
                className={`history-item ${c.id === activeId ? 'active' : ''}`}
                onClick={() => onSelect(c.id)}
              >
                <div className="history-item-left">
                  <span className="history-item-icon">
                    <ChatBubbleIcon size={14} />
                  </span>
                  <span className="history-item-title">{c.title}</span>
                </div>
                <span className="history-item-dots">⋯</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Footer Links & User Profile */}
      <div className="sidebar-footer">
        <button className="sidebar-link" onClick={onOpenSettings}>
          <SettingsIcon size={16} />
          <span>Settings</span>
        </button>
        <button className="sidebar-link" onClick={() => alert('Keyboard shortcuts:\nEnter: Send message\nShift+Enter: New line')}>
          <KeyboardIcon size={16} />
          <span>Keyboard shortcuts</span>
        </button>
        <button className="sidebar-link" onClick={() => alert('SARA Help & Documentation')}>
          <HelpIcon size={16} />
          <span>Help & FAQ</span>
        </button>

        <button
          className="sidebar-link sidebar-link-danger"
          onClick={() => {
            if (window.confirm('Clear all chat history? This cannot be undone.')) {
              onClearHistory?.()
            }
          }}
          title="Clear all chat history"
        >
          <TrashIcon size={16} />
          <span>Clear History</span>
        </button>

        <div className="sidebar-user" onClick={onOpenProfile}>
          <div className="avatar-circle">U</div>
          <div className="user-info">
            <div className="user-name">User</div>
            <div className="user-email">user@example.com</div>
          </div>
          <span style={{ color: 'var(--text-dim)', fontSize: 16 }}>⋯</span>
        </div>
      </div>
    </aside>
  )
}
