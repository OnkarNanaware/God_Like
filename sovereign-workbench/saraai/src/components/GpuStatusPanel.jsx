import React, { useState, useEffect, useCallback } from 'react'
import { fetchHardwareStatus, forceTier, forceModel } from '../hooks/useBackend'

const TIER_COLORS = {
  large: '#a78bfa',
  mid: '#60a5fa',
  small: '#34d399',
  default: '#94a3b8',
  unknown: '#94a3b8',
}

const MODALITY_LABELS = {
  text: 'Reasoning',
  code: 'Code',
  vision: 'Vision',
  embedding: 'Embeddings',
}

/**
 * GpuStatusPanel
 * ==============
 * Renders hardware tier information in the top header.
 *
 * Props
 * -----
 * onReady(isReady: bool)  — called when status resolves so App can unlock chat.
 */
export default function GpuStatusPanel({ onReady }) {
  const [status, setStatus] = useState(null)       // null = loading
  const [error, setError] = useState(null)
  const [showDetails, setShowDetails] = useState(false)
  const [devOpen, setDevOpen] = useState(false)
  const [forcingTier, setForcingTier] = useState(false)
  const [vramNote, setVramNote] = useState(null)   // Fix #5: post-switch note

  const [forcingModel, setForcingModel] = useState(null)

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchHardwareStatus()
      setStatus(data)
      setError(null)
      onReady?.(true)
    } catch (err) {
      setError(err.message || 'Backend unreachable')
      onReady?.(false)
    }
  }, [onReady])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  async function handleForceTier(tier) {
    setForcingTier(true)
    setDevOpen(false)
    try {
      const result = await forceTier(tier)
      // Fix #5: show the eviction-lag note immediately after a tier switch
      if (tier) {
        setVramNote(result.vram_note || 'Tier switching — Ollama may take a moment to unload the previous model from VRAM.')
        setTimeout(() => setVramNote(null), 8000)
      } else {
        setVramNote(null)
      }
      await loadStatus()
    } catch (err) {
      setError(`Force-tier failed: ${err.message}`)
    } finally {
      setForcingTier(false)
    }
  }

  async function handleForceModel(modality, modelName) {
    setForcingModel(modality)
    try {
      const result = await forceModel(modality, modelName)
      setVramNote(result.vram_note || 'Model override applied.')
      setTimeout(() => setVramNote(null), 6000)
      await loadStatus()
    } catch (err) {
      setError(`Force-model failed: ${err.message}`)
    } finally {
      setForcingModel(null)
    }
  }

  // ── Loading state ─────────────────────────────────────────────────
  if (!status && !error) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 12, color: 'var(--text-dim)',
        padding: '4px 10px',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        animation: 'pulse 1.5s ease-in-out infinite',
      }}>
        <span style={{ fontSize: 10 }}>⏳</span>
        <span>Detecting hardware…</span>
      </div>
    )
  }

  // ── Error / backend unreachable ───────────────────────────────────
  if (error) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 12, color: '#f87171',
        padding: '4px 10px',
        background: 'rgba(248,113,113,0.08)',
        border: '1px solid rgba(248,113,113,0.3)',
        borderRadius: 8,
      }}>
        <span>⚠</span>
        <span>Backend unreachable — running offline</span>
      </div>
    )
  }

  const degraded = status.degraded
  const models = status.resolved_models || []
  const availableModels = status.available_models || {}
  const gpuInfo = status.gpu_info || {}
  const activeTier = status.force_tier || 'auto'

  // Summary pill: show primary text-modality model
  const textSlot = models.find(m => m.modality === 'text')
  const summaryTag = textSlot?.ollama_tag || 'CPU'
  const summaryTier = textSlot?.tier || 'default'
  const summaryColor = TIER_COLORS[summaryTier] || TIER_COLORS.default

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      {/* Main status pill */}
      <button
        id="gpu-status-pill"
        onClick={() => setShowDetails(v => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 11.5,
          padding: '4px 10px',
          background: degraded
            ? 'rgba(251,191,36,0.08)'
            : 'rgba(255,255,255,0.04)',
          border: `1px solid ${degraded ? 'rgba(251,191,36,0.4)' : 'var(--border-subtle)'}`,
          borderRadius: 8,
          color: degraded ? '#fbbf24' : 'var(--text-muted)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          fontFamily: 'var(--font-mono)',
        }}
        title={degraded ? 'No GPU detected — running CPU tier' : 'GPU detected'}
        aria-label="Hardware status"
      >
        <span style={{ fontSize: 9, color: summaryColor }}>●</span>
        <span style={{ color: summaryColor, fontWeight: 600 }}>
          {summaryTier.toUpperCase()}
        </span>
        <span style={{ color: 'var(--text-dim)' }}>·</span>
        <span>{summaryTag}</span>
        {degraded && <span style={{ fontSize: 10 }}>⚠</span>}
        <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
          {showDetails ? '▲' : '▼'}
        </span>
      </button>

      {/* Detail dropdown */}
      {showDetails && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 6px)',
          left: 0,
          zIndex: 200,
          minWidth: 380,
          backgroundColor: '#0d101a',
          background: '#0d101a',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          borderRadius: 10,
          padding: '12px 14px',
          boxShadow: '0 12px 36px rgba(0,0,0,0.8)',
        }}>
          {/* GPU info */}
          <div style={{ marginBottom: 10, fontSize: 12 }}>
            <div style={{ fontWeight: 600, color: 'var(--text-highlight)', marginBottom: 4 }}>
              🖥 Hardware
            </div>
            {gpuInfo.gpu_available ? (
              <div style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
                <div>{gpuInfo.device_name}</div>
                <div>
                  VRAM: <span style={{ color: 'var(--text-highlight)' }}>
                    {gpuInfo.free_vram_mb?.toLocaleString()} MB free
                  </span>
                  {' / '}
                  {gpuInfo.total_vram_mb?.toLocaleString()} MB total
                </div>
              </div>
            ) : (
              <div style={{ color: '#fbbf24' }}>
                ⚠ No GPU detected — CPU inference only (slowest tier)
              </div>
            )}
          </div>

          {/* Per-slot model table with dropdowns */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ fontWeight: 600, fontSize: 12, color: 'var(--text-highlight)' }}>
                🧠 Active Models
              </div>
              <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>Auto-detected / Selectable</span>
            </div>
            {models.map(m => {
              const options = availableModels[m.modality] || []
              const hasChoices = options.length > 1
              const isModalityBusy = forcingModel === m.modality

              return (
                <div key={m.modality} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '6px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  fontSize: 12,
                  gap: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 80 }}>
                    <span style={{ color: 'var(--text-dim)' }}>
                      {MODALITY_LABELS[m.modality] || m.modality}
                    </span>
                    {m.manual && (
                      <span title="Manually pinned" style={{ fontSize: 10, color: '#fbbf24' }}>⚡</span>
                    )}
                  </div>

                  <div style={{ flex: 1 }}>
                    {hasChoices ? (
                      <select
                        value={m.model_name}
                        disabled={isModalityBusy || forcingTier}
                        onChange={(e) => handleForceModel(m.modality, e.target.value)}
                        style={{
                          width: '100%',
                          background: 'rgba(255, 255, 255, 0.06)',
                          border: m.manual ? '1px solid rgba(251, 191, 36, 0.4)' : '1px solid rgba(255, 255, 255, 0.12)',
                          borderRadius: 6,
                          color: '#e2e8f0',
                          padding: '3px 6px',
                          fontSize: 11,
                          fontFamily: 'var(--font-mono)',
                          cursor: 'pointer',
                          outline: 'none',
                        }}
                      >
                        {options.map((opt) => (
                          <option key={opt.model_name} value={opt.model_name} style={{ background: '#0d101a', color: '#fff' }}>
                            {opt.ollama_tag} ({opt.tier.toUpperCase()})
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                        {m.ollama_tag}
                      </span>
                    )}
                  </div>

                  <span style={{
                    fontSize: 10, fontWeight: 700,
                    color: TIER_COLORS[m.tier] || TIER_COLORS.default,
                    background: `${TIER_COLORS[m.tier] || TIER_COLORS.default}18`,
                    border: `1px solid ${TIER_COLORS[m.tier] || TIER_COLORS.default}40`,
                    borderRadius: 4, padding: '2px 6px',
                    minWidth: 44, textAlign: 'center',
                  }}>
                    {isModalityBusy ? '...' : m.tier?.toUpperCase()}
                  </span>
                </div>
              )
            })}
          </div>

          {/* VRAM eviction note (Fix #5) */}
          {vramNote && (
            <div style={{
              marginBottom: 8,
              padding: '6px 8px',
              background: 'rgba(251,191,36,0.08)',
              border: '1px solid rgba(251,191,36,0.3)',
              borderRadius: 6,
              fontSize: 11.5,
              color: '#fbbf24',
              lineHeight: 1.4,
            }}>
              ⏳ {vramNote}
            </div>
          )}

          {/* DEV: Force Tier */}
          <div style={{
            borderTop: '1px solid var(--border-subtle)',
            paddingTop: 8,
            marginTop: 4,
          }}>
            <div style={{
              fontSize: 10.5,
              color: 'var(--text-dim)',
              marginBottom: 6,
              fontWeight: 500,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}>
              🛠 Dev Mode — Force Tier
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {['small', 'mid', 'large', ''].map(t => (
                <button
                  key={t || 'auto'}
                  id={`force-tier-${t || 'auto'}`}
                  onClick={() => handleForceTier(t)}
                  disabled={forcingTier}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 6,
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: forcingTier ? 'wait' : 'pointer',
                    background: (status.force_tier === t || (!status.force_tier && t === ''))
                      ? 'rgba(167,139,250,0.2)'
                      : 'rgba(255,255,255,0.05)',
                    border: (status.force_tier === t || (!status.force_tier && t === ''))
                      ? '1px solid rgba(167,139,250,0.6)'
                      : '1px solid var(--border-subtle)',
                    color: (status.force_tier === t || (!status.force_tier && t === ''))
                      ? '#a78bfa'
                      : 'var(--text-dim)',
                    transition: 'all 0.15s',
                  }}
                >
                  {t ? t.toUpperCase() : 'AUTO'}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
