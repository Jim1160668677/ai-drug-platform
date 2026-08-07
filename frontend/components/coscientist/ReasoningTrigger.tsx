'use client';

/**
 * ReasoningTrigger — 通用原地推理触发器
 *
 * 在任意业务实体（靶点/分子/实验/治疗…）旁嵌入，点击即可发起一次就地轻推理。
 * - 调 quickReason({entity_type, entity_id, entity_name, project_id, reason_type})
 * - 成功后 toast「推理已启动」+ setCopilotOpen(true) 打开浮窗查看进度
 * - variant='button' 显示「🧪 AI 推理」按钮；variant='icon' 显示小图标按钮
 * - 加载中显示 spinner
 *
 * run_id 通过 queryClient.setQueryData 缓存到 ['coscientist-quick-reason', entityType, entityId]，
 * 供浮窗/进度面板订阅并轮询 getProgress。
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { quickReason } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import { FlaskConical, Loader2 } from 'lucide-react';

interface ReasoningTriggerProps {
  /** 实体类型：target / molecule / experiment / treatment ... */
  entityType: string;
  /** 实体 ID */
  entityId: string;
  /** 实体名称（注入到推理上下文，提升建议相关性） */
  entityName?: string;
  /** 项目 ID（可选，缺省从 useAppStore.currentProject 取） */
  projectId?: string;
  /** 推理类型，如 repurposing / mechanism / optimization / next_step ... */
  reasonType?: string;
  /** 展示形态：按钮或图标 */
  variant?: 'button' | 'icon';
  /** 按钮形态下的自定义文案 */
  label?: string;
}

export default function ReasoningTrigger({
  entityType,
  entityId,
  entityName,
  projectId,
  reasonType,
  variant = 'button',
  label,
}: ReasoningTriggerProps) {
  const queryClient = useQueryClient();
  const setCopilotOpen = useAppStore((s) => s.setCopilotOpen);
  const storeProjectId = useAppStore((s) => s.currentProject?.id);
  const effectiveProjectId = projectId ?? storeProjectId;

  const quickReasonMutation = useMutation({
    mutationFn: () =>
      quickReason({
        project_id: effectiveProjectId,
        entity_type: entityType,
        entity_id: entityId,
        entity_name: entityName,
        reason_type: reasonType,
      }),
    onSuccess: (res) => {
      // 缓存 run_id，浮窗可订阅该 queryKey 拿到 run_id 并轮询进度
      queryClient.setQueryData(['coscientist-quick-reason', entityType, entityId], res);
      toast.success('推理已启动', `运行 ID: ${res.run_id.slice(0, 8)}…，可在助手面板查看进度`);
      // 打开浮窗，让用户实时跟进推理进度
      setCopilotOpen(true);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '请稍后重试';
      toast.error('推理启动失败', msg);
    },
  });

  const isLoading = quickReasonMutation.isPending;
  const buttonLabel = label ?? 'AI 推理';

  if (variant === 'icon') {
    return (
      <button
        type="button"
        onClick={() => quickReasonMutation.mutate()}
        disabled={isLoading || !entityId}
        title={label ?? '对当前实体发起 AI 推理'}
        aria-label={label ?? 'AI 推理'}
        className="inline-flex items-center justify-center w-7 h-7 text-indigo-500 hover:text-indigo-700 hover:bg-indigo-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => quickReasonMutation.mutate()}
      disabled={isLoading || !entityId}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 hover:text-indigo-700 border border-indigo-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {isLoading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : (
        <span aria-hidden className="text-sm leading-none">🧪</span>
      )}
      {isLoading ? '推理中…' : buttonLabel}
    </button>
  );
}
