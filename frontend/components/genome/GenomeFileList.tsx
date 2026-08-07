'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, Trash2, CheckCircle2 } from 'lucide-react';
import { listGenomes, deleteGenome } from '@/lib/api';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Loading from '@/components/ui/Loading';

interface GenomeFileListProps {
  /** 当前选中的基因组 ID */
  selectedGenomeId?: string | null;
  /** 选中回调 */
  onSelect?: (genome: any) => void;
  /** 是否只读（不显示删除按钮） */
  readOnly?: boolean;
}

export default function GenomeFileList({
  selectedGenomeId,
  onSelect,
  readOnly = false,
}: GenomeFileListProps) {
  const queryClient = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['genome-files'],
    queryFn: () => listGenomes(1, 50),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteGenome(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['genome-files'] });
      import('@/lib/notification').then(({ toast }) => {
        toast.success('删除成功', '基因组文件已删除');
      });
      setDeletingId(null);
    },
    onError: (err: any) => {
      import('@/lib/notification').then(({ toast }) => {
        toast.error('删除失败', err?.response?.data?.detail || err?.message || '请稍后重试');
      });
      setDeletingId(null);
    },
  });

  const items: any[] = data?.data ?? data?.items ?? [];

  if (isLoading) {
    return <Loading label="加载基因组文件..." />;
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        加载失败，请重试
        <Button size="sm" variant="ghost" onClick={() => refetch()} className="ml-2">
          重试
        </Button>
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500">
        <FileText className="w-10 h-10 mx-auto mb-2 text-gray-400" />
        暂无上传的基因组文件
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((g: any) => {
        const selected = selectedGenomeId === g.id;
        return (
          <div
            key={g.id}
            className={`flex items-center justify-between rounded-lg border p-3 cursor-pointer transition-colors ${
              selected
                ? 'border-primary-500 bg-primary-50'
                : 'border-gray-200 bg-white hover:bg-gray-50'
            }`}
            onClick={() => onSelect?.(g)}
          >
            <div className="flex items-center gap-3 flex-1 min-w-0">
              {selected ? (
                <CheckCircle2 className="w-5 h-5 text-primary-600 shrink-0" />
              ) : (
                <FileText className="w-5 h-5 text-gray-400 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-900 truncate">
                  {g.file_name}
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                  <Badge variant="blue" value={g.genome_build || 'GRCh37'} />
                  <span>变体数：{g.total_variants ?? '—'}</span>
                  <span>格式：{g.source_format || 'generic'}</span>
                  {g.created_at && (
                    <span>上传于 {new Date(g.created_at).toLocaleString('zh-CN')}</span>
                  )}
                </div>
              </div>
            </div>
            {!readOnly && (
              <Button
                size="sm"
                variant="ghost"
                loading={deletingId === g.id}
                onClick={(e: any) => {
                  e?.stopPropagation?.();
                  if (confirm(`确定删除文件「${g.file_name}」吗？相关评估记录将一并删除。`)) {
                    setDeletingId(g.id);
                    deleteMutation.mutate(g.id);
                  }
                }}
                className="text-red-600 hover:bg-red-50"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
}
