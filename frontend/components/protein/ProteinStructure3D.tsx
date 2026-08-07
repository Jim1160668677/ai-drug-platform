'use client';

/**
 * ProteinStructure3D — 基于 3Dmol.js 的 3D 蛋白结构可视化组件
 *
 * 解决问题：蛋白结构预测页面只显示 PDB 文本，没有像 AlphaFold 那样的
 *          交互式 3D 结构。本组件用 3Dmol.js（GitHub 上的成熟方案）渲染。
 *
 * 集成方案（3Dmol.js 多 CDN 回退）：
 *   - 优先 jsdelivr，次选 unpkg，最后 3Dmol.org（官方证书有问题）
 *   - 通过 $3Dmol.createViewer 创建 WebGL 画布
 *   - 支持按 pLDDT 着色（AlphaFold 风格蓝→红渐变）
 *   - 支持 cartoon / stick / sphere / line 等多种渲染风格
 *   - 支持配体原子和结合位点残基高亮（Protenix 模式）
 *
 * 用法：
 *   <ProteinStructure3D pdbText={pdbText} plddtMean={0.85} />
 *   <ProteinStructure3D
 *     pdbText={pdbText}
 *     bindingSiteResidues={[12, 13, 14]}
 *     showLigand
 *   />
 */

import { useEffect, useRef, useState } from 'react';
import { Box, AlertCircle, RotateCw, Eye, EyeOff, Target } from 'lucide-react';

// 3Dmol.js 弱类型定义
type Viewer3D = {
  addModel: (data: string, format: string) => void;
  setStyle: (sel: object, style: object, options?: object) => void;
  setColorByProperty: (prop: string, scheme: string, range?: [number, number]) => void;
  setBackgroundColor: (hex: number) => void;
  setViewStyle: (style: object) => void;
  zoomTo: (sel?: object) => void;
  spin: (axis: string, speed?: number) => void;
  render: () => void;
  resize: () => void;
  clear: () => void;
};

declare global {
  interface Window {
    $3Dmol?: {
      createViewer: (el: HTMLElement, config?: object) => Viewer3D;
      builtinColorSchemes?: {
        pLDDT?: object;
      };
      Gradient?: {
        RWB?: any;
      };
    };
  }
}

// 多 CDN 回退：3Dmol.org 官方证书有问题，优先用 jsdelivr
const CDN_URLS_3DMOL = [
  'https://cdn.jsdelivr.net/npm/3dmol@2.4.0/build/3Dmol-min.js',
  'https://unpkg.com/3dmol@2.4.0/build/3Dmol-min.js',
  'https://3Dmol.org/build/3Dmol-min.js',
];
let loadPromise: Promise<boolean> | null = null;

