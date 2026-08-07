'use client';

/**
 * MoleculeStructure — 基于 RDKit.js 的 2D 化学结构式渲染组件
 *
 * 增强方案：
 * 1. 优先使用 RDKit.js CDN（多CDN回退）
 * 2. CDN不可达时降级到本地SVG生成
 * 3. 本地SVG使用简化化学结构绘制，保证基本可见性
 */

import { useEffect, useRef, useState } from 'react';
import { Atom, AlertCircle } from 'lucide-react';
import { loadScriptWithFallback } from '@/lib/utils/cdnLoader';
import { generateRdkitSvg as generate_rdkit_svg, isLocalRdkitAvailable as is_local_rdkit_available } from '@/lib/utils/chemistry';

// RDKit.js 全局类型（弱类型以避免 TS 报错）
type RDKitModule = {
  get_mol: (smiles: string) => {
    is_valid: () => boolean;
    draw_to_svg_with_offset: (
      svg: SVGSVGElement,
      x: number,
      y: number,
      width: number,
      height: number
    ) => void;
    get_smiles: () => string;
    delete: () => void;
  } | null;
};

declare global {
  interface Window {
    RDKit?: RDKitModule;
    initRDKitModule?: () => Promise<RDKitModule>;
  }
}

// 多 CDN 回退：优先国内可访问的 CDN（jsdelivr/unpkg 在国内常被墙）
const RDKIT_CDN_URLS = [
  // npmmirror（阿里云淘宝镜像）— 国内访问最稳定
  'https://registry.npmmirror.com/@rdkit/rdkit/2024.3.4-1.0.0/files/Code/MinimalLib/dist/RDKit_minimal.js',
  // jsdelivr — 全球 CDN（国内可能不稳定）
  'https://cdn.jsdelivr.net/npm/@rdkit/rdkit@2024.3.4-1.0.0/Code/MinimalLib/dist/RDKit_minimal.js',
  // unpkg — 备选
  'https://unpkg.com/@rdkit/rdkit@2024.3.4-1.0.0/Code/MinimalLib/dist/RDKit_minimal.js',
  // esm.sh
  'https://esm.sh/@rdkit/rdkit@2024.3.4-1.0.0/Code/MinimalLib/dist/RDKit_minimal.js',
];

let rdkitLoadPromise: Promise<RDKitModule | null> | null = null;

/** 单例加载 RDKit.js wasm 模块（多 CDN 回退） */
async function loadRDKit(): Promise<RDKitModule | null> {
  if (typeof window === 'undefined') return null;
  if (window.RDKit) return window.RDKit;
  if (rdkitLoadPromise) return rdkitLoadPromise;

  rdkitLoadPromise = (async () => {
    try {
      await loadScriptWithFallback(
        RDKIT_CDN_URLS,
        () => (window.initRDKitModule || window.RDKit ? (window.RDKit ?? undefined) : undefined),
        { attr: 'rdkit-loader', perUrlTimeoutMs: 10_000 },
      );
    } catch {
      return null;
    }

    if (window.initRDKitModule) {
      try {
        const mod = await window.initRDKitModule();
        window.RDKit = mod;
        return mod;
      } catch {
        return null;
      }
    }
    return window.RDKit ?? null;
  })();

  return rdkitLoadPromise;
}

export interface MoleculeStructureProps {
  smiles: string;
  width?: number;
  height?: number;
  showSmiles?: boolean;
  className?: string;
}

export default function MoleculeStructure({
  smiles,
  width = 220,
  height = 180,
  showSmiles = false,
  className = '',
}: MoleculeStructureProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'fallback'>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [fallbackSvg, setFallbackSvg] = useState<string>('');

  useEffect(() => {
    let cancelled = false;

    async function render() {
      if (!smiles) {
        setStatus('error');
        setErrorMsg('未提供 SMILES');
        return;
      }

      setStatus('loading');
      setErrorMsg('');
      setFallbackSvg('');

      // 优先尝试本地 RDKit（如果已安装）
      if (is_local_rdkit_available()) {
        try {
          const svg = await Promise.resolve(generate_rdkit_svg(smiles, width, height));
          if (!cancelled && svg) {
            setFallbackSvg(svg);
            setStatus('ready');
            return;
          }
        } catch {
          // 继续尝试 CDN
        }
      }

      // 尝试 CDN 加载 RDKit.js
      const rdkit = await loadRDKit();

      if (cancelled) return;

      if (rdkit) {
        try {
          const mol = rdkit.get_mol(smiles);
          if (!mol || !mol.is_valid()) {
            setStatus('error');
            setErrorMsg('SMILES 无效');
            return;
          }
          if (!svgRef.current || cancelled) return;
          while (svgRef.current.firstChild) {
            svgRef.current.removeChild(svgRef.current.firstChild);
          }
          svgRef.current.setAttribute('width', String(width));
          svgRef.current.setAttribute('height', String(height));
          svgRef.current.setAttribute('viewBox', `0 0 ${width} ${height}`);
          mol.draw_to_svg_with_offset(svgRef.current, 0, 0, width, height);
          if (!cancelled) setStatus('ready');
          return;
        } catch (e: any) {
          if (!cancelled) {
            setErrorMsg(e?.message || '渲染失败');
            setStatus('error');
          }
          return;
        }
      }

      // CDN 不可达，使用本地 SVG 降级方案
      if (!cancelled) {
        try {
          const svg = generate_rdkit_svg(smiles, width, height);
          setFallbackSvg(svg);
          setStatus('fallback');
        } catch {
          setStatus('error');
          setErrorMsg('结构渲染失败');
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [smiles, width, height]);

  if (status === 'loading') {
    return (
      <div
        className={`flex items-center justify-center bg-gray-50 border border-dashed border-gray-200 rounded text-xs text-gray-400 ${className}`}
        style={{ width, height }}
      >
        <div className="flex flex-col items-center gap-1">
          <Atom className="w-5 h-5 animate-pulse" />
          <span>渲染结构式中...</span>
        </div>
      </div>
    );
  }

  // 使用本地 SVG 降级方案
  if (status === 'fallback' && fallbackSvg) {
    return (
      <div
        className={`flex flex-col items-center bg-white border border-blue-200 rounded p-1 ${className}`}
        style={{ width, height }}
        title={`SMILES: ${smiles}（本地渲染）`}
      >
        <div
          className="max-w-full max-h-full"
          dangerouslySetInnerHTML={{ __html: fallbackSvg }}
        />
        {showSmiles && (
          <div className="mt-1 font-mono text-[10px] text-gray-500 break-all max-w-full">
            {smiles}
          </div>
        )}
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div
        className={`flex flex-col items-center justify-center bg-amber-50 border border-amber-200 rounded p-2 text-xs text-amber-700 ${className}`}
        style={{ width, height }}
        title={errorMsg}
      >
        <AlertCircle className="w-4 h-4 mb-1" />
        <div className="text-center leading-tight">{errorMsg}</div>
        <div className="mt-1 font-mono text-[10px] text-gray-500 break-all max-w-full">
          {smiles}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col items-center justify-center bg-white border border-gray-200 rounded p-1 ${className}`}
      style={{ width, height }}
      title={`SMILES: ${smiles}`}
    >
      <svg
        ref={svgRef}
        xmlns="http://www.w3.org/2000/svg"
        className="max-w-full max-h-full"
      />
      {showSmiles && (
        <div className="mt-1 font-mono text-[10px] text-gray-500 break-all max-w-full">
          {smiles}
        </div>
      )}
    </div>
  );
}
