/**
 * sequenceParser — 生物序列文件解析器
 *
 * 支持格式：
 *   1. FASTA（.fasta/.fa）— '>' 开头为注释/标题行，其余为序列
 *   2. GenBank（.genbank/.gb）— 解析 ORIGIN...// 区段，去除数字和空格
 *   3. 纯序列 — 直接输入的氨基酸序列
 *
 * 验证：
 *   - 氨基酸字母表校验（20 标准氨基酸 + X/B/Z/U/O 容错）
 *   - 大小写归一化为大写
 *   - 去除空白、数字、非字母字符
 */

/** 标准氨基酸字母（20 标准 + X 未知 + B/Z/U/O 容错） */
const VALID_AA = new Set('ACDEFGHIKLMNPQRSTVWYXBZUO'.split(''));

/** 解析结果 */
export interface SequenceParseResult {
  /** 解析出的序列（大写，无空白） */
  sequence: string;
  /** 检测到的格式 */
  format: 'fasta' | 'genbank' | 'plain' | 'unknown';
  /** 解析过程中的警告信息 */
  warnings: string[];
  /** 元数据（如 FASTA 标题、GenBank LOCUS 等） */
  metadata: {
    /** FASTA 标题行（> 之后的内容） */
    title?: string;
    /** GenBank LOCUS 行 */
    locus?: string;
    /** 序列长度 */
    length: number;
  };
}

/**
 * 解析序列文件文本内容
 * @param text 文件原始文本
 * @returns 解析结果
 */
export function parseSequenceFile(text: string): SequenceParseResult {
  const warnings: string[] = [];
  const trimmed = text.trim();

  if (!trimmed) {
    return {
      sequence: '',
      format: 'unknown',
      warnings: ['文件内容为空'],
      metadata: { length: 0 },
    };
  }

  let format: SequenceParseResult['format'] = 'plain';
  let sequence = '';
  let title: string | undefined;
  let locus: string | undefined;

  // 检测 FASTA 格式
  if (trimmed.startsWith('>')) {
    format = 'fasta';
    const result = parseFasta(trimmed);
    sequence = result.sequence;
    title = result.title;
    warnings.push(...result.warnings);
  }
  // 检测 GenBank 格式（包含 ORIGIN 标记或 LOCUS 标记）
  else if (/^LOCUS|ORIGIN\s*\n/im.test(trimmed)) {
    format = 'genbank';
    const result = parseGenBank(trimmed);
    sequence = result.sequence;
    locus = result.locus;
    warnings.push(...result.warnings);
  }
  // 纯序列
  else {
    format = 'plain';
    sequence = cleanSequence(trimmed);
  }

  // 验证氨基酸字母表
  const invalidChars = validateAminoAcids(sequence);
  if (invalidChars.length > 0) {
    warnings.push(`检测到非标准氨基酸字符: ${invalidChars.join(', ')}（已保留，请人工确认）`);
  }

  if (sequence.length === 0) {
    warnings.push('解析后序列为空');
  }

  return {
    sequence,
    format,
    warnings,
    metadata: {
      title,
      locus,
      length: sequence.length,
    },
  };
}

/** 解析 FASTA 格式 */
function parseFasta(text: string): { sequence: string; title: string; warnings: string[] } {
  const warnings: string[] = [];
  const lines = text.split(/\r?\n/);
  const seqParts: string[] = [];
  let title = '';

  for (const line of lines) {
    const trimmedLine = line.trim();
    if (!trimmedLine) continue;

    if (trimmedLine.startsWith('>')) {
      // 标题行（取第一个 > 之后的内容）
      if (!title) {
        title = trimmedLine.slice(1).trim();
      }
      // 多序列 FASTA — 仅取第一条序列
      else if (seqParts.length > 0) {
        warnings.push('检测到多条序列，仅使用第一条');
        break;
      }
    } else if (trimmedLine.startsWith(';')) {
      // FASTA 注释行，跳过
      continue;
    } else {
      seqParts.push(trimmedLine);
    }
  }

  const sequence = seqParts.join('');
  return { sequence, title, warnings };
}

/** 解析 GenBank 格式 */
function parseGenBank(text: string): { sequence: string; locus: string; warnings: string[] } {
  const warnings: string[] = [];
  let locus = '';

  // 提取 LOCUS 行
  const locusMatch = text.match(/^LOCUS\s+(.+)$/m);
  if (locusMatch) {
    locus = locusMatch[1].trim();
  }

  // 提取 ORIGIN...// 区段
  const originMatch = text.match(/ORIGIN[\s\S]*?\/\//);
  if (!originMatch) {
    warnings.push('未找到 ORIGIN 区段，尝试解析全文序列');
    return { sequence: cleanSequence(text), locus, warnings };
  }

  // ORIGIN 区段内：去除数字和空白，保留字母
  const originBlock = originMatch[0]
    .replace(/^ORIGIN\s*/, '')
    .replace(/\/\//, '')
    .replace(/[\d\s]/g, '');

  const sequence = originBlock.toUpperCase();
  return { sequence, locus, warnings };
}

/** 清理序列字符串：去除空白、数字，转大写 */
function cleanSequence(text: string): string {
  return text
    .replace(/[\d\s\r\n]/g, '') // 去除数字和空白
    .replace(/[^A-Za-z]/g, '') // 去除非字母字符
    .toUpperCase();
}

/** 验证氨基酸字母表，返回非法字符集合 */
function validateAminoAcids(sequence: string): string[] {
  const invalid = new Set<string>();
  for (const char of sequence) {
    if (!VALID_AA.has(char)) {
      invalid.add(char);
    }
  }
  return Array.from(invalid);
}
