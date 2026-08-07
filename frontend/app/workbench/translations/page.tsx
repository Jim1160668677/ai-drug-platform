'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listPartners,
  createPartner,
  listStages,
  createStage,
  updateStage,
  getTimeline,
  assignPartner,
  PARTNER_TYPE_LABELS,
  STAGE_TYPE_LABELS,
  STAGE_STATUS_LABELS,
  STAGE_STATUS_COLORS,
  type Partner,
  type TranslationStage,
  type Timeline,
} from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { Building2, GitBranch, Plus, CheckCircle, Clock, AlertCircle } from 'lucide-react';

type Tab = 'partners' | 'timeline';

export default function TranslationsPage() {
  const [tab, setTab] = useState<Tab>('partners');
  const { currentProject } = useAppStore();
  const projectId = currentProject?.id;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">合作方与转化路径</h1>
        <p className="text-sm text-slate-500 mt-1">
          管理临床转化所需的 CRO/CDMO/医院/检测机构资源，追踪分子的转化路径和累计成本
        </p>
      </div>

      {/* Tab 切换 */}
      <div className="flex border-b">
        <button
          onClick={() => setTab('partners')}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            tab === 'partners'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Building2 className="w-4 h-4 inline mr-1" />
          合作方管理
        </button>
        <button
          onClick={() => setTab('timeline')}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            tab === 'timeline'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <GitBranch className="w-4 h-4 inline mr-1" />
          转化路径
        </button>
      </div>

      {tab === 'partners' && <PartnersTab />}
      {tab === 'timeline' && <TimelineTab projectId={projectId} />}
    </div>
  );
}

// ========== 合作方管理 Tab ==========

