'use client';

/**
 * Molecule3DViewer — 基于 3Dmol.js 的 3D 分子可视化组件
 *
 * 用于展示分子对接后的结合姿态 3D 结构。
 * 加载 MOL/SDF block 并渲染为可交互的 3D 模型（旋转、缩放、平移）。
 *
 * 集成方案：
 *   - 通过 cdnLoader 从 CDN 加载 3Dmol.js（多源回退 + 竞态修复）
 *   - addModel(molBlock, 'sdf') 加载分子
 *   - stick + sphere 样式渲染
 *   - 可选自动旋转
 *
 * 用法：
 *   <Molecule3DViewer molBlock={molBlock} height={380} spin />
 */

import { useEffect, useRef, useState } from 'react';
import { loadScriptWithFallback } from '@/lib/utils/cdnLoader';
import { Box, AlertCircle } from 'lucide-react';

// 3Dmol.js 全局类型（弱类型以避免 TS 报错）
type Viewer3D = {
  addModel: (data: string, format: string) => void;
  setStyle: (sel: object, style: object) => void;
  setBackgroundColor: (color: number | string) => void;
  zoomTo: () => void;
  render: () => void;
  spin: (axis: string, speed?: number) => void;
  clear: () => void;
};

declare global {
  interface Window {
    $3Dmol?: {
      createViewer: (element: HTMLElement, config?: object) => Viewer3D;
    };
  }
}

// 3Dmol.js CDN 地址（多源回退）
const CDN_URLS_3DMOL = [
  'https://cdn.jsdelivr.net/npm/3dmol@2.4.0/build/3Dmol-min.js',
  'https://unpkg.com/3dmol@2.4.0/build/3Dmol-min.js',
  'https://cdn.staticfile.net/3dmol/2.4.0/build/3Dmol-min.js',
];

export interface Molecule3DViewerProps {
  /** MOL/SDF block 字符串（来自 RDKit MolToMolBlock） */
  molBlock: string;
  /** 画布高度（像素），默认 380 */
  height?: number;
  /** 是否自动旋转，默认 false */
  spin?: boolean;
  /** 自定义类名 */
  className?: string;
}

export default function Molecule3DViewer({
  molBlock,
  height = 380,
  spin = false,
  className = '',
}: Molecule3DViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer3D | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');

  useEffect(() => {
    let cancelled = false;

    async function init() {
      if (!molBlock || !containerRef.current) return;
      setStatus('loading');

      try {
        // 使用共享 CDN 加载器加载 3Dmol.js（修复竞态条件）
        await loadScriptWithFallback(
          CDN_URLS_3DMOL,
          () => window.$3Dmol,
          { attr: '3dmol-loader', perUrlTimeoutMs: 15_000 },
        );
        if (cancelled) return;

        if (!window.$3Dmol) {
          throw new Error('3Dmol.js 全局对象未就绪');
        }

        // 清理旧 viewer
        if (viewerRef.current) {
          try {
            viewerRef.current.clear();
          } catch {
            /* noop */
          }
        }
        if (containerRef.current) {
          containerRef.current.innerHTML = '';
        }

        // 创建新 viewer
        const viewer = window.$3Dmol.createViewer(containerRef.current, {
          backgroundColor: 'white',
          antialias: true,
        });
        viewerRef.current = viewer;

        // 加载分子模型
        viewer.addModel(molBlock, 'sdf');
        viewer.setStyle(
          {},
          { stick: { radius: 0.18 }, sphere: { scale: 0.28 } },
        );
        viewer.setBackgroundColor(0xffffff);
        viewer.zoomTo();
        viewer.render();

        // 自动旋转
        if (spin) {
          viewer.spin('y', 0.5);
        }

        if (!cancelled) setStatus('ready');
      } catch (e: unknown) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : '3D 渲染失败';
          setStatus('error');
          setErrorMsg(msg);
        }
      }
    }

    init();

    return () => {
      cancelled = true;
      if (viewerRef.current) {
        try {
          viewerRef.current.spin?.('y', 0);
          viewerRef.current.clear?.();
        } catch {
          /* noop */
        }
        viewerRef.current = null;
      }
    };
  }, [molBlock, spin]);

  if (status === 'loading') {
    return (
      <div
        className={`flex items-center justify-center bg-gray-50 border border-dashed border-gray-200 rounded ${className}`}
        style={{ height }}
      >
        <div className="flex flex-col items-center gap-2 text-gray-400">
          <Box className="w-6 h-6 animate-pulse" />
          <span className="text-xs">加载 3D 渲染引擎中...</span>
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div
        className={`flex flex-col items-center justify-center bg-amber-50 border border-amber-200 rounded p-4 ${className}`}
        style={{ height }}
      >
        <AlertCircle className="w-5 h-5 text-amber-600 mb-2" />
        <div className="text-sm text-amber-700 text-center">{errorMsg}</div>
        <div className="mt-2 text-xs text-gray-500">
          3Dmol.js 加载失败，请检查网络连接后刷新页面
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`border border-gray-200 rounded overflow-hidden ${className}`}
      style={{ height, width: '100%' }}
    />
  );
}
