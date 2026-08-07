/**
 * cdnLoader — 共享 CDN 脚本加载器
 *
 * 解决问题：MoleculeStructure 组件的 loadScript 函数存在竞态条件——
 * 当多个组件同时挂载时，第二个组件发现已有 <script> 标签，
 * 但仅 addEventListener('load')；若脚本已加载完成，load 事件不再触发，
 * 导致 Promise 永不 resolve，组件卡在 loading 状态。
 *
 * 核心修复：
 *   - 通过 dataset.loaded / dataset.error 标记脚本状态
 *   - 已 loaded → 立即 resolve
 *   - 已 error → 立即 reject
 *   - 加载中 → 添加事件监听
 *   - 每个 URL 超时保护，多 CDN 顺序回退
 *
 * v2 修复（关键）：多 CDN 回退时，失败的 script 标签会阻塞后续 CDN 尝试。
 *   - loadOneUrl 现在按 src 匹配已有 script，而非仅按 attr
 *   - 失败的 script 标签会被移除，使后续 CDN URL 能正常加载
 *   - 同一 URL 的并发请求复用同一 script 标签
 */

/** 探测全局对象是否就绪的函数类型 */
export type LoaderProbe<T> = () => T | undefined | null;

/** 加载选项 */
export interface LoadOptions {
  /** script 标签的 data-attr 标识（用于去重），如 'rdkit-loader' */
  attr: string;
  /** 单个 URL 超时时间（毫秒），默认 15000 */
  perUrlTimeoutMs?: number;
}

/**
 * 从多个 CDN URL 中顺序尝试加载脚本，直到 probe 探测到目标对象就绪。
 *
 * @param urls CDN URL 列表（按优先级排序）
 * @param probe 探测函数，返回非空值表示加载成功
 * @param opts 加载选项
 * @returns 探测到的目标对象
 * @throws 当所有 CDN 均失败时抛出错误
 */
export async function loadScriptWithFallback<T>(
  urls: string[],
  probe: LoaderProbe<T>,
  opts: LoadOptions,
): Promise<T> {
  if (typeof window === 'undefined') throw new Error('SSR environment not supported');

  // 快速路径：目标对象已就绪
  const existing = probe();
  if (existing) return existing;

  const timeoutMs = opts.perUrlTimeoutMs ?? 15_000;
  const attrSelector = `data-${opts.attr}`;

  for (const url of urls) {
    // 清理此前失败的 script 标签（同 attr 但不同 src），避免阻塞当前 URL
    const failedScripts = document.querySelectorAll<HTMLScriptElement>(
      `script[${attrSelector}][data-error="true"]`,
    );
    failedScripts.forEach((s) => {
      if (s.src !== url) s.remove();
    });

    try {
      await loadOneUrl(url, opts.attr, timeoutMs);
      const obj = probe();
      if (obj) return obj;
    } catch {
      // 当前 URL 失败，尝试下一个
    }
  }

  throw new Error(`所有 CDN 加载失败（共尝试 ${urls.length} 个 URL）`);
}

/**
 * 加载单个 URL 的脚本标签。
 * 通过 dataset 属性跟踪加载状态，解决竞态条件。
 *
 * 关键：按 src 精确匹配已有 script，避免不同 CDN URL 互相干扰。
 */
function loadOneUrl(url: string, attr: string, timeoutMs: number): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    // 按 attr + src 精确匹配已有 script（解决多 CDN 回退冲突）
    const existing = document.querySelector<HTMLScriptElement>(
      `script[data-${attr}][src="${url}"]`,
    );

    if (existing) {
      // 检查已存在脚本的状态
      if (existing.dataset.loaded === 'true') {
        return resolve();
      }
      if (existing.dataset.error === 'true') {
        return reject(new Error(`prior load error for ${url}`));
      }
      // 脚本仍在加载中，添加事件监听
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error(`load error for ${url}`)), {
        once: true,
      });
      return;
    }

    // 创建新的 script 标签
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.setAttribute(`data-${attr}`, 'true');

    const timer = setTimeout(() => {
      script.dataset.error = 'true';
      reject(new Error(`timeout after ${timeoutMs}ms for ${url}`));
    }, timeoutMs);

    script.addEventListener('load', () => {
      clearTimeout(timer);
      script.dataset.loaded = 'true';
      resolve();
    });

    script.addEventListener('error', () => {
      clearTimeout(timer);
      script.dataset.error = 'true';
      reject(new Error(`load error for ${url}`));
    });

    document.head.appendChild(script);
  });
}