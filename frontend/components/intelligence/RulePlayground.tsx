'use client';

/**
 * RulePlayground — 规则执行演练场（组件 18/18）
 *
 * 表单+展示组件：Monaco YAML 编辑器编辑规则，JSON 编辑器编辑 context，
 * 支持 validate（校验语法）与 execute（执行规则集并展示命中结果）。
 *
 * 端点：POST /intelligence/rules/validate + POST /intelligence/rules/execute
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import dynamic from 'next/dynamic';
import { Terminal, CheckCircle2, XCircle, Play, ShieldCheck, Zap, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import Button from '@/components/ui/Button';
import Card from '@/components/ui/Card';
import FormError from '@/components/ui/FormError';
import EmptyState from '@/components/ui/EmptyState';
import { validateRules, executeRules } from '@/lib/api';
import { toast } from '@/lib/notification';
import type { RuleValidateResponse, RuleExecuteResponse } from '@/types/intelligence';

// Monaco 编辑器动态加载（SSR 关闭）
const MonacoEditor = dynamic(() => import('@monaco-editor/react').then((m) => m.default), {
  ssr: false,
  loading: () => (
    <div className="h-48 flex items-center justify-center text-gray-400 text-sm">
      <Loader2 className="w-4 h-4 animate-spin mr-1" /> 编辑器加载中...
    </div>
  ),
});

const DEFAULT_YAML = `name: example_ruleset
version: "1.0"
description: 示例规则集
rules:
  - id: rule-1
    name: 高表达靶点告警
    when:
      field: expression_level
      op: ">"
      value: 10
    then:
      - action: set_flag
        target: target
        value: high_expression
        message: 该靶点表达水平过高
    priority: 1
    enabled: true
`;

const DEFAULT_CONTEXT = `{
  "target": "TP53",
  "expression_level": 15.6
}`;

export default function RulePlayground() {
  const [yamlContent, setYamlContent] = useState(DEFAULT_YAML);
  const [contextText, setContextText] = useState(DEFAULT_CONTEXT);
  const [tags, setTags] = useState('');
  const [validateResult, setValidateResult] = useState<RuleValidateResponse | null>(null);
  const [executeResult, setExecuteResult] = useState<RuleExecuteResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // 解析 context JSON
  const parseContext = (): Record<string, unknown> => {
    try {
      return JSON.parse(contextText);
    } catch {
      throw new Error('context 不是有效的 JSON');
    }
  };

  // 验证规则
  const validateMutation = useMutation({
    mutationFn: () => validateRules(yamlContent),
    onSuccess: (data) => {
      setValidateResult(data);
      setErrorMsg(null);
      if (data.valid) {
        toast.success(`规则校验通过（${data.rules_count} 条）`);
      } else {
        toast.warning(`规则校验失败（${data.errors.length} 个错误）`);
      }
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '规则校验失败';
      setErrorMsg(msg);
      toast.error('规则校验失败', msg);
    },
  });

  // 执行规则
  const executeMutation = useMutation({
    mutationFn: () => {
      const context = parseContext();
      return executeRules({
        yaml_content: yamlContent,
        context,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      });
    },
    onSuccess: (data) => {
      setExecuteResult(data);
      setErrorMsg(null);
      toast.success(`执行完成：命中 ${data.matched_rules}/${data.total_rules} 条规则`);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '规则执行失败';
      setErrorMsg(msg);
      toast.error('规则执行失败', msg);
    },
  });

  return (
    <div className="space-y-3">
      <Card title="规则演练场" action={<Terminal className="w-4 h-4 text-gray-400" />}>
        <div className="space-y-3">
          {/* YAML 编辑器 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">规则 YAML</label>
            <div className="border border-gray-300 rounded-md overflow-hidden">
              <MonacoEditor
                height={240}
                language="yaml"
                theme="light"
                value={yamlContent}
                onChange={(val) => setYamlContent(val ?? '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                  automaticLayout: true,
                }}
              />
            </div>
          </div>

          {/* Context 编辑器 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Context (JSON)</label>
            <div className="border border-gray-300 rounded-md overflow-hidden">
              <MonacoEditor
                height={140}
                language="json"
                theme="light"
                value={contextText}
                onChange={(val) => setContextText(val ?? '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                  automaticLayout: true,
                }}
              />
            </div>
          </div>

          {/* 标签 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">执行标签（逗号分隔，可选）</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="safety, toxicity"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {errorMsg && <FormError message={errorMsg} />}

          {/* 操作按钮 */}
          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              variant="secondary"
              loading={validateMutation.isPending}
              onClick={() => validateMutation.mutate()}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              校验规则
            </Button>
            <Button
              size="sm"
              loading={executeMutation.isPending}
              onClick={() => executeMutation.mutate()}
            >
              <Play className="w-3.5 h-3.5" />
              执行规则
            </Button>
          </div>
        </div>
      </Card>

      {/* 验证结果 */}
      {validateResult && (
        <Card title="校验结果">
          <div
            className={clsx(
              'flex items-center gap-2 p-2.5 rounded-md mb-2',
              validateResult.valid ? 'bg-green-50' : 'bg-red-50',
            )}
          >
            {validateResult.valid ? (
              <CheckCircle2 className="w-4 h-4 text-green-500" />
            ) : (
              <XCircle className="w-4 h-4 text-red-500" />
            )}
            <span className={clsx('text-sm font-medium', validateResult.valid ? 'text-green-700' : 'text-red-700')}>
              {validateResult.valid
                ? `校验通过 · ${validateResult.rules_count} 条规则`
                : `校验失败 · ${validateResult.errors.length} 个错误`}
            </span>
          </div>
          {validateResult.errors.length > 0 && (
            <ul className="space-y-1">
              {validateResult.errors.map((err, idx) => (
                <li key={idx} className="text-xs text-red-600 flex items-start gap-1.5">
                  <span className="text-red-400 mt-0.5">•</span>
                  <span className="break-words">{err}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* 执行结果 */}
      {executeResult ? (
        <Card
          title="执行结果"
          action={
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-50 text-purple-600 rounded text-xs font-medium">
              <Zap className="w-3 h-3" />
              {executeResult.duration_sec.toFixed(2)}s
            </span>
          }
        >
          <div className="space-y-3">
            {/* 统计 */}
            <div className="grid grid-cols-4 gap-2">
              <StatBox label="总规则" value={executeResult.total_rules} color="gray" />
              <StatBox label="命中" value={executeResult.matched_rules} color="green" />
              <StatBox label="执行动作" value={executeResult.executed_actions} color="blue" />
              <StatBox label="耗时(s)" value={Number(executeResult.duration_sec.toFixed(2))} color="purple" />
            </div>

            {/* 规则集名称 */}
            <p className="text-xs text-gray-500">规则集: {executeResult.ruleset_name}</p>

            {/* 命中详情 */}
            {executeResult.results.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-600 mb-1.5">命中详情</p>
                <ul className="space-y-1.5 max-h-60 overflow-y-auto">
                  {executeResult.results.map((r, idx) => (
                    <li
                      key={idx}
                      className={clsx(
                        'p-2 rounded-md border text-xs',
                        r.matched ? 'border-green-200 bg-green-50' : 'border-gray-100 bg-gray-50',
                      )}
                    >
                      <div className="flex items-center gap-1.5">
                        {r.matched ? (
                          <CheckCircle2 className="w-3 h-3 text-green-500" />
                        ) : (
                          <XCircle className="w-3 h-3 text-gray-300" />
                        )}
                        <span className="font-medium text-gray-700">{r.rule_name}</span>
                        {r.actions_executed > 0 && (
                          <span className="px-1 py-0.5 bg-blue-50 text-blue-600 rounded">
                            {r.actions_executed} 动作
                          </span>
                        )}
                        {r.error && (
                          <span className="px-1 py-0.5 bg-red-50 text-red-600 rounded">{r.error}</span>
                        )}
                      </div>
                      {r.outputs.length > 0 && (
                        <pre className="mt-1 p-1.5 bg-white rounded text-xs text-gray-600 overflow-x-auto">
                          {JSON.stringify(r.outputs, null, 2)}
                        </pre>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 上下文变更 */}
            {executeResult.context_changes &&
              Object.keys(executeResult.context_changes).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-1">Context 变更</p>
                  <pre className="p-2.5 bg-amber-50 rounded text-xs text-gray-700 overflow-x-auto max-h-40">
                    {JSON.stringify(executeResult.context_changes, null, 2)}
                  </pre>
                </div>
              )}
          </div>
        </Card>
      ) : (
        !executeMutation.isPending &&
        !validateResult && (
          <Card title="执行结果">
            <EmptyState title="编辑规则后点击「执行规则」查看结果" />
          </Card>
        )
      )}
    </div>
  );
}

// ========== 统计盒子 ==========
function StatBox({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: 'gray' | 'green' | 'blue' | 'purple';
}) {
  const colors = {
    gray: 'bg-gray-50 text-gray-700',
    green: 'bg-green-50 text-green-700',
    blue: 'bg-blue-50 text-blue-700',
    purple: 'bg-purple-50 text-purple-700',
  };
  return (
    <div className={clsx('p-2 rounded-md text-center', colors[color])}>
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-xs opacity-70">{label}</p>
    </div>
  );
}