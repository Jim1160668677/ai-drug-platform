'use client';

import { useState, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import { Play, Square, Loader2, Terminal, AlertCircle, CheckCircle2 } from 'lucide-react';
import clsx from 'clsx';
import api from '@/lib/api/client';

interface SandboxCodeRunnerProps {
  /** 默认语言 */
  defaultLanguage?: 'python' | 'r';
  /** 默认代码 */
  defaultCode?: string;
  /** 是否只读（Agent 自动执行时） */
  readOnly?: boolean;
  /** 最小高度 */
  minHeight?: number;
}

interface ExecutionResult {
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms?: number;
  execution_id?: string;
}

type ExecutionStatus = 'idle' | 'running' | 'success' | 'failed';

const LANGUAGE_OPTIONS = [
  { value: 'python' as const, label: 'Python 3', monacoLang: 'python' },
  { value: 'r' as const, label: 'R', monacoLang: 'r' },
];

const DEFAULT_CODE_PYTHON = '# 在沙箱中执行代码\n# 支持标准库 + numpy/pandas/scikit-learn\nimport numpy as np\n\nprint("Hello from sandbox!")\nprint(f"numpy version: {np.__version__}")\n';
const DEFAULT_CODE_R = '# 在沙箱中执行 R 代码\nprint("Hello from R sandbox!")\nprint(R.version.string)\n';

/**
 * SandboxCodeRunner — 代码沙箱执行 UI
 *
 * 设计来源：2026-07-18-agent-functional-design.md §4.4
 *
 * Monaco 编辑器 + 语言切换 + 执行按钮 + 输出展示。
 * 调用后端 POST /api/v1/sandbox/execute。
 */
export function SandboxCodeRunner({
  defaultLanguage = 'python',
  defaultCode,
  readOnly = false,
  minHeight = 400,
}: SandboxCodeRunnerProps) {
  const [language, setLanguage] = useState<'python' | 'r'>(defaultLanguage);
  const [code, setCode] = useState(
    defaultCode ?? (defaultLanguage === 'python' ? DEFAULT_CODE_PYTHON : DEFAULT_CODE_R)
  );
  const [stdin, setStdin] = useState('');
  const [status, setStatus] = useState<ExecutionStatus>('idle');
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showStdin, setShowStdin] = useState(false);

  const handleRun = useCallback(async () => {
    setStatus('running');
    setError(null);
    setResult(null);
    try {
      const resp = await api.post('/sandbox/execute', {
        code,
        language,
        stdin: stdin || undefined,
      });
      const data = resp.data as ExecutionResult;
      setResult(data);
      setStatus(data.exit_code === 0 ? 'success' : 'failed');
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        (err instanceof Error ? err.message : '执行失败');
      setError(msg);
      setStatus('failed');
    }
  }, [code, language, stdin]);

  const handleLanguageChange = useCallback(
    (newLang: 'python' | 'r') => {
      setLanguage(newLang);
      // 切换语言时若无自定义代码则载入默认模板
      if (!defaultCode) {
        setCode(newLang === 'python' ? DEFAULT_CODE_PYTHON : DEFAULT_CODE_R);
      }
    },
    [defaultCode]
  );

  const monacoLang =
    LANGUAGE_OPTIONS.find((o) => o.value === language)?.monacoLang ?? 'python';

  return (
    <div className="flex flex-col h-full border border-gray-200 rounded-lg overflow-hidden bg-white">
      {/* 工具栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-gray-500" />
          <select
            value={language}
            onChange={(e) => handleLanguageChange(e.target.value as 'python' | 'r')}
            disabled={readOnly}
            className="text-xs border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-primary-400"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleRun}
          disabled={status === 'running' || readOnly}
          className={clsx(
            'flex items-center gap-1 px-3 py-1 rounded text-xs font-medium transition-colors',
            status === 'running'
              ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
              : 'bg-primary-600 text-white hover:bg-primary-700'
          )}
        >
          {status === 'running' ? (
            <>
              <Square className="w-3 h-3" /> 运行中
            </>
          ) : (
            <>
              <Play className="w-3 h-3" /> 运行
            </>
          )}
        </button>
      </div>

      {/* Monaco 编辑器 */}
      <div style={{ minHeight: minHeight / 2 }}>
        <Editor
          language={monacoLang}
          value={code}
          onChange={(val) => setCode(val ?? '')}
          theme="vs-dark"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            tabSize: 4,
            readOnly,
            automaticLayout: true,
          }}
        />
      </div>

      {/* stdin 输入（可折叠） */}
      <div className="border-t border-gray-200">
        <button
          onClick={() => setShowStdin(!showStdin)}
          className="w-full flex items-center gap-1 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
        >
          <Terminal className="w-3 h-3" />
          标准输入 (stdin)
          {stdin && <span className="text-gray-400">· {stdin.length} 字符</span>}
        </button>
        {showStdin && (
          <textarea
            value={stdin}
            onChange={(e) => setStdin(e.target.value)}
            placeholder="输入标准输入内容..."
            className="w-full px-3 py-2 text-xs font-mono border-t border-gray-100 focus:outline-none focus:ring-1 focus:ring-primary-400"
            rows={3}
          />
        )}
      </div>

      {/* 输出区 */}
      <div className="border-t border-gray-200 flex-1">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border-b border-gray-100">
          {status === 'idle' && <span className="text-xs text-gray-400">等待执行</span>}
          {status === 'running' && (
            <>
              <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />
              <span className="text-xs text-blue-600">执行中...</span>
            </>
          )}
          {status === 'success' && (
            <>
              <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
              <span className="text-xs text-green-600">
                执行成功{result?.duration_ms ? ` · ${result.duration_ms}ms` : ''}
              </span>
            </>
          )}
          {status === 'failed' && (
            <>
              <AlertCircle className="w-3.5 h-3.5 text-red-500" />
              <span className="text-xs text-red-600">
                执行失败{result?.exit_code ? ` · exit ${result.exit_code}` : ''}
              </span>
            </>
          )}
        </div>

        {error && (
          <div className="px-3 py-2 text-xs text-red-600 bg-red-50 border-b border-red-100">
            {error}
          </div>
        )}

        {result && (
          <div className="px-3 py-2 space-y-2 overflow-auto" style={{ maxHeight: minHeight / 2 }}>
            {result.stdout && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">stdout</div>
                <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap break-all bg-gray-50 p-2 rounded">
                  {result.stdout}
                </pre>
              </div>
            )}
            {result.stderr && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-red-500 mb-1">stderr</div>
                <pre className="text-xs font-mono text-red-700 whitespace-pre-wrap break-all bg-red-50 p-2 rounded">
                  {result.stderr}
                </pre>
              </div>
            )}
            {!result.stdout && !result.stderr && (
              <div className="text-xs text-gray-400 italic">无输出</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
