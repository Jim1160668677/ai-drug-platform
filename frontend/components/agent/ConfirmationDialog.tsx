'use client';

import { AlertTriangle, X, Check } from 'lucide-react';
import Button from '@/components/ui/Button';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface ConfirmationDialogProps {
  open: boolean;
  task_id: string;
  tool: string;
  args: Record<string, unknown>;
  onConfirm: (taskId: string, approved: boolean) => void;
}

export function ConfirmationDialog({
  open,
  task_id,
  tool,
  args,
  onConfirm,
}: ConfirmationDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-200 bg-yellow-50">
          <AlertTriangle className="w-5 h-5 text-yellow-600" />
          <h3 className="text-sm font-semibold text-gray-900">副作用操作确认</h3>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-gray-700">
            Agent 即将执行具有副作用的工具，请确认是否继续：
          </p>

          <div className="bg-gray-50 border border-gray-200 rounded p-3">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
              工具
            </div>
            <div className="font-mono text-sm font-medium text-gray-900">{tool}</div>
          </div>

          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
              参数
            </div>
            <SyntaxHighlighter
              language="json"
              style={oneDark}
              customStyle={{ fontSize: '11px', padding: '8px', margin: 0 }}
            >
              {JSON.stringify(args, null, 2)}
            </SyntaxHighlighter>
          </div>

          <div className="text-xs text-gray-500">
            任务 ID: <span className="font-mono">{task_id.slice(0, 8)}...</span>
          </div>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 bg-gray-50 border-t border-gray-200">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onConfirm(task_id, false)}
          >
            <X className="w-3 h-3" /> 取消执行
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => onConfirm(task_id, true)}
          >
            <Check className="w-3 h-3" /> 确认执行
          </Button>
        </div>
      </div>
    </div>
  );
}
