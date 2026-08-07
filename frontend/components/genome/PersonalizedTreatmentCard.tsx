'use client';

import { Pill, Bot, AlertCircle, Activity, Lightbulb } from 'lucide-react';
import Badge from '@/components/ui/Badge';

interface PersonalizedTreatmentCardProps {
  /** 个性化治疗推荐结果 */
  data?: any;
  /** 是否加载中 */
  loading?: boolean;
}

export default function PersonalizedTreatmentCard({
  data,
  loading,
}: PersonalizedTreatmentCardProps) {
  if (loading) {
    return (
      <div className="space-y-2">
        <div className="h-6 w-1/3 animate-pulse rounded bg-gray-100" />
        <div className="h-32 w-full animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-500">
        <Pill className="w-10 h-10 mx-auto mb-2 text-gray-400" />
        暂无个性化治疗推荐，点击「生成治疗推荐」按钮
      </div>
    );
  }

  const llmModel: string = data.llm_model || '';
  const disease: string = data.disease || '';
  const recommendations: any[] = data.recommendations || [];
  const drugCandidates: any[] = data.drug_candidates || [];
  const geneDrugInteractions: any[] = data.gene_drug_interactions || [];
  const dosageAdjustments: any[] = data.dosage_adjustments || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Pill className="w-4 h-4 text-primary-600" />
          <h3 className="text-sm font-semibold text-gray-900">个性化治疗推荐</h3>
          {disease && (
            <Badge variant="blue" value={`疾病：${disease}`} />
          )}
        </div>
        {llmModel && (
          <Badge variant="purple">
            <span className="flex items-center gap-1">
              <Bot className="w-3 h-3" />
              {llmModel}
            </span>
          </Badge>
        )}
      </div>

      {/* 药物候选 */}
      {drugCandidates.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-gray-600 mb-2">
            <Pill className="w-3.5 h-3.5" />
            候选药物（{drugCandidates.length}）
          </div>
          <div className="space-y-2">
            {drugCandidates.map((drug: any, idx: number) => (
              <div
                key={drug.id || idx}
                className="flex items-center justify-between text-xs border-b border-gray-100 last:border-0 pb-2 last:pb-0"
              >
                <div>
                  <span className="font-medium text-gray-900">
                    {drug.name || drug.drug_name || '—'}
                  </span>
                  {drug.indication && (
                    <span className="ml-2 text-gray-500">{drug.indication}</span>
                  )}
                </div>
                {drug.mechanism && (
                  <span className="text-gray-400 truncate max-w-xs">
                    {drug.mechanism}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LLM 推荐 */}
      {recommendations.length > 0 && (
        <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-primary-700 mb-2">
            <Lightbulb className="w-3.5 h-3.5" />
            个性化用药建议
          </div>
          <ul className="space-y-1.5">
            {recommendations.map((rec: any, idx: number) => (
              <li
                key={idx}
                className="text-sm text-gray-800 flex items-start gap-2"
              >
                <span className="text-primary-600 mt-0.5">•</span>
                <span className="whitespace-pre-wrap">
                  {typeof rec === 'string' ? rec : rec?.content || rec?.text || JSON.stringify(rec)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 基因-药物相互作用 */}
      {geneDrugInteractions.length > 0 && (
        <div className="rounded-lg border border-orange-200 bg-orange-50/50 p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-orange-700 mb-2">
            <AlertCircle className="w-3.5 h-3.5" />
            基因-药物相互作用警示
          </div>
          <ul className="space-y-1.5">
            {geneDrugInteractions.map((g: any, idx: number) => (
              <li
                key={idx}
                className="text-xs text-orange-900 flex items-start gap-2"
              >
                <span className="text-orange-600 mt-0.5">⚠</span>
                <span className="whitespace-pre-wrap">
                  {typeof g === 'string' ? g : g?.description || g?.warning || JSON.stringify(g)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 剂量调整 */}
      {dosageAdjustments.length > 0 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
          <div className="flex items-center gap-1 text-xs font-medium text-blue-700 mb-2">
            <Activity className="w-3.5 h-3.5" />
            剂量调整建议
          </div>
          <ul className="space-y-1.5">
            {dosageAdjustments.map((d: any, idx: number) => (
              <li
                key={idx}
                className="text-xs text-blue-900 flex items-start gap-2"
              >
                <span className="text-blue-600 mt-0.5">→</span>
                <span className="whitespace-pre-wrap">
                  {typeof d === 'string' ? d : d?.description || d?.recommendation || JSON.stringify(d)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {recommendations.length === 0 &&
        drugCandidates.length === 0 &&
        geneDrugInteractions.length === 0 &&
        dosageAdjustments.length === 0 && (
          <div className="text-xs text-gray-500 text-center py-4">
            暂无可用推荐数据
          </div>
        )}

      <div className="flex items-start gap-2 rounded-lg bg-yellow-50 border border-yellow-200 p-3 text-xs text-yellow-800">
        <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
        <span>本推荐仅供参考，具体用药请遵医嘱</span>
      </div>
    </div>
  );
}
