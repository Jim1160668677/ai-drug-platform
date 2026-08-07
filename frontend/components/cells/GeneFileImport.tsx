'use client';

/**
 * GeneFileImport — 基因符号列表文件导入组件
 *
 * 支持上传 TXT/CSV/TSV 文件，读取文本内容并回调。
 * 配合 geneListParser 在父组件中解析验证。
 *
 * 用法：
 *   <GeneFileImport onGenesLoaded={(text) => setGeneInput(text)} />
 */

import { useRef, useState } from 'react';
import { Upload, AlertCircle } from 'lucide-react';

const ACCEPTED_EXTS = ['.txt', '.csv', '.tsv'];
const MAX_SIZE_BYTES = 2 * 1024 * 1024; // 2MB

export interface GeneFileImportProps {
  /** 文件读取完成回调，返回原始文本 */
  onGenesLoaded: (text: string) => void;
  className?: string;
}

export default function GeneFileImport({
  onGenesLoaded,
  className = '',
}: GeneFileImportProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const [dragOver, setDragOver] = useState(false);

  const handleFile = (file: File) => {
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
      setError(`不支持的扩展名 ${ext}，请上传 ${ACCEPTED_EXTS.join('/')} 文件`);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      setFileName(file.name);
      onGenesLoaded(text);
    };
    reader.onerror = () => setError('文件读取失败');
    reader.readAsText(file);
  };

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className={className}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`flex items-center gap-2 p-2 border border-dashed rounded text-xs cursor-pointer transition-colors ${
          dragOver
            ? 'border-primary-500 bg-primary-50'
            : 'border-gray-300 hover:border-primary-400 bg-gray-50'
        }`}
      >
        <Upload className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-gray-500">
          {fileName
            ? `已加载: ${fileName}（点击重新上传）`
            : `上传基因列表文件（${ACCEPTED_EXTS.join('/')}，逗号或换行分隔）`}
        </span>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTS.join(',')}
          onChange={handleSelect}
          className="hidden"
        />
      </div>
      {error && (
        <div className="flex items-center gap-1.5 text-xs text-red-600 mt-1">
          <AlertCircle className="w-3.5 h-3.5" />
          {error}
        </div>
      )}
    </div>
  );
}
