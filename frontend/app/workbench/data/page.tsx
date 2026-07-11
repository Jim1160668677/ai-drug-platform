'use client';

import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, FileText, Play, BarChart3, X, Trash2 } from 'lucide-react';
import { getDatasets, uploadData, parseDataset, getQuality, deleteDataset } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';

export default function DataPage() {
  const { currentProject } = useAppStore();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [uploadForm, setUploadForm] = useState({
    name: '',
    dataType: 'rna_seq',
    source: '',
  });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [qualityModal, setQualityModal] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const { data: datasets, isLoading } = useQuery({
    queryKey: ['datasets', currentProject?.id],
    queryFn: () => getDatasets(currentProject?.id),
    enabled: !!currentProject,
  });

  const uploadMutation = useMutation({
    mutationFn: () =>
      uploadData({
        projectId: currentProject!.id,
        name: uploadForm.name,
        dataType: uploadForm.dataType,
        source: uploadForm.source,
        file: selectedFile!,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
      setUploadForm({ name: '', dataType: 'rna_seq', source: '' });
      setSelectedFile(null);
      if (fileRef.current) fileRef.current.value = '';
      toast.success('上传成功', '数据集已上传');
    },
    onError: (err: any) => {
      toast.error('上传失败', err?.response?.data?.error?.message || '请检查文件格式');
    },
  });

  const parseMutation = useMutation({
    mutationFn: (id: string) => parseDataset(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
      toast.success('解析完成', '数据集解析已触发');
    },
    onError: (err: any) => {
      toast.error('解析失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDataset(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] });
      toast.success('删除成功', '数据集已删除');
    },
    onError: (err: any) => {
      toast.error('删除失败', err?.response?.data?.error?.message || '无权删除或数据集不存在');
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setSelectedFile(f);
      if (!uploadForm.name) setUploadForm((s) => ({ ...s, name: f.name.replace(/\.[^.]+$/, '') }));
    }
  };

  const handleUpload = () => {
    if (!selectedFile || !uploadForm.name || !currentProject) return;
    uploadMutation.mutate();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">数据管理</h1>
        <p className="text-sm text-gray-500 mt-1">多组学数据接入与解析（RNA-seq / scRNA-seq / WES / FASTA）</p>
      </div>

      {/* 上传区 */}
      <Card title="上传新数据">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">数据名称</label>
            <input
              type="text"
              value={uploadForm.name}
              onChange={(e) => setUploadForm((s) => ({ ...s, name: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              placeholder="例如：NSCLC RNA-seq"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">数据类型</label>
            <select
              value={uploadForm.dataType}
              onChange={(e) => setUploadForm((s) => ({ ...s, dataType: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="rna_seq">RNA-seq</option>
              <option value="scrna_seq">scRNA-seq</option>
              <option value="wes">WES (VCF)</option>
              <option value="fasta">FASTA</option>
              <option value="gene_report">基因报告 (PDF/图片)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">数据来源</label>
            <input
              type="text"
              value={uploadForm.source}
              onChange={(e) => setUploadForm((s) => ({ ...s, source: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              placeholder="例如：Illumina NovaSeq"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">文件</label>
            <input
              ref={fileRef}
              type="file"
              onChange={handleFileChange}
              className="w-full text-sm"
              accept=".csv,.tsv,.h5,.mtx,.vcf,.fasta,.fa,.pdf,.png,.jpg"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <Button
            onClick={handleUpload}
            loading={uploadMutation.isPending}
            disabled={!selectedFile || !uploadForm.name}
          >
            <Upload className="w-4 h-4" /> 上传
          </Button>
        </div>
        {uploadMutation.isError && (
          <div className="mt-2 text-sm text-danger">
            上传失败：{(uploadMutation.error as any)?.response?.data?.detail || '未知错误'}
          </div>
        )}
      </Card>

      {/* 数据集列表 */}
      <Card title={`数据集列表 (${datasets?.length || 0})`}>
        {isLoading ? (
          <div className="text-center py-8 text-gray-400">加载中...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-gray-500">
                  <th className="text-left py-2 px-3">名称</th>
                  <th className="text-left py-2 px-3">类型</th>
                  <th className="text-left py-2 px-3">格式</th>
                  <th className="text-left py-2 px-3">大小</th>
                  <th className="text-left py-2 px-3">状态</th>
                  <th className="text-left py-2 px-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {datasets?.map((d: any) => (
                  <tr key={d.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-3">
                      <div className="font-medium text-gray-800">{d.name}</div>
                      <div className="text-xs text-gray-400">{d.source}</div>
                    </td>
                    <td className="py-2 px-3">{d.data_type}</td>
                    <td className="py-2 px-3 font-mono text-xs">{d.file_format}</td>
                    <td className="py-2 px-3 text-xs">
                      {d.file_size ? `${(d.file_size / 1024).toFixed(1)} KB` : '—'}
                    </td>
                    <td className="py-2 px-3">
                      <Badge
                        variant="status"
                        value={
                          d.parse_status === 'completed'
                            ? 'completed'
                            : d.parse_status === 'parsing'
                              ? 'running'
                              : d.parse_status === 'failed'
                                ? 'failed'
                                : 'planned'
                        }
                      />
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={parseMutation.isPending}
                          onClick={() => parseMutation.mutate(d.id)}
                        >
                          <Play className="w-3 h-3" /> 解析
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setQualityModal(d.id)}
                        >
                          <BarChart3 className="w-3 h-3" /> 质量
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={deleteMutation.isPending}
                          onClick={() => setDeleteTarget({ id: d.id, name: d.name })}
                        >
                          <Trash2 className="w-3 h-3" /> 删除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(!datasets || datasets.length === 0) && (
              <div className="text-center py-8 text-gray-400">
                <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
                暂无数据集
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 质量报告弹窗 */}
      {qualityModal && (
        <QualityModal datasetId={qualityModal} onClose={() => setQualityModal(null)} />
      )}

      {/* 删除确认弹窗 — 替代 native confirm()，避免中文乱码 */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-md w-full">
            <div className="flex items-center justify-between px-5 py-3 border-b">
              <h3 className="font-semibold text-gray-900">确认删除</h3>
              <button onClick={() => setDeleteTarget(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5">
              <p className="text-sm text-gray-700">
                确认删除数据集「<span className="font-medium">{deleteTarget.name}</span>」？此操作不可撤销。
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
                  取消
                </Button>
                <Button
                  variant="danger"
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    deleteMutation.mutate(deleteTarget.id);
                    setDeleteTarget(null);
                  }}
                >
                  <Trash2 className="w-4 h-4" /> 确认删除
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function QualityModal({ datasetId, onClose }: { datasetId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['quality', datasetId],
    queryFn: () => getQuality(datasetId),
  });

  const metrics = data?.data?.quality_metrics || {};
  const summary = data?.data?.parsed_summary || {};

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold">数据质量报告</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {isLoading ? (
            <div className="text-center py-8 text-gray-400">加载中...</div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {Object.entries(metrics).map(([k, v]: any) => (
                  <div key={k} className="bg-gray-50 rounded p-3">
                    <div className="text-xs text-gray-500">{k}</div>
                    <div className="text-lg font-semibold">{typeof v === 'number' ? v.toFixed(3) : String(v)}</div>
                  </div>
                ))}
              </div>
              {summary && Object.keys(summary).length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">解析摘要</h4>
                  <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto">
                    {JSON.stringify(summary, null, 2)}
                  </pre>
                </div>
              )}
              {Object.keys(metrics).length > 0 && (
                <PlotlyChart
                  data={[
                    {
                      type: 'bar',
                      x: Object.keys(metrics),
                      y: Object.values(metrics).map((v: any) => (typeof v === 'number' ? v : 0)),
                      marker: { color: '#2563eb' },
                    },
                  ]}
                  layout={{
                    title: { text: '质量指标' },
                    margin: { t: 40, b: 40, l: 40, r: 20 },
                    height: 300,
                  }}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
