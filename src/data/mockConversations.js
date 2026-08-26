const mockConversations = [
  {
    id: 'c1',
    title: 'Build my portfolio',
    createdAt: '2026-08-26T09:00:00Z',
    messages: [
      { id: 'm1', role: 'assistant', text: 'Welcome — I can help design your portfolio. What do you want to emphasize?' },
      { id: 'm2', role: 'user', text: 'I want a clean, minimal portfolio showcasing projects and blog.' },
      { id: 'm3', role: 'assistant', text: 'Great — I recommend a projects-first layout, short about, and contact form.' }
    ]
  },
  {
    id: 'c2',
    title: 'Explain neural networks',
    createdAt: '2026-08-26T08:30:00Z',
    messages: [
      { id: 'm1', role: 'user', text: 'Explain neural networks like I am 12.' },
      { id: 'm2', role: 'assistant', text: 'Neural networks are like layered decision machines...' }
    ]
  },
  {
    id: 'c3',
    title: 'Project architecture',
    createdAt: '2026-08-26T07:10:00Z',
    messages: [
      { id: 'm1', role: 'assistant', text: 'Let\'s plan the architecture — what are the main components?' }
    ]
  },
  {
    id: 'c4',
    title: 'System design notes',
    createdAt: '2026-08-25T16:00:00Z',
    messages: [
      { id: 'm1', role: 'user', text: 'High level system design for social feed' },
      { id: 'm2', role: 'assistant', text: 'You can partition by feed shard and use fan-out on write for scale.' }
    ]
  },
  {
    id: 'c5',
    title: 'React debugging',
    createdAt: '2026-08-25T12:00:00Z',
    messages: [
      { id: 'm1', role: 'assistant', text: 'Have you tried isolating state into smaller components?' }
    ]
  }
]

export default mockConversations
