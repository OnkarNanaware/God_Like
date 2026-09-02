/**
 * useBackend.js
 * =============
 * Single source of truth for all backend API calls.
 *
 * Rules enforced here:
 *  - No direct calls to Ollama (localhost:11434) — everything goes through
 *    the FastAPI backend at BACKEND_URL.
 *  - No direct calls to Qdrant — same rule.
 *  - All file uploads go through POST /orchestrator/run (multipart).
 *  - SSE streaming is via native EventSource / fetch streaming.
 */

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Hardware / GPU status
// ---------------------------------------------------------------------------

/**
 * Fetch the current hardware tier status from the backend.
 *
 * Returns:
 *   { gpu_info, force_tier, resolved_models: [{modality, model_name, ollama_tag, tier, est_vram_mb}], degraded }
 */
export async function fetchHardwareStatus() {
  const res = await fetch(`${BACKEND_URL}/hardware/status`)
  if (!res.ok) throw new Error(`/hardware/status returned ${res.status}`)
  return res.json()
}

/**
 * DEV/DEMO MODE: force a specific tier across all model slots.
 *
 * @param {string} tier  - 'small' | 'mid' | 'large' | 'default' | ''
 * Returns the updated resolved_models list and a vram_note string.
 */
export async function forceTier(tier) {
  const body = new FormData()
  body.append('tier', tier)
  const res = await fetch(`${BACKEND_URL}/hardware/force_tier`, {
    method: 'POST',
    body,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail?.message || `force_tier returned ${res.status}`)
  }
  return res.json()
}

/**
 * Override a single modality slot with a specific model.
 *
 * @param {string} modality   - 'text' | 'code' | 'vision' | 'embedding'
 * @param {string} modelName  - Registry key (model_name field from available_models)
 * Returns { applied_modality, applied_model, resolved_models, manual_overrides, vram_note }
 */
export async function forceModel(modality, modelName) {
  const body = new FormData()
  body.append('modality', modality)
  body.append('model_name', modelName)
  const res = await fetch(`${BACKEND_URL}/hardware/force_model`, {
    method: 'POST',
    body,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail?.message || `force_model returned ${res.status}`)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Orchestrator: submit + stream
// ---------------------------------------------------------------------------

/**
 * Submit a goal to the agentic orchestrator loop.
 *
 * @param {string}   goal  - Natural-language task description.
 * @param {File[]}   files - Optional file attachments (image / PDF).
 * Returns { request_id, status, goal_preview, attached_files }
 */
export async function submitGoal(goal, files = []) {
  const body = new FormData()
  body.append('goal', goal)
  for (const f of files) {
    body.append('files', f)
  }
  const res = await fetch(`${BACKEND_URL}/orchestrator/run`, {
    method: 'POST',
    body,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err?.detail?.message || `/orchestrator/run returned ${res.status}`)
  }
  return res.json()
}

/**
 * Open an SSE stream for a running orchestrator request.
 *
 * @param {string}   requestId  - The request_id returned by submitGoal().
 * @param {function} onEvent    - Called with each parsed event object.
 * @param {function} onDone     - Called when the stream ends (normal or error).
 * @param {function} onError    - Called on network/parse errors.
 *
 * Returns an AbortController so the caller can cancel.
 */
export function streamRun(requestId, onEvent, onDone, onError) {
  const controller = new AbortController()
  const url = `${BACKEND_URL}/orchestrator/stream/${requestId}`

  // Use fetch instead of EventSource so we get signal/abort support.
  ;(async () => {
    try {
      const res = await fetch(url, { signal: controller.signal })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        onError?.(new Error(`SSE endpoint returned ${res.status}: ${text}`))
        onDone?.()
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by double-newlines.
        const frames = buffer.split('\n\n')
        buffer = frames.pop() // keep incomplete frame

        for (const frame of frames) {
          for (const line of frame.split('\n')) {
            if (line.startsWith('data: ')) {
              const raw = line.slice(6).trim()
              if (raw === '[DONE]') {
                onDone?.()
                return
              }
              try {
                const event = JSON.parse(raw)
                onEvent?.(event)
                if (event.type === 'done') {
                  onDone?.()
                  return
                }
              } catch {
                // keepalive comment or malformed line — ignore
              }
            }
            // SSE comments (: keepalive) are silently ignored
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        onError?.(err)
      }
      onDone?.()
    }
  })()

  return controller
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

/**
 * Fetch recent audit records from the backend.
 *
 * @param {string|null} requestId - Filter to a specific run (null = global).
 * @param {number}      n         - Max records to return (default 50).
 * Returns { records, chain_valid, chain_errors, total_scanned, returned }
 */
export async function fetchAuditRecent(requestId = null, n = 50) {
  const params = new URLSearchParams({ n: String(n) })
  if (requestId) params.set('request_id', requestId)
  const res = await fetch(`${BACKEND_URL}/audit/recent?${params}`)
  if (!res.ok) throw new Error(`/audit/recent returned ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Output file download URL builder
// ---------------------------------------------------------------------------

/**
 * Build a download URL for a registered artifact using its UUID.
 *
 * @param {string} artifactId - The 32-char hex artifact_id from the SSE event.
 * Returns the full download URL string.
 */
export function artifactDownloadUrl(artifactId) {
  return `${BACKEND_URL}/outputs/${encodeURIComponent(artifactId)}`
}

/**
 * @deprecated Use artifactDownloadUrl(artifact_id) instead.
 *
 * Build a URL for downloading a generated output file by basename.
 * Kept as a compatibility shim — the backend now requires a UUID artifact_id,
 * so this function will return URLs that result in 400 for any new artifact.
 *
 * @param {string} filename - Basename only (no path separators).
 */
export function outputFileUrl(filename) {
  // Strip any path components the server would reject anyway.
  const safe = filename.split('/').pop().split('\\').pop()
  return `${BACKEND_URL}/outputs/${encodeURIComponent(safe)}`
}

// ---------------------------------------------------------------------------
// Health check (used by GPU panel fallback)
// ---------------------------------------------------------------------------

export async function fetchHealth() {
  const res = await fetch(`${BACKEND_URL}/health`)
  if (!res.ok) throw new Error(`/health returned ${res.status}`)
  return res.json()
}
