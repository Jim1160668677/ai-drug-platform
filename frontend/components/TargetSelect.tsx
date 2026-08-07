'use client';

/**
 * TargetSelect — 靶点 ID 自动匹配下拉组件
 *
 * 解决问题：用户在设计分子/分子对接时不知道如何获取 target_id，
 *          需要手工复制 UUID。本组件自动从已发现的靶点列表中加载，
 *          以下拉框形式展示，并支持搜索过滤，降低使用门槛。
 *
 * 用法：
 *   <TargetSelect value={targetId} onChange={setTargetId} />
 *   <TargetSelect value={targetId} onChange={setTargetId} projectId={currentProject?.id} />
 */

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, Search, Target as TargetIcon, X } from 'lucide-react';
import { getTargets } from '@/lib/api';

export interface TargetSelectProps {
  /** 当前选中的 target_id */
  value?: string;
  /** 选择回调，参数为 target_id（空字符串表示清空） */
  onChange: (targetId: string) => void;
  /** 可选：项目 ID 过滤（不传则取所有项目靶点） */
  projectId?: string;
  /** 占位符 */
  placeholder?: string;
  /** 是否允许清空 */
  allowClear?: boolean;
  /** 是否禁用 */
  disabled?: boolean;
  /** 自定义类名 */
  className?: string;
}

export default function TargetSelect({
  value,
  onChange,
  projectId,
  placeholder = '选择已发现的靶点（自动匹配）',
  allowClear = true,
  disabled = false,
  className = '',
}: TargetSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  // 加载已发现的靶点列表
  const { data: targetsData, isLoading } = useQuery({
    queryKey: ['targets-for-select', projectId],
    queryFn: () => getTargets(projectId),
    staleTime: 60 * 1000, // 1 分钟内不重复请求
  });

  // 适配 PagedResponse / array 两种返回结构
  const targets: any[] = useMemo(() => {
    if (!targetsData) return [];
    if (Array.isArray(targetsData)) return targetsData;
    return ((targetsData as any)?.data ?? (targetsData as any)?.items) || [];
  }, [targetsData]);

  // 选中靶点的展示信息
  const selectedTarget = useMemo(
    () => targets.find((t) => t.id === value),
    [targets, value]
  );

  // 过滤搜索结果
  const filteredTargets = useMemo(() => {
    if (!search.trim()) return targets;
    const q = search.toLowerCase();
    return targets.filter(
      (t) =>
        (t.gene_symbol || '').toLowerCase().includes(q) ||
        (t.gene_name || '').toLowerCase().includes(q) ||
        (t.description || '').toLowerCase().includes(q) ||
        (t.id || '').toLowerCase().includes(q)
    );
  }, [targets, search]);

  // 关闭弹窗时清空搜索
  useEffect(() => {
    if (!open) setSearch('');
  }, [open]);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (!el.closest('[data-target-select-root]')) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div
      data-target-select-root
      className={`relative ${className}`}
    >
      <div
        className={`flex items-center gap-2 w-full border border-gray-300 rounded px-3 py-2 text-sm bg-white ${
          disabled ? 'bg-gray-100 cursor-not-allowed' : 'cursor-pointer hover:border-primary-400'
        }`}
        onClick={() => !disabled && setOpen((o) => !o)}
      >
        <TargetIcon className="w-4 h-4 text-gray-400 shrink-0" />
        {selectedTarget ? (
          <div className="flex-1 min-w-0">
            <span className="font-medium text-gray-900">
              {selectedTarget.gene_symbol || '未命名靶点'}
            </span>
            {selectedTarget.gene_name && (
              <span className="ml-2 text-xs text-gray-500 truncate">
                {selectedTarget.gene_name}
              </span>
            )}
            {selectedTarget.evidence_grade && (
              <span className="ml-2 inline-block px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium align-middle">
                {selectedTarget.evidence_grade} 级
              </span>
            )}
          </div>
        ) : (
          <span className="flex-1 text-gray-400">{placeholder}</span>
        )}
        {allowClear && value && !disabled && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onChange('');
            }}
            className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
            title="清空"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        <ChevronDown
          className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </div>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-md shadow-lg max-h-72 overflow-hidden flex flex-col">
          {/* 搜索框 */}
          <div className="p-2 border-b border-gray-100 flex items-center gap-2">
            <Search className="w-4 h-4 text-gray-400" />
            <input
              type="text"
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索基因符号/名称..."
              className="flex-1 text-sm outline-none"
              onClick={(e) => e.stopPropagation()}
            />
          </div>

          {/* 列表 */}
          <div className="overflow-y-auto flex-1">
            {isLoading ? (
              <div className="px-3 py-6 text-center text-sm text-gray-400">
                加载靶点列表中...
              </div>
            ) : filteredTargets.length === 0 ? (
              <div className="px-3 py-6 text-center text-sm text-gray-400">
                {targets.length === 0
                  ? '暂无已发现的靶点，请先到「靶点发现」页面执行发现流程'
                  : '没有匹配的靶点'}
              </div>
            ) : (
              filteredTargets.map((t) => {
                const active = t.id === value;
                return (
                  <div
                    key={t.id}
                    onClick={() => {
                      onChange(t.id);
                      setOpen(false);
                    }}
                    className={`px-3 py-2 cursor-pointer border-b border-gray-50 hover:bg-primary-50 ${
                      active ? 'bg-primary-50' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <span className="font-medium text-gray-900 text-sm">
                          {t.gene_symbol || '未命名'}
                        </span>
                        {t.gene_name && (
                          <span className="ml-2 text-xs text-gray-500 truncate">
                            {t.gene_name}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 ml-2 shrink-0">
                        {t.evidence_grade && (
                          <span className="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">
                            {t.evidence_grade}
                          </span>
                        )}
                        {t.confidence_score != null && (
                          <span className="text-[10px] text-gray-500">
                            {Math.round((t.confidence_score || 0) * 100)}%
                          </span>
                        )}
                      </div>
                    </div>
                    {t.id && (
                      <div className="text-[10px] text-gray-400 font-mono mt-0.5 truncate">
                        {t.id}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* 底部统计 */}
          {targets.length > 0 && (
            <div className="px-3 py-1.5 border-t border-gray-100 text-[10px] text-gray-400 bg-gray-50">
              共 {targets.length} 个靶点{search.trim() && `，匹配 ${filteredTargets.length} 个`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
