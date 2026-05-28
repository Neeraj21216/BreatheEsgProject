import React, { useState } from 'react';
import { uploadSAP, uploadUtility, uploadTravel } from '../api';

const SOURCES = [
  { key: 'sap',     label: 'SAP Flat File', fn: uploadSAP,     desc: 'CSV/TSV export from SAP MB51 or ME2N. Scope 1 fuel & procurement.', accept: '.csv,.tsv,.txt' },
  { key: 'utility', label: 'Utility CSV',   fn: uploadUtility, desc: 'Portal CSV export from electricity provider. Scope 2.', accept: '.csv' },
  { key: 'travel',  label: 'Travel CSV',    fn: uploadTravel,  desc: 'Concur or Navan export. Flights, hotels, ground transport. Scope 3.', accept: '.csv' },
];

function UploadCard({ source }) {
  const [file, setFile]     = useState(null);
  const [notes, setNotes]   = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr]       = useState('');

  const submit = async () => {
    if (!file) { setErr('Please select a file.'); return; }
    setLoading(true); setErr(''); setResult(null);
    try {
      const r = await source.fn(file, notes);
      setResult(r.data);
    } catch (e) {
      setErr(e.response?.data?.detail || 'Upload failed. Check console.');
    } finally { setLoading(false); }
  };

  return (
    <div className="upload-card">
      <h3>{source.label}</h3>
      <p>{source.desc}</p>
      <input className="file-input" type="file" accept={source.accept} onChange={e => setFile(e.target.files[0])} />
      <textarea className="notes-input" rows={2} placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} />
      <button className="btn btn-green" onClick={submit} disabled={loading}>
        {loading ? 'Uploading…' : 'Upload'}
      </button>
      {err && <p className="error">{err}</p>}
      {result && (
        <div style={{marginTop:12, fontSize:13}}>
          <span className={`badge badge-${result.status}`}>{result.status}</span>
          &nbsp; {result.parsed_rows}/{result.total_rows} rows parsed,&nbsp;
          {result.failed_rows} failed, {result.flagged_rows} flagged.
        </div>
      )}
    </div>
  );
}

export default function Upload() {
  return (
    <div>
      <h1 className="page-title">Upload Data</h1>
      <p style={{marginBottom:24, color:'#64748b', fontSize:14}}>
        Upload source files for ingestion. Each file is parsed, normalized, and queued for analyst review.
      </p>
      <div className="upload-grid">
        {SOURCES.map(s => <UploadCard key={s.key} source={s} />)}
      </div>
    </div>
  );
}