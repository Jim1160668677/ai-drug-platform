'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Plus, X, Ban, CheckCircle, XCircle, Clock } from 'lucide-react';
import { listConsents, grantConsent, revokeConsent } from '@/lib/api';
import type { ConsentRecord } from '@/lib/api/consent';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

const CONSENT_TYPES = [
  { value: 'data_use', label: '数据使用' },
  { value: 'sharing', label: '数据共享' },
  { value: 'publication', label: '学术发表' },
];

const STATUS_META: Record<string, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  granted: { label: '已授权', color: 'text-green-600 bg-green-100', icon: CheckCircle },
  withdrawn: { label: '已撤回', color: 'text-red-600 bg-red-100', icon: XCircle },
  expired: { label: '已过期', color: 'text-gray-600 bg-gray-100', icon: Clock },
};

export default function ConsentPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [showGrantForm, setShowGrantForm] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<ConsentRecord | null>(null);
  const [revokeReason, setRevokeReason] = useState('');

  // 表单状态
  const [formPatient, setFormPatient] = useState('');
  const [formType, setFormType] = useState('data_use');
  const [formPurpose, setFormPurpose] = useState('');
  const [formExpiry, setFormExpiry] = useState('');

  const { data: consents, isLoading, isError, refetch } = useQuery({
    queryKey: ['consents', currentProject?.id],
    queryFn: () => listConsents(currentProject!.id),
    enabled: !!currentProject,
  });

  const grantMutation = useMutation({
    mutationFn: () => grantConsent({
      project_id: currentProject!.id,
      patient_pseudonym: formPatient,
      consent_type: formType,
      purpose: formPurpose,
      expires_at: formExpiry || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['consents'] });
      toast.success('授权成功', '知情同意已授予');
      setShowGrantForm(false);
      setFormPatient('');
      setFormPurpose('');
      setFormExpiry('');
    },
    onError: (err: any) => {
      toast.error('授权失败', err?.response?.data?.detail || '请检查权限');
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeConsent(id, revokeReason || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['consents'] });
      toast.success('撤回成功', '知情同意已撤回');
      setRevokeTarget(null);
      setRevokeReason('');
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">知情同意管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理患者数据使用授权 — GDPR/HIPAA 合规</p>
        </div>
        <Button onClick={() => setShowGrantForm(true)}>
          <Plus className="w-4 h-4" /> 授予同意
        </Button>
      </div>

      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <Card><div className="text-center py-12 text-gray-400">加载中...</div></Card>
      ) : consents && consents.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {consents.map((c) => {
            const StatusIcon = STATUS_META[c.status]?.icon || ShieldCheck;
            return (
              <Card key={c.id}>
                <div className="space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-sm font-bold">{c.patient_pseudonym}</div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {CONSENT_TYPES.find((t) => t.value === c.consent_type)?.label || c.consent_type}
                      </div>
                    </div>
                    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${STATUS_META[c.status]?.color || ''}`}>
                      <StatusIcon className="w-3 h-3" />
                      {STATUS_META[c.status]?.label || c.status}
                    </span>
                  </div>

                  <div className="text-xs text-gray-600">
                    <div><span className="font-medium">用途：</span>{c.purpose}</div>
                    <div className="mt-1"><span className="font-medium">授权时间：</span>{c.granted_at ? new Date(c.granted_at).toLocaleString('zh-CN') : '—'}</div>
                    {c.expires_at && (
                      <div><span className="font-medium">过期时间：</span>{new Date(c.expires_at).toLocaleString('zh-CN')}</div>
                    )}
                    {c.revoked_at && (
                      <div className="text-red-500"><span className="font-medium">撤回时间：</span>{new Date(c.revoked_at).toLocaleString('zh-CN')}</div>
                    )}
                    {c.revoke_reason && (
                      <div className="text-red-500"><span className="font-medium">撤回原因：</span>{c.revoke_reason}</div>
                    )}
                    {c.constraints && (
                      <div className="mt-1"><span className="font-medium">约束：</span>{JSON.stringify(c.constraints)}</div>
                    )}
                  </div>

                  {c.status === 'granted' && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRevokeTarget(c)}
                      className="text-red-600 hover:bg-red-50"
                    >
                      <Ban className="w-3 h-3" /> 撤回
                    </Button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <ShieldCheck className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <div className="text-sm">暂无知情同意记录</div>
            <div className="text-xs mt-1">点击"授予同意"添加患者授权</div>
          </div>
        </Card>
      )}

      {/* 授予同意表单弹窗 */}
      {showGrantForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">授予知情同意</h3>
              <button onClick={() => setShowGrantForm(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">患者假名 *</label>
                <input
                  type="text"
                  value={formPatient}
                  onChange={(e) => setFormPatient(e.target.value)}
                  placeholder="PATIENT-001"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">同意类型 *</label>
                <select
                  value={formType}
                  onChange={(e) => setFormType(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                >
                  {CONSENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">用途说明 *</label>
                <textarea
                  value={formPurpose}
                  onChange={(e) => setFormPurpose(e.target.value)}
                  placeholder="药物研发数据分析..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  rows={3}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">过期时间（可选）</label>
                <input
                  type="datetime-local"
                  value={formExpiry}
                  onChange={(e) => setFormExpiry(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" onClick={() => setShowGrantForm(false)}>取消</Button>
                <Button
                  loading={grantMutation.isPending}
                  disabled={!formPatient || !formPurpose}
                  onClick={() => grantMutation.mutate()}
                >
                  授予
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 撤回确认弹窗 */}
      {revokeTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold text-red-600">确认撤回知情同意</h3>
              <button onClick={() => setRevokeTarget(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <p className="text-sm text-gray-700">
                确认撤回患者「<span className="font-medium">{revokeTarget.patient_pseudonym}</span>」的
                「{CONSENT_TYPES.find((t) => t.value === revokeTarget.consent_type)?.label}」同意？
                撤回后相关数据操作将被拒绝。
              </p>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">撤回原因（可选）</label>
                <textarea
                  value={revokeReason}
                  onChange={(e) => setRevokeReason(e.target.value)}
                  placeholder="患者主动撤回 / 其他原因..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  rows={2}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setRevokeTarget(null)}>取消</Button>
                <Button
                  variant="danger"
                  loading={revokeMutation.isPending}
                  onClick={() => revokeMutation.mutate(revokeTarget.id)}
                >
                  <Ban className="w-4 h-4" /> 确认撤回
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
