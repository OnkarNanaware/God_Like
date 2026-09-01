import React, { useState, useEffect } from 'react'

export default function KnowledgeBaseDrawer({ isOpen, onClose }) {
  const [documents, setDocuments] = useState([])
  const [selectedDoc, setSelectedDoc] = useState('')
  const [ingestStatus, setIngestStatus] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [collapsedCategories, setCollapsedCategories] = useState({})

  const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

  useEffect(() => {
    if (isOpen) {
      fetchDocuments()
    }
  }, [isOpen])

  async function fetchDocuments() {
    try {
      const res = await fetch(`${BACKEND_URL}/kb/documents`)
      if (res.ok) {
        const data = await res.json()
        if (data.documents && Array.isArray(data.documents)) {
          setDocuments(data.documents)
          if (!selectedDoc && data.documents.length > 0) {
            setSelectedDoc(data.documents[0].name)
          }
        }
      }
    } catch (err) {
      console.warn('Could not fetch KB documents:', err)
    }
  }

  async function uploadFileToKB(file) {
    if (!file) return
    setIsUploading(true)
    setIngestStatus(`⏳ Ingesting "${file.name}" into Qdrant vector index...`)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('collection', 'sovereign_knowledge_base')
      const res = await fetch(`${BACKEND_URL}/ingest/upload`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail?.message || `Server returned ${res.status}`)
      }
      const data = await res.json()
      setIngestStatus(`✓ Ingest Complete: "${file.name}" (${data.chunks_ingested} chunk(s) indexed in Qdrant)`)
      setSelectedDoc(file.name)
      await fetchDocuments()
      setTimeout(() => setIngestStatus(''), 7000)
    } catch (err) {
      setIngestStatus(`❌ Ingest Error: ${err.message}`)
      setTimeout(() => setIngestStatus(''), 7000)
    } finally {
      setIsUploading(false)
    }
  }

  async function ingestLocalFile(docName) {
    setIsUploading(true)
    setIngestStatus(`⏳ Indexing "${docName}" into Qdrant...`)
    try {
      const formData = new FormData()
      formData.append('filename', docName)
      formData.append('collection', 'sovereign_knowledge_base')
      const res = await fetch(`${BACKEND_URL}/kb/ingest_local`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail?.message || `Server returned ${res.status}`)
      }
      const data = await res.json()
      setIngestStatus(`✓ Indexed "${docName}" (${data.chunks_ingested} chunk(s) stored in Qdrant)`)
      await fetchDocuments()
      setTimeout(() => setIngestStatus(''), 7000)
    } catch (err) {
      setIngestStatus(`❌ Index Error: ${err.message}`)
      setTimeout(() => setIngestStatus(''), 7000)
    } finally {
      setIsUploading(false)
    }
  }

  function toggleCategory(cat) {
    setCollapsedCategories(prev => ({ ...prev, [cat]: !prev[cat] }))
  }

  function handleDrop(e) {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadFileToKB(e.dataTransfer.files[0])
    }
  }

  function handleFileSelect(e) {
    if (e.target.files && e.target.files[0]) {
      uploadFileToKB(e.target.files[0])
    }
    e.target.value = ''
  }

  function formatBytes(bytes) {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (!isOpen) return null

  // Group documents strictly from the real directory / backend response
  const categories = {}
  documents.forEach(doc => {
    const cat = doc.category || 'Other Documents'
    if (!categories[cat]) categories[cat] = []
    categories[cat].push(doc)
  })

  const selectedDocObj = documents.find(d => d.name === selectedDoc)

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="drawer-title">
            <span>📁</span>
            <span>Knowledge Base & SOPs</span>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Direct real directory categories */}
          {Object.keys(categories).length === 0 ? (
            <div style={{ padding: '20px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
              No documents found in knowledge_base/
            </div>
          ) : (
            Object.entries(categories).map(([catName, docs]) => {
              const isCollapsed = !!collapsedCategories[catName]
              return (
                <div key={catName}>
                  <div
                    onClick={() => toggleCategory(catName)}
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--text-highlight)',
                      marginBottom: 6,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      cursor: 'pointer',
                      userSelect: 'none'
                    }}
                  >
                    <span>{isCollapsed ? '▶' : '▼'}</span>
                    <span>{catName}</span>
                    <span style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 'auto' }}>
                      ({docs.length} file{docs.length > 1 ? 's' : ''})
                    </span>
                  </div>

                  {!isCollapsed && (
                    <ul style={{ listStyle: 'none', paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {docs.map(doc => {
                        const isSelected = selectedDoc === doc.name
                        const isIngested = doc.chunks > 0
                        return (
                          <li
                            key={doc.name}
                            style={{
                              fontSize: 12,
                              color: isSelected ? 'var(--accent-purple)' : (isIngested ? 'var(--text-highlight)' : 'var(--text-muted)'),
                              cursor: 'pointer',
                              padding: '6px 8px',
                              borderRadius: 6,
                              background: isSelected ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                              border: isSelected ? '1px solid rgba(167, 139, 250, 0.3)' : '1px solid transparent',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              gap: 6
                            }}
                            onClick={() => setSelectedDoc(doc.name)}
                          >
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={doc.name}>
                              • {doc.name}
                            </span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              {isIngested ? (
                                <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'rgba(34, 197, 94, 0.15)', color: '#4ade80', whiteSpace: 'nowrap' }}>
                                  {doc.chunks} chunk{doc.chunks > 1 ? 's' : ''}
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); ingestLocalFile(doc.name); }}
                                  disabled={isUploading}
                                  style={{
                                    fontSize: 10,
                                    padding: '2px 6px',
                                    borderRadius: 4,
                                    background: 'rgba(167, 139, 250, 0.15)',
                                    border: '1px solid rgba(167, 139, 250, 0.4)',
                                    color: 'var(--accent-purple)',
                                    cursor: isUploading ? 'not-allowed' : 'pointer'
                                  }}
                                  title="Index this file into Qdrant"
                                >
                                  + Index
                                </button>
                              )}
                            </div>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })
          )}

          {/* Selected Document Details Card */}
          {selectedDocObj && (
            <div style={{ marginTop: 8, padding: 12, borderRadius: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', fontSize: 11 }}>
              <div style={{ fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 4, wordBreak: 'break-all' }}>
                📄 {selectedDocObj.name}
              </div>
              <div style={{ display: 'flex', gap: 12, color: 'var(--text-dim)', marginBottom: 6 }}>
                <span>Folder: {selectedDocObj.category}</span>
                {selectedDocObj.size_bytes && <span>Size: {formatBytes(selectedDocObj.size_bytes)}</span>}
              </div>
              <div style={{ color: selectedDocObj.chunks > 0 ? '#4ade80' : 'var(--text-dim)', marginBottom: selectedDocObj.preview ? 6 : 0 }}>
                Status: {selectedDocObj.chunks > 0 ? `Indexed in Qdrant (${selectedDocObj.chunks} chunks)` : 'Stored in folder (Not indexed yet)'}
              </div>
              {selectedDocObj.preview && (
                <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', background: 'rgba(0,0,0,0.2)', padding: '6px 8px', borderRadius: 4 }}>
                  "{selectedDocObj.preview}..."
                </div>
              )}
            </div>
          )}

          {/* Ingest Actions */}
          <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <label
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                padding: '9px 12px',
                borderRadius: 8,
                background: isUploading ? 'rgba(167, 139, 250, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-highlight)',
                fontSize: 13,
                fontWeight: 500,
                cursor: isUploading ? 'not-allowed' : 'pointer'
              }}
            >
              <span>{isUploading ? '⏳ Indexing into Qdrant...' : '＋ Ingest New File'}</span>
              <input
                type="file"
                style={{ display: 'none' }}
                onChange={handleFileSelect}
                accept=".pdf,.doc,.docx,.md,.txt,.json,.jsonl"
                disabled={isUploading}
              />
            </label>

            <div
              style={{
                marginTop: 10,
                border: '1px dashed var(--border-medium)',
                borderRadius: 8,
                padding: '16px 12px',
                textAlign: 'center',
                fontSize: 12,
                color: 'var(--text-dim)',
                background: 'rgba(255, 255, 255, 0.02)',
                cursor: isUploading ? 'not-allowed' : 'pointer'
              }}
              onDragOver={e => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => document.querySelector('.drawer-panel input[type="file"]')?.click()}
            >
              [Drop PDF/Doc here to index into Qdrant]
            </div>

            {ingestStatus && (
              <div style={{
                fontSize: 12,
                color: ingestStatus.startsWith('✓') ? 'var(--accent-green)' : (ingestStatus.startsWith('❌') ? 'var(--accent-red)' : 'var(--text-highlight)'),
                marginTop: 10,
                padding: '8px 10px',
                borderRadius: 6,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid var(--border-subtle)',
                textAlign: 'center',
                fontWeight: 500
              }}>
                {ingestStatus}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
