import React, { useMemo, useState } from 'react'

export default function Sidebar({ open, onToggle, conversations, onNewChat, onSelect, onOpenSettings, onOpenProfile }) {
  const [query, setQuery] = useState('')

  const groups = useMemo(() => {
    const today = []
    const yesterday = []
    const older = []
    const now = new Date()
    conversations.forEach(c => {
      const d = new Date(c.createdAt)
      const diff = (now - d) / (1000 * 60 * 60 * 24)
      if (diff < 1) today.push(c)
      else if (diff < 2) yesterday.push(c)
      else older.push(c)
    })
    return { today, yesterday, older }
  }, [conversations])

  const filtered = (arr) => arr.filter(c => c.title.toLowerCase().includes(query.toLowerCase()))

  return (
    <aside className={`sidebar ${open ? 'open' : 'closed'}`} aria-hidden={!open}>
      <div className="sidebar-top">
        <div style={{display:'flex',alignItems:'center',gap:12}}>
          <div className="brand" onClick={() => onSelect(conversations[0]?.id)}>
            <img src="/assets/sara-logo-placeholder.svg" alt="Sa-Ra AI" className="logo-img" />
            <div className="title">Sa-Ra AI</div>
          </div>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="hamburger" onClick={onToggle} aria-label="Toggle sidebar">☰</button>
        </div>
      </div>

      <div className="sidebar-actions" style={{marginTop:12}}>
        <button className="btn new-chat" onClick={onNewChat}>+ New chat</button>
        <button className="icon-btn" title="Open list">≡</button>
      </div>

      <div className="search" style={{marginTop:12}}>
        <input aria-label="Search conversations" placeholder="Search chats..." value={query} onChange={e => setQuery(e.target.value)} />
      </div>

      <nav className="conversations" aria-label="Conversations">
        {filtered(groups.today).length > 0 && (
          <div className="group">
            <div className="group-title">Today</div>
            {filtered(groups.today).map(c => (
              <div key={c.id} className="conv" onClick={() => onSelect(c.id)}>
                <div className="conv-left"><div className="icon">💬</div><div>{c.title}</div></div>
                <div className="three">⋯</div>
              </div>
            ))}
          </div>
        )}

        {filtered(groups.yesterday).length > 0 && (
          <div className="group">
            <div className="group-title">Yesterday</div>
            {filtered(groups.yesterday).map(c => (
              <div key={c.id} className="conv" onClick={() => onSelect(c.id)}>
                <div className="conv-left"><div className="icon">💬</div><div>{c.title}</div></div>
                <div className="three">⋯</div>
              </div>
            ))}
          </div>
        )}

        {filtered(groups.older).length > 0 && (
          <div className="group">
            <div className="group-title">Previous 7 days</div>
            {filtered(groups.older).map(c => (
              <div key={c.id} className="conv" onClick={() => onSelect(c.id)}>
                <div className="conv-left"><div className="icon">💬</div><div>{c.title}</div></div>
                <div className="three">⋯</div>
              </div>
            ))}
          </div>
        )}
      </nav>

      <div className="sidebar-bottom">
        <div style={{display:'flex',flexDirection:'column',gap:6}}>
          <button className="link">Settings</button>
          <button className="link">Keyboard shortcuts</button>
          <button className="link">Help & FAQ</button>
        </div>

        <div className="sidebar-user">
          <div className="avatar-circle">U</div>
          <div style={{flex:1}}>
            <div style={{color:'#eaf1ff',fontWeight:700}}>User</div>
            <a href="mailto:user@example.com" style={{color:'var(--muted)',fontSize:13,textDecoration:'none'}}>user@example.com</a>
          </div>
          <div className="three">⋯</div>
        </div>
      </div>
    </aside>
  )
}
