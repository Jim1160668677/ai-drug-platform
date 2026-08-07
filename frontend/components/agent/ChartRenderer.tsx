'use client';

/**
 * 通用图表渲染器 — 将工具返回的 chart spec 渲染为 Plotly 图表
 *
 * 支持的 chart_type: scatter / bar / line / heatmap / pie / violin / box
 * 兼容两種数据格式：
 *   1. { chart_type, title, data: [{x,y,...}], x_field, y_field }   ← VisualizeDataTool
 *   2. 任意 BioAnalyzer.plot_data 结构（自动推断）                    ← AnalyzeDatasetTool
 */
import { useMemo } from 'react';
import dynamic from 'next/dynamic';
import { BarChart3, AlertCircle } from 'lucide-react';

// Plotly 依赖 window，必须客户端动态加载避免 SSR
// 使用 factory 模式适配 plotly.js-dist-min（项目已安装）
const Plot = dynamic(() => import('./plotly-loader'), {
  ssr: false,
  loading: () => (
    <div className="h-64 flex items-center justify-center text-xs text-gray-400">
      图表加载中...
    </div>
  ),
});

export interface ChartSpec {
  chart_type?: string;
  title?: string;
  data?: unknown[];
  x_field?: string;
  y_field?: string;
  [key: string]: unknown;
}

interface ChartRendererProps {
  spec: ChartSpec | null | undefined;
}

/** 提取数组数据中的字段值 */
function pluck(arr: unknown[], field: string): unknown[] {
  return arr.map((item) => (item && typeof item === 'object' ? (item as Record<string, unknown>)[field] : undefined));
}

/** 判断是否为数值数组 */
function isNumericArray(arr: unknown[]): boolean {
  return arr.filter((v) => typeof v === 'number').length >= Math.max(1, arr.length / 2);
}

/** 根据 spec 构建 Plotly data + layout */
function buildPlotlyConfig(spec: ChartSpec) {
  const chartType = (spec.chart_type || 'bar').toLowerCase();
  const rawData = Array.isArray(spec.data) ? spec.data : [];
  const xField = spec.x_field || 'x';
  const yField = spec.y_field || 'y';

  // 兼容：直接传入 plot_data 的 traces（BioAnalyzer 已构造好 Plotly traces）
  if (Array.isArray(spec.traces) && spec.traces.length > 0) {
    return {
      data: spec.traces,
      layout: {
        title: spec.title || '',
        autosize: true,
        margin: { l: 50, r: 20, t: spec.title ? 40 : 20, b: 50 },
        ...((spec.layout as object) || {}),
      },
    };
  }

  // 兼容：data 是 { x: [...], y: [...] } 形式（Plotly 原生）
  if (rawData.length === 0 && Array.isArray(spec.x) && Array.isArray(spec.y)) {
    return {
      data: [{ type: chartType, x: spec.x, y: spec.y, mode: chartType === 'scatter' ? 'markers' : undefined }],
      layout: { title: spec.title || '', autosize: true, margin: { l: 50, r: 20, t: 40, b: 50 } },
    };
  }

  // 通用：data 是对象数组，按字段提取
  const xs = pluck(rawData, xField);
  const ys = pluck(rawData, yField);

  let trace: Record<string, unknown>;
  switch (chartType) {
    case 'scatter':
      trace = { type: 'scatter', mode: 'markers', x: xs, y: ys, marker: { size: 8, color: '#6366f1' } };
      break;
    case 'line':
      trace = { type: 'scatter', mode: 'lines+markers', x: xs, y: ys, line: { color: '#6366f1' } };
      break;
    case 'bar':
      trace = { type: 'bar', x: xs, y: ys, marker: { color: '#6366f1' } };
      break;
    case 'pie': {
      const labels = pluck(rawData, xField);
      const values = pluck(rawData, yField).map((v) => (typeof v === 'number' ? v : 0));
      trace = { type: 'pie', labels, values };
      break;
    }
    case 'heatmap': {
      // 热图：尝试从 z 字段或构造二维
      const z = (spec.z as number[][]) || (Array.isArray(spec.matrix) ? spec.matrix : undefined);
      if (z) {
        trace = { type: 'heatmap', z };
      } else {
        trace = { type: 'heatmap', x: xs, y: ys, z: ys.map((v) => (typeof v === 'number' ? [v] : [0])) };
      }
      break;
    }
    case 'violin':
      trace = { type: 'violin', x: xs, y: ys, points: 'all' };
      break;
    case 'box':
      trace = { type: 'box', x: xs, y: ys };
      break;
    default:
      trace = { type: 'bar', x: xs, y: ys };
  }

  const layout = {
    title: spec.title || '',
    autosize: true,
    margin: { l: 50, r: 20, t: spec.title ? 40 : 20, b: 50 },
    xaxis: { title: xField },
    yaxis: { title: yField },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { size: 11 },
  };

  return { data: [trace], layout };
}

export function ChartRenderer({ spec }: ChartRendererProps) {
  const config = useMemo(() => (spec ? buildPlotlyConfig(spec) : null), [spec]);

  if (!spec || !config) {
    return (
      <div className="text-center text-xs text-gray-400 py-8 flex flex-col items-center gap-2">
        <BarChart3 className="w-8 h-8 opacity-40" />
        <span>暂无可视化数据</span>
      </div>
    );
  }

  // 数据校验
  const hasData =
    (config.data && Array.isArray(config.data) && config.data.length > 0) ||
    (Array.isArray(spec.data) && spec.data.length > 0);

  if (!hasData) {
    return (
      <div className="text-center text-xs text-amber-600 py-6 flex flex-col items-center gap-2 bg-amber-50 rounded">
        <AlertCircle className="w-6 h-6" />
        <span>分析完成，但无足够数据生成图表</span>
      </div>
    );
  }

  return (
    <div className="w-full">
      <Plot
        data={config.data as any}
        layout={config.layout as any}
        config={{ displaylogo: false, responsive: true, displayModeBar: false }}
        useResizeHandler
        style={{ width: '100%', height: 360 }}
      />
    </div>
  );
}

export default ChartRenderer;
