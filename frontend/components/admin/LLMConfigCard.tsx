'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2,
  Cpu,
  Pencil,
  Plus,
  Power,
  Sparkles,
  Trash2,
  XCircle,
  Zap,
} from 'lucide-react';
import {
  activateLLMConfig,
  createLLMConfig,
  deleteLLMConfig,
  getLLMConfigs,
  testLLMConfig,
  updateLLMConfig,
} from '@/lib/api';
import { toast } from '@/lib/notification';
import { validate, llmConfigCreateSchema, llmConfigSchema } from '@/lib/validation';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';
import FormError from '@/components/ui/FormError';

interface LLMConfig {
  id: string;
  name: string;
  provider: string;
  access_mode: string;
  upstream_protocol: string;
  base_url: string;
  api_key_masked: string;
  test_model: string;
  fast_model?: string;
  deep_model?: string;
  temperature: number;
  max_tokens: number;
  timeout_sec: number;
  is_active: boolean;
  description?: string;
  last_test_at?: string;
  last_test_success?: boolean;
  last_test_message?: string;
  created_at: string;
  updated_at: string;
}

const EMPTY_FORM = {
  name: '',
  provider: 'openai_compatible',
  access_mode: 'api_only',
  upstream_protocol: 'chat_completions',
  base_url: '',
  api_key: '',
  test_model: '',
  fast_model: '',
  deep_model: '',
  temperature: 0.7,
  max_tokens: 2000,
  timeout_sec: 60,
  description: '',
  is_active: false,
};

const ACCESS_MODE_LABEL: Record<string, string> = {
  api_only: 'API Only',
  local_deploy: '本地部署',
  proxy: '代理',
};

const PROTOCOL_LABEL: Record<string, string> = {
  chat_completions: 'Chat Completions',
  completions: 'Completions',
  anthropic: 'Anthropic Messages',
};

