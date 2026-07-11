'use client';

import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import Card from '@/components/ui/Card';
import type { AnalysisResult } from '@/types/chat';

interface AnalysisResultCardProps {
  analysis: AnalysisResult | null;
}

export function AnalysisResultCard({ analysis }: AnalysisResultCardProps) {
  if (!analysis) return null;

  return (
    <Card title="深度分析报告">
      <div className="space-y-3">
        {analysis.report && (
          <div className="markdown-body">
            <ReactMarkdown>{analysis.report}</ReactMarkdown>
          </div>
        )}
        {analysis.conclusion && (
          <div className="bg-blue-50 p-3 rounded text-sm">
            <strong>结论：</strong>
            {analysis.conclusion}
          </div>
        )}
        {analysis.code && (
          <SyntaxHighlighter language="python" style={oneDark}>
            {analysis.code}
          </SyntaxHighlighter>
        )}
        {analysis.references && (
          <div className="text-xs">
            <strong>参考文献：</strong>
            {analysis.references.map((r, i) => (
              <div key={i}>{typeof r === 'string' ? r : r.title}</div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
