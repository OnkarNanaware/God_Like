import React, { useState, useRef, useEffect } from 'react'
import Composer from './Composer'
import AgentActivity from './AgentActivity'
import EmptyState from './EmptyState'

function Message({ m }) {
  return (
    <div className={`message ${m.role}`}>
      <div className="bubble">
        <div className="text">{m.text}</div>
      </div>
    </div>
  )
}

export default function ChatWindow({ conversation, onUpdateConversation, onToggleSidebar, onOpenProfile }) {
  const [local, setLocal] = useState(conversation)
  const [isThinking, setIsThinking] = useState(false)
  const scrollRef = useRef()

  useEffect(() => setLocal(conversation), [conversation])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [local])

  if (!conversation) return null

  function handleSend(text) {
    if (!text) return
    const userMsg = { id: Date.now().toString(), role: 'user', text }
    const updated = { ...local, messages: [...(local.messages || []), userMsg] }
    setLocal(updated)
    onUpdateConversation(updated)

    setIsThinking(true)
    setTimeout(() => {
      const reply = { id: Date.now().toString() + 'r', role: 'assistant', text: mockAssistantReply(text) }
      const updated2 = { ...updated, messages: [...updated.messages, reply] }
      setLocal(updated2)
      onUpdateConversation(updated2)
      setIsThinking(false)
    }, 900)
  }

  return (
    <main className="chat-window">
      <header className="chat-header">
        <div className="brand-left">
          <button className="hamburger small" onClick={onToggleSidebar} aria-label="Toggle sidebar">☰</button>
          <div style={{display:'flex',flexDirection:'column'}}>
            <div style={{fontWeight:800}}>Sa-Ra AI <span className="version">3.5 ▾</span></div>
            <div style={{fontSize:12,color:'var(--muted)'}}>Assistant</div>
          </div>
        </div>
        <div className="header-right">
          <button className="upgrade-btn">Upgrade to Pro</button>
          <button className="user-avatar-small" onClick={onOpenProfile}>U</button>
        </div>
      </header>

      <section className="chat-body" ref={scrollRef} aria-live="polite">
        {(!local.messages || local.messages.length === 0) ? (
          <EmptyState />
        ) : (
          local.messages.map(m => <Message key={m.id} m={m} />)
        )}

        {isThinking && <AgentActivity />}
      </section>

      <div style={{display:'flex',flexDirection:'column',alignItems:'center'}}>
        <Composer onSend={handleSend} />
        <div style={{color:'var(--muted)',fontSize:13,marginTop:10}}>Sa-Ra AI can make mistakes. Check important info. ⓘ</div>
      </div>
      <button className="help-fab" aria-label="Help">?</button>
    </main>
  )
}

function mockAssistantReply(text) {
  // Very simple mock mapping
  if (text.toLowerCase().includes('portfolio')) return 'Mocked assistant: For a portfolio, emphasize projects, concise case studies, and contact.'
  if (text.toLowerCase().includes('explain')) return 'Mocked assistant: Here is a clear explanation with examples and bullets.'
  return 'Sa-Ra: I have processed your request and prepared a short plan. (mock response)'
}