function loadScriptFromUrl(url: string, attr: string): Promise<boolean> {
  return new Promise((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-${attr}]`);
    if (existing) {
      existing.addEventListener('load', () => resolve(true));
      existing.addEventListener('error', () => resolve(false));
      return;
    }
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.setAttribute(`data-${attr}`, 'true');
    script.addEventListener('load', () => resolve(true));
    script.addEventListener('error', () => resolve(false));
    document.head.appendChild(script);
  });
}

async function load3Dmol(): Promise<boolean> {
  if (typeof window === 'undefined') return false;
  if (window.$3Dmol) return true;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    for (const url of CDN_URLS_3DMOL) {
      const ok = await loadScriptFromUrl(url, '3dmol-loader');
      if (ok && window.$3Dmol) return true;
    }
    return false;
  })();

  return loadPromise;
}

export interface ProteinStructure3DProps {
  /** PDB 文本（必填） */
  pdbText: string;
  /** 平均 pLDDT 评分（0~1，可选） */
  plddtMean?: number;
  /** 渲染风格 */
  style?: 'cartoon' | 'stick' | 'sphere' | 'line';
  /** 画布高度 */
  height?: number;
  /** 是否自动旋转 */
  spin?: boolean;
  /** 自定义类名 */
  className?: string;
  /** 结合位点残基序号列表（Protenix 返回） */
  bindingSiteResidues?: number[];
  /** 是否高亮显示配体（HETATM）原子 */
  showLigand?: boolean;
  /** 是否显示结合位点残基侧链 */
  showBindingSite?: boolean;
}

type RenderStyle = 'cartoon' | 'stick' | 'sphere' | 'line';

export default function ProteinStructure3D({
  pdbText,
  plddtMean,
  style = 'cartoon',
  height = 500,
  spin = true,
  className = '',
  bindingSiteResidues,
  showLigand = true,
  showBindingSite = true,
}: ProteinStructure3DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer3D | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [autoSpin, setAutoSpin] = useState(spin);
  const [currentStyle, setCurrentStyle] = useState<RenderStyle>(style);
  const [highlightLigand, setHighlightLigand] = useState(showLigand);
  const [highlightBinding, setHighlightBinding] = useState(showBindingSite);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      if (!pdbText || !containerRef.current) return;
      setStatus('loading');
      const ok = await load3Dmol();
      if (cancelled) return;
      if (!ok || !window.$3Dmol) {
        setStatus('error');
        setErrorMsg('3Dmol.js 库加载失败（CDN 不可达），无法显示 3D 结构');
        return;
      }
      try {
        // 清空旧 viewer
        if (viewerRef.current) {
          try {
            (viewerRef.current as any).clear();
          } catch {
            /* noop */
          }
          viewerRef.current = null;
        }
        // 容器清空
        containerRef.current.innerHTML = '';

        const viewer = window.$3Dmol.createViewer(containerRef.current, {
          backgroundColor: 'white',
          antialias: true,
        });
        viewerRef.current = viewer;

        viewer.addModel(pdbText, 'pdb');
        viewer.setBackgroundColor(0xffffff);

        // 应用主体风格 + 配体/结合位点高亮
        applyFullStyle(viewer, currentStyle, {
          highlightLigand,
          highlightBinding,
          bindingSiteResidues,
        });

        // 按 pLDDT 着色（AlphaFold 风格）：
        // 高 pLDDT (>90) → 深蓝；中等 (70-90) → 浅蓝；低 (<50) → 橙红
        try {
          viewer.setColorByProperty('b', 'rwb', [50, 90]);
        } catch {
          /* 部分版本不支持按 b 因子着色，忽略错误 */
        }

        viewer.zoomTo();
        viewer.render();

        if (autoSpin) {
          viewer.spin('y', 0.5);
        }

        if (!cancelled) setStatus('ready');
      } catch (e: any) {
        if (!cancelled) {
          setStatus('error');
          setErrorMsg(e?.message || '3D 渲染失败');
        }
      }
    }

    init();
    return () => {
      cancelled = true;
      if (viewerRef.current) {
        try {
          (viewerRef.current as any).spin?.('y', 0);
          (viewerRef.current as any).clear?.();
        } catch {
          /* noop */
        }
        viewerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdbText]);

  // 切换自动旋转
  useEffect(() => {
    if (viewerRef.current && status === 'ready') {
      try {
        viewerRef.current.spin('y', autoSpin ? 0.5 : 0);
      } catch {
        /* noop */
      }
    }
  }, [autoSpin, status]);

  // 切换渲染风格或高亮开关
  useEffect(() => {
    if (viewerRef.current && status === 'ready') {
      try {
        applyFullStyle(viewerRef.current, currentStyle, {
          highlightLigand,
          highlightBinding,
          bindingSiteResidues,
        });
        viewerRef.current.render();
      } catch {
        /* noop */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStyle, status, highlightLigand, highlightBinding, bindingSiteResidues]);

  // 窗口大小变化时调整 viewer
  useEffect(() => {
    const onResize = () => {
      if (viewerRef.current) {
        try {
          viewerRef.current.resize();
          viewerRef.current.render();
        } catch {
          /* noop */
        }
      }
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const hasLigand = pdbText.includes('HETATM');
  const hasBindingSite = (bindingSiteResidues?.length ?? 0) > 0;

  return (
    <div className={`flex flex-col ${className}`}>
      {/* 工具栏 */}
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <span className="text-xs font-medium text-gray-600">渲染风格：</span>
        {(['cartoon', 'stick', 'sphere', 'line'] as RenderStyle[]).map((s) => (
          <button
            key={s}
            onClick={() => setCurrentStyle(s)}
            className={`px-2 py-0.5 rounded text-xs border ${
              currentStyle === s
                ? 'bg-primary-600 text-white border-primary-600'
                : 'bg-white text-gray-700 border-gray-300 hover:border-primary-400'
            }`}
            title={
              s === 'cartoon'
                ? 'Cartoon（卡通，AlphaFold 默认）'
                : s === 'stick'
                ? 'Stick（棍状，显示原子键）'
                : s === 'sphere'
                ? 'Sphere（球状）'
                : 'Line（线状）'
            }
          >
            {s === 'cartoon' ? 'Cartoon' : s === 'stick' ? 'Stick' : s === 'sphere' ? 'Sphere' : 'Line'}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 flex-wrap">
          {hasLigand && (
            <button
              onClick={() => setHighlightLigand((s) => !s)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${
                highlightLigand
                  ? 'bg-emerald-600 text-white border-emerald-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:border-emerald-400'
              }`}
              title="切换配体显示（Protenix 预测的小分子药物）"
            >
              {highlightLigand ? (
                <Eye className="w-3 h-3" />
              ) : (
                <EyeOff className="w-3 h-3" />
              )}
              <span>配体</span>
            </button>
          )}
          {hasBindingSite && (
            <button
              onClick={() => setHighlightBinding((s) => !s)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${
                highlightBinding
                  ? 'bg-orange-600 text-white border-orange-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:border-orange-400'
              }`}
              title="切换结合位点残基高亮（Protenix 预测的药物结合口袋）"
            >
              <Target className="w-3 h-3" />
              <span>结合位点（{(bindingSiteResidues?.length) || 0}）</span>
            </button>
          )}
          <button
            onClick={() => setAutoSpin((s) => !s)}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-xs border border-gray-300 hover:border-primary-400"
            title="切换自动旋转"
          >
            {autoSpin ? (
              <>
                <RotateCw className="w-3 h-3 text-primary-600" />
                <span>暂停旋转</span>
              </>
            ) : (
              <>
                <RotateCw className="w-3 h-3 text-gray-400" />
                <span>开始旋转</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 3D 画布 */}
      <div
        className="relative bg-white border border-gray-200 rounded-lg overflow-hidden"
        style={{ height }}
      >
        {status === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center bg-white bg-opacity-80 z-10 text-sm text-gray-500">
            <div className="flex flex-col items-center gap-2">
              <Box className="w-6 h-6 animate-pulse text-primary-600" />
              <span>正在加载 3D 结构...</span>
            </div>
          </div>
        )}
        {status === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center bg-amber-50 z-10 p-4">
            <div className="flex flex-col items-center gap-2 text-amber-700 text-sm max-w-md text-center">
              <AlertCircle className="w-6 h-6" />
              <div>{errorMsg}</div>
              <details className="mt-2 w-full">
                <summary className="text-xs text-gray-500 cursor-pointer">查看 PDB 文本</summary>
                <pre className="mt-2 p-2 bg-gray-100 text-xs font-mono max-h-48 overflow-auto text-left">
                  {pdbText.slice(0, 2000)}
                </pre>
              </details>
            </div>
          </div>
        )}
        <div
          ref={containerRef}
          className="w-full h-full"
          style={{ width: '100%', height: '100%' }}
        />
      </div>

      {/* pLDDT 说明 + 图例 */}
      <div className="mt-2 text-xs text-gray-500 flex items-center gap-3 flex-wrap">
        {plddtMean != null && (
          <span>
            平均 pLDDT：
            <span
              className={`font-bold ml-1 ${
                plddtMean >= 0.9
                  ? 'text-blue-700'
                  : plddt_color(plddtMean)
              }`}
            >
              {(plddtMean * 100).toFixed(1)}%
            </span>
          </span>
        )}
        <span>置信度色阶：</span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ background: '#ff7d45' }} />
          <span>低 (&lt;50)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ background: '#ffdb13' }} />
          <span>中 (50-70)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ background: '#65cbf3' }} />
          <span>较高 (70-90)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded" style={{ background: '#0053d6' }} />
          <span>高 (&gt;90)</span>
        </span>
        {hasLigand && highlightLigand && (
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded" style={{ background: '#10b981' }} />
            <span>配体原子</span>
          </span>
        )}
        {hasBindingSite && highlightBinding && (
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded" style={{ background: '#f97316' }} />
            <span>结合位点</span>
          </span>
        )}
        <span className="text-gray-400">· 可拖动旋转 / 滚轮缩放</span>
      </div>
    </div>
  );
}

function plddt_color(v: number) {
  if (v >= 0.7) return 'text-cyan-600';
  if (v >= 0.5) return 'text-yellow-600';
  return 'text-orange-600';
}

interface ApplyStyleOpts {
  highlightLigand: boolean;
  highlightBinding: boolean;
  bindingSiteResidues?: number[];
}

/** 应用渲染风格 + 配体/结合位点高亮到 3Dmol viewer */
function applyFullStyle(
  viewer: Viewer3D,
  style: RenderStyle,
  opts: ApplyStyleOpts
) {
  // 1) 主体蛋白风格（排除异质原子 HETATM）
  const proteinSel = { hetflag: false };
  switch (style) {
    case 'cartoon':
      viewer.setStyle(proteinSel, { cartoon: { color: 'spectrum' } });
      break;
    case 'stick':
      viewer.setStyle(proteinSel, { stick: { colorscheme: 'yellowCarbon' } });
      break;
    case 'sphere':
      viewer.setStyle(proteinSel, { sphere: { colorscheme: 'yellowCarbon' } });
      break;
    case 'line':
      viewer.setStyle(proteinSel, { line: { colorscheme: 'yellowCarbon' } });
      break;
  }

  // 2) 结合位点残基高亮：在指定残基上叠加 stick + sphere
  //    3Dmol.js 支持 resi 数组选择 + byres 包含整残基
  if (opts.highlightBinding && opts.bindingSiteResidues && opts.bindingSiteResidues.length > 0) {
    const resiArr = opts.bindingSiteResidues;
    try {
      // 在 cartoon 模式下也叠加 stick 让侧链可见
      viewer.setStyle(
        { resi: resiArr, hetflag: false, byres: true } as any,
        { stick: { color: '#f97316', radius: 0.15 } }
      );
      // 用小 sphere 标识 CA 原子（避免遮挡 cartoon）
      viewer.setStyle(
        { resi: resiArr, atom: 'CA', hetflag: false } as any,
        { sphere: { color: '#f97316', radius: 0.6 } }
      );
    } catch {
      /* 某些版本不支持数组 resi，忽略 */
    }
  }

  // 3) 配体原子（HETATM）显示为绿色 stick + sphere
  if (opts.highlightLigand) {
    viewer.setStyle(
      { hetflag: true } as any,
      {
        stick: { colorscheme: 'greenCarbon', radius: 0.2 },
        sphere: { scale: 0.3, colorscheme: 'greenCarbon' },
      }
    );
  } else {
    // 隐藏配体
    viewer.setStyle({ hetflag: true } as any, {});
  }
}
