'use client';

/**
 * PoseValidationPanel — 结合姿态坐标验证面板
 *
 * 对分子对接输出的结合姿态坐标进行结构化验证和展示：
 *   - 原子总数 / 重原子数
 *   - 坐标范围（X/Y/Z 三轴的 min/max）
 *   - 质心坐标
 *   - 是否在对接盒子内（box center ± size/2 范围校验）
 *   - 坐标系统一致性（NaN/Inf 检测）
 *   - RMSD 值（若提供）
 *
 * 用法：
 *   <PoseValidationPanel coordinates={coords} boxCenter={[0,0,0]} boxSize={[20,20,20]} rmsd={1.2} />
 */

import { useMemo } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Ruler, Crosshair } from 'lucide-react';

export interface PoseValidationPanelProps {
  /** 原子坐标数组 [[x,y,z], ...] */
  coordinates: number[][];
  /** 对接盒子中心 [x, y, z] */
  boxCenter?: number[];
  /** 对接盒子尺寸 [x, y, z] */
  boxSize?: number[];
  /** RMSD 值（Å） */
  rmsd?: number;
  /** 原子总数 */
  atomCount?: number;
  /** 重原子数 */
  heavyAtomCount?: number;
}

interface AxisRange {
  min: number;
  max: number;
  span: number;
}

export default function PoseValidationPanel({
  coordinates,
  boxCenter,
  boxSize,
  rmsd,
  atomCount,
  heavyAtomCount,
}: PoseValidationPanelProps) {
  const validation = useMemo(() => {
    if (!coordinates || coordinates.length === 0) {
      return null;
    }

    // 检测 NaN/Inf
    const hasInvalid = coordinates.some((coord) =>
      coord.some((v) => !Number.isFinite(v)),
    );

    // 计算三轴范围
    const xs = coordinates.map((c) => c[0]);
    const ys = coordinates.map((c) => c[1]);
    const zs = coordinates.map((c) => c[2]);

    const computeRange = (vals: number[]): AxisRange => {
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      return { min, max, span: max - min };
    };

    const xRange = computeRange(xs);
    const yRange = computeRange(ys);
    const zRange = computeRange(zs);

    // 质心
    const n = coordinates.length;
    const centroid = [
      xs.reduce((a, b) => a + b, 0) / n,
      ys.reduce((a, b) => a + b, 0) / n,
      zs.reduce((a, b) => a + b, 0) / n,
    ];

    // 对接盒子内校验
    let inBox = true;
    let outOfBoxCount = 0;
    if (boxCenter && boxSize) {
      const bounds = boxCenter.map((c, i) => ({
        min: c - boxSize[i] / 2,
        max: c + boxSize[i] / 2,
      }));
      for (const coord of coordinates) {
        const outside = coord.some(
          (v, i) => v < bounds[i].min || v > bounds[i].max,
        );
        if (outside) {
          outOfBoxCount++;
          inBox = false;
        }
      }
    }

    return {
      hasInvalid,
      xRange,
      yRange,
      zRange,
      centroid,
      inBox,
      outOfBoxCount,
      totalAtoms: coordinates.length,
    };
  }, [coordinates, boxCenter, boxSize]);

  if (!validation) {
    return (
      <div className="bg-white border rounded-lg p-4 text-sm text-gray-500">
        无坐标数据可供验证
      </div>
    );
  }

  const axes = [
    { label: 'X', range: validation.xRange, color: 'text-red-600' },
    { label: 'Y', range: validation.yRange, color: 'text-green-600' },
    { label: 'Z', range: validation.zRange, color: 'text-blue-600' },
  ];

  return (
    <div className="bg-white border rounded-lg p-4 space-y-4">
      <h3 className="font-semibold flex items-center gap-2">
        <Ruler className="w-4 h-4 text-primary-600" />
        结合姿态坐标验证
      </h3>

      {/* 一致性校验 */}
      <div className="space-y-1.5">
        <div className="text-xs font-medium text-gray-500">坐标系统一致性</div>
        {validation.hasInvalid ? (
          <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
            <XCircle className="w-4 h-4" />
            检测到 NaN/Inf 坐标值，坐标系统异常
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1">
            <CheckCircle2 className="w-4 h-4" />
            所有坐标值有效（无 NaN/Inf）
          </div>
        )}
      </div>

      {/* 原子统计 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div className="bg-gray-50 rounded p-2">
          <div className="text-gray-500">坐标点数</div>
          <div className="font-bold text-gray-800">{validation.totalAtoms}</div>
        </div>
        {atomCount != null && (
          <div className="bg-gray-50 rounded p-2">
            <div className="text-gray-500">原子总数</div>
            <div className="font-bold text-gray-800">{atomCount}</div>
          </div>
        )}
        {heavyAtomCount != null && (
          <div className="bg-gray-50 rounded p-2">
            <div className="text-gray-500">重原子数</div>
            <div className="font-bold text-gray-800">{heavyAtomCount}</div>
          </div>
        )}
        {rmsd != null && (
          <div className="bg-gray-50 rounded p-2">
            <div className="text-gray-500">RMSD</div>
            <div className="font-bold text-gray-800">{rmsd.toFixed(2)} Å</div>
          </div>
        )}
      </div>

      {/* 坐标范围表格 */}
      <div>
        <div className="text-xs font-medium text-gray-500 mb-2">坐标范围（Å）</div>
        <table className="w-full text-xs border rounded overflow-hidden">
          <thead>
            <tr className="bg-gray-50 border-b text-left text-gray-500">
              <th className="px-2 py-1">轴</th>
              <th className="px-2 py-1">最小值</th>
              <th className="px-2 py-1">最大值</th>
              <th className="px-2 py-1">跨度</th>
            </tr>
          </thead>
          <tbody>
            {axes.map((axis) => (
              <tr key={axis.label} className="border-b last:border-0">
                <td className={`px-2 py-1 font-bold ${axis.color}`}>{axis.label}</td>
                <td className="px-2 py-1 font-mono">{axis.range.min.toFixed(3)}</td>
                <td className="px-2 py-1 font-mono">{axis.range.max.toFixed(3)}</td>
                <td className="px-2 py-1 font-mono">{axis.range.span.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 质心 */}
      <div className="flex items-center gap-2 text-xs">
        <Crosshair className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-gray-500">质心坐标：</span>
        <span className="font-mono text-gray-800">
          [{validation.centroid.map((c) => c.toFixed(3)).join(', ')}]
        </span>
      </div>

      {/* 对接盒子内校验 */}
      {boxCenter && boxSize && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-gray-500">对接盒子校验</div>
          <div className="text-xs text-gray-500 mb-1">
            盒子范围：center [{boxCenter.map((c) => c.toFixed(1)).join(', ')}]
            ± size [{boxSize.map((s) => s.toFixed(1)).join(', ')}]
          </div>
          {validation.inBox ? (
            <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1">
              <CheckCircle2 className="w-4 h-4" />
              所有原子均在对接盒子内
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              <AlertTriangle className="w-4 h-4" />
              {validation.outOfBoxCount} 个原子超出对接盒子范围（共 {validation.totalAtoms} 个）
            </div>
          )}
        </div>
      )}
    </div>
  );
}
