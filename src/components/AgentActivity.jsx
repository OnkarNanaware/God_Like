import React from 'react'

export default function AgentActivity() {
  const steps = [
    { text: 'Understanding request', done: true },
    { text: 'Planning approach', done: true },
    { text: 'Researching information', done: false },
    { text: 'Preparing response', done: false }
  ]

  return (
    <div className="agent-activity" aria-live="polite">
      <div className="agent-title">Sa‑Ra is working</div>
      <ul>
        {steps.map((s, i) => (
          <li key={i} className={s.done ? 'done' : 'pending'}>
            <span className="dot">{s.done ? '✓' : '◌'}</span>
            <span>{s.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
