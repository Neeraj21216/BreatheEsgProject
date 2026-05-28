import axios from 'axios';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api';
const api = axios.create({ baseURL: apiBaseUrl });

export const getDashboard  = ()         => api.get('/dashboard/');
export const getJobs       = ()         => api.get('/jobs/');
export const getRecords    = (params)   => api.get('/records/', { params });
export const approveRecords = (ids)     => api.post('/records/approve/', { record_ids: ids });
export const flagRecords   = (ids, reason, note) =>
  api.post('/records/flag/', { record_ids: ids, reason, note });
export const getAuditLog   = (id)       => api.get(`/records/${id}/audit_log/`);
export const uploadSAP     = (file, notes) => {
  const fd = new FormData(); fd.append('file', file); fd.append('notes', notes);
  return api.post('/jobs/upload_sap/', fd);
};
export const uploadUtility = (file, notes) => {
  const fd = new FormData(); fd.append('file', file); fd.append('notes', notes);
  return api.post('/jobs/upload_utility/', fd);
};
export const uploadTravel  = (file, notes) => {
  const fd = new FormData(); fd.append('file', file); fd.append('notes', notes);
  return api.post('/jobs/upload_travel/', fd);
};