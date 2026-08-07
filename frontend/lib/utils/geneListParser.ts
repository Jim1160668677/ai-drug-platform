/**
 * geneListParser — 基因符号列表解析器
 *
 * 支持分隔符：逗号、换行、空格、制表符
 * 验证规则：基因符号通常为大写字母+数字，1-10 字符（如 EGFR、TP53、BRCA1、CD8A）
 * 自动去重（保留首次出现顺序）
 */

/** 解析结果 */
export interface GeneListParseResult {
  /** 有效的基因符号列表（去重，保留顺序） */
  genes: string[];
  /** 无效的 token 列表 */
  invalid: string[];
  /** 总 token 数（含重复） */
  total: number;
}

/** 基因符号正则：1-10 字符，字母开头，含字母和数字 */
const GENE_SYMBOL_REGEX = /^[A-Za-z][A-Za-z0-9]{0,9}$/;

/**
 * 解析基因符号列表文本
 * @param text 输入文本（逗号/换行/空格/制表符分隔）
 * @returns 解析结果
 */
export function parseGeneList(text: string): GeneListParseResult {
  if (!text || !text.trim()) {
    return { genes: [], invalid: [], total: 0 };
  }

  // 按多种分隔符拆分
  const tokens = text
    .split(/[,，\n\r\t\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);

  const seen = new Set<string>();
  const genes: string[] = [];
  const invalid: string[] = [];

  for (const token of tokens) {
    // 归一化为大写
    const normalized = token.toUpperCase();

    // 跳过已见（去重）
    if (seen.has(normalized)) continue;
    seen.add(normalized);

    // 验证基因符号格式
    if (GENE_SYMBOL_REGEX.test(normalized)) {
      genes.push(normalized);
    } else {
      invalid.push(token);
    }
  }

  return {
    genes,
    invalid,
    total: tokens.length,
  };
}