function PartnersTab() {
  const [filterType, setFilterType] = useState<string>('');
  const [showCreate, setShowCreate] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['partners', filterType],
    queryFn: () => listPartners(filterType || undefined),
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<Partner>) => createPartner(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['partners'] });
      setShowCreate(false);
    },
  });

  const partners: Partner[] = data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-3 py-1.5 text-sm border rounded bg-white"
        >
          <option value="">全部类型</option>
          {Object.entries(PARTNER_TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" /> 新增合作方
        </button>
      </div>

      {showCreate && (
        <CreatePartnerForm
          onSubmit={(data) => createMutation.mutate(data)}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {isLoading && <div className="text-center py-4 text-slate-400">加载中...</div>}

      {!isLoading && partners.length === 0 && (
        <div className="text-center py-8 text-slate-400 border-2 border-dashed rounded">
          暂无合作方记录
        </div>
      )}

      {partners.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="text-left px-3 py-2">名称</th>
                <th className="text-left px-3 py-2">类型</th>
                <th className="text-left px-3 py-2">能力</th>
                <th className="text-right px-3 py-2">周期(天)</th>
                <th className="text-right px-3 py-2">单价(USD)</th>
                <th className="text-right px-3 py-2">评级</th>
              </tr>
            </thead>
            <tbody>
              {partners.map((p) => (
                <tr key={p.id} className="border-b hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium">{p.name}</td>
                  <td className="px-3 py-2">
                    <span className="px-2 py-0.5 bg-slate-100 rounded text-xs">
                      {PARTNER_TYPE_LABELS[p.partner_type] ?? p.partner_type}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(p.capabilities ?? []).slice(0, 3).map((c, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded text-xs"
                        >
                          {c}
                        </span>
                      ))}
                      {(p.capabilities ?? []).length > 3 && (
                        <span className="text-xs text-slate-400">
                          +{p.capabilities.length - 3}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="text-right px-3 py-2 font-mono">{p.lead_time_days ?? '-'}</td>
                  <td className="text-right px-3 py-2 font-mono">
                    {p.cost_per_unit_usd ? `$${p.cost_per_unit_usd.toLocaleString()}` : '-'}
                  </td>
                  <td className="text-right px-3 py-2 font-mono">
                    {p.quality_rating ? `${p.quality_rating}/5` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CreatePartnerForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (data: Partial<Partner>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    name: '',
    partner_type: 'cro',
    capabilities: '',
    contact_name: '',
    contact_email: '',
    lead_time_days: '',
    cost_per_unit_usd: '',
    quality_rating: '',
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name: form.name,
      partner_type: form.partner_type as Partner['partner_type'],
      capabilities: form.capabilities.split(',').map((s) => s.trim()).filter(Boolean),
      contact_name: form.contact_name || null,
      contact_email: form.contact_email || null,
      lead_time_days: form.lead_time_days ? parseInt(form.lead_time_days) : null,
      cost_per_unit_usd: form.cost_per_unit_usd ? parseFloat(form.cost_per_unit_usd) : null,
      quality_rating: form.quality_rating ? parseFloat(form.quality_rating) : null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="p-4 border rounded-lg space-y-3 bg-slate-50">
      <div className="grid grid-cols-2 gap-3">
        <input
          placeholder="合作方名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
          required
        />
        <select
          value={form.partner_type}
          onChange={(e) => setForm({ ...form, partner_type: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded bg-white"
        >
          {Object.entries(PARTNER_TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <input
        placeholder="能力标签（逗号分隔，如 toxicity_study,phase1_trial）"
        value={form.capabilities}
        onChange={(e) => setForm({ ...form, capabilities: e.target.value })}
        className="w-full px-3 py-1.5 text-sm border rounded"
      />
      <div className="grid grid-cols-2 gap-3">
        <input
          placeholder="联系人"
          value={form.contact_name}
          onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
        />
        <input
          placeholder="邮箱"
          value={form.contact_email}
          onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
        />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <input
          type="number"
          placeholder="周期(天)"
          value={form.lead_time_days}
          onChange={(e) => setForm({ ...form, lead_time_days: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
        />
        <input
          type="number"
          placeholder="单价(USD)"
          value={form.cost_per_unit_usd}
          onChange={(e) => setForm({ ...form, cost_per_unit_usd: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
        />
        <input
          type="number"
          step="0.1"
          placeholder="评级(1-5)"
          value={form.quality_rating}
          onChange={(e) => setForm({ ...form, quality_rating: e.target.value })}
          className="px-3 py-1.5 text-sm border rounded"
        />
      </div>
      <div className="flex gap-2">
        <button type="submit" className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded">
          创建
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-1.5 text-sm border rounded"
        >
          取消
        </button>
      </div>
    </form>
  );
}

// ========== 转化路径 Tab ==========

function TimelineTab({ projectId }: { projectId?: string }) {
  const queryClient = useQueryClient();

  const { data: timeline, isLoading } = useQuery({
    queryKey: ['timeline', projectId],
    queryFn: () => getTimeline(projectId!),
    enabled: !!projectId,
  });

  if (!projectId) {
    return (
      <div className="text-center py-8 text-slate-400 border-2 border-dashed rounded">
        请先在项目管理中选择一个项目
      </div>
    );
  }

  if (isLoading) return <div className="text-center py-4 text-slate-400">加载中...</div>;

  if (!timeline || timeline.total_stages === 0) {
    return (
      <div className="text-center py-12 text-slate-400 border-2 border-dashed rounded">
        <AlertCircle className="w-8 h-8 mx-auto mb-2 text-slate-300" />
        暂无转化路径，请创建第一个阶段
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 顶部汇总卡片 */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-4 border rounded-lg bg-white">
          <div className="text-xs text-slate-500">总成本</div>
          <div className="text-2xl font-bold mt-1">
            ${timeline.total_cost_usd.toLocaleString()}
          </div>
        </div>
        <div className="p-4 border rounded-lg bg-white">
          <div className="text-xs text-slate-500">总周期</div>
          <div className="text-2xl font-bold mt-1">{timeline.total_duration_days} 天</div>
        </div>
        <div className="p-4 border rounded-lg bg-white">
          <div className="text-xs text-slate-500">完成度</div>
          <div className="text-2xl font-bold mt-1">{timeline.completion_pct}%</div>
          <div className="w-full bg-slate-100 rounded h-1.5 mt-2">
            <div
              className="bg-green-500 h-1.5 rounded"
              style={{ width: `${timeline.completion_pct}%` }}
            />
          </div>
        </div>
      </div>

      {/* 横向时间线 */}
      <div className="overflow-x-auto pb-4">
        <div className="flex items-start gap-2 min-w-max">
          {timeline.stages.map((stage, i) => (
            <div key={stage.id} className="flex items-start">
              <div className="w-48 p-3 border rounded-lg bg-white">
                <div className="text-xs text-slate-400">
                  {STAGE_TYPE_LABELS[stage.stage_type] ?? stage.stage_type}
                </div>
                <div className="font-medium text-sm mt-1">{stage.stage_name}</div>
                <span
                  className={`inline-block mt-2 px-2 py-0.5 rounded text-xs border ${
                    STAGE_STATUS_COLORS[stage.status]
                  }`}
                >
                  {STAGE_STATUS_LABELS[stage.status]}
                </span>
                {stage.partner_name && (
                  <div className="text-xs text-slate-500 mt-2">
                    委托: {stage.partner_name}
                  </div>
                )}
                {stage.cost_usd != null && (
                  <div className="text-xs font-mono mt-1">${stage.cost_usd.toLocaleString()}</div>
                )}
                {stage.duration_days != null && (
                  <div className="text-xs text-slate-400">{stage.duration_days} 天</div>
                )}
                {stage.go_no_go && (
                  <div
                    className={`text-xs font-bold mt-2 ${
                      stage.go_no_go === 'go' ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {stage.go_no_go === 'go' ? '✓ GO' : '✗ NO GO'}
                  </div>
                )}
              </div>
              {i < timeline.stages.length - 1 && (
                <div className="flex items-center h-24 px-1 text-slate-300">→</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
