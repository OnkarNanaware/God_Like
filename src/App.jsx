import React, { useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import CosmicBackground from './components/CosmicBackground'
import SettingsModal from './components/SettingsModal'
import ProfileMenu from './components/ProfileMenu'
import mockConversations from './data/mockConversations'

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [conversations, setConversations] = useState(mockConversations)
  const [activeId, setActiveId] = useState(conversations[0].id)
  const [showSettings, setShowSettings] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)

  const activeConversation = conversations.find(c => c.id === activeId)

  function addConversation(title = 'New Conversation') {
    const id = Date.now().toString()
    const conv = { id, title, createdAt: new Date().toISOString(), messages: [] }
    setConversations(prev => [conv, ...prev])
    setActiveId(id)
    setSidebarOpen(false)
  }

  function updateConversation(updated) {
    setConversations(prev => prev.map(c => c.id === updated.id ? updated : c))
  }

  return (
    <div className="app">
      <CosmicBackground />
      <div className={`ui-shell ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
        <Sidebar
          open={sidebarOpen}
          onToggle={() => setSidebarOpen(v => !v)}
          conversations={conversations}
          onNewChat={() => addConversation()}
          onSelect={id => { setActiveId(id); setSidebarOpen(true) }}
          onOpenSettings={() => setShowSettings(true)}
          onOpenProfile={() => setProfileOpen(v => !v)}
        />

        <ChatWindow
          conversation={activeConversation}
          onUpdateConversation={updateConversation}
          onToggleSidebar={() => setSidebarOpen(v => !v)}
          onOpenProfile={() => setProfileOpen(v => !v)}
        />

        {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
        {profileOpen && <ProfileMenu onClose={() => setProfileOpen(false)} />}
      </div>
    </div>
  )
}
