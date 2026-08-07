import '@testing-library/jest-dom';

// ========== jsdom 环境补齐 ==========

/**
 * ResizeObserver polyfill
 * reactflow / react-virtuoso 等库依赖 ResizeObserver，jsdom 不提供
 */
class ResizeObserverMock {
  private callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element) {
    // 立即触发一次回调，模拟元素已布局
    this.callback(
      [
        {
          target,
          contentRect: {
            x: 0,
            y: 0,
            width: target.clientWidth || 800,
            height: target.clientHeight || 600,
            top: 0,
            left: 0,
            bottom: 0,
            right: 0,
          },
          borderBoxSize: [{ inlineSize: 800, blockSize: 600 }],
          contentBoxSize: [{ inlineSize: 800, blockSize: 600 }],
          devicePixelContentBoxSize: [{ inlineSize: 800, blockSize: 600 }],
        },
      ] as unknown as ResizeObserverEntry[],
      this
    );
  }
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

/**
 * DOMMatrix polyfill（reactflow 在 measure 时调用）
 */
if (!globalThis.DOMMatrix) {
  class DOMMatrixMock {
    m11 = 1;
    m12 = 0;
    m13 = 0;
    m14 = 0;
    m21 = 0;
    m22 = 1;
    m23 = 0;
    m24 = 0;
    m31 = 0;
    m32 = 0;
    m33 = 1;
    m34 = 0;
    m41 = 0;
    m42 = 0;
    m43 = 0;
    m44 = 1;
    a = 1;
    b = 0;
    c = 0;
    d = 1;
    e = 0;
    f = 0;
    is2D = true;
    isIdentity = true;
    constructor() {}
    multiply() {
      return new DOMMatrixMock();
    }
    inverse() {
      return new DOMMatrixMock();
    }
    translate() {
      return new DOMMatrixMock();
    }
    scale() {
      return new DOMMatrixMock();
    }
    rotate() {
      return new DOMMatrixMock();
    }
    transformPoint() {
      return { x: 0, y: 0, z: 0, w: 1 };
    }
    toFloat32Array() {
      return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    }
  }
  globalThis.DOMMatrix = DOMMatrixMock as unknown as typeof DOMMatrix;
  // reactflow 在 updateNodeDimensions 中调用 new DOMMatrixReadOnly()
  globalThis.DOMMatrixReadOnly = DOMMatrixMock as unknown as typeof DOMMatrixReadOnly;
}

/**
 * matchMedia polyfill（useMediaQuery Hook 在 jsdom 中需要）
 */
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/**
 * IntersectionObserver polyfill（部分组件可能依赖）
 */
class IntersectionObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;
}

/**
 * scrollTo polyfill（react-virtuoso 在 jsdom 下会调用）
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
