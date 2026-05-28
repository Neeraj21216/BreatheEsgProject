import React, { useEffect, useState } from 'react';
import { getDashboard } from '../api';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';

const COLORS = ['#16a34a','#2563eb','#f59e0b'];

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState('');

  useEffect(() => {
    getDashboard().then(r => setData(r.data)).catch(() => setErr('Could not load dashboard. Make sure a Tenant exists in admin.'));
  }, []);

  if (err)   return <div><p className="page-title">Dashboard</p><p className="error">{err}</p></div>;
  if (!data) return <p>Loading…</p>;

  const scopeData = [
    { name: 'Scope 1', value: parseFloat(data.by_scope['1']) },
    { name: 'Scope 2', value: parseFloat(data.by_scope['2']) },
    { name: 'Scope 3', value: parseFloat(data.by_scope['3']) },
  ];

  const statusData = [
    { name: 'Pending',  value: data.pending },
    { name: 'Flagged',  value: data.flagged },
    { name: 'Approved', value: data.approved },
    { name: 'Locked',   value: data.locked },
  ];

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>

      <div className="stat-grid">
        <div className="stat"><div className="label">Total Records</div><div className="value">{data.total_records}</div></div>
        <div className="stat"><div className="label">Total tCO₂e</div><div className="value" style={{color:'#16a34a'}}>{parseFloat(data.total_co2e).toFixed(2)}</div></div>
        <div className="stat"><div className="label">Pending Review</div><div className="value" style={{color:'#f59e0b'}}>{data.pending}</div></div>
        <div className="stat"><div className="label">Flagged</div><div className="value" style={{color:'#dc2626'}}>{data.flagged}</div></div>
        <div className="stat"><div className="label">Approved</div><div className="value" style={{color:'#16a34a'}}>{data.approved}</div></div>
        <div className="stat"><div className="label">Locked</div><div className="value" style={{color:'#6366f1'}}>{data.locked}</div></div>
      </div>

      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, marginBottom:24}}>
        <div className="card">
          <h2>Emissions by Scope (tCO₂e)</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={scopeData}>
              <XAxis dataKey="name" /><YAxis /><Tooltip />
              <Bar dataKey="value" fill="#16a34a" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h2>Records by Status</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {statusData.map((_, i) => <Cell key={i} fill={['#f59e0b','#dc2626','#16a34a','#6366f1'][i]} />)}
              </Pie>
              <Legend /><Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h2>Recent Ingestion Jobs</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Source</th><th>Status</th><th>Total</th><th>Parsed</th><th>Failed</th><th>Date</th></tr></thead>
            <tbody>
              {data.recent_jobs.length === 0 && <tr><td colSpan={6} style={{color:'#94a3b8'}}>No jobs yet — upload some data.</td></tr>}
              {data.recent_jobs.map(j => (
                <tr key={j.id}>
                  <td>{j.source_type}</td>
                  <td><span className={`badge badge-${j.status}`}>{j.status}</span></td>
                  <td>{j.total_rows}</td><td>{j.parsed_rows}</td><td>{j.failed_rows}</td>
                  <td>{new Date(j.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}