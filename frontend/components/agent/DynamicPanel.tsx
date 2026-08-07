'use client';

import { useMemo } from 'react';
import { Database, Target, Atom, FileText, BarChart3, Code2 } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ToolResult } from '@/types/agent';
import { ChartRenderer } from './ChartRenderer';

interface DynamicPanelProps {
  result: ToolResult | null;
}

/** 根据工具名 + display + 数据特征推断展示类型 */
function inferRenderType(
  tool: string,
  data: unknown,
  display?: { type?: string; payload?: unknown }
):
  | 'molecule'
  | 'target'
  | 'chart'
  | 'document'
  | 'code'
  | 'json'
  | 'empty' {
  if (!data) return 'empty';

  // 优先：服务端 display.type 明确指定渲染类型
  if (display?.type === 'chart') return 'chart';
  if (display?.type === 'table') return 'json';

  // 按工具名推断
  if (tool.includes('molecule') || tool.includes('design')) return 'molecule';
  if (tool.includes('target') || tool.includes('discover')) return 'target';
  if (tool.includes('visualize') || tool.includes('chart')) return 'chart';
  if (tool.includes('analyze_dataset')) return 'chart';
  if (tool.includes('search') || tool.includes('literature') || tool.includes('knowledge'))
    return 'document';

  // 按数据特征推断
  if (typeof data === 'string' && data.includes('def ')) return 'code';
  if (typeof data === 'object' && (data as any)?.smiles) return 'molecule';
  if (typeof data === 'object' && (data as any)?.gene_symbol) return 'target';
  // 数据中含 chart_type 字段 → 视为图表 spec
  if (typeof data === 'object' && (data as any)?.chart_type) return 'chart';

  return 'json';
}

function MoleculeView({ data }: { data: unknown }) {
  const d = data as { smiles?: string; molecule_id?: string; score?: number };
  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500">SMILES</div>
      <div className="font-mono text-xs bg-gray-50 p-2 rounded break-all">
        {d.smiles ?? '—'}
      </div>
      {d.score != null && (
        <div className="text-xs">
          <span className="text-gray-500">评分：</span>
          <span className="font-medium text-green-600">{d.score.toFixed(3)}</span>
        </div>
      )}
      {/* TODO: 接入 RDKit.js 渲染结构图 */}
      <div className="h-32 flex items-center justify-center bg-gray-50 rounded text-xs text-gray-400">
        分子结构图（待接入 RDKit.js）
      </div>
    </div>
  );
}

function TargetView({ data }: { data: unknown }) {
  const d = data as {
    gene_symbol?: string;
    confidence?: number;
    evidence_grade?: string;
    description?: string;
  };
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="w-10 h-10 rounded-lg bg-red-50 flex items-center justify-center">
          <Target className="w-5 h-5 text-red-500" />
        </div>
        <div>
          <div className="font-semibold text-gray-900">{d.gene_symbol ?? '未知靶点'}</div>
          {d.evidence_grade && (
            <div className="text-xs text-gray-500">证据等级：{d.evidence_grade}</div>
          )}
        </div>
      </div>
      {d.confidence != null && (
        <div className="text-xs">
          <div className="flex items-center justify-between mb-1">
            <span className="text-gray-500">置信度</span>
            <span className="font-medium">{(d.confidence * 100).toFixed(1)}%</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-500"
              style={{ width: `${d.confidence * 100}%` }}
            />
          </div>
        </div>
      )}
      {d.description && (
        <div className="text-xs text-gray-700 leading-relaxed">{d.description}</div>
      )}
    </div>
  );
}

function DocumentView({ data }: { data: unknown }) {
  const docs = Array.isArray(data) ? data : [data];
  return (
    <div className="space-y-2 max-h-96 overflow-y-auto">
      {docs.map((doc, i) => {
        const d = doc as { text?: string; title?: string; similarity?: number; source?: string };
        return (
          <div key={i} className="border border-gray-200 rounded p-2">
            <div className="flex items-center justify-between mb-1">
              <div className="text-xs font-medium text-gray-700 truncate">
                {d.title ?? `文档 ${i + 1}`}
              </div>
              {d.similarity != null && (
                <span className="text-[10px] text-gray-400">
                  {(d.similarity * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <div className="text-xs text-gray-600 line-clamp-3">{d.text}</div>
            {d.source && (
              <div className="text-[10px] text-gray-400 mt-1">来源：{d.source}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function JsonView({ data }: { data: unknown }) {
  return (
    <SyntaxHighlighter
      language="json"
      style={oneDark}
      customStyle={{ fontSize: '11px', padding: '8px', margin: 0, maxHeight: '400px' }}
    >
      {JSON.stringify(data, null, 2)}
    </SyntaxHighlighter>
  );
}

function CodeView({ data }: { data: unknown }) {
  const code = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  return (
    <SyntaxHighlighter
      language="python"
      style={oneDark}
      customStyle={{ fontSize: '11px', padding: '8px', margin: 0, maxHeight: '400px' }}
    >
      {code}
    </SyntaxHighlighter>
  );
}

export function DynamicPanel({ result }: DynamicPanelProps) {
  const renderType = useMemo(
    () =>
      result?.success
        ? inferRenderType(result.tool, result.data, result.display)
        : 'empty',
    [result]
  );

  const Icon =
    renderType === 'molecule'
      ? Atom
      : renderType === 'target'
      ? Target
      : renderType === 'document'
      ? FileText
      : renderType === 'chart'
      ? BarChart3
      : renderType === 'code'
      ? Code2
      : Database;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 bg-white">
        <Icon className="w-4 h-4 text-primary-600" />
        <h3 className="text-sm font-semibold text-gray-800">动态结果面板</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {!result || !result.success ? (
          <div className="text-center py-12 text-gray-400">
            <Database className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-xs">
              {result?.error
                ? `工具执行失败：${result.error}`
                : '工具调用结果将在此处动态展示'}
            </p>
          </div>
        ) : (
          <>
            <div className="mb-3 text-xs text-gray-500 flex items-center justify-between">
              <span>
                工具：<span className="font-mono">{result.tool}</span>
              </span>
              {result.duration_ms != null && <span>{result.duration_ms}ms</span>}
            </div>
            {renderType === 'molecule' && <MoleculeView data={result.data} />}
            {renderType === 'target' && <TargetView data={result.data} />}
            {renderType === 'document' && <DocumentView data={result.data} />}
            {renderType === 'chart' && (
              <ChartRenderer
                spec={(result.display?.payload as any) || (result.data as any)}
              />
            )}
            {renderType === 'code' && <CodeView data={result.data} />}
            {renderType === 'json' && <JsonView data={result.data} />}
          </>
        )}
      </div>
    </div>
  );
}
