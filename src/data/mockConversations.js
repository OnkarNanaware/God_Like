const mockConversations = [
  {
    id: 'c-pv101',
    title: 'Check wall thinning on PV-101',
    group: 'Today',
    createdAt: new Date().toISOString(),
    messages: [
      {
        id: 'm1',
        role: 'user',
        text: 'Check wall thinning on PV-101 (8.4mm) against SOP-128.'
      },
      {
        id: 'm2',
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
    ]
  },
  {
    id: 'c-quantum',
    title: 'Explain quantum computing',
    group: 'Today',
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    messages: [
      {
        id: 'm1',
        role: 'user',
        text: 'Explain quantum computing in simple terms.'
      },
      {
        id: 'm2',
        role: 'assistant',
        text: `Quantum computing utilizes principles of quantum mechanics—such as **superposition** and **entanglement**—to process complex information exponentially faster than classical binary bits.

• **Qubits:** Unlike classical bits (0 or 1), qubits can exist simultaneously in both states.
• **Applications:** Materials science, cryptography, optimization, and molecular simulation.`
      }
    ]
  },
  {
    id: 'c-todo',
    title: 'Code a To-do app in React',
    group: 'Today',
    createdAt: new Date(Date.now() - 7200000).toISOString(),
    messages: []
  },
  {
    id: 'c-css',
    title: 'Best practices for CSS',
    group: 'Today',
    createdAt: new Date(Date.now() - 10800000).toISOString(),
    messages: []
  },
  {
    id: 'c-url',
    title: 'System design: URL shortener',
    group: 'Yesterday',
    createdAt: new Date(Date.now() - 86400000).toISOString(),
    messages: []
  },
  {
    id: 'c-python',
    title: 'Debug Python code',
    group: 'Yesterday',
    createdAt: new Date(Date.now() - 90000000).toISOString(),
    messages: []
  },
  {
    id: 'c-git',
    title: 'Git branching strategies',
    group: 'Yesterday',
    createdAt: new Date(Date.now() - 93600000).toISOString(),
    messages: []
  },
  {
    id: 'c-docker',
    title: 'What is Docker?',
    group: 'Previous 7 days',
    createdAt: new Date(Date.now() - 172800000).toISOString(),
    messages: []
  },
  {
    id: 'c-tips',
    title: 'Tips for productivity',
    group: 'Previous 7 days',
    createdAt: new Date(Date.now() - 259200000).toISOString(),
    messages: []
  },
  {
    id: 'c-eventloop',
    title: 'JavaScript event loop',
    group: 'Previous 7 days',
    createdAt: new Date(Date.now() - 345600000).toISOString(),
    messages: []
  }
]

export default mockConversations
