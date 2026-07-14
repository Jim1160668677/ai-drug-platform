import { api } from './client';

// ========== 知情同意 ==========

export interface ConsentRecord {
  id: string;
  project_id: string;
  patient_pseudonym: string;
  consent_type: string;
  status: 'granted' | 'withdrawn' | 'expired';
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  purpose: string;
  constraints: Record<string, any> | null;
  granted_by: string | null;
}

export interface ConsentCheckResult {
  granted: boolean;
  project_id: string;
  patient_pseudonym: string;
  consent_type: string;
}

export const grantConsent = (data: {
  project_id: string;
  patient_pseudonym: string;
  consent_type: string;
  purpose: string;
  expires_at?: string;
  constraints?: Record<string, any>;
}) => api.post('/consent', data).then((r) => r.data?.data ?? r.data) as Promise<ConsentRecord>;

export const revokeConsent = (consentId: string, reason?: string) =>
  api.delete(`/consent/${consentId}`, { data: { reason } }).then((r) => r.data?.data ?? r.data) as Promise<ConsentRecord>;

export const listConsents = (projectId: string, patientPseudonym?: string) =>
  api
    .get('/consent', { params: { project_id: projectId, patient_pseudonym: patientPseudonym } })
    .then((r) => (r.data?.data ?? r.data) as ConsentRecord[]);

export const checkConsent = (projectId: string, patientPseudonym: string, consentType: string) =>
  api
    .get('/consent/check', { params: { project_id: projectId, patient_pseudonym: patientPseudonym, consent_type: consentType } })
    .then((r) => (r.data?.data ?? r.data) as ConsentCheckResult);

export const getConsentDetail = (consentId: string) =>
  api.get(`/consent/${consentId}`).then((r) => (r.data?.data ?? r.data) as ConsentRecord);
