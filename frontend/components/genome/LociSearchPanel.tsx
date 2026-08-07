'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, Dna, RefreshCw } from 'lucide-react';
import { getTraitLoci, searchLoci } from '@/lib/api';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Loading from '@/components/ui/Loading';

interface LociSearchPanelProps {
  /** 性状 ID */
  traitId: string | null;
  /** 性状名称（用于显示） */
  traitName?: string;
  /** 用户 LLM 配置 ID（可选） */
  userLlmConfigId?: string;
  /** 搜索完成后回调 */
  onSearched?: (result: any) => void;
}

export default function LociSearchPanel({
  traitId,
  traitName,
  userLlmConfigId,
  onSearched,
}: LociSearchPanelProps) {
  const queryClient = useQueryClient();
  const [useExternal, setUseExternal] = useState(true);

  const { data: lociData, isLoading: lociLoading } = useQuery({
    queryKey: ['genome-trait-loci', traitId],
    queryFn: () => getTraitLoci(traitId!, true),
    enabled: !!traitId,
  });

  const searchMutation = useMutation({
    mutationFn: () =>
      searchLoci(traitId!, {
        useExternal,
        userLlmConfigId,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['genome-trait-loci', traitId] });
      import('@/lib/notification').then(({ toast }) => {
        const result = res?.data ?? res;
        const added = result?.new_loci_added ?? result?.loci_added ?? 0;
        toast.success('AI 检索完成', `新增 ${added} 个候选位点`);
      });
      onSearched?.(res?.data ?? res);
    },
    onError: (err: any) => {
      import('@/lib/notification').then(({ toast }) => {
        toast.error(
          'AI 检索失败',
          err?.response?.data?.detail || err?.message || '请稍后重试'
        );
      });
    },
  });

  if (!traitId) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500">
        <Dna className="w-10 h-10 mx-auto mb-2 text-gray-400" />
        请先在上方选择一个性状
      </div>
    );
  }

  const loci: any[] = lociData?.data?.loci ?? lociData?.loci ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Dna className="w-4 h-4 text-primary-600" />
          <span className="text-sm font-semibold text-gray-900">
            {traitName || '性状'} — 位点列表
          </span>
          <Badge variant="blue" value={`${loci.length} 个`} />
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={useExternal}
              onChange={(e) => setUseExternal(e.target.checked)}
              className="rounded"
              disabled={searchMutation.isPending}
            />
            查询外部数据源（GWAS/ClinVar/OMIM）
          </label>
          <Button
            size="sm"
            loading={searchMutation.isPending}
            onClick={() => searchMutation.mutate()}
            disabled={searchMutation.isPending}
          >
            <Search className="w-3.5 h-3.5" />
            AI 检索位点
          </Button>
        </div>
      </div>

      {lociLoading ? (
        <Loading size="sm" label="加载位点..." />
      ) : loci.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-xs text-gray-500">
          暂无位点，点击「AI 检索位点」从外部数据源扩充
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-xs">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="px-3 py-2 text-left">rsID</th>
                <th className="px-3 py-2 text-left">染色体</th>
                <th className="px-3 py-2 text-left">位置</th>
                <th className="px-3 py-2 text-left">风险基因型</th>
                <th className="px-3 py-2 text-left">效应量</th>
                <th className="px-3 py-2 text-left">层级</th>
                <th className="px-3 py-2 text-left">审核</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loci.map((l: any, idx: number) => (
                <tr key={l.id || idx} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-mono text-gray-900">
                    {l.rsid || '—'}
                  </td>
                  <td className="px-3 py-2">{l.chromosome || '—'}</td>
                  <td className="px-3 py-2">{l.position?.toLocaleString() || '—'}</td>
                  <td className="px-3 py-2 font-mono">
                    {l.risk_genotype || l.risk_allele || '—'}
                  </td>
                  <td className="px-3 py-2">
                    {l.effect_size != null ? Number(l.effect_size).toFixed(2) : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {l.locus_tier === 'CORE' ? (
                      <Badge variant="red" value="核心" />
                    ) : (
                      <Badge variant="gray" value="辅助" />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {l.is_approved ? (
                      <Badge variant="green" value="已审" />
                    ) : (
                      <Badge variant="yellow" value="待审" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {searchMutation.isPending && (
        <div className="flex items-center gap-2 text-xs text-primary-600">
          <RefreshCw className="w-3 h-3 animate-spin" />
          正在调用 LLM 检索位点（可能需要数秒）...
        </div>
      )}
    </div>
  );
}
