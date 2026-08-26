import React from 'react'

export default function ProfileMenu({ onClose }) {
  return (
    <div className="profile-menu" role="menu">
      <div className="profile-top">
        <div className="avatar">👤</div>
        <div>
          <div className="name">User</div>
          <div className="email">user@example.com</div>
        </div>
      </div>
      <ul>
        <li><button>Account</button></li>
        <li><button>Settings</button></li>
        <li><button>Keyboard shortcuts</button></li>
        <li><button onClick={onClose}>Close</button></li>
      </ul>
    </div>
  )
}
