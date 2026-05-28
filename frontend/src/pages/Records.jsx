import React, { useEffect, useState, useCallback } from 'react';
import { getRecords, approveRecords, flagRecords, getAuditLog } from '../api';

const FLAG_REASONS = [
  'unit_ambiguous','missing_factor','outlier_value','duplicate_suspected',
  'period_gap','period_overlap','plant_unknown','negative_value','manual_flag',
];

export default function Records() {
  const [records, setRecords]   = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [filters, setFilters]   = useState({ status: '', scope: '', category: '' });
  const [loading, setLoading]   = useState(false);
  const [msg, setMsg]           = useState('');
  const [auditLog, setAuditLog] = useState(null);
  const [auditId, setAuditId]   = useState(null);
  const [flagReason, setFlagReason] = useState('manual_flag');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getRecords(Object.fromEntries(Object.entries(filters).filter(([,v])=>v)));
      setRecords(r.data.results || r.data);
    } catch { setMsg('Failed to load records.'); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  const toggle = id => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSelected(s => s.size === records.length ? new Set() : new Set(records.map(r=>r.id)));

  const approve = async () => {
    if (!selected.size) return;
    const r = await approveRecords([...selected]);
    setMsg(`✅ Approved ${r.data.approved} records.`);
    setSelected(new Set()); load();
  };

  const flag = async () => {
    if (!selected.size) return;
    const r = await flagRecords([...selected], flagReason, '');
    setMsg(`🚩 Flagged ${r.data.flagged} records.`);
    setSelected(new Set()); load();
  };

  const showAudit = async id => {
    const r = await getAuditLog(id);
    setAuditLog(r.data); setAuditId(id);
  };

  return (
    <div>
      <h1 className="page-title">Review Records</h1>

      <div className="filters">
        <select value={filters.status} onChange={e => setFilters(f=>({...f,status:e.target.value}))}>
          <option value="">All statuses</option>
          <option>pending</option><option>flagged</option><option>approved</option><option>locked</option>
        </select>
        <select value={filters.scope} onChange={e => setFilters(f=>({...f,scope:e.target.value}))}>
          <option value="">All scopes</option>
          <option value="1">Scope 1</option><option value="2">Scope 2</option><option value="3">Scope 3</option>
        </select>
        <button className="btn btn-gray" onClick={load}>Refresh</button>
        {selected.size > 0 && <>
          <button className="btn btn-green" onClick={approve}>Approve ({selected.size})</button>
          <select value={flagReason} onChange={e=>setFlagReason(e.target.value)}>
            {FLAG_REASONS.map(r=><option key={r}>{r}</option>)}
          </select>
          <button className="btn btn-red" onClick={flag}>Flag ({selected.size})</button>
        </>}
      </div>

      {msg && <p className="success" style={{marginBottom:12}}>{msg}</p>}

      <div className="card">
        <div className="tbl-wrap">
          {loading ? <p>Loading…</p> : (
            <table>
              <thead>
                <tr>
                  <th><input type="checkbox" onChange={toggleAll} checked={selected.size===records.length && records.length>0} /></th>
                  <th>Scope</th><th>Category</th><th>Period</th>
                  <th>Quantity</th><th>tCO₂e</th><th>Status</th><th>Flags</th><th>Audit</th>
                </tr>
              </thead>
              <tbody>
                {records.length === 0 && <tr><td colSpan={9} style={{color:'#94a3b8'}}>No records yet — upload some data first.</td></tr>}
                {records.map(r => (
                  <tr key={r.id}>
                    <td><input type="checkbox" checked={selected.has(r.id)} onChange={()=>toggle(r.id)} disabled={r.status==='locked'} /></td>
                    <td>Scope {r.scope}</td>
                    <td style={{maxWidth:140, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.category}</td>
                    <td>{r.period_start} → {r.period_end}</td>
                    <td>{r.original_quantity} {r.original_unit}</td>
                    <td style={{fontWeight:600}}>{r.co2e_tonnes ?? '—'}</td>
                    <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                    <td style={{color:'#dc2626', fontSize:11}}>{r.flags?.join(', ')}</td>
                    <td><button className="btn btn-gray" style={{padding:'4px 8px',fontSize:11}} onClick={()=>showAudit(r.id)}>Log</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {auditLog && (
        <div className="card" style={{marginTop:20}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12}}>
            <h2>Audit Log — {auditId}</h2>
            <button className="btn btn-gray" onClick={()=>setAuditLog(null)}>Close</button>
          </div>
          {auditLog.length === 0 ? <p style={{color:'#94a3b8'}}>No audit entries yet.</p> : (
            <table>
              <thead><tr><th>Action</th><th>Field</th><th>Old</th><th>New</th><th>By</th><th>When</th></tr></thead>
              <tbody>
                {auditLog.map(e=>(
                  <tr key={e.id}>
                    <td>{e.action}</td><td>{e.field_name}</td>
                    <td>{e.old_value}</td><td>{e.new_value}</td>
                    <td>{e.changed_by}</td>
                    <td>{new Date(e.timestamp).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}