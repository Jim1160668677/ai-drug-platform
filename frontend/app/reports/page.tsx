'use client';

import { useState, useMemo } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  FileText, Download, Database, BarChart3, Database as DBIcon,
  Target as TargetIcon, GitBranch, FlaskConical, HeartPulse,
  CheckCircle, XCircle, AlertTriangle, Printer, Layers,
  ChevronDown, ChevronRight, FileSpreadsheet, FileJson,
  Sparkles, ListChecks, Activity,
} from 'lucide-react';
import { exportSDTM, exportADaM, exportFHIR, validateSDTM, getProjectSummary, getProjects } from '@/lib/api';
import { useQuery } from '@tanstack/react-query';
import { useAppStore } from '@/lib/store';
import { toast } from '@/lib/notification';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import PlotlyChart from '@/components/charts/PlotlyChart';

// 通用下载助手
function downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadJSONFile(data: any, filename: string) {
  downloadBlob(JSON.stringify(data, null, 2), filename, 'application/json;charset=utf-8');
}

// 通用 CSV 生成（带表头注释）
function buildCSV(
  sections: { header: string; comment?: string; rows: Record<string, any>[] }[]
): string {
  const lines: string[] = [];
  for (const section of sections) {
    if (section.comment) {
      for (const c of section.comment.split('\n')) lines.push(`# ${c}`);
      lines.push('');
    }
    lines.push(`--- ${section.header} ---`);
    if (!section.rows.length) {
      lines.push('(无数据)');
      lines.push('');
      continue;
    }
    const fields = Object.keys(section.rows[0]);
    lines.push(fields.join(','));
    for (const row of section.rows) {
      lines.push(fields.map((f) => `"${String(row[f] ?? '').replace(/"/g, '""')}"`).join(','));
    }
    lines.push('');
  }
  return lines.join('\n');
}

