import React, { useState, useEffect, useCallback, useRef } from 'react'
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
import GpuStatusPanel from './components/GpuStatusPanel'
import mockConversations from './data/mockConversations'
import { HamburgerIcon, SparkleIcon, FolderIcon, ShieldIcon } from './components/Icons'
import { submitGoal, streamRun } from './hooks/useBackend'

// ---------------------------------------------------------------------------
// localStorage helpers for history persistence
// ---------------------------------------------------------------------------
const LS_CONVERSATIONS = 'saraai_conversations'
const LS_ACTIVE_ID     = 'saraai_active_id'

function loadConversations() {
  try {
    const raw = localStorage.getItem(LS_CONVERSATIONS)
    if (raw) return JSON.parse(raw)
  } catch (_) { /* corrupt data — fall through */ }
  return mockConversations
}

function loadActiveId(convs) {
  try {
    const saved = localStorage.getItem(LS_ACTIVE_ID)
    if (saved && convs.some(c => c.id === saved)) return saved
  } catch (_) { /* fall through */ }
  return convs[0]?.id || 'c-pv101'
}

export default function App() {
  const [conversations, setConversations] = useState(() => loadConversations())
  const [activeId, setActiveId] = useState(() => {
    const convs = loadConversations()
    return loadActiveId(convs)
  })
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
  const [activeAuditRequestId, setActiveAuditRequestId] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)

  // Phase E: hardware readiness — chat is locked until GPU status resolves
  const [backendReady, setBackendReady] = useState(false)

  // Ref to allow cancelling an in-flight SSE stream on new submission
  const activeStreamController = useRef(null)

  const activeConversation = conversations.find(c => c.id === activeId) || conversations[0]

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------
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
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // ---------------------------------------------------------------------------
  // Persist conversations + activeId to localStorage on every change
  // ---------------------------------------------------------------------------
  useEffect(() => {
    try {
      localStorage.setItem(LS_CONVERSATIONS, JSON.stringify(conversations))
    } catch (_) { /* storage quota exceeded — silently ignore */ }
  }, [conversations])

  useEffect(() => {
    try {
      localStorage.setItem(LS_ACTIVE_ID, activeId)
    } catch (_) { /* silently ignore */ }
  }, [activeId])


  // ---------------------------------------------------------------------------
  // Conversation helpers
  // ---------------------------------------------------------------------------
  function handleNewChat() {
    const id = 'c-' + Date.now().toString().slice(-6)
    const newConv = {
      id,
      title: 'New Conversation',
      group: 'Today',
      createdAt: new Date().toISOString(),
      messages: [],
    }
    setConversations(prev => [newConv, ...prev])
    setActiveId(id)
  }

  function updateConversation(updated) {
    setConversations(prev => prev.map(c => (c.id === updated.id ? updated : c)))
  }

  function updateMessage(convId, msgId, patch) {
    setConversations(prev =>
      prev.map(c => {
        if (c.id !== convId) return c
        return {
          ...c,
          messages: c.messages.map(m => (m.id === msgId ? { ...m, ...patch } : m)),
        }
      })
    )
  }

  // Clear all persisted history from state + localStorage
  function handleClearHistory() {
    try {
      localStorage.removeItem(LS_CONVERSATIONS)
      localStorage.removeItem(LS_ACTIVE_ID)
    } catch (_) { /* ignore */ }
    setConversations(mockConversations)
    setActiveId(mockConversations[0]?.id || 'c-pv101')
  }

  // ---------------------------------------------------------------------------
  // Main send handler — routes to real orchestrator
  // ---------------------------------------------------------------------------
  async function handleSend(text, files = []) {
    if (!text && files.length === 0) return
    if (!activeConversation) return

    // Cancel any in-flight stream
    if (activeStreamController.current) {
      activeStreamController.current.abort()
      activeStreamController.current = null
    }

    // Add user message
    const userMsgId = 'm-' + Date.now()
    const userMsg = {
      id: userMsgId,
      role: 'user',
      text: text || `[${files.length} file(s) attached]`,
      files: files.map(f => f.name),
    }

    // Add placeholder streaming message
    const streamingMsgId = 'm-' + (Date.now() + 1)
    const streamingMsg = {
      id: streamingMsgId,
      role: 'assistant',
      text: '',
      isStreaming: true,
      streamingSteps: [],
      currentTool: null,
    }

    const updatedConv = {
      ...activeConversation,
      title:
        activeConversation.messages.length === 0
          ? (text || 'File upload').slice(0, 28)
          : activeConversation.title,
      messages: [...(activeConversation.messages || []), userMsg, streamingMsg],
    }
    updateConversation(updatedConv)
    setIsGenerating(true)

    let requestId = null

    try {
      // Submit to real orchestrator
      const runResult = await submitGoal(text || '', files)
      requestId = runResult.request_id

      // Accumulate plan steps for the live trace
      let planSteps = []

      // Open SSE stream
      const controller = streamRun(
        requestId,
        // onEvent
        (event) => {
          const { type, payload } = event

          if (type === 'plan_ready') {
            planSteps = (payload.steps || []).map(s => ({
              ...s,
              done: false,
              success: null,
              attempt: 1,
            }))
            updateMessage(updatedConv.id, streamingMsgId, {
              streamingSteps: [...planSteps],
              currentTool: null,
            })
          }

          if (type === 'step_start') {
            const idx = planSteps.findIndex(s => s.step_index === payload.step_index)
            if (idx !== -1) {
              planSteps[idx] = { ...planSteps[idx], done: false, attempt: payload.attempt }
            }
            updateMessage(updatedConv.id, streamingMsgId, {
              streamingSteps: [...planSteps],
              currentTool: payload.tool_name,
            })
          }

          if (type === 'step_done') {
            const idx = planSteps.findIndex(s => s.step_index === payload.step_index)
            if (idx !== -1) {
              planSteps[idx] = {
                ...planSteps[idx],
                done: true,
                success: payload.success,
                error: payload.error,
                attempt: payload.attempt,
              }
            }
            updateMessage(updatedConv.id, streamingMsgId, {
              streamingSteps: [...planSteps],
              currentTool: null,
            })
          }

          if (type === 'retry') {
            const idx = planSteps.findIndex(s => s.step_index === payload.step_index)
            if (idx !== -1) {
              planSteps[idx] = { ...planSteps[idx], done: false, attempt: payload.attempt }
            }
            updateMessage(updatedConv.id, streamingMsgId, {
              streamingSteps: [...planSteps],
              currentTool: payload.tool_name,
            })
          }

          if (type === 'synthesis_start') {
            updateMessage(updatedConv.id, streamingMsgId, {
              currentTool: 'synthesis',
            })
          }

          if (type === 'completed') {
            // Build a clean trace object for AgentActivity
            const trace = {
              router: 'Sovereign Workbench Orchestrator',
              steps: planSteps.map((s, i) => ({
                id: i + 1,
                action: `${s.tool_name}${s.description ? ': ' + s.description : ''}`,
                done: s.done,
              })),
            }
            const evidence = {
              hash: `#${requestId.slice(0, 4)}…${requestId.slice(-2)}`,
              verified: true,
              tool: {
                name: planSteps[planSteps.length - 1]?.tool_name || 'orchestrator',
                query: text?.slice(0, 80),
                latency: '—',
              },
              sources: payload.sources || [],
            }

            updateMessage(updatedConv.id, streamingMsgId, {
              isStreaming: false,
              text: payload.final_output || '(No output)',
              sources: payload.sources || [],
              outputFiles: payload.output_files || [],
              trace,
              evidence,
              requestId,
            })

            setIsGenerating(false)
          }

          if (type === 'failed') {
            updateMessage(updatedConv.id, streamingMsgId, {
              isStreaming: false,
              isError: true,
              text: payload.failure_summary || 'The agent run failed.',
              retryQuery: text,
            })
            setIsGenerating(false)
          }
        },
        // onDone
        () => {
          setIsGenerating(false)
        },
        // onError
        (err) => {
          console.error('SSE error:', err)
          updateMessage(updatedConv.id, streamingMsgId, {
            isStreaming: false,
            isError: true,
            text: `Connection error: ${err.message}`,
            retryQuery: text,
          })
          setIsGenerating(false)
        }
      )
      activeStreamController.current = controller

    } catch (err) {
      // submitGoal() failed (network / backend down)
      updateMessage(updatedConv.id, streamingMsgId, {
        isStreaming: false,
        isError: true,
        text: `Failed to reach backend: ${err.message}`,
        retryQuery: text,
      })
      setIsGenerating(false)
    }
  }

  function handleOpenAudit(evidence, reqId) {
    setActiveAuditData(evidence || null)
    setActiveAuditRequestId(reqId || null)
    setAuditDrawerOpen(true)
  }

  function handleOpenHelpShortcuts(tab = 'shortcuts') {
    setHelpModalTab(tab)
    setHelpModalOpen(true)
  }

  // Wrap onOpenAudit to also pass requestId from the message
  function handleOpenAuditFromMessage(evidence) {
    // evidence may carry a .requestId set by the completed handler
    handleOpenAudit(evidence, evidence?.requestId || null)
  }

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
        onClearHistory={handleClearHistory}
      />

      {/* Main Viewport */}
      <main className={`main-viewport ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
        <CosmicBackground />

        {/* Top Header */}
        <header className="main-header">
          <div className="header-left">
            <button
              className="hamburger-btn"
              onClick={() => setSidebarOpen(v => !v)}
              title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
              aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            >
              <HamburgerIcon size={18} />
            </button>

            {/* Phase E: GPU/tier status panel — blocks chat until ready */}
            <GpuStatusPanel onReady={setBackendReady} />
          </div>

          <div className="header-right">
            <button
              className="btn-header-pill"
              onClick={() => setKbDrawerOpen(true)}
              title="Knowledge Base & SOPs"
            >
              <FolderIcon size={14} />
              <span>Knowledge Base</span>
            </button>

            <button
              className="btn-header-pill"
              onClick={() => {
                setActiveAuditData(null)
                setActiveAuditRequestId(null)
                setAuditDrawerOpen(true)
              }}
              title="Audit & Evidence Records"
            >
              <ShieldIcon size={14} />
              <span>Audit & Evidence</span>
            </button>

            <button
              className="btn-upgrade"
              onClick={() => setUpgradeModalOpen(true)}
              title="Upgrade to Pro"
            >
              <SparkleIcon size={14} />
              <span>Upgrade to Pro</span>
            </button>

            <button
              className="header-avatar"
              onClick={() => setProfileOpen(v => !v)}
              title="Operator Profile"
            >
              U
            </button>
          </div>
        </header>

        {/* Chat */}
        <ChatWindow
          conversation={activeConversation}
          onSendCustom={(text) => handleSend(text)}
          onOpenAudit={handleOpenAuditFromMessage}
          isGenerating={isGenerating}
        />

        {/* Composer — disabled until backend ready */}
        <Composer
          onSend={handleSend}
          onOpenHelp={() => handleOpenHelpShortcuts('faq')}
          disabled={!backendReady}
        />
      </main>

      <KnowledgeBaseDrawer
        isOpen={kbDrawerOpen}
        onClose={() => setKbDrawerOpen(false)}
      />

      <AuditPanel
        isOpen={auditDrawerOpen}
        evidence={activeAuditData}
        requestId={activeAuditRequestId}
        onClose={() => setAuditDrawerOpen(false)}
      />

      {showSettings && (
        <SettingsModal
          defaultTab={settingsTab}
          onClose={() => setShowSettings(false)}
        />
      )}

      <UpgradeModal
        isOpen={upgradeModalOpen}
        onClose={() => setUpgradeModalOpen(false)}
      />

      <HelpShortcutsModal
        isOpen={helpModalOpen}
        defaultTab={helpModalTab}
        onClose={() => setHelpModalOpen(false)}
      />

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
