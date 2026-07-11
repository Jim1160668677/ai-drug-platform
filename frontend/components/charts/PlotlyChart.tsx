'use client';

import dynamic from 'next/dynamic';
import { ComponentProps } from 'react';

// 使用 factory 模式绑定已安装的 plotly.js-dist-min，避免 react-plotly.js
// 默认 import 'plotly.js/dist/plotly'（需 plotly.js 完整包）导致的 Module not found。
const Plot = dynamic(
  () =>
    Promise.all([import('react-plotly.js/factory'), import('plotly.js-dist-min')]).then(
      ([factoryMod, plotlyMod]) => factoryMod.default(plotlyMod.default)
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        图表加载中...
      </div>
    ),
  }
);

type PlotProps = ComponentProps<typeof Plot>;

export default function PlotlyChart(props: PlotProps) {
  return (
    <Plot
      config={{ displayModeBar: false, responsive: true, ...props.config }}
      style={{ width: '100%', height: '100%', minHeight: '300px', ...props.style }}
      {...props}
    />
  );
}
