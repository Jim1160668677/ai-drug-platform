'use client';

/**
 * SequenceInput — 突变蛋白序列输入组件
 *
 * 支持：
 *   1. 手工输入（textarea）
 *   2. 文件上传（FASTA/GenBank/TXT）
 *   3. 拖拽上传
 *   4. 自动解析 + 验证（调用 sequenceParser）
 *   5. 解析后显示格式标签、序列长度、验证警告
 *
 * 用法：
 *   <SequenceInput value={seq} onChange={setSeq} placeholder="MKWVTIAVL..." />
 */

import { useState, useCallback, useRef } from 'react';
import { parseSequenceFile, type SequenceParseResult } from '@/lib/utils/sequenceParser';
import { Upload, FileText, AlertCircle, CheckCircle2 } from 'lucide-react';

const ACCEPTED_EXTS = ['.fasta', '.fa', '.genbank', '.gb', '.txt'];
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5MB

export interface SequenceInputProps {
  /** 当前序列值 */
  value: string;
  /** 序列变化回调 */
  onChange: (seq: string) => void;
  /** 占位文本 */
  placeholder?: string;
  /** textarea 行数 */
  rows?: number;
  /** 自定义类名 */
  className?: string;
}

export default function SequenceInput({
  value,
  onChange,
  placeholder = 'MKWVTIAVLCLAVL...',
  rows = 3,
  className = '',
}: SequenceInputProps) {
  const [parsed, setParsed] = useState<SequenceParseResult | null>(null);
  const [fileName, setFileName] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      setError('');
      if (file.size === 0) {
        setError('文件为空');
        return;
      }
      if (file.size > MAX_SIZE_BYTES) {
        setError(`文件超过 ${MAX_SIZE_BYTES / 1024 / 1024}MB 限制`);
        return;
      }
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      if (!ACCEPTED_EXTS.includes(ext)) {
        setError(`不支持的文件扩展名 ${ext}，请上传 ${ACCEPTED_EXTS.join('/')} 文件`);
        return;
      }

      const reader = new FileReader();
      reader.onload = () => {
        const text = String(reader.result || '');
        const result = parseSequenceFile(text);
        setParsed(result);
        setFileName(file.name);
        if (result.sequence) {
          onChange(result.sequence);
        } else if (result.warnings.length > 0) {
          setError(result.warnings.join('; '));
        }
      };
      reader.onerror = () => setError('文件读取失败');
      reader.readAsText(file);
    },
    [onChange],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    // 重置 input 以便重复选择同一文件
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const formatLabel = parsed
    ? parsed.format === 'fasta'
      ? 'FASTA'
      : parsed.format === 'genbank'
        ? 'GenBank'
        : parsed.format === 'plain'
          ? '纯序列'
          : '未知'
    : '';

  return (
    <div className={`space-y-2 ${className}`}>
      {/* 文件上传区 */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex items-center gap-2 p-2 border border-dashed rounded text-xs cursor-pointer transition-colors ${
          dragOver
            ? 'border-primary-500 bg-primary-50'
            : 'border-gray-300 hover:border-primary-400 bg-gray-50'
        }`}
        onClick={() => fileInputRef.current?.click()}
      >
        <Upload className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-gray-500">
          点击或拖拽上传 FASTA/GenBank 文件（{ACCEPTED_EXTS.join('/')}）
        </span>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTS.join(',')}
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* 文件信息 */}
      {fileName && parsed && (
        <div className="flex items-center gap-2 text-xs">
          <FileText className="w-3.5 h-3.5 text-blue-500" />
          <span className="text-gray-700 font-medium">{fileName}</span>
          <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">{formatLabel}</span>
          <span className="text-gray-500">{parsed.metadata.length} aa</span>
          {parsed.warnings.length === 0 ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
          ) : (
            <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
          )}
        </div>
      )}

      {/* 文本输入 */}
      <textarea
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          // 手工输入时清除文件解析状态
          if (fileName) {
            setFileName('');
            setParsed(null);
          }
        }}
        placeholder={placeholder}
        rows={rows}
        className="w-full px-3 py-2 border rounded font-mono text-sm focus:outline-none focus:border-primary-400"
      />

      {/* 警告信息 */}
      {error && (
        <div className="flex items-center gap-1.5 text-xs text-red-600">
          <AlertCircle className="w-3.5 h-3.5" />
          {error}
        </div>
      )}
      {parsed && parsed.warnings.length > 0 && !error && (
        <div className="flex items-start gap-1.5 text-xs text-amber-600">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{parsed.warnings.join('; ')}</span>
        </div>
      )}
    </div>
  );
}