// HTML 表格生成（用于 .xls 导出 — Excel 可直接打开）
function buildHTMLTable(title: string, rows: Record<string, any>[]): string {
  if (!rows.length) return `<h3>${title}</h3><p>无数据</p>`;
  const fields = Object.keys(rows[0]);
  const thead = fields.map((f) => `<th>${f}</th>`).join('');
  const tbody = rows.map((r) =>
    `<tr>${fields.map((f) => `<td>${String(r[f] ?? '').replace(/</g, '&lt;')}</td>`).join('')}</tr>`
  ).join('');
  return `<h3>${title} (${rows.length} 条)</h3><table border="1"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

export default function ReportsPage() {
  const { currentProject } = useAppStore();
  const [sdtmData, setSdtmData] = useState<any>(null);
  const [adamData, setAdamData] = useState<any>(null);
  const [csvContent, setCsvContent] = useState<string>('');
  const [fhirData, setFhirData] = useState<any>(null);
  const [validationData, setValidationData] = useState<any>(null);
  const [showValidation, setShowValidation] = useState(false);
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());
  const [expandedDatasets, setExpandedDatasets] = useState<Set<string>>(new Set());
  const [fhirResourceFilter, setFhirResourceFilter] = useState<string>('ALL');
  const [fhirShowAll, setFhirShowAll] = useState(false);

  const { data: projects } = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const projectId = currentProject?.id || projects?.[0]?.id;

  const { data: summary, refetch: refetchSummary } = useQuery({
    queryKey: ['project-summary', projectId],
    queryFn: () => getProjectSummary(projectId!),
    enabled: !!projectId,
  });

  const sdtmMutation = useMutation({
    mutationFn: () => exportSDTM(projectId!),
    onSuccess: (res) => {
      const data = res?.data || res;
      setSdtmData(data);
      setCsvContent(data.csv || '');
      toast.success('SDTM 导出完成', '已生成 CDISC SDTM 域');
    },
    onError: (err: any) => {
      toast.error('SDTM 导出失败', err?.response?.data?.detail || err?.message || '请重试');
    },
  });

  const adamMutation = useMutation({
    mutationFn: () => exportADaM(projectId!),
    onSuccess: (res) => {
      const data = res?.data || res;
      setAdamData(data);
      toast.success('ADaM 导出完成', '已生成 ADaM 分析数据集');
    },
    onError: (err: any) => {
      toast.error('ADaM 导出失败', err?.response?.data?.detail || err?.message || '请重试');
    },
  });

  const fhirMutation = useMutation({
    mutationFn: () => exportFHIR(projectId!),
    onSuccess: (res) => {
      const data = res?.data || res;
      setFhirData(data);
      toast.success('FHIR R4 导出完成', `已生成 ${data?.entry?.length || 0} 个资源`);
    },
    onError: (err: any) => {
      toast.error('FHIR 导出失败', err?.response?.data?.detail || err?.message || '请重试');
    },
  });

  const validateMutation = useMutation({
    mutationFn: () => validateSDTM(projectId!),
    onSuccess: (res) => {
      const data = res?.data || res;
      setValidationData(data);
      setShowValidation(true);
      if (data.passed) {
        toast.success('校验通过', 'SDTM 数据符合 FDA 核心规则');
      } else {
        toast.warning('校验未通过', `${data.errors?.length || 0} 个错误需修复`);
      }
    },
    onError: (err: any) => {
      toast.error('校验失败', err?.response?.data?.detail || err?.message || '请重试');
    },
  });

  // 批量生成所有报告
  const generateAll = async () => {
    if (!projectId) return;
    toast.info('开始批量生成', '正在依次生成 SDTM/ADaM/FHIR 报告');
    try {
      await sdtmMutation.mutateAsync();
      await adamMutation.mutateAsync();
      await fhirMutation.mutateAsync();
      toast.success('批量生成完成', '所有报告已生成');
    } catch (e) {
      // 单个 mutation 的 onError 已处理
    }
  };

  // 下载函数集合
  const downloadCSV = () => {
    if (!csvContent) return;
    downloadBlob(csvContent, `sdtm_${projectId}.csv`, 'text/csv;charset=utf-8');
  };

  const downloadSDTMJSON = () => {
    if (!sdtmData) return;
    downloadJSONFile(sdtmData, `sdtm_${projectId}.json`);
  };

  const downloadSDTMXLS = () => {
    if (!sdtmData?.domains) return;
    const meta = sdtmData.metadata || {};
    let html = `<html><head><meta charset="utf-8"></head><body>`;
    html += `<h2>CDISC SDTM Export</h2>`;
    html += `<p>Study: ${meta.study_id || ''} | Version: ${meta.version || 'SDTMIG 3.3'} | Export: ${meta.export_time || ''}</p>`;
    for (const [domain, rows] of Object.entries(sdtmData.domains)) {
      html += buildHTMLTable(`${domain} Domain`, rows as any[]);
    }
    html += `</body></html>`;
    downloadBlob(html, `sdtm_${projectId}.xls`, 'application/vnd.ms-excel;charset=utf-8');
  };

  const downloadAdamCSV = () => {
    if (!adamData?.datasets) return;
    const meta = adamData.metadata || {};
    const sections = Object.entries(adamData.datasets).map(([name, rows]) => ({
      header: `${name} Dataset`,
      comment: `Count: ${(rows as any[]).length}`,
      rows: rows as any[],
    }));
    const csv = `# CDISC ADaM Export\n# Study: ${meta.study_id || ''}\n# ADaM Version: ${meta.adam_version || 'ADaMIG 1.1'}\n# Export Time: ${meta.export_time || ''}\n# Dataset Counts: ${JSON.stringify(meta.dataset_counts || {})}\n\n${buildCSV(sections)}`;
    downloadBlob(csv, `adam_${projectId}.csv`, 'text/csv;charset=utf-8');
  };

  const downloadAdamJSON = () => {
    if (!adamData) return;
    downloadJSONFile(adamData, `adam_${projectId}.json`);
  };

  const downloadAdamXLS = () => {
    if (!adamData?.datasets) return;
    const meta = adamData.metadata || {};
    let html = `<html><head><meta charset="utf-8"></head><body>`;
    html += `<h2>CDISC ADaM Export</h2>`;
    html += `<p>Study: ${meta.study_id || ''} | ADaM: ${meta.adam_version || 'ADaMIG 1.1'} | Export: ${meta.export_time || ''}</p>`;
    for (const [name, rows] of Object.entries(adamData.datasets)) {
      html += buildHTMLTable(`${name} Dataset`, rows as any[]);
    }
    html += `</body></html>`;
    downloadBlob(html, `adam_${projectId}.xls`, 'application/vnd.ms-excel;charset=utf-8');
  };

  const downloadFhirJSON = () => {
    if (!fhirData) return;
    downloadJSONFile(fhirData, `fhir_bundle_${projectId}.json`);
  };

  const downloadFhirCSV = () => {
    if (!fhirData?.entry) return;
    const lines: string[] = ['ResourceType,ID,Status,Method,Description,Subject,LastUpdated'];
    for (const e of fhirData.entry) {
      const r = e.resource || {};
      const desc =
        r.name?.[0]?.text || r.code?.text || r.medicationCodeableConcept?.text ||
        r.code?.coding?.[0]?.display || '';
      const status = r.status || r.clinicalStatus?.coding?.[0]?.code || r.verificationStatus?.coding?.[0]?.code || '';
      const subject = r.subject?.reference || '';
      const updated = r.meta?.lastUpdated || '';
      lines.push(`${r.resourceType || ''},${r.id || ''},${status},${e.request?.method || 'POST'},"${desc.replace(/"/g, '""')}",${subject},${updated}`);
    }
    downloadBlob(lines.join('\n'), `fhir_resources_${projectId}.csv`, 'text/csv;charset=utf-8');
  };

  const downloadFhirNDJSON = () => {
    if (!fhirData?.entry) return;
    const lines = fhirData.entry.map((e: any) => JSON.stringify(e.resource || {}));
    downloadBlob(lines.join('\n'), `fhir_ndjson_${projectId}.ndjson`, 'application/ndjson;charset=utf-8');
  };

  const downloadValidationJSON = () => {
    if (!validationData) return;
    downloadJSONFile(validationData, `sdtm_validation_${projectId}.json`);
  };

  const downloadValidationCSV = () => {
    if (!validationData) return;
    const lines: string[] = ['# SDTM Validation Report'];
    lines.push(`# Project: ${projectId}`);
    lines.push(`# Passed: ${validationData.passed ? 'YES' : 'NO'}`);
    lines.push(`# Errors: ${validationData.errors?.length || 0}`);
    lines.push(`# Warnings: ${validationData.warnings?.length || 0}`);
    lines.push(`# Rules Checked: ${validationData.rules_checked || 0}`);
    lines.push('');
    lines.push('Type,Rule ID,Domain,Message');
    for (const e of validationData.errors || []) {
      lines.push(`Error,${e.rule_id || ''},${e.domain || ''},"${(e.message || '').replace(/"/g, '""')}"`);
    }
    for (const w of validationData.warnings || []) {
      lines.push(`Warning,${w.rule_id || ''},${w.domain || ''},"${(w.message || '').replace(/"/g, '""')}"`);
    }
    downloadBlob(lines.join('\n'), `sdtm_validation_${projectId}.csv`, 'text/csv;charset=utf-8');
  };

  // 打印
  const handlePrint = () => {
    window.print();
  };

  // 展开/折叠
  const toggleDomain = (d: string) => {
    setExpandedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d); else next.add(d);
      return next;
    });
  };
  const toggleDataset = (d: string) => {
    setExpandedDatasets((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d); else next.add(d);
      return next;
    });
  };

  // FHIR 资源类型统计
  const fhirResourceTypes = useMemo(() => {
    if (!fhirData?.entry) return [] as [string, number][];
    const counts: Record<string, number> = {};
    for (const e of fhirData.entry) {
      const t = e.resource?.resourceType || 'Unknown';
      counts[t] = (counts[t] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [fhirData]);

  const filteredFhirEntries = useMemo(() => {
    if (!fhirData?.entry) return [];
    if (fhirResourceFilter === 'ALL') return fhirData.entry;
    return fhirData.entry.filter((e: any) => e.resource?.resourceType === fhirResourceFilter);
  }, [fhirData, fhirResourceFilter]);

  // SDTM 总记录数
  const sdtmTotalRecords = useMemo(() => {
    if (!sdtmData?.domains) return 0;
    return Object.values(sdtmData.domains).reduce((sum: number, rows: any) => sum + (rows?.length || 0), 0);
  }, [sdtmData]);

  const isGeneratingAll = sdtmMutation.isPending || adamMutation.isPending || fhirMutation.isPending;

  return (
    <div className="space-y-6">
      <style>{`@media print { .no-print { display: none !important; } }`}</style>
      <div className="flex items-center justify-between no-print">
        <div>
          <h1 className="text-2xl font-bold">报告中心</h1>
          <p className="text-sm text-gray-500 mt-1">
            CDISC SDTM/ADaM 标准导出 + FHIR R4 互操作 + 项目摘要
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={generateAll}
            loading={isGeneratingAll}
            disabled={!projectId}
          >
            <Sparkles className="w-3 h-3" /> 批量生成
          </Button>
          <Button size="sm" variant="secondary" onClick={handlePrint} disabled={!sdtmData && !adamData && !fhirData}>
            <Printer className="w-3 h-3" /> 打印
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* SDTM 导出 */}
        <Card
          title="SDTM 导出"
          action={
            <div className="flex gap-1 no-print">
              <Button
                size="sm"
                onClick={() => sdtmMutation.mutate()}
                loading={sdtmMutation.isPending}
                disabled={!projectId}
              >
                <Database className="w-3 h-3" /> 生成
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => validateMutation.mutate()}
                loading={validateMutation.isPending}
                disabled={!projectId}
              >
                <CheckCircle className="w-3 h-3" /> 校验
              </Button>
            </div>
          }
        >
          {sdtmData?.domains ? (
            <div className="space-y-3">
              {/* 顶部统计条 */}
              <div className="flex items-center gap-3 bg-blue-50 border border-blue-100 rounded-lg p-2">
                <div className="flex items-center gap-2 text-blue-700">
                  <ListChecks className="w-4 h-4" />
                  <span className="text-xs font-medium">
                    {Object.keys(sdtmData.domains).length} 个域 · {sdtmTotalRecords} 条记录
                  </span>
                </div>
                {validationData && (
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${validationData.passed ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                    {validationData.passed ? '✓ 校验通过' : `✗ ${validationData.errors?.length || 0} 错误`}
                  </span>
                )}
              </div>
              {/* 域标签 */}
              <div className="flex gap-2 flex-wrap">
                {Object.keys(sdtmData.domains).map((d) => {
                  const cnt = sdtmData.domains[d]?.length || 0;
                  return (
                    <span key={d} className="px-2 py-0.5 bg-primary-100 text-primary-800 rounded text-xs font-medium">
                      {d} ({cnt})
                    </span>
                  );
                })}
              </div>
              {/* 各域表格 */}
              {Object.entries(sdtmData.domains).map(([domain, rows]: any) => {
                const expanded = expandedDomains.has(domain);
                const displayRows = expanded ? rows : rows.slice(0, 5);
                return (
                  <div key={domain}>
                    <button
                      onClick={() => toggleDomain(domain)}
                      className="flex items-center gap-1 text-xs font-semibold text-gray-700 mb-1 hover:text-primary-700"
                    >
                      {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      {domain} ({rows.length} 条)
                    </button>
                    <div className="overflow-x-auto border border-gray-200 rounded">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            {rows[0] && Object.keys(rows[0]).map((k) => (
                              <th key={k} className="px-2 py-1 text-left border-b">{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {displayRows.map((r: any, i: number) => (
                            <tr key={i} className="border-b border-gray-100">
                              {Object.values(r).map((v: any, j: number) => (
                                <td key={j} className="px-2 py-1">{String(v ?? '—')}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {rows.length > 5 && !expanded && (
                      <button onClick={() => toggleDomain(domain)} className="text-xs text-primary-600 mt-1 hover:underline">
                        展开全部 {rows.length} 条
                      </button>
                    )}
                  </div>
                );
              })}
              {/* 元数据 */}
              {sdtmData.metadata && (
                <div className="text-xs text-gray-500 bg-gray-50 rounded p-2">
                  <div><span className="font-medium">Study:</span> {sdtmData.metadata.study_id || '—'}</div>
                  <div><span className="font-medium">版本:</span> {sdtmData.metadata.version || '—'}</div>
                  <div><span className="font-medium">导出时间:</span> {sdtmData.metadata.export_time || '—'}</div>
                  <div><span className="font-medium">记录数:</span> {JSON.stringify(sdtmData.metadata.record_counts || {})}</div>
                </div>
              )}
              {/* 下载按钮组 */}
              <div className="flex gap-2 flex-wrap no-print">
                <Button size="sm" variant="secondary" onClick={downloadCSV}>
                  <Download className="w-3 h-3" /> CSV
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadSDTMJSON}>
                  <FileJson className="w-3 h-3" /> JSON
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadSDTMXLS}>
                  <FileSpreadsheet className="w-3 h-3" /> Excel
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400 text-sm">
              <Database className="w-12 h-12 mx-auto mb-2 opacity-50" />
              点击"生成"导出 SDTM 域（DM/VS/RS/EX/SV）
            </div>
          )}
        </Card>

        {/* ADaM 导出 */}
        <Card
          title="ADaM 导出"
          action={
            <Button
              size="sm"
              onClick={() => adamMutation.mutate()}
              loading={adamMutation.isPending}
              disabled={!projectId}
              className="no-print"
            >
              <BarChart3 className="w-3 h-3" /> 生成
            </Button>
          }
        >
          {adamData?.datasets ? (
            <div className="space-y-3">
              {/* 顶部统计条 */}
              <div className="flex items-center gap-3 bg-purple-50 border border-purple-100 rounded-lg p-2">
                <div className="flex items-center gap-2 text-purple-700">
                  <Layers className="w-4 h-4" />
                  <span className="text-xs font-medium">
                    {Object.keys(adamData.datasets).length} 个数据集 ·{' '}
                    {Object.values(adamData.datasets).reduce((s: number, r: any) => s + (r?.length || 0), 0)} 条记录
                  </span>
                </div>
              </div>
              {/* 元数据 */}
              {adamData.metadata && (
                <div className="text-xs text-gray-500 bg-gray-50 rounded p-2">
                  <div><span className="font-medium">ADaM 版本:</span> {adamData.metadata.adam_version || 'ADaMIG 1.1'}</div>
                  <div><span className="font-medium">数据集计数:</span> {JSON.stringify(adamData.metadata.dataset_counts || {})}</div>
                </div>
              )}
              {/* 数据集表格 */}
              {Object.entries(adamData.datasets).map(([ds, rows]: any) => {
                const expanded = expandedDatasets.has(ds);
                const displayRows = expanded ? rows : rows.slice(0, 5);
                return (
                  <div key={ds}>
                    <button
                      onClick={() => toggleDataset(ds)}
                      className="flex items-center gap-1 text-xs font-semibold text-gray-700 mb-1 hover:text-primary-700"
                    >
                      {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      {ds} ({rows.length} 条)
                    </button>
                    <div className="overflow-x-auto border border-gray-200 rounded">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            {rows[0] && Object.keys(rows[0]).map((k) => (
                              <th key={k} className="px-2 py-1 text-left border-b">{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {displayRows.map((r: any, i: number) => (
                            <tr key={i} className="border-b border-gray-100">
                              {Object.values(r).map((v: any, j: number) => (
                                <td key={j} className="px-2 py-1">{String(v ?? '—')}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {rows.length > 5 && !expanded && (
                      <button onClick={() => toggleDataset(ds)} className="text-xs text-primary-600 mt-1 hover:underline">
                        展开全部 {rows.length} 条
                      </button>
                    )}
                  </div>
                );
              })}
              {/* 下载按钮组 */}
              <div className="flex gap-2 flex-wrap no-print">
                <Button size="sm" variant="secondary" onClick={downloadAdamCSV}>
                  <Download className="w-3 h-3" /> CSV
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadAdamJSON}>
                  <FileJson className="w-3 h-3" /> JSON
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadAdamXLS}>
                  <FileSpreadsheet className="w-3 h-3" /> Excel
                </Button>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400 text-sm">
              <BarChart3 className="w-12 h-12 mx-auto mb-2 opacity-50" />
              点击"生成"派生 ADaM 数据集（ADSL/ADRS/ADAE）
            </div>
          )}
        </Card>
      </div>

      {/* FHIR R4 导出 */}
      <Card
        title="FHIR R4 导出"
        action={
          <Button
            size="sm"
            onClick={() => fhirMutation.mutate()}
            loading={fhirMutation.isPending}
            disabled={!projectId}
            className="no-print"
          >
            <HeartPulse className="w-3 h-3" /> 生成 Bundle
          </Button>
        }
      >
        {fhirData ? (
          <div className="space-y-3">
            {/* Bundle 元信息 */}
            <div className="flex items-center gap-3 text-xs flex-wrap">
              <span className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded font-medium">
                {fhirData.resourceType || 'Bundle'}
              </span>
              <span className="text-gray-500">type: {fhirData.type || 'transaction'}</span>
              <span className="text-gray-500">entry: {(fhirData.entry || []).length} 条</span>
              {fhirData.total && <span className="text-gray-500">total: {fhirData.total}</span>}
              <div className="ml-auto flex gap-1 no-print">
                <Button size="sm" variant="secondary" onClick={downloadFhirJSON}>
                  <FileJson className="w-3 h-3" /> JSON
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadFhirCSV}>
                  <Download className="w-3 h-3" /> CSV
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadFhirNDJSON}>
                  <FileJson className="w-3 h-3" /> NDJSON
                </Button>
              </div>
            </div>
            {/* 资源类型筛选标签 */}
            <div className="flex gap-2 flex-wrap no-print">
              <button
                onClick={() => setFhirResourceFilter('ALL')}
                className={`px-2 py-0.5 rounded text-xs font-medium ${fhirResourceFilter === 'ALL' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
              >
                全部 ({fhirData.entry?.length || 0})
              </button>
              {fhirResourceTypes.map(([type, count]) => (
                <button
                  key={type}
                  onClick={() => setFhirResourceFilter(type)}
                  className={`px-2 py-0.5 rounded text-xs font-medium ${fhirResourceFilter === type ? 'bg-primary-600 text-white' : 'bg-emerald-100 text-emerald-800 hover:bg-emerald-200'}`}
                >
                  {type} ({count})
                </button>
              ))}
            </div>
            {/* 资源详情表格 */}
            <div className="overflow-x-auto border border-gray-200 rounded">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-2 py-1 text-left border-b">#</th>
                    <th className="px-2 py-1 text-left border-b">ResourceType</th>
                    <th className="px-2 py-1 text-left border-b">ID</th>
                    <th className="px-2 py-1 text-left border-b">Status</th>
                    <th className="px-2 py-1 text-left border-b">描述</th>
                    <th className="px-2 py-1 text-left border-b">Subject</th>
                    <th className="px-2 py-1 text-left border-b">Method</th>
                  </tr>
                </thead>
                <tbody>
                  {(fhirShowAll ? filteredFhirEntries : filteredFhirEntries.slice(0, 10)).map((e: any, i: number) => {
                    const r = e.resource || {};
                    const desc =
                      r.name?.[0]?.text ||
                      r.code?.text ||
                      r.medicationCodeableConcept?.text ||
                      r.code?.coding?.[0]?.display ||
                      '';
                    const status = r.status || r.clinicalStatus?.coding?.[0]?.code || r.verificationStatus?.coding?.[0]?.code || '';
                    const subject = r.subject?.reference || '';
                    return (
                      <tr key={i} className="border-b border-gray-100">
                        <td className="px-2 py-1">{i + 1}</td>
                        <td className="px-2 py-1 font-medium">{r.resourceType || '—'}</td>
                        <td className="px-2 py-1 text-gray-500 font-mono">{(r.id || '—').slice(0, 12)}</td>
                        <td className="px-2 py-1">
                          {status ? (
                            <span className="px-1.5 py-0.5 bg-gray-100 rounded text-xs">{status}</span>
                          ) : '—'}
                        </td>
                        <td className="px-2 py-1 max-w-xs truncate" title={desc}>{desc || '—'}</td>
                        <td className="px-2 py-1 text-gray-500">{subject || '—'}</td>
                        <td className="px-2 py-1">{e.request?.method || 'POST'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {filteredFhirEntries.length > 10 && (
              <button
                onClick={() => setFhirShowAll(!fhirShowAll)}
                className="text-xs text-primary-600 hover:underline no-print"
              >
                {fhirShowAll ? '收起' : `展开全部 ${filteredFhirEntries.length} 条`}
              </button>
            )}
            {/* Bundle 元信息 */}
            {fhirData.meta && (
              <div className="text-xs text-gray-500 bg-gray-50 rounded p-2">
                <div><span className="font-medium">最后更新:</span> {fhirData.meta.lastUpdated || '—'}</div>
                <div><span className="font-medium">Profile:</span> {(fhirData.meta.profile || []).join(', ') || '—'}</div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-400 text-sm">
            <HeartPulse className="w-12 h-12 mx-auto mb-2 opacity-50" />
            点击"生成 Bundle"导出 FHIR R4 资源（Patient/Observation/Condition/MedicationStatement）
          </div>
        )}
      </Card>

      {/* SDTM 校验结果弹窗 */}
      {showValidation && validationData && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 no-print">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
              <h3 className="font-semibold flex items-center gap-2">
                {validationData.passed ? (
                  <CheckCircle className="w-5 h-5 text-green-500" />
                ) : (
                  <XCircle className="w-5 h-5 text-red-500" />
                )}
                SDTM 校验结果
              </h3>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="secondary" onClick={downloadValidationJSON}>
                  <FileJson className="w-3 h-3" /> JSON
                </Button>
                <Button size="sm" variant="secondary" onClick={downloadValidationCSV}>
                  <Download className="w-3 h-3" /> CSV
                </Button>
                <button onClick={() => setShowValidation(false)} className="text-gray-400 hover:text-gray-600">
                  ✕
                </button>
              </div>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-red-50 p-3 rounded text-center">
                  <div className="text-xs text-gray-500">错误</div>
                  <div className="text-xl font-bold text-red-700">{validationData.errors?.length || 0}</div>
                </div>
                <div className="bg-yellow-50 p-3 rounded text-center">
                  <div className="text-xs text-gray-500">警告</div>
                  <div className="text-xl font-bold text-yellow-700">{validationData.warnings?.length || 0}</div>
                </div>
                <div className="bg-blue-50 p-3 rounded text-center">
                  <div className="text-xs text-gray-500">规则数</div>
                  <div className="text-xl font-bold text-blue-700">{validationData.rules_checked || 0}</div>
                </div>
              </div>
              <div className={`p-3 rounded text-sm font-medium ${validationData.passed ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                {validationData.summary || (validationData.passed ? '校验通过' : '校验未通过')}
              </div>
              {validationData.errors?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-red-700 mb-2">错误详情</div>
                  <div className="space-y-1">
                    {validationData.errors.map((e: any, i: number) => (
                      <div key={i} className="text-xs bg-red-50 p-2 rounded border border-red-100">
                        <span className="font-mono text-red-600">{e.rule_id}</span>
                        <span className="ml-2 text-gray-700">{e.message}</span>
                        {e.domain && <span className="ml-2 text-gray-400">[{e.domain}]</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {validationData.warnings?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-yellow-700 mb-2">警告详情</div>
                  <div className="space-y-1">
                    {validationData.warnings.map((w: any, i: number) => (
                      <div key={i} className="text-xs bg-yellow-50 p-2 rounded border border-yellow-100">
                        <AlertTriangle className="w-3 h-3 inline text-yellow-500" />
                        <span className="font-mono text-yellow-600 ml-1">{w.rule_id}</span>
                        <span className="ml-2 text-gray-700">{w.message}</span>
                        {w.domain && <span className="ml-2 text-gray-400">[{w.domain}]</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 项目摘要看板 */}
      <Card title="项目摘要看板" action={
        <Button size="sm" variant="secondary" onClick={() => refetchSummary()} disabled={!projectId} className="no-print">
          <FileText className="w-3 h-3" /> 刷新
        </Button>
      }>
        {(() => {
          const s = (summary as any)?.data || summary;
          if (!s) {
            return (
              <div className="text-center py-8 text-gray-400 text-sm">
                <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
                {!projectId ? '请先选择项目' : '点击"刷新"加载项目摘要'}
              </div>
            );
          }
          const datasets = s.datasets || { total: 0, by_type: {} };
          const targets = s.targets || { total: 0, by_grade: {} };
          const hyps = s.hypotheses || { total: 0, completed: 0 };
          const exps = s.experiments || { total: 0, successful: 0 };
          const hypPct = hyps.total > 0 ? Math.round((hyps.completed / hyps.total) * 100) : 0;
          const expPct = exps.total > 0 ? Math.round((exps.successful / exps.total) * 100) : 0;

          const gradeEntries = Object.entries(targets.by_grade || {});
          const typeEntries = Object.entries(datasets.by_type || {});

          return (
            <div className="space-y-4">
              {/* 4 个统计卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-blue-50 border border-blue-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-blue-700">
                    <DBIcon className="w-4 h-4" />
                    <span className="text-xs font-medium">数据集</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-blue-900">{datasets.total}</div>
                  <div className="text-xs text-blue-600 mt-0.5">
                    {typeEntries.length} 种类型
                  </div>
                </div>
                <div className="bg-purple-50 border border-purple-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-purple-700">
                    <TargetIcon className="w-4 h-4" />
                    <span className="text-xs font-medium">靶点</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-purple-900">{targets.total}</div>
                  <div className="text-xs text-purple-600 mt-0.5">
                    {gradeEntries.length} 个分级
                  </div>
                </div>
                <div className="bg-amber-50 border border-amber-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-amber-700">
                    <GitBranch className="w-4 h-4" />
                    <span className="text-xs font-medium">假设</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-amber-900">{hyps.total}</div>
                  <div className="text-xs text-amber-600 mt-0.5">
                    已完成 {hyps.completed}/{hyps.total}
                  </div>
                </div>
                <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-emerald-700">
                    <FlaskConical className="w-4 h-4" />
                    <span className="text-xs font-medium">实验</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold text-emerald-900">{exps.total}</div>
                  <div className="text-xs text-emerald-600 mt-0.5">
                    成功 {exps.successful}/{exps.total}
                  </div>
                </div>
              </div>

              {/* 进度条 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">假设完成度</span>
                    <span className="text-gray-500">{hyps.completed}/{hyps.total} ({hypPct}%)</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-amber-500 h-full rounded-full transition-all"
                      style={{ width: `${hypPct}%` }}
                    />
                  </div>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-medium text-gray-700">实验成功率</span>
                    <span className="text-gray-500">{exps.successful}/{exps.total} ({expPct}%)</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-emerald-500 h-full rounded-full transition-all"
                      style={{ width: `${expPct}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* 分布图表 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {gradeEntries.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-700 mb-2">靶点分级分布</div>
                    <PlotlyChart
                      data={[{
                        type: 'bar',
                        x: gradeEntries.map(([g]) => `Grade ${g}`),
                        y: gradeEntries.map(([, v]: any) => v),
                        marker: { color: ['#16a34a', '#2563eb', '#d97706', '#dc2626', '#6b7280'] },
                        text: gradeEntries.map(([, v]: any) => String(v)),
                        textposition: 'auto',
                      }]}
                      layout={{
                        margin: { t: 20, b: 40, l: 30, r: 10 },
                        height: 220,
                        yaxis: { title: { text: '数量' }, dtick: 1 },
                        xaxis: { title: { text: '证据分级' } },
                      }}
                    />
                  </div>
                )}
                {typeEntries.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-700 mb-2">数据集类型分布</div>
                    <PlotlyChart
                      data={[{
                        type: 'pie',
                        labels: typeEntries.map(([t]) => t),
                        values: typeEntries.map(([, v]: any) => v),
                        hole: 0.4,
                        textinfo: 'label+value',
                        marker: { colors: ['#2563eb', '#16a34a', '#d97706', '#9333ea', '#0891b2'] },
                      }]}
                      layout={{
                        margin: { t: 10, b: 10, l: 10, r: 10 },
                        height: 220,
                        showlegend: true,
                        legend: { font: { size: 10 } },
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })()}
      </Card>
    </div>
  );
}
