'use client';

import { useState, useRef, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { UploadCloud, FileText, X } from 'lucide-react';
import { uploadGenome } from '@/lib/api';
import Button from '@/components/ui/Button';
import ProgressBar from '@/components/ui/ProgressBar';

interface GenomeUploaderProps {
  /** 上传成功回调 */
  onUploaded?: (genome: any) => void;
  /** 关联项目 ID（可选） */
  projectId?: string;
  /** 默认基因组版本 */
  defaultGenomeBuild?: string;
}

const ACCEPTED_EXTS = ['.txt', '.csv', '.tsv', '.zip'];
const MAX_SIZE_BYTES = 50 * 1024 * 1024; // 50MB

export default function GenomeUploader({
  onUploaded,
  projectId,
  defaultGenomeBuild = 'GRCh37',
}: GenomeUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [genomeBuild, setGenomeBuild] = useState(defaultGenomeBuild);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadGenome(file, { genomeBuild, projectId }),
    onSuccess: (data) => {
      const genome = data?.data ?? data;
      import('@/lib/notification').then(({ toast }) => {
        toast.success('上传成功', `文件 ${genome?.file_name || ''} 已解析完成`);
      });
      setSelectedFile(null);
      onUploaded?.(genome);
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || err?.message || '上传失败，请稍后重试';
      setErrorMsg(msg);
      import('@/lib/notification').then(({ toast }) => {
        toast.error('上传失败', msg);
      });
    },
  });

  const validateFile = useCallback((file: File): string | null => {
    if (file.size === 0) return '文件为空';
    if (file.size > MAX_SIZE_BYTES) {
      return `文件大小 ${(file.size / 1024 / 1024).toFixed(1)}MB 超过上限 50MB`;
    }
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!ACCEPTED_EXTS.includes(ext)) {
      return `不支持的文件类型 ${ext}，允许：${ACCEPTED_EXTS.join(', ')}`;
    }
    return null;
  }, []);

  const handleFile = useCallback(
    (file: File) => {
      setErrorMsg('');
      const err = validateFile(file);
      if (err) {
        setErrorMsg(err);
        return;
      }
      setSelectedFile(file);
    },
    [validateFile]
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    // 重置 input 以支持重复选择同一文件
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleUpload = () => {
    if (!selectedFile) return;
    uploadMutation.mutate(selectedFile);
  };

  return (
    <div className="space-y-3">
      <div
        className={`relative rounded-xl border-2 border-dashed p-8 text-center transition-colors cursor-pointer ${
          isDragging
            ? 'border-primary-500 bg-primary-50'
            : 'border-gray-300 bg-gray-50 hover:border-primary-300 hover:bg-gray-100/50'
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTS.join(',')}
          className="hidden"
          onChange={handleInputChange}
        />
        <UploadCloud className="w-12 h-12 mx-auto mb-3 text-gray-400" />
        <div className="text-sm font-medium text-gray-700">
          点击或拖拽文件到此处上传
        </div>
        <div className="text-xs text-gray-500 mt-1">
          支持 23andme / ancestry / wechat_gene / generic 格式
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          允许扩展名：{ACCEPTED_EXTS.join(' / ')} · 上限 50MB
        </div>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-600">基因组版本：</label>
        <select
          value={genomeBuild}
          onChange={(e) => setGenomeBuild(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1 text-sm"
          disabled={uploadMutation.isPending}
        >
          <option value="GRCh37">GRCh37 (hg19)</option>
          <option value="GRCh38">GRCh38 (hg38)</option>
        </select>
      </div>

      {selectedFile && (
        <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-3">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <FileText className="w-5 h-5 text-primary-600 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-gray-900 truncate">
                {selectedFile.name}
              </div>
              <div className="text-xs text-gray-500">
                {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              loading={uploadMutation.isPending}
              onClick={handleUpload}
              disabled={uploadMutation.isPending}
            >
              <UploadCloud className="w-4 h-4" />
              上传并解析
            </Button>
            <button
              onClick={() => setSelectedFile(null)}
              disabled={uploadMutation.isPending}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {errorMsg && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
          {errorMsg}
        </div>
      )}

      {uploadMutation.isPending && (
        <ProgressBar status="running" percent={50} message="正在上传并解析文件..." />
      )}
    </div>
  );
}
