/**
 * RDKit 本地降级方案 — 当 CDN 不可达时使用本地方法生成化学结构图
 */

/** 基本 SMILES 解析 — 提取原子和键信息 */
export function parseSmilesBasic(smiles: string): {
  valid: boolean;
  atoms: string[];
  rings: number[];
  atomCount: number;
} {
  if (!smiles || typeof smiles !== 'string') {
    return { valid: false, atoms: [], rings: [], atomCount: 0 };
  }

  // 简单的有效性检查
  const validChars = new Set(
    'ACDEFGHIKLMNPQSTUVWXYZabcdefghijklmnopqrstuvwxyz1234567890()=[]#/%+.=- '
  );
  if (![...smiles].every((c) => validChars.has(c))) {
    return { valid: false, atoms: [], rings: [], atomCount: 0 };
  }

  // 提取原子符号
  const atomPattern = smiles.match(/[A-Z][a-z]?\d*/g) || [];
  // 提取环信息
  const ringMatches = smiles.match(/\d+/g) || [];

  return {
    valid: true,
    atoms: atomPattern.slice(0, 20),
    rings: ringMatches.slice(0, 10).map((r) => parseInt(r, 10)),
    atomCount: atomPattern.length,
  };
}

/** 生成简化的化学结构 SVG（无 RDKit 依赖） */
export function generateSimpleSvg(smiles: string, width: number = 220, height: number = 180): string {
  const info = parseSmilesBasic(smiles);

  if (!info.valid) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
      <rect width="${width}" height="${height}" fill="#fef3c7"/>
      <text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#92400e" font-size="12">SMILES 无效</text>
    </svg>`;
  }

  const atoms = info.atoms.slice(0, 8);
  const rings = info.rings;
  const positions: [number, number][] = [];
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) / 3;

  if (rings.length > 0) {
    // 有环结构，画多边形
    const n = Math.min(rings.length, 6);
    for (let i = 0; i < n; i++) {
      const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
      positions.push([centerX + radius * 0.6 * Math.cos(angle), centerY + radius * 0.6 * Math.sin(angle)]);
    }
  } else {
    // 链状结构，简单排列
    const n = Math.min(atoms.length, 6);
    const spacing = radius * 1.5 / Math.max(n - 1, 1);
    for (let i = 0; i < n; i++) {
      const x = centerX + (i - (n - 1) / 2) * spacing;
      positions.push([x, centerY]);
    }
  }

  const svgParts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
  ];

  // 画键（线）
  for (let i = 0; i < positions.length - 1; i++) {
    const [x1, y1] = positions[i];
    const [x2, y2] = positions[i + 1];
    svgParts.push(`<line x1="${x1.toFixed(0)}" y1="${y1.toFixed(0)}" x2="${x2.toFixed(0)}" y2="${y2.toFixed(0)}" stroke="#374151" stroke-width="2"/>`);
  }

  // 画原子（圆圈 + 符号）
  for (let i = 0; i < positions.length; i++) {
    const [x, y] = positions[i];
    const symbol = i < atoms.length ? atoms[i] : 'C';
    const display = symbol[0].toUpperCase();
    const color = ['N', 'O', 'S', 'P'].includes(display) ? '#10b981' : '#374151';
    svgParts.push(`<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="12" fill="white" stroke="${color}" stroke-width="2"/>`);
    svgParts.push(`<text x="${x.toFixed(0)}" y="${y.toFixed(0)}" text-anchor="middle" dominant-baseline="middle" fill="${color}" font-size="11" font-weight="bold">${display}</text>`);
  }

  // 添加 SMILES 文本
  const smilesText = smiles.length > 30 ? smiles.slice(0, 30) + '...' : smiles;
  svgParts.push(`<text x="${centerX}" y="${height - 15}" text-anchor="middle" fill="#6b7280" font-size="9" font-family="monospace">${smilesText}</text>`);
  svgParts.push('</svg>');

  return svgParts.join('');
}

/** 检查本地 RDKit 是否可用（Node.js 环境） */
export function isLocalRdkitAvailable(): boolean {
  try {
    // 浏览器环境无法直接 import，这里返回 false
    return false;
  } catch {
    return false;
  }
}

/** 生成 RDKit SVG（优先本地，降级到简化版） */
export function generateRdkitSvg(smiles: string, width: number = 220, height: number = 180): string {
  // 浏览器环境无法使用 Python RDKit，直接返回简化 SVG
  return generateSimpleSvg(smiles, width, height);
}
