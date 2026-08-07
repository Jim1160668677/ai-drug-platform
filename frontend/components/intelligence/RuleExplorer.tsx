'use client';

/**
 * RuleExplorer — 规则浏览器（组件 17/18）
 *
 * 数据展示组件：左侧列出所有 preset 与 ruleset，右侧展示选中 ruleset 的规则详情。
 * 双栏联动，支持搜索过滤规则。
 *
 * 端点：GET /intelligence/rules + GET /intelligence/rules/{preset}
 */
import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BookOpen, Search, Tag, Shield, ArrowRight, Zap } from 'lucide-react';
import clsx from 'clsx';
import Card from '@/components/ui/Card';
import EmptyState from '@/components/ui/EmptyState';
import { SkeletonList } from '@/components/ui/Skeleton';
import { listRules, getRulePreset } from '@/lib/api';
import type { RuleResponse } from '@/types/intelligence';

export default function RuleExplorer() {
  const [selectedPreset, setSelectedPreset] = useState<string>('');
  const [search, setSearch] = useState('');

  // 获取规则集列表
  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['intelligence-rules-list'],
    queryFn: () => listRules(),
  });

  // 选中第一个 preset 作为默认值
  const effectivePreset =
    selectedPreset || listData?.presets?.[0] || listData?.rulesets?.[0]?.name || '';

  // 获取选中的 ruleset 详情
  const { data: ruleset, isLoading: presetLoading } = useQuery({
    queryKey: ['intelligence-rule-preset', effectivePreset],
    queryFn: () => getRulePreset(effectivePreset),
    enabled: !!effectivePreset,
  });

  // 过滤规则
  const filteredRules = useMemo(() => {
    if (!ruleset?.rules) return [];
    if (!search.trim()) return ruleset.rules;
    const q = search.toLowerCase();
    return ruleset.rules.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.description?.toLowerCase().includes(q) ||
        r.tags?.some((t) => t.toLowerCase().includes(q)),
    );
  }, [ruleset, search]);

  return (
    <Card title="规则浏览器" action={<BookOpen className="w-4 h-4 text-gray-400" />}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 左栏：preset 列表 */}
        <div className="md:col-span-1 space-y-2">
          <p className="text-xs font-medium text-gray-600">规则集</p>
          {listLoading ? (
            <SkeletonList count={3} />
          ) : listData && (listData.presets.length > 0 || listData.rulesets.length > 0) ? (
            <ul className="space-y-1 max-h-80 overflow-y-auto">
              {/* 内置 preset */}
              {listData.presets.map((preset) => (
                <li key={preset}>
                  <button
                    onClick={() => setSelectedPreset(preset)}
                    className={clsx(
                      'w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors',
                      effectivePreset === preset
                        ? 'bg-primary-50 text-primary-700 font-medium'
                        : 'hover:bg-gray-50 text-gray-600',
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <Tag className="w-3 h-3 flex-shrink-0" />
                      <span className="truncate">{preset}</span>
                    </span>
                  </button>
                </li>
              ))}
              {/* 自定义 ruleset */}
              {listData.rulesets.map((rs) => (
                <li key={rs.name}>
                  <button
                    onClick={() => setSelectedPreset(rs.name)}
                    className={clsx(
                      'w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors',
                      effectivePreset === rs.name
                        ? 'bg-primary-50 text-primary-700 font-medium'
                        : 'hover:bg-gray-50 text-gray-600',
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <Shield className="w-3 h-3 flex-shrink-0" />
                      <span className="truncate">{rs.name}</span>
                      <span className="ml-auto text-xs text-gray-400">{rs.rules.length}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="无规则集" />
          )}
        </div>

        {/* 右栏：规则详情 */}
        <div className="md:col-span-2 space-y-3">
          {/* 搜索框 */}
          {ruleset && ruleset.rules.length > 0 && (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索规则名称/描述/标签..."
                className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
          )}

          {presetLoading ? (
            <SkeletonList count={4} />
          ) : ruleset ? (
            <>
              {/* ruleset 元信息 */}
              <div className="px-3 py-2 bg-gray-50 rounded-md">
                <div className="flex items-center gap-2 mb-0.5">
                  <h4 className="text-sm font-semibold text-gray-800">{ruleset.name}</h4>
                  <span className="px-1.5 py-0.5 bg-white text-gray-500 rounded text-xs">
                    v{ruleset.version}
                  </span>
                </div>
                {ruleset.description && (
                  <p className="text-xs text-gray-500">{ruleset.description}</p>
                )}
              </div>

              {/* 规则列表 */}
              {filteredRules.length > 0 ? (
                <ul className="space-y-2">
                  {filteredRules.map((rule) => (
                    <RuleItem key={rule.id} rule={rule} />
                  ))}
                </ul>
              ) : (
                <EmptyState title={search ? '无匹配规则' : '该规则集为空'} />
              )}
            </>
          ) : (
            <EmptyState title="选择左侧规则集查看详情" />
          )}
        </div>
      </div>
    </Card>
  );
}

// ========== 规则条目 ==========
function RuleItem({ rule }: { rule: RuleResponse }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="border border-gray-100 rounded-md overflow-hidden">
      <div
        className="flex items-start gap-2 p-2.5 cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded((v) => !v)}
      >
        <Zap
          className={clsx(
            'w-3.5 h-3.5 flex-shrink-0 mt-0.5',
            rule.enabled ? 'text-green-500' : 'text-gray-300',
          )}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-700 truncate">{rule.name}</span>
            {rule.priority !== 0 && (
              <span className="px-1 py-0.5 bg-amber-50 text-amber-600 rounded text-xs">
                P{rule.priority}
              </span>
            )}
            {!rule.enabled && (
              <span className="px-1 py-0.5 bg-gray-100 text-gray-400 rounded text-xs">禁用</span>
            )}
          </div>
          {rule.description && (
            <p className="text-xs text-gray-500 mt-0.5 break-words line-clamp-1">
              {rule.description}
            </p>
          )}
          {rule.tags && rule.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {rule.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-1 py-0.5 bg-blue-50 text-blue-500 rounded text-xs"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-3 py-2 bg-gray-50 border-t border-gray-100 space-y-2">
          {/* when 条件 */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-0.5">WHEN</p>
            <pre className="text-xs text-gray-700 bg-white p-2 rounded overflow-x-auto">
              {JSON.stringify(rule.when, null, 2)}
            </pre>
          </div>
          {/* then 动作 */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-0.5 flex items-center gap-1">
              THEN <ArrowRight className="w-3 h-3" />
            </p>
            <pre className="text-xs text-gray-700 bg-white p-2 rounded overflow-x-auto">
              {JSON.stringify(rule.then, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </li>
  );
}