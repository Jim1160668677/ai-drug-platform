'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  KeyRound,
  Plus,
  Pencil,
  Trash2,
  Zap,
  CheckCircle2,
  AlertCircle,
  X,
} from 'lucide-react';
import {
  listUserLlmConfigs,
  createUserLlmConfig,
  updateUserLlmConfig,
  deleteUserLlmConfig,
  activateUserLlmConfig,
  testUserLlmConfig,
  getLLMConfigs,
  activateLLMConfig,
} from '@/lib/api';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Card from '@/components/ui/Card';
import Loading from '@/components/ui/Loading';

interface ConfigForm {
  id?: string;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  timeout_sec: number;
  is_active: boolean;
}

const PROVIDERS = [
  { value: 'doubao', label: '豆包（火山方舟）' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'custom', label: '自定义' },
];

const EMPTY_FORM: ConfigForm = {
  name: '',
  provider: 'doubao',
  base_url: '',
  api_key: '',
  model_name: '',
  temperature: 0.7,
  max_tokens: 2048,
  timeout_sec: 60,
  is_active: false,
};

export default function UserLlmConfigPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ConfigForm>(EMPTY_FORM);
  const [testResult, setTestResult] = useState<any>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['user-llm-configs'],
    queryFn: () => listUserLlmConfigs(1, 100),
  });

  // 系统级 LLM 配置（Agnes 默认 + 可切换其他模型）
  const { data: sysData, refetch: refetchSys } = useQuery({
    queryKey: ['system-llm-configs'],
    queryFn: () => getLLMConfigs(),
  });
  const sysConfigs: any[] = sysData?.data?.items ?? sysData?.data ?? [];
  const activeSysConfig = sysConfigs.find((c: any) => c.is_active);

  const sysActivateMutation = useMutation({
    mutationFn: (id: string) => activateLLMConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-llm-configs'] });
      import('@/lib/notification').then(({ toast }) =>
        toast.success('切换成功', '系统默认 LLM 已切换')
      );
    },
    onError: (err: any) => {
      import('@/lib/notification').then(({ toast }) =>
        toast.error('切换失败', err?.response?.data?.detail || '请重试')
      );
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: ConfigForm) => createUserLlmConfig(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-llm-configs'] });
      import('@/lib/notification').then(({ toast }) =>
        toast.success('创建成功', 'LLM 配置已添加')
      );
      setShowForm(false);
      setForm(EMPTY_FORM);
    },
    onError: (err: any) => {
      import('@/lib/notification').then(({ toast }) =>
        toast.error(
          '创建失败',
          err?.response?.data?.detail || err?.message || '请重试'
        )
      );
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<ConfigForm> }) =>
      updateUserLlmConfig(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-llm-configs'] });
      import('@/lib/notification').then(({ toast }) =>
        toast.success('更新成功', '配置已更新')
      );
      setShowForm(false);
      setForm(EMPTY_FORM);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteUserLlmConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-llm-configs'] });
      import('@/lib/notification').then(({ toast }) =>
        toast.success('删除成功', '配置已删除')
      );
    },
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => activateUserLlmConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-llm-configs'] });
      import('@/lib/notification').then(({ toast }) =>
        toast.success('激活成功', '已切换到该配置')
      );
    },
  });

  const testMutation = useMutation({
    mutationFn: (configId: string) => testUserLlmConfig({ config_id: configId }),
    onSuccess: (res) => {
      const result = res?.data ?? res;
      setTestResult(result);
      setTestingId(null);
    },
    onError: (err: any) => {
      setTestResult({
        success: false,
        message: err?.response?.data?.detail || err?.message || '测试失败',
      });
      setTestingId(null);
    },
  });

  const handleEdit = (cfg: any) => {
    setForm({
      id: cfg.id,
      name: cfg.name || '',
      provider: cfg.provider || 'custom',
      base_url: cfg.base_url || '',
      api_key: '', // 编辑时不回填密文
      model_name: cfg.model_name || '',
      temperature: cfg.temperature ?? 0.7,
      max_tokens: cfg.max_tokens ?? 2048,
      timeout_sec: cfg.timeout_sec ?? 60,
      is_active: cfg.is_active ?? false,
    });
    setShowForm(true);
    setTestResult(null);
  };

  const handleSubmit = () => {
    if (!form.name || !form.provider || !form.model_name) {
      import('@/lib/notification').then(({ toast }) =>
        toast.error('表单校验失败', '名称 / Provider / 模型名必填')
      );
      return;
    }
    if (!form.id && !form.api_key) {
      import('@/lib/notification').then(({ toast }) =>
        toast.error('表单校验失败', '新建配置时 API Key 必填')
      );
      return;
    }

    const payload: any = {
      name: form.name,
      provider: form.provider,
      base_url: form.base_url || null,
      model_name: form.model_name,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
      timeout_sec: form.timeout_sec,
      is_active: form.is_active,
    };
    if (form.api_key) payload.api_key = form.api_key;

    if (form.id) {
      updateMutation.mutate({ id: form.id, payload });
    } else {
      createMutation.mutate(payload);
    }
  };

  const items: any[] = data?.data ?? data?.items ?? [];

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <KeyRound className="w-6 h-6 text-primary-600" />
          我的 LLM 配置
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          绑定自有 API Key（豆包/DeepSeek/OpenAI 等），仅用于「个人基因组解读」场景
        </p>
      </div>

      {/* 安全提示 */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-xs text-blue-800">
        <div className="flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-1">安全提示</div>
            <ul className="list-disc list-inside space-y-0.5">
              <li>API Key 通过 Fernet 加密存储（enc: 前缀），不会以明文出现在数据库或日志中</li>
              <li>调用失败时自动降级到系统默认（Agnes），确保服务可用</li>
              <li>同一时刻仅一个配置处于激活状态</li>
              <li>仅用于个人基因组解读；其他场景仍使用系统默认 LLM</li>
            </ul>
          </div>
        </div>
      </div>

      {/* ========== 系统默认 LLM（Agnes） ========== */}
      <div className="rounded-lg border-2 border-primary-200 bg-gradient-to-r from-primary-50 to-indigo-50 p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold flex items-center gap-2 text-gray-900">
            <Zap className="w-5 h-5 text-primary-600" />
            系统默认大模型
          </h2>
          <span className="text-xs text-gray-500">全平台共用 · 管理员可切换</span>
        </div>

        {sysConfigs.length === 0 ? (
          <div className="text-sm text-gray-500 py-2">
            暂无系统配置（将使用 .env 中的 AGNES_API_KEY 作为默认）
          </div>
        ) : (
          <div className="space-y-2">
            {sysConfigs.map((cfg: any) => (
              <div
                key={cfg.id}
                className={`rounded-lg border p-3 flex items-center justify-between flex-wrap gap-2 ${
                  cfg.is_active
                    ? 'border-green-300 bg-white'
                    : 'border-gray-200 bg-white/60'
                }`}
              >
                <div className="flex items-center gap-3">
                  {cfg.is_active ? (
                    <CheckCircle2 className="w-5 h-5 text-green-600 shrink-0" />
                  ) : (
                    <div className="w-5 h-5 rounded-full border-2 border-gray-300 shrink-0" />
                  )}
                  <div>
                    <div className="text-sm font-semibold text-gray-900">
                      {cfg.name}
                      {cfg.is_active && (
                        <Badge variant="green" value="当前激活" />
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      {cfg.provider} · {cfg.test_model}
                      {cfg.fast_model && cfg.fast_model !== cfg.test_model && ` · ${cfg.fast_model}`}
                      {cfg.deep_model && cfg.deep_model !== cfg.test_model && ` · ${cfg.deep_model}`}
                    </div>
                    {cfg.base_url && (
                      <div className="text-xs text-gray-400 font-mono mt-0.5">
                        {cfg.base_url}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!cfg.is_active && (
                    <Button
                      size="sm"
                      variant="primary"
                      loading={sysActivateMutation.isPending}
                      onClick={() => sysActivateMutation.mutate(cfg.id)}
                    >
                      切换为此模型
                    </Button>
                  )}
                  {cfg.last_test_success != null && (
                    <Badge
                      variant={cfg.last_test_success ? 'green' : 'red'}
                      value={cfg.last_test_success ? '测试通过' : '测试失败'}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 text-xs text-gray-500 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          系统默认模型用于：AI 对话、流水线假设生成、专业报告解读、Agent 编排
        </div>
      </div>

      {/* ========== 用户个人 LLM 配置（BYO Key） ========== */}

      {/* 操作栏 */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">
          已配置 <strong>{items.length}</strong> 个 LLM
        </div>
        <Button
          onClick={() => {
            setForm(EMPTY_FORM);
            setTestResult(null);
            setShowForm(true);
          }}
        >
          <Plus className="w-4 h-4" />
          新建配置
        </Button>
      </div>

      {/* 列表 */}
      {isLoading ? (
        <Loading label="加载配置列表..." />
      ) : items.length === 0 ? (
        <Card>
          <div className="text-center py-8 text-sm text-gray-400">
            <KeyRound className="w-10 h-10 mx-auto mb-2 opacity-50" />
            暂无配置，点击右上角「新建配置」开始
          </div>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((cfg: any) => (
            <div
              key={cfg.id}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    {cfg.is_active && (
                      <CheckCircle2 className="w-5 h-5 text-green-600 shrink-0" />
                    )}
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-gray-900 truncate">
                        {cfg.name}
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {cfg.provider} · {cfg.model_name}
                      </div>
                    </div>
                  </div>
                  {cfg.is_active && <Badge variant="green" value="已激活" />}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="text-xs text-gray-500 font-mono">
                    {cfg.api_key_masked || '***'}
                  </div>
                  {cfg.base_url && (
                    <Badge variant="gray" value={cfg.base_url} />
                  )}
                  {cfg.last_test_at && (
                    <Badge
                      variant={cfg.last_test_success ? 'green' : 'red'}
                      value={cfg.last_test_success ? '测试通过' : '测试失败'}
                    />
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={testingId === cfg.id}
                    disabled={testingId === cfg.id}
                    onClick={() => {
                      setTestingId(cfg.id);
                      setTestResult(null);
                      testMutation.mutate(cfg.id);
                    }}
                  >
                    <Zap className="w-3.5 h-3.5" />
                    测试
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={cfg.is_active}
                    loading={
                      activateMutation.isPending &&
                      activateMutation.variables === cfg.id
                    }
                    onClick={() => activateMutation.mutate(cfg.id)}
                  >
                    激活
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleEdit(cfg)}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={cfg.is_active}
                    loading={
                      deleteMutation.isPending &&
                      deleteMutation.variables === cfg.id
                    }
                    onClick={() => {
                      if (confirm(`确定删除配置「${cfg.name}」吗？`)) {
                        deleteMutation.mutate(cfg.id);
                      }
                    }}
                    className="text-red-600 hover:bg-red-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>

              {/* 测试结果 */}
              {testingId === cfg.id && testMutation.isPending && (
                <div className="mt-3 text-xs text-primary-600 flex items-center gap-2">
                  <Zap className="w-3 h-3 animate-spin" />
                  正在测试连通性...
                </div>
              )}
              {testResult && testingId === null && (
                <div
                  className={`mt-3 rounded-lg p-3 text-xs ${
                    testResult.success
                      ? 'bg-green-50 border border-green-200 text-green-800'
                      : 'bg-red-50 border border-red-200 text-red-800'
                  }`}
                >
                  <div className="font-medium mb-1">
                    {testResult.success ? '✓ 测试成功' : '✗ 测试失败'}
                  </div>
                  <div className="text-xs">{testResult.message}</div>
                  {testResult.model && (
                    <div className="text-xs mt-1">
                      模型回显：<code>{testResult.model}</code>
                    </div>
                  )}
                  {testResult.duration_sec != null && (
                    <div className="text-xs mt-1">
                      响应时间：{testResult.duration_sec.toFixed(2)}s
                    </div>
                  )}
                  {testResult.response_text && (
                    <div className="text-xs mt-1 bg-white/50 p-2 rounded font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                      {testResult.response_text}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 新增/编辑弹窗 */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-lg w-full max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
              <h3 className="font-semibold">
                {form.id ? '编辑配置' : '新建 LLM 配置'}
              </h3>
              <button
                onClick={() => {
                  setShowForm(false);
                  setForm(EMPTY_FORM);
                  setTestResult(null);
                }}
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <FormRow label="配置名称 *">
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="例如：豆包默认"
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
              </FormRow>
              <FormRow label="Provider *">
                <select
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </FormRow>
              <FormRow label="模型名 *">
                <input
                  type="text"
                  value={form.model_name}
                  onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                  placeholder="例如：doubao-pro-4k"
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
              </FormRow>
              <FormRow label="Base URL">
                <input
                  type="text"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://ark.cn-beijing.volces.com/api/v3"
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                />
              </FormRow>
              <FormRow label={form.id ? 'API Key（留空则不变）' : 'API Key *'}>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder="sk-..."
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm font-mono"
                />
              </FormRow>
              <div className="grid grid-cols-3 gap-3">
                <FormRow label="Temperature">
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={form.temperature}
                    onChange={(e) =>
                      setForm({ ...form, temperature: Number(e.target.value) })
                    }
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                  />
                </FormRow>
                <FormRow label="Max Tokens">
                  <input
                    type="number"
                    min="1"
                    max="32000"
                    value={form.max_tokens}
                    onChange={(e) =>
                      setForm({ ...form, max_tokens: Number(e.target.value) })
                    }
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                  />
                </FormRow>
                <FormRow label="Timeout (s)">
                  <input
                    type="number"
                    min="5"
                    max="600"
                    value={form.timeout_sec}
                    onChange={(e) =>
                      setForm({ ...form, timeout_sec: Number(e.target.value) })
                    }
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
                  />
                </FormRow>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
                设为激活（其他配置将自动置为非激活）
              </label>
            </div>
            <div className="flex justify-end gap-2 px-5 py-3 border-t sticky bottom-0 bg-white">
              <Button
                variant="ghost"
                onClick={() => {
                  setShowForm(false);
                  setForm(EMPTY_FORM);
                  setTestResult(null);
                }}
              >
                取消
              </Button>
              <Button
                loading={createMutation.isPending || updateMutation.isPending}
                disabled={createMutation.isPending || updateMutation.isPending}
                onClick={handleSubmit}
              >
                {form.id ? '保存' : '创建'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
