import React, { useState } from 'react';
import Dashboard from './pages/Dashboard';
import Records from './pages/Records';
import Upload from './pages/Upload';
import Jobs from './pages/Jobs';
import './App.css';

const NAV = [
  { id: 'dashboard', label: '📊 Dashboard' },
  { id: 'upload',    label: '📤 Upload' },
  { id: 'records',   label: '📋 Records' },
  { id: 'jobs',      label: '🔄 Jobs' },
];

export default function App() {
  const [page, setPage] = useState('dashboard');

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo">🌿 Breathe ESG</div>
        <nav>
          {NAV.map(n => (
            <button
              key={n.id}
              className={`nav-btn ${page === n.id ? 'active' : ''}`}
              onClick={() => setPage(n.id)}
            >{n.label}</button>
          ))}
        </nav>
      </aside>
      <main className="main">
        {page === 'dashboard' && <Dashboard />}
        {page === 'upload'    && <Upload />}
        {page === 'records'   && <Records />}
        {page === 'jobs'      && <Jobs />}
      </main>
    </div>
  );
}