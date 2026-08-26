import React, { useState, useEffect } from 'react'
import CosmicBackground from './components/CosmicBackground'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import KnowledgeBaseDrawer from './components/KnowledgeBaseDrawer'
import AuditPanel from './components/AuditPanel'
import SettingsModal from './components/SettingsModal'
import ProfileMenu from './components/ProfileMenu'
import UpgradeModal from './components/UpgradeModal'
import HelpShortcutsModal from './components/HelpShortcutsModal'
import mockConversations from './data/mockConversations'
import { HamburgerIcon, SparkleIcon, FolderIcon, ShieldIcon } from './components/Icons'

export default function App() {
  const [conversations, setConversations] = useState(mockConversations)
  const [activeId, setActiveId] = useState(conversations[0]?.id || 'c-pv101')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [settingsTab, setSettingsTab] = useState('appearance')
  const [profileOpen, setProfileOpen] = useState(false)
  const [kbDrawerOpen, setKbDrawerOpen] = useState(false)
  const [auditDrawerOpen, setAuditDrawerOpen] = useState(false)
  const [upgradeModalOpen, setUpgradeModalOpen] = useState(false)
  const [helpModalOpen, setHelpModalOpen] = useState(false)
  const [helpModalTab, setHelpModalTab] = useState('shortcuts')
  const [activeAuditData, setActiveAuditData] = useState(null)
  const [modelName, setModelName] = useState('Sa-Ra AI 3.5')
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)

  const activeConversation = conversations.find(c => c.id === activeId) || conversations[0]

  // Global Keyboard Shortcuts (Stitch Screen 14)
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'S' || e.key === 's')) {
        e.preventDefault()
        setSidebarOpen(v => !v)
      } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'O' || e.key === 'o')) {
        e.preventDefault()
        handleNewChat()
      } else if (e.key === 'Escape') {
        setShowSettings(false)
        setProfileOpen(false)
        setKbDrawerOpen(false)
        setAuditDrawerOpen(false)
        setUpgradeModalOpen(false)
        setHelpModalOpen(false)
        setShowModelMenu(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  function handleNewChat() {
    const id = 'c-' + Date.now().toString().slice(-6)
    const newConv = {
      id,
      title: 'New Conversation',
      group: 'Today',
      createdAt: new Date().toISOString(),
      messages: []
    }
    setConversations(prev => [newConv, ...prev])
    setActiveId(id)
  }

  function updateConversation(updated) {
    setConversations(prev => prev.map(c => (c.id === updated.id ? updated : c)))
  }

  function handleSend(text) {
    if (!text || !activeConversation) return

    const userMsg = {
      id: 'm-' + Date.now(),
      role: 'user',
      text
    }

    const updatedWithUser = {
      ...activeConversation,
      title: activeConversation.messages.length === 0 ? text.slice(0, 28) : activeConversation.title,
      messages: [...(activeConversation.messages || []), userMsg]
    }
    updateConversation(updatedWithUser)

    // Simulate Agent Streaming response generation (Stitch Screen 9)
    setIsGenerating(true)
    setTimeout(() => {
      setIsGenerating(false)
      const generatedReply = generateAssistantResponse(text)
      const updatedWithAgent = {
        ...updatedWithUser,
        messages: [...updatedWithUser.messages, generatedReply]
      }
      updateConversation(updatedWithAgent)
    }, 900)
  }

  function handleOpenAudit(evidence) {
    setActiveAuditData(evidence)
    setAuditDrawerOpen(true)
  }

  function handleOpenHelpShortcuts(tab = 'shortcuts') {
    setHelpModalTab(tab)
    setHelpModalOpen(true)
  }

  const models = [
    'Sa-Ra AI 3.5',
    'Sa-Ra AI 4.0 Pro',
    'qwen2.5:14b (Auto-RAG)',
    'llama3.1:8b (Local)'
  ]

  return (
    <div className="sara-app">
      {/* Left Sidebar */}
      <Sidebar
        open={sidebarOpen}
        conversations={conversations}
        activeId={activeId}
        onSelect={id => setActiveId(id)}
        onNewChat={handleNewChat}
        onOpenSettings={() => {
          setSettingsTab('appearance')
          setShowSettings(true)
        }}
        onOpenProfile={() => setProfileOpen(v => !v)}
      />

      {/* Main Viewport */}
      <main className={`main-viewport ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
        {/* Moon & Planet Cosmic Layer anchored inside Main Viewport for dynamic recentering */}
        <CosmicBackground />

        {/* Top Header */}
        <header className="main-header">
          <div className="header-left">
            {/* Hamburger Button: ONLY controls the left sidebar */}
            <button
              className="hamburger-btn"
              onClick={() => setSidebarOpen(v => !v)}
              title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
              aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            >
              <HamburgerIcon size={18} />
            </button>

            {/* Model Selector */}
            <div style={{ position: 'relative' }}>
              <button
                className="model-selector-btn"
                onClick={() => setShowModelMenu(v => !v)}
                aria-label="Select Model"
              >
                <span>{modelName}</span>
                <span className="model-arrow">▾</span>
              </button>

              {showModelMenu && (
                <div className="model-dropdown-menu">
                  {models.map(m => (
                    <div
                      key={m}
                      className={`model-option ${m === modelName ? 'active' : ''}`}
                      onClick={() => {
                        setModelName(m)
                        setShowModelMenu(false)
                      }}
                    >
                      {m === modelName ? '✓ ' : '  '}
                      {m}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="header-right">
            {/* Knowledge Base Trigger */}
            <button
              className="btn-header-pill"
              onClick={() => setKbDrawerOpen(true)}
              title="Knowledge Base & SOPs"
            >
              <FolderIcon size={14} />
              <span>Knowledge Base</span>
            </button>

            {/* Audit & Evidence Trigger */}
            <button
              className="btn-header-pill"
              onClick={() => {
                setActiveAuditData(null)
                setAuditDrawerOpen(true)
              }}
              title="Audit & Evidence Records"
            >
              <ShieldIcon size={14} />
              <span>Audit & Evidence</span>
            </button>

            {/* Upgrade to Pro Trigger (Stitch Screen 13) */}
            <button
              className="btn-upgrade"
              onClick={() => setUpgradeModalOpen(true)}
              title="Upgrade to Pro"
            >
              <SparkleIcon size={14} />
              <span>Upgrade to Pro</span>
            </button>

            {/* User Profile Avatar */}
            <button
              className="header-avatar"
              onClick={() => setProfileOpen(v => !v)}
              title="Operator Profile"
            >
              U
            </button>
          </div>
        </header>

        {/* Chat / Home Workspace */}
        <ChatWindow
          conversation={activeConversation}
          onSendCustom={handleSend}
          onOpenAudit={handleOpenAudit}
          isGenerating={isGenerating}
        />

        {/* Bottom Composer */}
        <Composer
          onSend={handleSend}
          onOpenHelp={() => handleOpenHelpShortcuts('faq')}
        />
      </main>

      {/* Knowledge Base Drawer (Stitch Screen 4) */}
      <KnowledgeBaseDrawer
        isOpen={kbDrawerOpen}
        onClose={() => setKbDrawerOpen(false)}
      />

      {/* Audit & Evidence Drawer (Stitch Screen 3) */}
      <AuditPanel
        isOpen={auditDrawerOpen}
        evidence={activeAuditData}
        onClose={() => setAuditDrawerOpen(false)}
      />

      {/* Settings Modal (Stitch Screens 6 & 7) */}
      {showSettings && (
        <SettingsModal
          defaultTab={settingsTab}
          onClose={() => setShowSettings(false)}
        />
      )}

      {/* Upgrade to Pro Modal (Stitch Screen 13) */}
      <UpgradeModal
        isOpen={upgradeModalOpen}
        onClose={() => setUpgradeModalOpen(false)}
      />

      {/* Keyboard Shortcuts & Help Modal (Stitch Screens 14 & 15) */}
      <HelpShortcutsModal
        isOpen={helpModalOpen}
        defaultTab={helpModalTab}
        onClose={() => setHelpModalOpen(false)}
      />

      {/* Profile Popover Menu (Stitch Screen 8) */}
      {profileOpen && (
        <ProfileMenu
          onClose={() => setProfileOpen(false)}
          onOpenSettings={() => {
            setSettingsTab('appearance')
            setShowSettings(true)
          }}
          onOpenKnowledgeBase={() => setKbDrawerOpen(true)}
          onOpenUpgrade={() => setUpgradeModalOpen(true)}
          onOpenHelpShortcuts={handleOpenHelpShortcuts}
        />
      )}
    </div>
  )
}

function generateAssistantResponse(query) {
  const lower = query.toLowerCase()

  if (lower.includes('pv-101') || lower.includes('thinning') || lower.includes('128')) {
    return {
      id: 'm-' + Date.now() + '-reply',
      role: 'assistant',
      text: `Per **SOP-STD-128 §4.2**, nominal thickness is 12.0 mm with a minimum allowable thickness of **8.0 mm**.

• **Current Reading:** 8.4 mm
• **Safety Margin:** 0.4 mm
• **Status:** PASS (Acceptable for continued operation)
• **Action:** Schedule UT re-inspection in **6 months**.`,
      trace: {
        router: 'Selected qwen2.5:14b (Modality: Text + RAG)',
        steps: [
          { id: 1, action: "Queried Qdrant collection: 'synthetic_sops'", done: true },
          { id: 2, action: 'Retrieved SOP_STD_128.md §4.2 (Score: 0.91)', done: true }
        ]
      },
      evidence: {
        hash: '#a3f9...d1',
        verified: true,
        tool: {
          name: 'RagSearchTool',
          query: '"PV-101 SOP-128"',
          latency: '42ms'
        },
        sources: [
          { name: 'SOP_STD_128.md:p14', note: 'Section 4.2 Minimum allowable wall thickness: 8.0 mm' }
        ],
        exports: [
          { label: 'Download .docx Report', type: 'docx' },
          { label: 'Download Audit JSONL', type: 'jsonl' }
        ]
      }
    }
  }

  if (lower.includes('quantum')) {
    return {
      id: 'm-' + Date.now() + '-reply',
      role: 'assistant',
      text: `Quantum computing leverages quantum mechanical phenomena—specifically **superposition** and **entanglement**—to perform computational tasks exponentially faster than classical supercomputers.

• **Superposition:** Qubits can exist as 0, 1, or both simultaneously.
• **Entanglement:** Qubits correlate instantly regardless of distance.
• **Key Fields:** Materials discovery, post-quantum cryptography, portfolio optimization, and complex chemical simulation.`
    }
  }

  if (lower.includes('cover letter')) {
    return {
      id: 'm-' + Date.now() + '-reply',
      role: 'assistant',
      text: `Here is a tailored cover letter draft:

Dear Hiring Manager,

I am writing to express my strong interest in the Senior Engineering role. With over 6 years of experience building distributed systems and AI-driven platforms, I specialize in translating complex technical requirements into scalable, reliable architectures.

• **Key Strengths:** Scalable frontend architectures, agentic workflow integrations, and performance optimization.
• **Recent Impact:** Reduced RAG inference latency by 45% while achieving 99.9% uptime.

I look forward to discussing how my experience aligns with your team's goals.

Best regards,  
Candidate`
    }
  }

  if (lower.includes('plan my day') || lower.includes('schedule')) {
    return {
      id: 'm-' + Date.now() + '-reply',
      role: 'assistant',
      text: `Here is an optimized daily plan designed for deep work:

• **09:00 - 11:30 AM:** Deep Work Block 1 (Core Architecture & Coding)
• **11:30 - 12:00 PM:** Asynchronous Comms & Code Reviews
• **12:00 - 01:00 PM:** Lunch & Mental Reset
• **01:00 - 03:00 PM:** Deep Work Block 2 (Feature Implementation & Unit Tests)
• **03:00 - 04:00 PM:** Team Sync & Cross-Functional Alignment
• **04:00 - 05:00 PM:** Planning & Next-day Task Prioritization`
    }
  }

  // Default response
  return {
    id: 'm-' + Date.now() + '-reply',
    role: 'assistant',
    text: `I have processed your request for: "${query}".

• **Synthesis:** Query analyzed across available local models and context memory.
• **Status:** Completed successfully.
• **Next steps:** Let me know if you would like a detailed breakdown, report export, or follow-up analysis.`
  }
}
