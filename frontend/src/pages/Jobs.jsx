import React, { useEffect, useState } from 'react';
import { getJobs } from '../api';

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => { getJobs().then(r => setJobs(r.data.results || r.data)); }, []);

  return (
    <div>
      <h1 className="page-title">Ingestion Jobs</h1>
      <div className="card">
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr><th>Source</th><th>File</th><th>Status</th><th>Total</th><th>Parsed</th><th>Failed</th><th>Flagged</th><th>Date</th><th>Errors</th></tr>
            </thead>
            <tbody>
              {jobs.length === 0 && <tr><td colSpan={9} style={{color:'#94a3b8'}}>No jobs yet.</td></tr>}
              {jobs.map(j => (
                <React.Fragment key={j.id}>
                  <tr>
                    <td>{j.source_type}</td>
                    <td style={{maxWidth:160, overflow:'hidden', textOverflow:'ellipsis'}}>{j.file_name}</td>
                    <td><span className={`badge badge-${j.status}`}>{j.status}</span></td>
                    <td>{j.total_rows}</td><td>{j.parsed_rows}</td><td>{j.failed_rows}</td><td>{j.flagged_rows}</td>
                    <td>{new Date(j.created_at).toLocaleDateString()}</td>
                    <td>
                      {j.parse_errors?.length > 0 &&
                        <button className="btn btn-gray" style={{padding:'3px 8px',fontSize:11}} onClick={()=>setExpanded(expanded===j.id?null:j.id)}>
                          {j.parse_errors.length} errors
                        </button>}
                    </td>
                  </tr>
                  {expanded === j.id && (
                    <tr><td colSpan={9}>
                      <pre style={{background:'#fef2f2',padding:12,borderRadius:8,fontSize:12,overflowX:'auto',maxHeight:200}}>
                        {JSON.stringify(j.parse_errors, null, 2)}
                      </pre>
                    </td></tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}