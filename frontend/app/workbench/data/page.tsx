'use client';

import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, FileText, Play, BarChart3, X, Trash2, Microscope, Dna, AlertTriangle, CheckCircle, Info, FlaskConical, Download } from 'lucide-react';
import { getDatasets, uploadData, parseDataset, getQuality, deleteDataset, analyzeDataset, exportDataset } from '@/lib/api';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import PlotlyChart from '@/components/charts/PlotlyChart';
import ProgressBar from '@/components/ui/ProgressBar';

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
  const [bioinfoModal, setBioinfoModal] = useState<string | null>(null);
  const [analysisModal, setAnalysisModal] = useState<string | null>(null);
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
        <p className="text-sm text-gray-500 mt-1">多组学数据接入与解析（RNA-seq / scRNA-seq / WES / WGS / VCF / FASTA / 蛋白质组学 / 代谢组学 / 临床影像 / 临床检验等）</p>
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
              <option value="rna_seq">RNA-seq（转录组）</option>
              <option value="scrna_seq">scRNA-seq（单细胞测序）</option>
              <option value="wes">WES（全外显子测序）</option>
              <option value="wgs">WGS（全基因组测序）</option>
              <option value="vcf">VCF（变异文件）</option>
              <option value="fasta">FASTA（序列）</option>
              <option value="proteomics">蛋白质组学</option>
              <option value="metabolomics">代谢组学</option>
              <option value="gene_report">基因报告 (PDF/图片)</option>
              <option value="ihc">免疫组化 (IHC)</option>
              <option value="imaging">临床影像</option>
              <option value="clinical_lab">临床检验</option>
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
              accept=".csv,.tsv,.h5,.mtx,.vcf,.fasta,.fa,.pdf,.png,.jpg,.xlsx,.xls,.txt,.tiff,.dcm"
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
        {parseMutation.isPending && (
          <div className="mb-3">
            <ProgressBar
              status="running"
              percent={50}
              message="正在解析数据集..."
            />
          </div>
        )}
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
                          variant="secondary"
                          onClick={() => setBioinfoModal(d.id)}
                        >
                          <Microscope className="w-3 h-3" /> 生信分析
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setAnalysisModal(d.id)}
                        >
                          <FlaskConical className="w-3 h-3" /> 高级分析
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

      {/* 生信分析报告弹窗 */}
      {bioinfoModal && (
        <BioinfoReport datasetId={bioinfoModal} onClose={() => setBioinfoModal(null)} />
      )}

      {/* 高级分析面板 */}
      {analysisModal && (
        <AnalysisPanel datasetId={analysisModal} onClose={() => setAnalysisModal(null)} />
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

// ========== 生信分析报告组件 ==========
function BioinfoReport({ datasetId, onClose }: { datasetId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['quality', datasetId],
    queryFn: () => getQuality(datasetId),
  });

  const metrics = data?.data?.quality_metrics || {};
  const summary = data?.data?.parsed_summary || {};
  const parseStatus = data?.data?.parse_status || 'pending';

  // 根据数据类型和数据内容生成生信分析结论
  const analysis = generateBioinfoAnalysis(metrics, summary, parseStatus);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-4xl w-full max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <Dna className="w-5 h-5 text-primary-600" /> 自动化生信分析报告
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="text-center py-12 text-gray-400">分析中...</div>
        ) : parseStatus !== 'completed' ? (
          <div className="p-5">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-yellow-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-yellow-900">数据尚未解析</p>
                <p className="text-sm text-yellow-700 mt-1">
                  请先点击「解析」按钮完成数据解析，然后才能进行生信分析。当前状态：{parseStatus}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-5 space-y-5">
            {/* 分析概览 */}
            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
              <h4 className="font-semibold text-blue-900 mb-2 flex items-center gap-2">
                <Info className="w-4 h-4" /> 分析概览
              </h4>
              <p className="text-sm text-gray-700">{analysis.overview}</p>
            </div>

            {/* 关键发现 */}
            <div>
              <h4 className="font-semibold mb-3 flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-green-600" /> 关键发现
              </h4>
              <div className="space-y-2">
                {analysis.findings.map((f: any, i: number) => (
                  <div key={i} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                      f.level === 'high' ? 'bg-red-100 text-red-700' :
                      f.level === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-green-100 text-green-700'
                    }`}>
                      {i + 1}
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-gray-900">{f.title}</div>
                      <div className="text-xs text-gray-600 mt-1">{f.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 质量评估解读 */}
            {Object.keys(metrics).length > 0 && (
              <div>
                <h4 className="font-semibold mb-3">质量评估解读</h4>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {analysis.qualityInterpretation.map((q: any, i: number) => (
                    <div key={i} className={`p-3 rounded-lg border ${q.pass ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
                      <div className="flex items-center gap-2 mb-1">
                        {q.pass ? (
                          <CheckCircle className="w-4 h-4 text-green-600" />
                        ) : (
                          <AlertTriangle className="w-4 h-4 text-red-600" />
                        )}
                        <span className="text-xs font-medium text-gray-700">{q.name}</span>
                      </div>
                      <div className="text-lg font-bold text-gray-900">{q.value}</div>
                      <div className="text-xs text-gray-500 mt-1">{q.interpretation}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 数据摘要统计 */}
            {Object.keys(summary).length > 0 && (
              <div>
                <h4 className="font-semibold mb-3">数据统计摘要</h4>
                <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                  {analysis.summaryStats.map((s: any, i: number) => (
                    <div key={i} className="flex justify-between text-sm">
                      <span className="text-gray-600">{s.label}</span>
                      <span className="font-medium text-gray-900">{s.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 分析结论 */}
            <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
              <h4 className="font-semibold text-indigo-900 mb-2">分析结论</h4>
              <ul className="space-y-2">
                {analysis.conclusions.map((c: string, i: number) => (
                  <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                    <span className="text-indigo-600 font-bold shrink-0">•</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* 建议 */}
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
              <h4 className="font-semibold text-amber-900 mb-2">下一步建议</h4>
              <ul className="space-y-2">
                {analysis.recommendations.map((r: string, i: number) => (
                  <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                    <span className="text-amber-600 font-bold shrink-0">→</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 生信分析结论生成器
function generateBioinfoAnalysis(metrics: any, summary: any, parseStatus: string) {
  const dataType = summary?.data_type || summary?.file_format || '未知';
  const totalReads = metrics?.total_reads || metrics?.total_variants || summary?.total_reads || 0;
  const mappedReads = metrics?.mapped_reads || summary?.mapped_reads || 0;
  const mappingRate = totalReads > 0 ? (mappedReads / totalReads * 100) : 0;
  const qcRate = metrics?.qc_pass_rate || metrics?.quality_score || 0;
  const duplicationRate = metrics?.duplication_rate || 0;
  const totalGenes = summary?.total_genes || summary?.gene_count || metrics?.n_genes || 0;
  const totalVariants = summary?.total_variants || metrics?.total_variants || 0;
  const clusters = summary?.n_clusters || summary?.clusters?.length || 0;

  const findings: any[] = [];
  const qualityInterpretation: any[] = [];
  const summaryStats: any[] = [];
  const conclusions: string[] = [];
  const recommendations: string[] = [];

  // 质量指标解读
  if (mappingRate > 0) {
    const pass = mappingRate >= 80;
    qualityInterpretation.push({
      name: '比对率',
      value: `${mappingRate.toFixed(1)}%`,
      pass,
      interpretation: pass ? '比对率良好，数据质量达标' : '比对率偏低，可能存在污染或质量问题',
    });
  }
  if (qcRate > 0) {
    const pass = qcRate >= 85;
    qualityInterpretation.push({
      name: '质控通过率',
      value: `${qcRate.toFixed(1)}%`,
      pass,
      interpretation: pass ? '质控通过率高，数据可信度强' : '质控通过率偏低，需关注低质量数据',
    });
  }
  if (duplicationRate > 0) {
    const pass = duplicationRate < 20;
    qualityInterpretation.push({
      name: '重复率',
      value: `${duplicationRate.toFixed(1)}%`,
      pass,
      interpretation: pass ? '重复率正常，文库复杂度良好' : '重复率偏高，文库复杂度可能不足',
    });
  }
  if (totalReads > 0) {
    const pass = totalReads >= 10000000;
    qualityInterpretation.push({
      name: '总读数',
      value: totalReads > 1000000 ? `${(totalReads / 1000000).toFixed(1)}M` : totalReads.toLocaleString(),
      pass,
      interpretation: pass ? '测序深度充足' : '测序深度偏低，可能影响下游分析',
    });
  }

  // 关键发现
  if (totalGenes > 0) {
    findings.push({
      level: totalGenes > 15000 ? 'high' : 'medium',
      title: `检测到 ${totalGenes.toLocaleString()} 个基因表达`,
      detail: totalGenes > 15000
        ? '基因检出率高，覆盖了大部分人类基因组（约2万个蛋白编码基因），数据质量优秀，可用于差异表达分析和通路富集分析。'
        : '基因检出率中等，建议检查测序深度和比对参数。对于下游分析，建议关注高表达基因。',
    });
  }
  if (totalVariants > 0) {
    findings.push({
      level: totalVariants > 1000 ? 'high' : 'medium',
      title: `识别到 ${totalVariants.toLocaleString()} 个变异`,
      detail: totalVariants > 1000
        ? '变异检出数量丰富，包含SNV、Indel等多种类型。建议进一步进行功能注释和临床意义分级。'
        : '变异检出数量适中，建议关注已知致病性变异和药物靶点相关变异。',
    });
  }
  if (clusters > 0) {
    findings.push({
      level: 'medium',
      title: `单细胞聚类识别 ${clusters} 个细胞亚群`,
      detail: `成功识别出 ${clusters} 个不同的细胞亚群，可用于细胞类型注释和肿瘤异质性分析。建议进行标记基因分析和通路富集。`,
    });
  }
  if (mappingRate > 0 && mappingRate < 80) {
    findings.push({
      level: 'high',
      title: '比对率偏低告警',
      detail: `比对率仅为 ${mappingRate.toFixed(1)}%，低于推荐阈值80%。可能原因：参考基因组不匹配、样本污染、接头序列残留。建议检查样本质量和比对参数。`,
    });
  }
  if (duplicationRate > 20) {
    findings.push({
      level: 'medium',
      title: '文库复杂度偏低',
      detail: `重复率 ${duplicationRate.toFixed(1)}% 高于推荐阈值20%。可能原因：上机浓度偏低、PCR扩增过度。建议增加上机量或优化文库构建流程。`,
    });
  }

  // 摘要统计
  if (totalReads > 0) {
    summaryStats.push({ label: '总测序读数', value: totalReads > 1000000 ? `${(totalReads / 1000000).toFixed(2)} M` : totalReads.toLocaleString() });
  }
  if (mappedReads > 0) {
    summaryStats.push({ label: '比对读数', value: mappedReads > 1000000 ? `${(mappedReads / 1000000).toFixed(2)} M` : mappedReads.toLocaleString() });
  }
  if (totalGenes > 0) {
    summaryStats.push({ label: '检出基因数', value: totalGenes.toLocaleString() });
  }
  if (totalVariants > 0) {
    summaryStats.push({ label: '检出变异数', value: totalVariants.toLocaleString() });
  }
  if (clusters > 0) {
    summaryStats.push({ label: '细胞亚群数', value: `${clusters} 个` });
  }
  Object.keys(summary).forEach((key) => {
    if (!['total_reads', 'mapped_reads', 'total_genes', 'gene_count', 'total_variants', 'n_clusters', 'clusters', 'data_type', 'file_format', 'error'].includes(key)) {
      const val = summary[key];
      if (typeof val === 'number' || typeof val === 'string') {
        summaryStats.push({ label: key.replace(/_/g, ' '), value: String(val) });
      }
    }
  });

  // 分析结论
  if (mappingRate >= 80 || qcRate >= 85) {
    conclusions.push('数据整体质量良好，满足下游生信分析要求，可进行靶点发现和分子设计流程。');
  } else {
    conclusions.push('数据质量存在一定问题，建议优化后再进行深度分析，或结合多组学数据进行综合评估。');
  }
  if (totalGenes > 0) {
    conclusions.push(`成功检出 ${totalGenes.toLocaleString()} 个基因，覆盖了人类基因组的主要功能区域，可用于差异表达分析、通路富集和靶点筛选。`);
  }
  if (totalVariants > 0) {
    conclusions.push(`识别到 ${totalVariants.toLocaleString()} 个基因组变异，建议进一步进行功能注释（如ClinVar、COSMIC）以筛选潜在致病突变和药物靶点变异。`);
  }
  if (clusters > 0) {
    conclusions.push(`单细胞分析识别出 ${clusters} 个细胞亚群，揭示了肿瘤异质性，可用于精准分型和个性化治疗策略制定。`);
  }
  if (conclusions.length === 0) {
    conclusions.push('数据已成功解析，但可用信息有限。建议补充更多组学数据或提高测序深度以获得更全面的分析结果。');
  }

  // 建议
  recommendations.push('将数据接入「靶点发现」模块，利用AI驱动的靶点识别引擎筛选潜在药物靶点。');
  if (totalVariants > 0) {
    recommendations.push('对检出变异进行临床意义分级（I/II/III/IV级），优先关注I级（已获批药物靶点）和II级（临床试验阶段）变异。');
  }
  if (totalGenes > 0) {
    recommendations.push('进行差异表达分析（DEG）和通路富集分析（KEGG/GO），识别异常激活的信号通路。');
  }
  recommendations.push('将分析结果与已知药物数据库（DrugBank、ChEMBL）交叉比对，发现老药新用机会。');
  if (mappingRate < 80 || duplicationRate > 20) {
    recommendations.push('数据质量指标存在告警，建议优化样本制备或测序参数后重新分析。');
  }

  return {
    overview: `本次分析对数据集进行了自动化生信质控和特征提取。数据类型：${dataType}，解析状态：${parseStatus}。共检测到 ${Object.keys(metrics).length} 项质量指标，${Object.keys(summary).length} 项数据摘要。以下为详细分析结果和结论。`,
    findings: findings.length > 0 ? findings : [{ level: 'medium', title: '数据已解析', detail: '数据集已成功解析，但未检测到显著特征。建议检查数据格式或补充更多信息。' }],
    qualityInterpretation,
    summaryStats,
    conclusions,
    recommendations,
  };
}

// ========== 高级分析面板 ==========
function AnalysisPanel({ datasetId, onClose }: { datasetId: string; onClose: () => void }) {
  const [analysisType, setAnalysisType] = useState<'de' | 'clustering' | 'pathway' | 'pca'>('de');
  const [params, setParams] = useState<Record<string, any>>({
    fdr_threshold: 0.05,
    method: 'kmeans',
    n_clusters: 5,
    source: 'kegg',
    n_components: 2,
    group_a: '',
    group_b: '',
    gene_list: '',
  });
  const [result, setResult] = useState<any>(null);

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeDataset(datasetId, analysisType, params),
    onSuccess: (data) => {
      setResult(data);
    },
  });

  const exportMutation = useMutation({
    mutationFn: (format: string) => exportDataset(datasetId, format, analysisType),
    onSuccess: () => {
      toast.success('导出成功', `${analysisType} 分析结果已导出`);
    },
    onError: (err: any) => {
      toast.error('导出失败', err?.response?.data?.error?.message || '请稍后重试');
    },
  });

  const handleAnalyze = () => {
    analyzeMutation.mutate();
  };

  // 构建火山图数据
  const buildVolcanoData = (deResult: any) => {
    const genes = deResult?.genes || deResult?.differential_genes || [];
    if (!genes.length) return null;
    return [
      {
        type: 'scatter',
        mode: 'markers',
        x: genes.map((g: any) => g.log2fc || g.log2_fold_change || 0),
        y: genes.map((g: any) => -Math.log10(g.pvalue || g.p_value || 0.001)),
        text: genes.map((g: any) => g.gene_id || g.name || ''),
        marker: {
          color: genes.map((g: any) =>
            Math.abs(g.log2fc || g.log2_fold_change || 0) > 1 && (g.pvalue || g.p_value || 1) < 0.05
              ? '#ef4444'
              : '#3b82f6'
          ),
          size: 6,
        },
        name: '基因',
      },
    ];
  };

  // 构建聚类散点图
  const buildClusterScatter = (clusterResult: any) => {
    const clusters = clusterResult?.clusters || [];
    if (!clusters.length) return null;
    const colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];
    return clusters.map((c: any, i: number) => ({
      type: 'scatter',
      mode: 'markers',
      x: c.pca_x || c.x || c.coordinates?.[0] || [],
      y: c.pca_y || c.y || c.coordinates?.[1] || [],
      name: `Cluster ${c.cluster_id ?? i + 1}`,
      marker: { color: colors[i % colors.length], size: 8 },
    }));
  };

  // 构建PCA散点图
  const buildPCAScatter = (pcaResult: any) => {
    const points = pcaResult?.points || pcaResult?.components || [];
    if (!points.length) return null;
    return [
      {
        type: 'scatter',
        mode: 'markers',
        x: points.map((p: any) => p.pc1 || p.x || p[0] || 0),
        y: points.map((p: any) => p.pc2 || p.y || p[1] || 0),
        text: points.map((p: any, i: number) => p.label || `Sample ${i + 1}`),
        marker: { color: '#3b82f6', size: 10 },
        name: '样本',
      },
    ];
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-5xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white z-10">
          <h3 className="font-semibold flex items-center gap-2">
            <FlaskConical className="w-5 h-5 text-primary-600" /> 高级生信分析
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* 分析类型选择 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">分析类型</label>
            <div className="flex gap-2">
              {[
                { key: 'de', label: '差异表达分析', desc: 'DEG' },
                { key: 'clustering', label: '聚类分析', desc: 'Clustering' },
                { key: 'pathway', label: '通路富集', desc: 'Pathway' },
                { key: 'pca', label: 'PCA 降维', desc: 'PCA' },
              ].map((t) => (
                <button
                  key={t.key}
                  onClick={() => { setAnalysisType(t.key as any); setResult(null); }}
                  className={`px-3 py-2 rounded-md text-sm border transition ${
                    analysisType === t.key
                      ? 'bg-primary-600 text-white border-primary-600'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  {t.label} <span className="text-xs opacity-70">({t.desc})</span>
                </button>
              ))}
            </div>
          </div>

          {/* 参数配置 */}
          <Card title="参数配置">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {analysisType === 'de' && (
                <>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">A组样本（逗号分隔）</label>
                    <input
                      type="text"
                      value={params.group_a}
                      onChange={(e) => setParams({ ...params, group_a: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                      placeholder="sample1,sample2"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">B组样本（逗号分隔）</label>
                    <input
                      type="text"
                      value={params.group_b}
                      onChange={(e) => setParams({ ...params, group_b: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                      placeholder="sample3,sample4"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">FDR 阈值</label>
                    <input
                      type="number"
                      step="0.01"
                      value={params.fdr_threshold}
                      onChange={(e) => setParams({ ...params, fdr_threshold: parseFloat(e.target.value) })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                    />
                  </div>
                </>
              )}
              {analysisType === 'clustering' && (
                <>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">聚类方法</label>
                    <select
                      value={params.method}
                      onChange={(e) => setParams({ ...params, method: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                    >
                      <option value="kmeans">K-Means</option>
                      <option value="hierarchical">层次聚类</option>
                      <option value="dbscan">DBSCAN</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">簇数量</label>
                    <input
                      type="number"
                      min="2"
                      max="20"
                      value={params.n_clusters}
                      onChange={(e) => setParams({ ...params, n_clusters: parseInt(e.target.value) })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                    />
                  </div>
                </>
              )}
              {analysisType === 'pathway' && (
                <>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">通路数据库</label>
                    <select
                      value={params.source}
                      onChange={(e) => setParams({ ...params, source: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                    >
                      <option value="kegg">KEGG</option>
                      <option value="go">GO</option>
                      <option value="reactome">Reactome</option>
                    </select>
                  </div>
                  <div className="col-span-2">
                    <label className="block text-xs text-gray-600 mb-1">基因列表（逗号分隔，留空使用全部）</label>
                    <input
                      type="text"
                      value={params.gene_list}
                      onChange={(e) => setParams({ ...params, gene_list: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                      placeholder="TP53,EGFR,KRAS"
                    />
                  </div>
                </>
              )}
              {analysisType === 'pca' && (
                <div>
                  <label className="block text-xs text-gray-600 mb-1">主成分数量</label>
                  <input
                    type="number"
                    min="2"
                    max="10"
                    value={params.n_components}
                    onChange={(e) => setParams({ ...params, n_components: parseInt(e.target.value) })}
                    className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                  />
                </div>
              )}
            </div>
            <div className="mt-3 flex gap-2">
              <Button onClick={handleAnalyze} loading={analyzeMutation.isPending}>
                <Play className="w-4 h-4" /> 执行分析
              </Button>
              {result && (
                <>
                  <Button variant="secondary" onClick={() => exportMutation.mutate('csv')} loading={exportMutation.isPending}>
                    <Download className="w-4 h-4" /> 导出 CSV
                  </Button>
                  <Button variant="secondary" onClick={() => exportMutation.mutate('json')} loading={exportMutation.isPending}>
                    <Download className="w-4 h-4" /> 导出 JSON
                  </Button>
                </>
              )}
            </div>
          </Card>

          {/* 结果可视化 */}
          {analyzeMutation.isError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              分析失败：{(analyzeMutation.error as any)?.response?.data?.error?.message || '请检查参数或数据'}
            </div>
          )}

          {result && (
            <Card title="分析结果">
              {/* DE 火山图 */}
              {analysisType === 'de' && buildVolcanoData(result?.result || result) && (
                <PlotlyChart
                  data={buildVolcanoData(result?.result || result)!}
                  layout={{
                    title: { text: '火山图（Volcano Plot）' },
                    xaxis: { title: 'log2 Fold Change' },
                    yaxis: { title: '-log10(p-value)' },
                    margin: { t: 40, b: 50, l: 50, r: 20 },
                    height: 400,
                  }}
                />
              )}

              {/* 聚类散点图 */}
              {analysisType === 'clustering' && buildClusterScatter(result?.result || result) && (
                <PlotlyChart
                  data={buildClusterScatter(result?.result || result)!}
                  layout={{
                    title: { text: '聚类结果（PCA 投影）' },
                    xaxis: { title: 'PC1' },
                    yaxis: { title: 'PC2' },
                    margin: { t: 40, b: 50, l: 50, r: 20 },
                    height: 400,
                  }}
                />
              )}

              {/* 通路富集表格 */}
              {analysisType === 'pathway' && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200 text-gray-500">
                        <th className="text-left py-2 px-3">通路名称</th>
                        <th className="text-left py-2 px-3">来源</th>
                        <th className="text-left py-2 px-3">基因数</th>
                        <th className="text-left py-2 px-3">p-value</th>
                        <th className="text-left py-2 px-3">FDR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {((result?.result || result)?.pathways || []).map((p: any, i: number) => (
                        <tr key={i} className="border-b border-gray-100">
                          <td className="py-2 px-3 font-medium">{p.name || p.pathway_id}</td>
                          <td className="py-2 px-3">{p.source || 'KEGG'}</td>
                          <td className="py-2 px-3">{p.gene_count || p.count || 0}</td>
                          <td className="py-2 px-3">{(p.pvalue || 0).toFixed(4)}</td>
                          <td className="py-2 px-3">{(p.fdr || p.adj_pvalue || 0).toFixed(4)}</td>
                        </tr>
                      ))}
                      {(!((result?.result || result)?.pathways || []).length) && (
                        <tr>
                          <td colSpan={5} className="py-4 text-center text-gray-400">暂无通路富集结果</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              {/* PCA 散点图 */}
              {analysisType === 'pca' && buildPCAScatter(result?.result || result) && (
                <PlotlyChart
                  data={buildPCAScatter(result?.result || result)!}
                  layout={{
                    title: { text: 'PCA 降维结果' },
                    xaxis: { title: 'PC1' },
                    yaxis: { title: 'PC2' },
                    margin: { t: 40, b: 50, l: 50, r: 20 },
                    height: 400,
                  }}
                />
              )}

              {/* 原始结果 JSON */}
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-gray-600">查看原始结果 JSON</summary>
                <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-x-auto mt-2 max-h-60 overflow-y-auto">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
