'use client';

import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import clsx from 'clsx';

interface JsonViewerProps {
  data: any;
  className?: string;
  /** 关键字段高亮（如 score, confidence, status） */
  highlightKeys?: string[];
  /** 最大展开层级，默认 3 */
  maxLevel?: number;
}

const HIGHLIGHT_KEYS = new Set([
  'score', 'confidence', 'confidence_score', 'status', 'success',
  'druglikeness_score', 'efficacy_score', 'risk_score',
  'evidence_grade', 'p_value', 'ic50', 'ec50',
]);

export default function JsonViewer({
  data,
  className,
  highlightKeys = [],
  maxLevel = 3,
}: JsonViewerProps) {
  const highlightSet = new Set([...HIGHLIGHT_KEYS, ...highlightKeys]);

  const renderValue = (value: any, level: number, key?: string): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span className="text-gray-400 italic">null</span>;
    }
    if (typeof value === 'boolean') {
      return <span className="text-purple-600">{String(value)}</span>;
    }
    if (typeof value === 'number') {
      const isHighlight = key && highlightSet.has(key.toLowerCase());
      return (
        <span className={isHighlight ? 'text-green-600 font-semibold' : 'text-blue-600'}>
          {Number.isInteger(value) ? value : value.toFixed(4)}
        </span>
      );
    }
    if (typeof value === 'string') {
      if (key && highlightSet.has(key.toLowerCase())) {
        return <span className="text-green-600 font-semibold">"{value}"</span>;
      }
      if (value.length > 100) {
        return <span className="text-amber-700">"{value.slice(0, 100)}..."</span>;
      }
      return <span className="text-amber-700">"{value}"</span>;
    }
    if (Array.isArray(value)) {
      return <JsonArray items={value} level={level} maxLevel={maxLevel} highlightSet={highlightSet} keyName={key} />;
    }
    if (typeof value === 'object') {
      return <JsonObject obj={value} level={level} maxLevel={maxLevel} highlightSet={highlightSet} keyName={key} />;
    }
    return <span>{String(value)}</span>;
  };

  return (
    <div className={clsx('font-mono text-xs leading-relaxed', className)}>
      {renderValue(data, 0)}
    </div>
  );
}

function JsonObject({
  obj,
  level,
  maxLevel,
  highlightSet,
  keyName,
}: {
  obj: Record<string, any>;
  level: number;
  maxLevel: number;
  highlightSet: Set<string>;
  keyName?: string;
}) {
  const [expanded, setExpanded] = useState(level < maxLevel);
  const keys = Object.keys(obj);
  const isCollapsible = level >= 1 && keys.length > 0;

  if (!isCollapsible || expanded) {
    return (
      <span>
        <span className="text-gray-500">{'{'}</span>
        <div className="ml-4">
          {keys.map((k, i) => (
            <div key={k} className="flex">
              <span className="text-indigo-600 shrink-0">"{k}"</span>
              <span className="text-gray-400 mx-1 shrink-0">:</span>
              <span className="break-all">
                {renderNestedValue(obj[k], level + 1, maxLevel, highlightSet, k)}
              </span>
              {i < keys.length - 1 && <span className="text-gray-400">,</span>}
            </div>
          ))}
        </div>
        <span className="text-gray-500">{'}'}</span>
      </span>
    );
  }

  return (
    <span>
      <button
        onClick={() => setExpanded(true)}
        className="inline-flex items-center hover:bg-gray-100 rounded px-1"
      >
        <ChevronRight className="w-3 h-3 text-gray-400" />
        <span className="text-gray-500 ml-1">
          {keyName ? `"${keyName}": ` : ''}{`{${keys.length} keys}`}
        </span>
      </button>
    </span>
  );
}

function JsonArray({
  items,
  level,
  maxLevel,
  highlightSet,
  keyName,
}: {
  items: any[];
  level: number;
  maxLevel: number;
  highlightSet: Set<string>;
  keyName?: string;
}) {
  const [expanded, setExpanded] = useState(level < maxLevel);
  const isCollapsible = level >= 1 && items.length > 0;

  // 如果是对象数组，尝试表格化展示
  if (expanded && items.length > 0 && typeof items[0] === 'object' && !Array.isArray(items[0])) {
    const columns: string[] = Array.from(
      items.reduce<Set<string>>((set, item) => {
        Object.keys(item || {}).forEach((k) => set.add(k));
        return set;
      }, new Set<string>())
    ).slice(0, 8); // 最多 8 列

    if (columns.length > 0) {
      return (
        <span>
          <span className="text-gray-500">[</span>
          <div className="overflow-x-auto my-1">
            <table className="text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-300">
                  {columns.map((col) => (
                    <th key={col} className="text-left py-1 px-2 text-indigo-600 font-semibold whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <tr key={idx} className="border-b border-gray-100">
                    {columns.map((col) => (
                      <td key={col} className="py-1 px-2 align-top">
                        {item?.[col] !== undefined
                          ? renderNestedValue(item[col], level + 1, maxLevel, highlightSet, col)
                          : <span className="text-gray-300">—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <span className="text-gray-500">]</span>
        </span>
      );
    }
  }

  if (!isCollapsible || expanded) {
    return (
      <span>
        <span className="text-gray-500">[</span>
        <div className="ml-4">
          {items.map((item, i) => (
            <div key={i} className="flex">
              <span className="text-gray-400 mr-1 shrink-0">{i}:</span>
              <span className="break-all">
                {renderNestedValue(item, level + 1, maxLevel, highlightSet)}
              </span>
              {i < items.length - 1 && <span className="text-gray-400">,</span>}
            </div>
          ))}
        </div>
        <span className="text-gray-500">]</span>
      </span>
    );
  }

  return (
    <button
      onClick={() => setExpanded(true)}
      className="inline-flex items-center hover:bg-gray-100 rounded px-1"
    >
      <ChevronRight className="w-3 h-3 text-gray-400" />
      <span className="text-gray-500 ml-1">
        {keyName ? `"${keyName}": ` : ''}{`[${items.length} items]`}
      </span>
    </button>
  );
}

function renderNestedValue(
  value: any,
  level: number,
  maxLevel: number,
  highlightSet: Set<string>,
  key?: string
): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className="text-gray-400 italic">null</span>;
  }
  if (typeof value === 'boolean') {
    return <span className="text-purple-600">{String(value)}</span>;
  }
  if (typeof value === 'number') {
    const isHighlight = key && highlightSet.has(key.toLowerCase());
    return (
      <span className={isHighlight ? 'text-green-600 font-semibold' : 'text-blue-600'}>
        {Number.isInteger(value) ? value : Number(value).toFixed(4)}
      </span>
    );
  }
  if (typeof value === 'string') {
    if (key && highlightSet.has(key.toLowerCase())) {
      return <span className="text-green-600 font-semibold">"{value}"</span>;
    }
    return <span className="text-amber-700">"{value}"</span>;
  }
  if (Array.isArray(value)) {
    return <JsonArray items={value} level={level} maxLevel={maxLevel} highlightSet={highlightSet} keyName={key} />;
  }
  if (typeof value === 'object') {
    return <JsonObject obj={value} level={level} maxLevel={maxLevel} highlightSet={highlightSet} keyName={key} />;
  }
  return <span>{String(value)}</span>;
}
