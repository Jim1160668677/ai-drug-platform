import { api } from './client';

// ========== AI 问答 ==========

export const chat = ({ message, projectId, tier }: { message: string; projectId?: string; tier: string }) =>
  api.post('/chat', { message, project_id: projectId, tier }).then((r) => r.data);

export const analyze = ({ message, projectId, tier }: { message: string; projectId: string; tier: string }) =>
  api
    .post('/chat/analyze', null, {
      params: { message, project_id: projectId, tier },
    })
    .then((r) => r.data);

export const getTiers = () => api.get('/chat/tiers').then((r) => r.data);
