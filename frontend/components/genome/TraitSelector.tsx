'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Circle } from 'lucide-react';
import { listTraits } from '@/lib/api';
import Badge from '@/components/ui/Badge';
import Loading from '@/components/ui/Loading';

interface TraitSelectorProps {
  /** 已选中的性状 ID 列表 */
  selectedTraitIds: string[];
  /** 选中变更回调 */
  onChange: (ids: string[]) => void;
  /** 类别过滤（可选） */
  category?: string;
}

/** 9 大性状类别 → 中文标签 + 颜色映射 */
const CATEGORY_LABELS: Record<string, string> = {
  allergy: '过敏易感',
  metabolism: '代谢能力',
  cardio: '心血管',
  athletic: '运动潜能',
  sleep: '睡眠节律',
  skin_hair: '皮肤毛发',
  cognition: '认知能力',
  altitude: '高原适应',
  drug_response: '药物反应',
};

const CATEGORY_COLORS: Record<string, any> = {
  allergy: 'red',
  metabolism: 'yellow',
  cardio: 'red',
  athletic: 'green',
  sleep: 'purple',
  skin_hair: 'blue',
  cognition: 'purple',
  altitude: 'blue',
  drug_response: 'yellow',
};

export default function TraitSelector({
  selectedTraitIds,
  onChange,
  category,
}: TraitSelectorProps) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['genome-traits', category],
    queryFn: () => listTraits(category, 1, 100),
  });

  const traits: any[] = useMemo(() => data?.data ?? data?.items ?? [], [data]);

  // 注意：所有 Hook 必须在任何条件 return 之前调用，否则违反 React Rules of Hooks。
  // 此处 groups useMemo 必须先于 isLoading / isError / 空列表的早返回，保证 Hook 数量恒定。
  const groups = useMemo(() => {
    const map = new Map<string, any[]>();
    (traits || []).forEach((t) => {
      const key = t.category || 'other';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(t);
    });
    return Array.from(map.entries());
  }, [traits]);

  const toggle = (id: string) => {
    if (selectedTraitIds.includes(id)) {
      onChange(selectedTraitIds.filter((x) => x !== id));
    } else {
      onChange([...selectedTraitIds, id]);
    }
  };

  if (isLoading) return <Loading label="加载性状列表..." />;

  if (isError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        加载失败
        <button onClick={() => refetch()} className="ml-2 underline">
          重试
        </button>
      </div>
    );
  }

  if (!traits || traits.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500">
        暂无可选性状
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {groups.map(([cat, items]) => (
        <div key={cat}>
          <div className="flex items-center gap-2 mb-2">
            <Badge variant={CATEGORY_COLORS[cat] || 'gray'} value={CATEGORY_LABELS[cat] || cat} />
            <span className="text-xs text-gray-400">{items.length} 项</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((t) => {
              const selected = selectedTraitIds.includes(t.id);
              return (
                <div
                  key={t.id}
                  className={`rounded-lg border p-3 cursor-pointer transition-all ${
                    selected
                      ? 'border-primary-500 bg-primary-50 ring-2 ring-primary-100'
                      : 'border-gray-200 bg-white hover:border-primary-300'
                  }`}
                  onClick={() => toggle(t.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-gray-900 truncate">
                        {t.name}
                      </div>
                      {t.description && (
                        <div className="text-xs text-gray-500 mt-1 line-clamp-2">
                          {t.description}
                        </div>
                      )}
                    </div>
                    {selected ? (
                      <CheckCircle2 className="w-5 h-5 text-primary-600 shrink-0 ml-2" />
                    ) : (
                      <Circle className="w-5 h-5 text-gray-300 shrink-0 ml-2" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
