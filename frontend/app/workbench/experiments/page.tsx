'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FlaskConical, RefreshCw, Send, Activity } from 'lucide-react';
import { getExperiments, submitExperimentResult } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function ExperimentsPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const [submitTarget, setSubmitTarget] = useState<string | null>(null);
  const [resultForm, setResultForm] = useState({ measured: '', notes: '' });

  const { data: experiments, isLoading } = useQuery({
    queryKey: ['experiments', currentProject?.id],
    queryFn: () => getExperiments(currentProject?.id),
    enabled: !!currentProject,
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      submitExperimentResult(
        submitTarget!,
        { measured: parseFloat(resultForm.measured) },
        true,
        resultForm.notes
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['experiments'] });
      setSubmitTarget(null);
      setResultForm({ measured: '', notes: '' });
    },
  });

  // 按迭代分组
  const byIteration = (experiments || []).reduce((acc: any, exp: any) => {
    const it = exp.iteration || 1;
    if (!acc[it]) acc[it] = [];
    acc[it].push(exp);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">干湿闭环</h1>
        <p className="text-sm text-gray-500 mt-1">
          Dry Prediction → Wet Experiment → 误差反馈 → 模型迭代
        </p>
      </div>

      {/* 反馈循环示意图 */}
      <Card title="反馈循环">
        <PlotlyChart
          data={[
            {
              type: 'scatter',
              mode: 'text+lines+markers',
              x: [0, 1, 2, 3, 0],
              y: [0, 0, 0, 0, 0],
              text: ['Dry Prediction', 'Wet Experiment', 'Error Analysis', 'Model Update', ''],
              textposition: 'top center',
              line: { color: '#2563eb', shape: 'spline' },
              marker: { size: 16 },
            },
          ]}
          layout={{
            margin: { t: 40, b: 20, l: 20, r: 20 },
            height: 180,
            xaxis: { visible: false },
            yaxis: { visible: false },
            showlegend: false,
          }}
        />
      </Card>

      {/* 迭代时间线 */}
      <Card title="迭代时间线">
        {isLoading ? (
          <div className="text-center py-8 text-gray-400">加载中...</div>
        ) : Object.keys(byIteration).length > 0 ? (
          <div className="space-y-6">
            {Object.entries(byIteration).map(([iter, exps]: any) => (
              <div key={iter}>
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-8 h-8 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-sm font-bold">
                    {iter}
                  </div>
                  <div className="text-sm font-medium">迭代 {iter}</div>
                </div>
                <div className="ml-4 space-y-2 border-l-2 border-gray-200 pl-4">
                  {(exps as any[]).map((exp) => (
                    <div key={exp.id} className="bg-white border border-gray-100 rounded p-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm font-medium">{exp.name}</div>
                          <div className="text-xs text-gray-500">
                            {exp.exp_type} · {exp.lab_source || '实验室内'}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {exp.feedback_applied && (
                            <Badge variant="status" value="completed" />
                          )}
                          <Badge variant="status" value={exp.status} />
                        </div>
                      </div>
                      {exp.result && (
                        <div className="mt-2 text-xs grid grid-cols-2 md:grid-cols-4 gap-2">
                          {Object.entries(exp.result).slice(0, 4).map(([k, v]: any) => (
                            <div key={k} className="bg-gray-50 px-2 py-1 rounded">
                              <span className="text-gray-500">{k}：</span>
                              <span className="font-mono">{typeof v === 'number' ? v.toFixed(3) : String(v)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="mt-2 flex gap-2">
                        {exp.status === 'running' || exp.status === 'planned' ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setSubmitTarget(exp.id)}
                          >
                            <Send className="w-3 h-3" /> 提交结果
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-400">
            <FlaskConical className="w-12 h-12 mx-auto mb-2 opacity-50" />
            暂无实验记录
          </div>
        )}
      </Card>

      {/* 提交结果弹窗 */}
      {submitTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold">提交实验结果</h3>
              <button onClick={() => setSubmitTarget(null)} className="text-gray-400">
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">实测值</label>
                <input
                  type="number"
                  step="0.001"
                  value={resultForm.measured}
                  onChange={(e) => setResultForm((s) => ({ ...s, measured: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  placeholder="例如：0.85"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">备注</label>
                <textarea
                  value={resultForm.notes}
                  onChange={(e) => setResultForm((s) => ({ ...s, notes: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                  rows={3}
                  placeholder="实验观察、异常情况等"
                />
              </div>
              <Button
                className="w-full"
                loading={submitMutation.isPending}
                onClick={() => submitMutation.mutate()}
                disabled={!resultForm.measured}
              >
                提交并触发反馈
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 反馈结果 */}
      {submitMutation.data && (
        <Card title="反馈分析结果" action={<Activity className="w-4 h-4 text-accent" />}>
          <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs overflow-x-auto">
            {JSON.stringify(submitMutation.data, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