export default function LLMConfigCard() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<any>(EMPTY_FORM);
  const [testMessage, setTestMessage] = useState('');
  const [testResult, setTestResult] = useState<any>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const { data: configsResp, isLoading } = useQuery({
    queryKey: ['llm-configs'],
    queryFn: getLLMConfigs,
  });
  const configs: LLMConfig[] = (configsResp as any) || [];

  // 创建/更新
  const saveMutation = useMutation({
    mutationFn: async (payload: any) => {
      const data = { ...payload };
      // 空字符串字段转 undefined，避免后端校验失败
      Object.keys(data).forEach((k) => {
        if (data[k] === '') data[k] = undefined;
      });
      // 必填字段保留
      data.name = payload.name;
      data.base_url = payload.base_url;
      data.test_model = payload.test_model;
      // api_key 编辑时若为空则不传（保留原值）
      if (editingId && !payload.api_key) delete data.api_key;
      // 数值字段转类型
      data.temperature = Number(payload.temperature);
      data.max_tokens = Number(payload.max_tokens);
      data.timeout_sec = Number(payload.timeout_sec);
      data.is_active = Boolean(payload.is_active);

      if (editingId) {
        return updateLLMConfig(editingId, data);
      }
      return createLLMConfig(data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llm-configs'] });
      handleCloseForm();
    },
    onError: (err: any) => {
      toast.error('保存失败', err?.response?.data?.detail || err.message);
    },
  });

  // 删除
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteLLMConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llm-configs'] });
      toast.success('配置已删除');
    },
    onError: (err: any) => toast.error('删除失败', err?.response?.data?.detail || err.message),
  });

  // 激活
  const activateMutation = useMutation({
    mutationFn: (id: string) => activateLLMConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llm-configs'] });
      toast.success('配置已激活');
    },
    onError: (err: any) => toast.error('激活失败', err?.response?.data?.detail || err.message),
  });

  // 测试连通性
  const testMutation = useMutation({
    mutationFn: (payload: { config_id?: string; custom_message?: string }) =>
      testLLMConfig(payload),
    onSuccess: (data) => {
      setTestResult(data);
      queryClient.invalidateQueries({ queryKey: ['llm-configs'] });
    },
    onError: (err: any) => {
      setTestResult({
        success: false,
        message: `测试请求失败: ${err?.response?.data?.detail || err.message}`,
      });
    },
  });

  const handleOpenCreate = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setShowForm(true);
    setTestResult(null);
  };

  const handleAgnesPreset = () => {
    setForm({
      ...EMPTY_FORM,
      name: 'Agnes',
      provider: 'agnes',
      access_mode: 'api_only',
      upstream_protocol: 'chat_completions',
      base_url: 'https://apihub.agnes-ai.com/v1',
      api_key: '',
      test_model: 'agnes-2.0-flash',
      fast_model: 'agnes-2.0-flash',
      deep_model: 'agnes-2.0-flash',
      description: 'Agnes AI 大模型 API（API Only / Chat Completions）',
      is_active: true,
    });
    setEditingId(null);
    setShowForm(true);
    setTestResult(null);
  };

  const handleOpenEdit = (cfg: LLMConfig) => {
    setForm({
      name: cfg.name,
      provider: cfg.provider,
      access_mode: cfg.access_mode,
      upstream_protocol: cfg.upstream_protocol,
      base_url: cfg.base_url,
      api_key: '', // 编辑时留空表示不修改
      test_model: cfg.test_model,
      fast_model: cfg.fast_model || '',
      deep_model: cfg.deep_model || '',
      temperature: cfg.temperature,
      max_tokens: cfg.max_tokens,
      timeout_sec: cfg.timeout_sec,
      description: cfg.description || '',
      is_active: cfg.is_active,
    });
    setEditingId(cfg.id);
    setShowForm(true);
    setTestResult(null);
  };

  const handleCloseForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFieldErrors({});
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const schema = editingId ? llmConfigSchema : llmConfigCreateSchema;
    const result = validate(schema, form);
    if (!result.success) {
      setFieldErrors(result.errors);
      const firstError = Object.values(result.errors)[0];
      if (firstError) toast.warning('表单校验失败', firstError);
      return;
    }
    setFieldErrors({});
    saveMutation.mutate(form);
  };

  const handleTest = (cfg?: LLMConfig) => {
    setTestResult(null);
    setTestingId(cfg?.id || null);
    testMutation.mutate({
      config_id: cfg?.id,
      custom_message: testMessage || undefined,
    });
  };

  const handleDelete = (cfg: LLMConfig) => {
    if (cfg.is_active) {
      toast.warning('不能删除当前激活的配置，请先切换到其他配置');
      return;
    }
    if (confirm(`确认删除配置 "${cfg.name}" 吗？此操作不可恢复。`)) {
      deleteMutation.mutate(cfg.id);
    }
  };

  return (
    <Card
      title="大模型 API 设置"
      action={
        <div className="flex items-center gap-2">
          <button
            onClick={handleAgnesPreset}
            className="inline-flex items-center gap-1 px-3 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700"
            title="一键填充 Agnes 配置参数"
          >
            <Sparkles className="w-3 h-3" /> Agnes 预设
          </button>
          <button
            onClick={handleOpenCreate}
            className="inline-flex items-center gap-1 px-3 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            <Plus className="w-3 h-3" /> 新建配置
          </button>
        </div>
      }
    >
      {/* 当前激活配置提示 */}
      {configs.length > 0 && (
        <div className="mb-4 p-3 bg-gradient-to-r from-blue-50 to-indigo-50 rounded border border-blue-100">
          <div className="flex items-center gap-2 text-sm">
            <Sparkles className="w-4 h-4 text-blue-600" />
            <span className="text-gray-700">
              当前激活：
              <span className="font-semibold text-blue-700">
                {configs.find((c) => c.is_active)?.name || '无'}
              </span>
              {configs.find((c) => c.is_active)?.test_model && (
                <span className="ml-2 text-gray-500">
                  （模型: {configs.find((c) => c.is_active)?.test_model}）
                </span>
              )}
            </span>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-gray-400">加载中...</div>
      ) : configs.length === 0 ? (
        <div className="text-center py-8 text-gray-400">
          <Cpu className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p className="text-sm">暂无 LLM 配置，点击右上角"新建配置"添加</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500">
                <th className="text-left py-2 px-3">名称</th>
                <th className="text-left py-2 px-3">访问模式</th>
                <th className="text-left py-2 px-3">协议</th>
                <th className="text-left py-2 px-3">基础 URL</th>
                <th className="text-left py-2 px-3">API Key</th>
                <th className="text-left py-2 px-3">测试模型</th>
                <th className="text-left py-2 px-3">状态</th>
                <th className="text-left py-2 px-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {configs.map((cfg) => (
                <tr key={cfg.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 px-3">
                    <div className="font-semibold text-gray-800">{cfg.name}</div>
                    {cfg.description && (
                      <div className="text-xs text-gray-400">{cfg.description}</div>
                    )}
                  </td>
                  <td className="py-2 px-3 text-xs">
                    {ACCESS_MODE_LABEL[cfg.access_mode] || cfg.access_mode}
                  </td>
                  <td className="py-2 px-3 text-xs">
                    {PROTOCOL_LABEL[cfg.upstream_protocol] || cfg.upstream_protocol}
                  </td>
                  <td className="py-2 px-3 text-xs font-mono text-gray-600 max-w-[200px] truncate">
                    {cfg.base_url}
                  </td>
                  <td className="py-2 px-3 text-xs font-mono text-gray-500">
                    {cfg.api_key_masked}
                  </td>
                  <td className="py-2 px-3 text-xs font-mono">{cfg.test_model}</td>
                  <td className="py-2 px-3">
                    {cfg.is_active ? (
                      <Badge variant="status" value="active" />
                    ) : (
                      <span className="text-xs text-gray-400">未激活</span>
                    )}
                    {cfg.last_test_success !== null && cfg.last_test_success !== undefined && (
                      <div className="mt-1 text-[10px]">
                        {cfg.last_test_success ? (
                          <span className="text-green-600">最近测试通过</span>
                        ) : (
                          <span className="text-red-600">最近测试失败</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1">
                      {!cfg.is_active && (
                        <button
                          onClick={() => activateMutation.mutate(cfg.id)}
                          title="激活"
                          className="p-1 hover:bg-green-50 rounded"
                        >
                          <Power className="w-4 h-4 text-green-600" />
                        </button>
                      )}
                      <button
                        onClick={() => handleTest(cfg)}
                        title="测试连通性"
                        className="p-1 hover:bg-blue-50 rounded"
                      >
                        <Zap className="w-4 h-4 text-blue-600" />
                      </button>
                      <button
                        onClick={() => handleOpenEdit(cfg)}
                        title="编辑"
                        className="p-1 hover:bg-gray-100 rounded"
                      >
                        <Pencil className="w-4 h-4 text-gray-600" />
                      </button>
                      <button
                        onClick={() => handleDelete(cfg)}
                        title="删除"
                        className="p-1 hover:bg-red-50 rounded"
                      >
                        <Trash2 className="w-4 h-4 text-red-600" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 测试连通性区域 */}
      <div className="mt-4 pt-4 border-t border-gray-100">
        <div className="flex items-center gap-2 mb-2">
          <input
            type="text"
            value={testMessage}
            onChange={(e) => setTestMessage(e.target.value)}
            placeholder="自定义测试消息（可选，默认 ping）"
            className="flex-1 px-3 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={() => handleTest(undefined)}
            disabled={testMutation.isPending}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {testMutation.isPending ? '测试中...' : '测试激活配置'}
          </button>
        </div>
        {testResult && (
          <div
            className={`p-3 rounded text-sm ${
              testResult.success
                ? 'bg-green-50 border border-green-200 text-green-800'
                : 'bg-red-50 border border-red-200 text-red-800'
            }`}
          >
            <div className="flex items-start gap-2">
              {testResult.success ? (
                <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" />
              ) : (
                <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              )}
              <div className="flex-1">
                <div className="font-semibold">{testResult.message}</div>
                {testResult.model && (
                  <div className="text-xs mt-1 text-gray-600">模型: {testResult.model}</div>
                )}
                {testResult.response_text && (
                  <div className="text-xs mt-1 text-gray-600">
                    响应: {testResult.response_text}
                  </div>
                )}
                {testResult.duration_sec && (
                  <div className="text-xs mt-1 text-gray-500">
                    耗时: {testResult.duration_sec}s
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 新建/编辑表单 Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                {editingId ? '编辑 LLM 配置' : '新建 LLM 配置'}
              </h3>
              <button onClick={handleCloseForm} className="text-gray-400 hover:text-gray-600">
                <XCircle className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    配置名称 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="如 Agnes、OpenAI、Azure"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                    required
                  />
                  <FormError message={fieldErrors.name} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    Provider
                  </label>
                  <input
                    type="text"
                    value={form.provider}
                    onChange={(e) => setForm({ ...form, provider: e.target.value })}
                    placeholder="openai_compatible"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    访问模式
                  </label>
                  <select
                    value={form.access_mode}
                    onChange={(e) => setForm({ ...form, access_mode: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="api_only">API Only</option>
                    <option value="local_deploy">本地部署</option>
                    <option value="proxy">代理</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    上游协议
                  </label>
                  <select
                    value={form.upstream_protocol}
                    onChange={(e) => setForm({ ...form, upstream_protocol: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="chat_completions">Chat Completions (OpenAI 兼容)</option>
                    <option value="completions">Completions (旧版)</option>
                    <option value="anthropic">Anthropic Messages</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  基础 URL <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://apihub.agnes-ai.com/v1"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  required
                />
                <FormError message={fieldErrors.base_url} />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  API 密钥{' '}
                  {editingId && (
                    <span className="text-gray-400">（留空表示不修改）</span>
                  )}
                  {!editingId && <span className="text-red-500">*</span>}
                </label>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder="sk-..."
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                  required={!editingId}
                />
                <FormError message={fieldErrors.api_key} />
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    测试模型 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.test_model}
                    onChange={(e) => setForm({ ...form, test_model: e.target.value })}
                    placeholder="agnes-2.0-flash"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                    required
                  />
                  <FormError message={fieldErrors.test_model} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    快速筛查模型
                  </label>
                  <input
                    type="text"
                    value={form.fast_model}
                    onChange={(e) => setForm({ ...form, fast_model: e.target.value })}
                    placeholder="可选"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    深度洞察模型
                  </label>
                  <input
                    type="text"
                    value={form.deep_model}
                    onChange={(e) => setForm({ ...form, deep_model: e.target.value })}
                    placeholder="可选"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    温度 (0-2)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={form.temperature}
                    onChange={(e) => setForm({ ...form, temperature: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <FormError message={fieldErrors.temperature} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    最大 Token
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="32000"
                    value={form.max_tokens}
                    onChange={(e) => setForm({ ...form, max_tokens: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <FormError message={fieldErrors.max_tokens} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    超时（秒）
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="600"
                    value={form.timeout_sec}
                    onChange={(e) => setForm({ ...form, timeout_sec: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <FormError message={fieldErrors.timeout_sec} />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">
                  描述
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="可选"
                  rows={2}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  className="rounded"
                />
                <span className="text-sm text-gray-700">
                  设为当前激活配置（其他配置将自动取消激活）
                </span>
              </label>

              <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={handleCloseForm}
                  className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={saveMutation.isPending}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {saveMutation.isPending ? '保存中...' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </Card>
  );
}
