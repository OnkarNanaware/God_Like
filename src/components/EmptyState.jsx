import React from 'react'

export default function EmptyState() {
  return (
    <div className="empty-state">
      <div className="moon-visual" aria-hidden />
      <h1>SARA-AI</h1>
      <p className="lead">How can I help you today?<br/>Ask, create, analyze, or research.</p>
      <div className="suggestions">
        <button className="chip"><strong>Explain</strong><div className="sub">quantum computing</div></button>
        <button className="chip"><strong>Write</strong><div className="sub">a cover letter</div></button>
        <button className="chip"><strong>Help me</strong><div className="sub">plan my day</div></button>
        <button className="chip"><strong>Analyze</strong><div className="sub">this data</div></button>
        <button className="chip"><strong>More</strong><div className="sub">&nbsp;</div></button>
      </div>
    </div>
  )
}
