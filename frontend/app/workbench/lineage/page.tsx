'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GitBranch, Search, ArrowDown, ArrowUp, Network } from 'lucide-react';
import { getDAG } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import PlotlyChart from '@/components/charts/PlotlyChart';

const NODE_TYPES = [
  { value: 'dataset', label: '数据集', color: '#2563eb' },
  { value: 'target', label: '靶点', color: '#9333ea' },
  { value: 'molecule', label: '分子', color: '#16a34a' },
  { value: 'treatment', label: '治疗方案', color: '#d97706' },
];

const TYPE_COLOR: Record<string, string> = Object.fromEntries(NODE_TYPES.map((t) => [t.value, t.color]));

export default function LineagePage() {
  const { currentProject } = useAppStore();
  const [nodeType, setNodeType] = useState('dataset');
  const [nodeId, setNodeId] = useState('');
  const [depth, setDepth] = useState(3);
  const [searchKey, setSearchKey] = useState(0);

  const { data: dag, isLoading, isError, refetch } = useQuery({
    queryKey: ['lineage-dag', currentProject?.id, nodeType, nodeId, depth, searchKey],
    queryFn: () => getDAG(currentProject!.id, nodeType, nodeId, depth),
    enabled: !!currentProject && !!nodeId && searchKey > 0,
  });

  const handleSearch = () => {
    if (nodeId.trim()) setSearchKey((k) => k + 1);
  };

  // 构建 Plotly 散点图数据
  const chartData = (() => {
    if (!dag || !dag.nodes || dag.nodes.length === 0) return null;

    const nodes = dag.nodes;
    const nodeMap = new Map(nodes.map((n) => [`${n.type}:${n.id}`, n]));

    // 按深度分配 Y 坐标，同层节点分散在 X 轴
    const depthGroups: Record<number, typeof nodes> = {};
    nodes.forEach((n) => {
      const d = n.direction === 'upstream' ? -n.depth : n.direction === 'downstream' ? n.depth : 0;
      if (!depthGroups[d]) depthGroups[d] = [];
      depthGroups[d].push(n);
    });

    const traces: any[] = [];

    // 节点散点
    NODE_TYPES.forEach((nt) => {
      const typeNodes = nodes.filter((n) => n.type === nt.value);
      if (typeNodes.length === 0) return;

      const xs: number[] = [];
      const ys: number[] = [];
      const texts: string[] = [];

      typeNodes.forEach((n) => {
        const d = n.direction === 'upstream' ? -n.depth : n.direction === 'downstream' ? n.depth : 0;
        const sameDepth = depthGroups[d] || [];
        const idx = sameDepth.indexOf(n);
        xs.push(idx - (sameDepth.length - 1) / 2);
        ys.push(d);
        texts.push(`${nt.label}: ${n.id.slice(0, 8)}...`);
      });

      traces.push({
        type: 'scatter',
        mode: 'markers+text',
        x: xs,
        y: ys,
        text: texts,
        textposition: 'top center',
        marker: { size: 20, color: nt.color },
        name: nt.label,
        hovertemplate: '%{text}<extra></extra>',
      });
    });

    // 边连线
    if (dag.edges && dag.edges.length > 0) {
      const edgeX: number[] = [];
      const edgeY: number[] = [];

      dag.edges.forEach((e) => {
        const sourceNode = nodeMap.get(e.source);
        const targetNode = nodeMap.get(e.target);
        if (sourceNode && targetNode) {
          const sd = sourceNode.direction === 'upstream' ? -sourceNode.depth : sourceNode.direction === 'downstream' ? sourceNode.depth : 0;
          const td = targetNode.direction === 'upstream' ? -targetNode.depth : targetNode.direction === 'downstream' ? targetNode.depth : 0;
          const sIdx = (depthGroups[sd] || []).indexOf(sourceNode);
          const tIdx = (depthGroups[td] || []).indexOf(targetNode);
          const sx = sIdx - ((depthGroups[sd] || []).length - 1) / 2;
          const tx = tIdx - ((depthGroups[td] || []).length - 1) / 2;
          edgeX.push(sx, tx, null);
          edgeY.push(sd, td, null);
        }
      });

      if (edgeX.length > 0) {
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x: edgeX,
          y: edgeY,
          line: { color: '#cbd5e1', width: 1.5, dash: 'dot' },
          showlegend: false,
          hoverinfo: 'skip',
        });
      }
    }

    return traces;
  })();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">数据血缘追踪</h1>
        <p className="text-sm text-gray-500 mt-1">追踪数据从原始数据集到治疗方案的完整流转链路</p>
      </div>

      <Card title="查询条件">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">节点类型</label>
            <select
              value={nodeType}
              onChange={(e) => setNodeType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              {NODE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">节点 ID</label>
            <input
              type="text"
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              placeholder="输入节点 UUID"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">遍历深度: {depth}</label>
            <input
              type="range"
              min={1}
              max={5}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="flex items-end">
            <Button onClick={handleSearch} className="w-full">
              <Search className="w-4 h-4" /> 查询
            </Button>
          </div>
        </div>
      </Card>

      {isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-600 mb-3">数据加载失败</p>
          <button onClick={() => refetch()} className="text-xs text-primary-600 underline">重试</button>
        </div>
      ) : isLoading ? (
        <Card>
          <div className="text-center py-12 text-gray-400">加载中...</div>
        </Card>
      ) : dag ? (
        <div className="space-y-4">
          <Card title="DAG 可视化" action={
            <div className="flex gap-3 text-xs text-gray-500">
              <span>节点: {dag.node_count}</span>
              <span>边: {dag.edge_count}</span>
            </div>
          }>
            {chartData ? (
              <PlotlyChart
                data={chartData}
                layout={{
                  margin: { t: 20, b: 40, l: 40, r: 20 },
                  height: 400,
                  xaxis: { showgrid: false, zeroline: false, showticklabels: false },
                  yaxis: { title: { text: '深度' }, dtick: 1, zeroline: true, zerolinewidth: 2, zerolinecolor: '#e2e8f0' },
                  showlegend: true,
                  legend: { font: { size: 10 }, orientation: 'h', y: -0.2 },
                }}
              />
            ) : (
              <div className="text-center py-8 text-gray-400 text-sm">无可视化数据</div>
            )}
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card title="上游节点（数据来源）">
              <div className="space-y-2">
                {dag.nodes.filter((n) => n.direction === 'upstream').length > 0 ? (
                  dag.nodes.filter((n) => n.direction === 'upstream').map((n, i) => (
                    <div key={i} className="flex items-center gap-2 p-2 bg-blue-50 rounded text-sm">
                      <ArrowUp className="w-3 h-3 text-blue-500" />
                      <span className="px-2 py-0.5 rounded text-xs font-medium" style={{ backgroundColor: TYPE_COLOR[n.type] + '20', color: TYPE_COLOR[n.type] }}>
                        {n.type}
                      </span>
                      <span className="text-gray-600 font-mono text-xs">{n.id.slice(0, 12)}...</span>
                      <span className="text-gray-400 text-xs ml-auto">深度 {n.depth}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-4 text-gray-400 text-sm">无上游节点</div>
                )}
              </div>
            </Card>

            <Card title="下游节点（数据去向）">
              <div className="space-y-2">
                {dag.nodes.filter((n) => n.direction === 'downstream').length > 0 ? (
                  dag.nodes.filter((n) => n.direction === 'downstream').map((n, i) => (
                    <div key={i} className="flex items-center gap-2 p-2 bg-emerald-50 rounded text-sm">
                      <ArrowDown className="w-3 h-3 text-emerald-500" />
                      <span className="px-2 py-0.5 rounded text-xs font-medium" style={{ backgroundColor: TYPE_COLOR[n.type] + '20', color: TYPE_COLOR[n.type] }}>
                        {n.type}
                      </span>
                      <span className="text-gray-600 font-mono text-xs">{n.id.slice(0, 12)}...</span>
                      <span className="text-gray-400 text-xs ml-auto">深度 {n.depth}</span>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-4 text-gray-400 text-sm">无下游节点</div>
                )}
              </div>
            </Card>
          </div>

          {dag.edges && dag.edges.length > 0 && (
            <Card title="转换关系">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-2 py-1 text-left border-b">来源</th>
                      <th className="px-2 py-1 text-left border-b">目标</th>
                      <th className="px-2 py-1 text-left border-b">转换</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dag.edges.filter((e) => e.source && e.target).slice(0, 10).map((e, i) => (
                      <tr key={i} className="border-b border-gray-100">
                        <td className="px-2 py-1 font-mono text-gray-600">{e.source.slice(0, 16)}...</td>
                        <td className="px-2 py-1 font-mono text-gray-600">{e.target.slice(0, 16)}...</td>
                        <td className="px-2 py-1">
                          <span className="px-2 py-0.5 bg-primary-100 text-primary-800 rounded text-xs">{e.transformation}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {dag.edges.length > 10 && (
                  <div className="text-xs text-gray-400 mt-1">显示前 10 条，共 {dag.edges.length} 条</div>
                )}
              </div>
            </Card>
          )}
        </div>
      ) : (
        <Card>
          <div className="text-center py-12 text-gray-400">
            <Network className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <div className="text-sm">输入节点 ID 并点击"查询"查看数据血缘关系</div>
            <div className="text-xs mt-1">典型链路：数据集 → 靶点 → 分子 → 治疗方案</div>
          </div>
        </Card>
      )}
    </div>
  );
}
