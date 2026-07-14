'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Pill, Activity, Zap, X, Trash2, FileText, AlertTriangle, Search, ShieldAlert, ClipboardList } from 'lucide-react';
import { getTreatments, getTreatmentDetail, optimizeTreatments, monitorEfficacy, deleteTreatment, checkDDI, createClinicalFeedback, getClinicalFeedbacks } from '@/lib/api';
import type { DDIResult } from '@/lib/api/treatments';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function TreatmentsPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [monitorData, setMonitorData] = useState<any>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [ddiDrugs, setDdiDrugs] = useState('');
  const [ddiResult, setDdiResult] = useState<DDIResult | null>(null);
  const [feedbackTarget, setFeedbackTarget] = useState<string | null>(null);
  const [feedbackForm, setFeedbackForm] = useState({
    patient_code: '', age: '', gender: '', dosage: '', duration_days: '',
    efficacy: 'partial', adverse_reactions: '', biomarker_changes: '', notes: '',
  });
  const [feedbackResult, setFeedbackResult] = useState<any>(null);
  const [feedbackListTarget, setFeedbackListTarget] = useState<string | null>(null);

  const { data: treatments, isLoading, isError, refetch } = useQuery({
    queryKey: ['treatments', currentProject?.id],
    queryFn: () => getTreatments(currentProject?.id),
    enabled: !!currentProject,
  });

  const optimizeMutation = useMutation({
    mutationFn: () => optimizeTreatments(currentProject!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['treatments'] });
      toast.success('优化完成', '治疗组合已优化');
    },
  });

  const monitorMutation = useMutation({
    mutationFn: (id: string) => monitorEfficacy(id),
    onSuccess: (res) => {
      setMonitorData((res as any)?.data || res);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTreatment(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['treatments'] });
      toast.success('删除成功', '治疗方案已删除');
    },
    onError: (err: any) => {
      toast.error('删除失败', err?.response?.data?.error?.message || '无权删除或方案不存在');
    },
  });

  const ddiMutation = useMutation({
    mutationFn: (drugs: string[]) => checkDDI(drugs),
    onSuccess: (data) => {
      setDdiResult(data);
      if (data.risk_level === 'none') {
        toast.success('无相互作用', '未检测到药物相互作用');
      } else if (data.risk_level === 'contraindicated' || data.risk_level === 'major') {
        toast.error('高风险警告', data.summary);
      } else {
        toast.warning('DDI 提示', data.summary);
      }
    },
    onError: (err: any) => {
      toast.error('检查失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: ({ treatmentId, data }: { treatmentId: string; data: Record<string, unknown> }) =>
      createClinicalFeedback(treatmentId, data),
    onSuccess: (res) => {
      setFeedbackResult(res);
      toast.success('反馈已录入', '临床反馈已提交，闭环分析完成');
    },
    onError: (err: any) => {
      toast.error('录入失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const handleDDICheck = () => {
    const drugs = ddiDrugs
      .split(/[,，\n\s]+/)
      .map((d) => d.trim())
      .filter(Boolean);
    if (drugs.length < 2) {
      toast.warning('输入不足', '请输入至少 2 个药物名称（用逗号分隔）');
      return;
    }
    ddiMutation.mutate(drugs);
  };

  const RISK_META: Record<string, { label: string; color: string }> = {
    none: { label: '无风险', color: 'text-green-600 bg-green-100' },
    minor: { label: '轻微', color: 'text-blue-600 bg-blue-100' },
    moderate: { label: '中度', color: 'text-yellow-600 bg-yellow-100' },
    major: { label: '严重', color: 'text-orange-600 bg-orange-100' },
    contraindicated: { label: '禁忌', color: 'text-red-600 bg-red-100' },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">治疗方案</h1>
          <p className="text-sm text-gray-500 mt-1">个性化治疗组合优化 — 靶向/免疫/化疗/联合</p>
        </div>
        <Button onClick={() => optimizeMutation.mutate()} loading={optimizeMutation.isPending}>
          <Zap className="w-4 h-4" /> 优化组合
        </Button>
      </div>

      {/* DDI 药物相互作用检查 */}
      <Card title="药物相互作用（DDI）检查">
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-xs text-gray-500 mb-2">
            <ShieldAlert className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
            <span>
              输入治疗方案中使用的药物名称（英文，逗号分隔），系统将检查药物间的相互作用风险。
              规则库包含 50+ 常见 DDI 规则 + 靶点重合度算法。
            </span>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={ddiDrugs}
              onChange={(e) => setDdiDrugs(e.target.value)}
              placeholder="例如：warfarin, aspirin, amiodarone"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
              onKeyDown={(e) => e.key === 'Enter' && handleDDICheck()}
            />
            <Button
              size="sm"
              loading={ddiMutation.isPending}
              onClick={handleDDICheck}
            >
              <Search className="w-3.5 h-3.5" /> 检查
            </Button>
          </div>

          {ddiResult && (
            <div className="mt-3 border-t border-gray-100 pt-3">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs text-gray-500">风险等级：</span>
                <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${RISK_META[ddiResult.risk_level]?.color || ''}`}>
                  <AlertTriangle className="w-3 h-3" />
                  {RISK_META[ddiResult.risk_level]?.label || ddiResult.risk_level}
                </span>
                <span className="text-xs text-gray-400 ml-auto">
                  检查药物 {ddiResult.drug_count} 种 · 发现 {ddiResult.interactions.length} 项相互作用
                </span>
              </div>
              <p className="text-sm text-gray-600 mb-3">{ddiResult.summary}</p>

              {ddiResult.interactions.length > 0 && (
                <div className="space-y-2">
                  {ddiResult.interactions.map((i, idx) => (
                    <div key={idx} className={`p-3 rounded-lg border ${RISK_META[i.severity]?.color || ''} bg-opacity-10`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium">
                          {i.drug_a} + {i.drug_b}
                        </span>
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${RISK_META[i.severity]?.color || ''}`}>
                          {RISK_META[i.severity]?.label || i.severity}
                        </span>
                      </div>
                      <div className="text-xs text-gray-600">
                        <div><span className="font-medium">机制：</span>{i.mechanism}</div>
                        <div><span className="font-medium">临床影响：</span>{i.clinical_effect}</div>
                        <div className="text-gray-400 mt-1">来源：{i.source === 'rule_table' ? '规则表' : i.source === 'target_overlap' ? '靶点重合' : '靶点列表'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {treatments?.map((t: any) => (
            <Card key={t.id}>
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-lg font-bold">{t.name}</div>
                    <div className="text-xs text-gray-500">{t.therapy_type}</div>
                  </div>
                  <Badge variant="status" value={t.status || 'planned'} />
                </div>

                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div className="bg-emerald-50 p-2 rounded">
                    <div className="text-xs text-gray-500">疗效评分</div>
                    <div className="text-lg font-semibold text-emerald-700">
                      {t.efficacy_score != null ? t.efficacy_score.toFixed(2) : '—'}
                    </div>
                  </div>
                  <div className="bg-red-50 p-2 rounded">
                    <div className="text-xs text-gray-500">风险评分</div>
                    <div className="text-lg font-semibold text-red-700">
                      {t.risk_score != null ? t.risk_score.toFixed(2) : '—'}
                    </div>
                  </div>
                  <div className="bg-blue-50 p-2 rounded">
                    <div className="text-xs text-gray-500">置信度</div>
                    <div className="text-lg font-semibold text-blue-700">
                      {t.confidence != null ? (t.confidence * 100).toFixed(0) + '%' : '—'}
                    </div>
                  </div>
                </div>

                <div className="text-xs text-gray-500">
                  靶点：{(t.target_ids || []).length} 个 · 分子：{(t.molecule_ids || []).length} 个
                </div>

                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setReportId(t.id)}
                    className="flex-1"
                  >
                    <FileText className="w-3 h-3" /> 详细报告
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={monitorMutation.isPending}
                    onClick={() => monitorMutation.mutate(t.id)}
                    className="flex-1"
                  >
                    <Activity className="w-3 h-3" /> 监测疗效
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={deleteMutation.isPending}
                    onClick={() => setDeleteTarget({ id: t.id, name: t.name })}
                  >
                    <Trash2 className="w-3 h-3" /> 删除
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => { setFeedbackTarget(t.id); setFeedbackResult(null); }}
                  >
                    <ClipboardList className="w-3 h-3" /> 临床反馈
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(!treatments || treatments.length === 0) && !isLoading && (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <Pill className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无治疗方案，请点击"优化组合"
          </div>
        </Card>
      )}

      {/* 详细报告弹窗 */}
      {reportId && <TreatmentReport treatmentId={reportId} onClose={() => setReportId(null)} />}

      {/* 疗效监测弹窗 */}
      {monitorData && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">疗效监测</h3>
              <button onClick={() => setMonitorData(null)}>
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">当前疗效</div>
                  <div className="text-lg font-semibold">{monitorData.current_efficacy?.toFixed(2) || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">趋势</div>
                  <div className="text-lg font-semibold">{monitorData.trend || '—'}</div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">不良事件</div>
                  <div className="text-lg font-semibold">
                    {Array.isArray(monitorData.adverse_events) ? monitorData.adverse_events.length : (monitorData.adverse_events || 0)}
                  </div>
                </div>
                <div className="bg-gray-50 p-3 rounded">
                  <div className="text-xs text-gray-500">实验数</div>
                  <div className="text-lg font-semibold">{monitorData.experiments_count || 0}</div>
                </div>
              </div>
              <div className="bg-yellow-50 border border-yellow-200 p-3 rounded text-sm">
                <strong>建议：</strong>{monitorData.recommendation || '继续监测'}
              </div>
              <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto">
                {JSON.stringify(monitorData, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold text-gray-900">确认删除</h3>
              <button onClick={() => setDeleteTarget(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5">
              <p className="text-sm text-gray-700">
                确认删除治疗方案「<span className="font-medium">{deleteTarget.name}</span>」？此操作不可撤销。
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setDeleteTarget(null)}>取消</Button>
                <Button
                  variant="danger"
                  loading={deleteMutation.isPending}
                  onClick={() => { deleteMutation.mutate(deleteTarget.id); setDeleteTarget(null); }}
                >
                  <Trash2 className="w-4 h-4" /> 确认删除
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 优化结果 */}
      {optimizeMutation.data && (
        <Card title="优化结果">
          <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs overflow-x-auto">
            {JSON.stringify((optimizeMutation.data as any)?.data || optimizeMutation.data, null, 2)}
          </pre>
        </Card>
      )}

      {/* 临床反馈弹窗 */}
      {feedbackTarget && (
        <ClinicalFeedbackModal
          treatmentId={feedbackTarget}
          form={feedbackForm}
          setForm={setFeedbackForm}
          result={feedbackResult}
          loading={feedbackMutation.isPending}
          onSubmit={() => feedbackMutation.mutate({ treatmentId: feedbackTarget, data: feedbackForm })}
          onClose={() => { setFeedbackTarget(null); setFeedbackResult(null); }}
        />
      )}
    </div>
  );
}

// ========== 详细报告组件 ==========
function TreatmentReport({ treatmentId, onClose }: { treatmentId: string; onClose: () => void }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['treatment-detail', treatmentId],
    queryFn: () => getTreatmentDetail(treatmentId),
  });

  const detail = (data as any)?.data || data;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-3xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <FileText className="w-4 h-4" /> 治疗方案详细报告
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {isError ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-sm text-red-600 mb-3">报告加载失败</p>
            <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
          </div>
        ) : isLoading ? (
          <div className="text-center py-12 text-gray-400">加载报告中...</div>
        ) : error || !detail ? (
          <div className="text-center py-12 text-red-500">加载失败，请稍后重试</div>
        ) : (
          <div className="p-5 space-y-5">
            {/* 基本信息 */}
            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h2 className="text-xl font-bold text-gray-900">{detail.name}</h2>
                  <div className="text-sm text-gray-600 mt-1">
                    {detail.therapy_type_label || detail.therapy_type} · {detail.status_label || detail.status}
                  </div>
                </div>
                <Badge variant="status" value={detail.status || 'planned'} />
              </div>
              {detail.created_at && (
                <div className="text-xs text-gray-500">创建时间：{new Date(detail.created_at).toLocaleString('zh-CN')}</div>
              )}
            </div>

            {/* 评分卡片 */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-emerald-50 p-4 rounded-lg text-center">
                <div className="text-xs text-gray-500 mb-1">疗效评分</div>
                <div className="text-2xl font-bold text-emerald-700">
                  {detail.efficacy_score != null ? detail.efficacy_score.toFixed(2) : '—'}
                </div>
                <div className="mt-2 h-1.5 bg-emerald-100 rounded-full overflow-hidden">
                  <div className="h-full bg-emerald-500" style={{ width: `${(detail.efficacy_score || 0) * 100}%` }} />
                </div>
              </div>
              <div className="bg-red-50 p-4 rounded-lg text-center">
                <div className="text-xs text-gray-500 mb-1">风险评分</div>
                <div className="text-2xl font-bold text-red-700">
                  {detail.risk_score != null ? detail.risk_score.toFixed(2) : '—'}
                </div>
                <div className="mt-2 h-1.5 bg-red-100 rounded-full overflow-hidden">
                  <div className="h-full bg-red-500" style={{ width: `${(detail.risk_score || 0) * 100}%` }} />
                </div>
              </div>
              <div className="bg-blue-50 p-4 rounded-lg text-center">
                <div className="text-xs text-gray-500 mb-1">置信度</div>
                <div className="text-2xl font-bold text-blue-700">
                  {detail.confidence != null ? (detail.confidence * 100).toFixed(0) + '%' : '—'}
                </div>
                <div className="mt-2 h-1.5 bg-blue-100 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500" style={{ width: `${(detail.confidence || 0) * 100}%` }} />
                </div>
              </div>
            </div>

            {/* 效益-风险雷达图 */}
            <div>
              <h4 className="text-sm font-semibold mb-2">效益-风险综合评估</h4>
              <PlotlyChart
                data={[
                  {
                    type: 'scatterpolar',
                    r: [
                      (detail.efficacy_score || 0) * 100,
                      (detail.confidence || 0) * 100,
                      (1 - (detail.risk_score || 0)) * 100,
                      (detail.efficacy_score || 0) * 100,
                    ],
                    theta: ['疗效', '置信度', '安全性', '疗效'],
                    fill: 'toself',
                    line: { color: '#2563eb' },
                    name: '当前方案',
                  },
                ]}
                layout={{
                  polar: { radialaxis: { visible: true, range: [0, 100] } },
                  margin: { t: 20, b: 20, l: 40, r: 40 },
                  height: 300,
                }}
              />
            </div>

            {/* 关联靶点 */}
            {detail.targets && detail.targets.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold mb-2">关联靶点（{detail.targets.length}）</h4>
                <div className="space-y-2">
                  {detail.targets.map((tgt: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">{tgt.gene_symbol}</div>
                        <div className="text-xs text-gray-500">{tgt.gene_name || '—'}</div>
                      </div>
                      <Badge variant="evidence" value={tgt.evidence_grade || 'IV'} />
                      <div className="text-right">
                        <div className="text-xs text-gray-500">置信度</div>
                        <div className="text-sm font-medium">{((tgt.confidence_score || 0) * 100).toFixed(0)}%</div>
                      </div>
                      {tgt.approved_drugs && tgt.approved_drugs.length > 0 && (
                        <div className="text-right">
                          <div className="text-xs text-gray-500">获批药物</div>
                          <div className="text-sm font-medium">{tgt.approved_drugs.length} 个</div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 关联分子 */}
            {detail.molecules && detail.molecules.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold mb-2">关联分子（{detail.molecules.length}）</h4>
                <div className="space-y-2">
                  {detail.molecules.map((mol: any, i: number) => (
                    <div key={i} className="p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center justify-between mb-1">
                        <div className="font-medium text-gray-900">{mol.name || '未命名'}</div>
                        {mol.is_approved && <Badge variant="status" value="completed" />}
                      </div>
                      <div className="font-mono text-xs text-gray-600 break-all">{mol.smiles}</div>
                      <div className="flex gap-4 mt-2 text-xs text-gray-500">
                        <span>分子量：{mol.molecular_weight?.toFixed(1) || '—'}</span>
                        <span>LogP：{mol.logp?.toFixed(2) || '—'}</span>
                        <span>来源：{mol.source || '—'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 方案配置 */}
            {detail.config && (
              <div>
                <h4 className="text-sm font-semibold mb-2">方案配置</h4>
                <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                  {detail.config.strategy && (
                    <div className="text-sm">
                      <span className="text-gray-500">策略：</span>
                      <span className="font-medium">{detail.config.strategy}</span>
                    </div>
                  )}
                  {detail.config.mechanism && (
                    <div className="text-sm">
                      <span className="text-gray-500">作用机制：</span>
                      <span className="font-medium">{detail.config.mechanism}</span>
                    </div>
                  )}
                  {detail.config.drugs && detail.config.drugs.length > 0 && (
                    <div className="text-sm">
                      <span className="text-gray-500">药物列表：</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {detail.config.drugs.map((d: any, i: number) => (
                          <span key={i} className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                            {d.name || d}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {detail.config.molecules && detail.config.molecules.length > 0 && (
                    <div className="text-sm">
                      <span className="text-gray-500">候选分子：</span>
                      <span className="font-medium">{detail.config.molecules.length} 个</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 监测数据 */}
            {detail.monitoring_data && (
              <div>
                <h4 className="text-sm font-semibold mb-2">监测数据</h4>
                <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto">
                  {JSON.stringify(detail.monitoring_data, null, 2)}
                </pre>
              </div>
            )}

            {/* 备注 */}
            {detail.notes && (
              <div>
                <h4 className="text-sm font-semibold mb-2">备注</h4>
                <div className="bg-yellow-50 border border-yellow-200 p-3 rounded text-sm text-gray-700">
                  {detail.notes}
                </div>
              </div>
            )}

            {/* 具体治疗建议 */}
            <TreatmentRecommendations detail={detail} />

            {/* 完整 JSON */}
            <details className="border-t pt-3">
              <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">查看原始 JSON 数据</summary>
              <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto mt-2">
                {JSON.stringify(detail, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

// ========== 具体治疗建议组件 ==========
function TreatmentRecommendations({ detail }: { detail: any }) {
  const recs = generateRecommendations(detail);

  return (
    <div className="space-y-4">
      <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-lg p-4 border border-amber-200">
        <h4 className="font-semibold text-amber-900 mb-3">具体治疗建议</h4>
        <div className="space-y-4">
          {/* 用药建议 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">用药方案建议</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200 space-y-2">
              {recs.dosage.map((d: string, i: number) => (
                <div key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="text-amber-600 font-bold shrink-0">→</span>
                  <span>{d}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 联合用药理由 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">联合用药策略</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200">
              {recs.combination.map((c: string, i: number) => (
                <div key={i} className="text-sm text-gray-700 flex items-start gap-2 mb-2">
                  <span className="text-blue-600 font-bold shrink-0">•</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 监测计划 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">疗效监测计划</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                {recs.monitoring.schedule.map((m: any, i: number) => (
                  <div key={i} className="bg-blue-50 p-2 rounded text-center">
                    <div className="text-xs text-gray-500">{m.timepoint}</div>
                    <div className="text-sm font-medium text-blue-700">{m.action}</div>
                  </div>
                ))}
              </div>
              <div className="text-sm text-gray-700 space-y-1">
                {recs.monitoring.items.map((item: string, i: number) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="text-blue-600 shrink-0">✓</span>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 风险控制 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">风险控制措施</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200 space-y-2">
              {recs.riskMitigation.map((r: string, i: number) => (
                <div key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="text-red-600 font-bold shrink-0">⚠</span>
                  <span>{r}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 替代方案 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">替代治疗方案</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200 space-y-2">
              {recs.alternatives.map((a: string, i: number) => (
                <div key={i} className="text-sm text-gray-700 flex items-start gap-2">
                  <span className="text-green-600 font-bold shrink-0">{i + 1}.</span>
                  <span>{a}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 预后评估 */}
          <div>
            <h5 className="text-sm font-medium text-gray-700 mb-2">预后评估</h5>
            <div className="bg-white rounded-lg p-3 border border-gray-200">
              <p className="text-sm text-gray-700">{recs.prognosis}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// 治疗建议生成器
function generateRecommendations(detail: any) {
  const efficacy = detail.efficacy_score || 0;
  const risk = detail.risk_score || 0;
  const confidence = detail.confidence || 0;
  const therapyType = detail.therapy_type || detail.therapy_type_label || '';
  const targets = detail.targets || [];
  const molecules = detail.molecules || [];
  const drugs = detail.config?.drugs || [];

  // 用药方案建议
  const dosage: string[] = [];
  if (efficacy >= 0.7) {
    dosage.push('疗效评分较高，推荐作为一线治疗方案。');
  } else if (efficacy >= 0.5) {
    dosage.push('疗效评分中等，建议作为二线治疗或联合用药基础方案。');
  } else {
    dosage.push('疗效评分偏低，建议考虑联合用药或替换方案。');
  }
  if (drugs.length > 0) {
    dosage.push(`推荐药物：${drugs.map((d: any) => d.name || d).join(' + ')}，建议遵循说明书标准剂量。`);
  }
  if (molecules.length > 0) {
    dosage.push(`候选分子 ${molecules.length} 个，建议优先开展动物药效学实验确定有效剂量范围。`);
  }
  dosage.push('给药频率和疗程应根据患者个体情况（体重、肝肾功能、年龄）进行调整，建议治疗每 2-3 周评估一次疗效。');

  // 联合用药策略
  const combination: string[] = [];
  if (targets.length > 1) {
    combination.push(`本方案涉及 ${targets.length} 个靶点，多靶点联合策略有助于克服肿瘤异质性和耐药机制。`);
  }
  if (therapyType.includes('combination') || therapyType.includes('联合')) {
    combination.push('联合用药方案可产生协同效应，但需注意药物相互作用，建议查阅药物相互作用数据库。');
  }
  const hasApproved = targets.some((t: any) => t.approved_drugs && t.approved_drugs.length > 0);
  const hasCandidate = molecules.length > 0;
  if (hasApproved && hasCandidate) {
    combination.push('已获批药物与候选分子联合使用，可在保证安全性的同时探索增效可能。建议已获批药物为主干，候选分子为辅助。');
  }
  combination.push('建议评估 PD-1/PD-L1 免疫检查点抑制剂联合可能性，免疫联合靶向是当前肿瘤治疗的重要趋势。');

  // 监测计划
  const monitoring = {
    schedule: [
      { timepoint: '第 2 周', action: '首次疗效评估' },
      { timepoint: '第 4 周', action: '影像学复查' },
      { timepoint: '第 8 周', action: '全面疗效评估' },
    ],
    items: [
      '每 2 周检测肿瘤标志物（CEA、CA125 等）变化趋势',
      '每 4 周进行影像学检查（CT/MRI）评估病灶变化',
      '每次随访检查血常规、肝肾功能、心电图',
      '密切关注免疫相关不良事件（irAE），特别是皮疹、腹泻、肝功能异常',
      '记录患者生活质量评分（QoL），作为疗效补充指标',
    ],
  };

  // 风险控制
  const riskMitigation: string[] = [];
  if (risk >= 0.7) {
    riskMitigation.push(`风险评分较高（${(risk * 100).toFixed(0)}%），建议在三级医院专科医生指导下用药，备好急救预案。`);
  } else if (risk >= 0.4) {
    riskMitigation.push(`风险评分中等（${(risk * 100).toFixed(0)}%），建议常规监测不良反应，及时调整剂量。`);
  } else {
    riskMitigation.push(`风险评分较低（${(risk * 100).toFixed(0)}%），安全性良好，可按标准方案给药。`);
  }
  riskMitigation.push('用药前评估患者心血管功能、肝肾功能基线，排除禁忌症。');
  riskMitigation.push('如出现 3 级及以上不良反应，应立即暂停用药并对症处理，待恢复至 1 级后再考虑减量给药。');
  riskMitigation.push('建议建立患者用药日记，记录服药时间、剂量和不适症状，便于及时干预。');
  if (targets.some((t: any) => t.evidence_grade === 'III' || t.evidence_grade === 'IV')) {
    riskMitigation.push('部分靶点证据等级较低，建议在知情同意前提下谨慎使用，密切监测疗效。');
  }

  // 替代方案
  const alternatives: string[] = [];
  if (efficacy < 0.7) {
    alternatives.push('如本方案疗效不佳，可考虑切换为其他作用机制的靶向药物（如从 TKI 切换为抗体药物）。');
  }
  alternatives.push('化疗联合方案：如靶向治疗失败，可考虑含铂双药化疗（顺铂/卡铂 + 培美曲塞/紫杉醇）。');
  alternatives.push('免疫单药治疗：如 PD-L1 高表达（TPS ≥50%），可考虑帕博利珠单抗单药一线治疗。');
  alternatives.push('临床试验：建议查询符合入组条件的新药临床试验，为患者提供更多治疗选择。');
  if (molecules.length > 0) {
    alternatives.push('候选分子方案：如有候选分子，可在完成临床前研究后申请研究者发起的临床试验（IIT）。');
  }

  // 预后评估
  let prognosis = '';
  if (efficacy >= 0.7 && confidence >= 0.7) {
    prognosis = `综合评估显示该方案疗效预期良好（${(efficacy * 100).toFixed(0)}%），置信度高（${(confidence * 100).toFixed(0)}%）。预计患者客观缓解率（ORR）较高，无进展生存期（PFS）有望延长。建议积极推行该方案，同时做好长期随访规划。`;
  } else if (efficacy >= 0.5) {
    prognosis = `该方案疗效预期中等（${(efficacy * 100).toFixed(0)}%），置信度${(confidence * 100).toFixed(0)}%。部分患者可能获益，建议在治疗 8 周后评估，如达到 SD（疾病稳定）以上可继续治疗，否则考虑转换方案。`;
  } else {
    prognosis = `该方案疗效预期有限（${(efficacy * 100).toFixed(0)}%），建议作为探索性治疗或联合基础方案。需要密切监测疗效，如 4-8 周内未见明显获益，应及时调整策略。建议同时寻找其他潜在靶点和治疗机会。`;
  }

  return {
    dosage,
    combination,
    monitoring,
    riskMitigation,
    alternatives,
    prognosis,
  };
}
