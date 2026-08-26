import React from 'react'
import {
  GraduationCapIcon,
  PencilIcon,
  CalendarIcon,
  ChartIcon,
  MoreDotsIcon
} from './Icons'

export default function EmptyState({ onSelectSuggestion }) {
  const suggestions = [
    {
      icon: <GraduationCapIcon size={18} />,
      action: 'Explain',
      topic: 'quantum computing',
      prompt: 'Explain quantum computing in simple terms with real-world examples.'
    },
    {
      icon: <PencilIcon size={18} />,
      action: 'Write',
      topic: 'a cover letter',
      prompt: 'Write a professional cover letter for a Senior Software Engineer role.'
    },
    {
      icon: <CalendarIcon size={18} />,
      action: 'Help me',
      topic: 'plan my day',
      prompt: 'Help me plan my day with focused deep-work blocks.'
    },
    {
      icon: <ChartIcon size={18} />,
      action: 'Analyze',
      topic: 'this data',
      prompt: 'Check wall thinning on PV-101 (8.4mm) against SOP-128.'
    },
    {
      icon: <MoreDotsIcon size={18} />,
      action: 'More',
      topic: '',
      prompt: 'Summarize SOx reduction targets from MRPL Sustainability Report 2024.'
    }
  ]

  return (
    <div className="home-empty-container">
      <h1 className="home-hero-title">SARA-AI</h1>
      <div className="home-hero-subtitle">How can I help you today?</div>
      <div className="home-hero-desc">Ask, create, analyze, or research.</div>

      <div className="suggestions-row">
        {suggestions.map((item, idx) => (
          <div
            key={idx}
            className="suggestion-chip"
            onClick={() => onSelectSuggestion && onSelectSuggestion(item.prompt)}
          >
            <div className="chip-icon-wrapper">{item.icon}</div>
            <div className="chip-text">
              <span className="chip-action">{item.action}</span>
              {item.topic && <span className="chip-topic">{item.topic}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
