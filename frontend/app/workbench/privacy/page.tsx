'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Shield, Plus, Lock, Eye, EyeOff } from 'lucide-react';
import { getPrivacyDomains, createPrivacyDomain } from '@/lib/api';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';

export default function PrivacyPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [newDomain, setNewDomain] = useState({
    name: '',
    data_schema: '',
    privacy_params: '',
  });

  const { data: domains, isLoading } = useQuery({
    queryKey: ['privacy-domains'],
    queryFn: getPrivacyDomains,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      let schema: any = {};
      let params: any = {};
      try {
        schema = newDomain.data_schema ? JSON.parse(newDomain.data_schema) : {};
      } catch {
        schema = {};
      }
      try {
        params = newDomain.privacy_params ? JSON.parse(newDomain.privacy_params) : {};
      } catch {
        params = {};
      }
      return createPrivacyDomain({
        name: newDomain.name,
        data_schema: schema,
        privacy_params: params,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['privacy-domains'] });
      setShowCreate(false);
      setNewDomain({ name: '', data_schema: '', privacy_params: '' });
    },
  });

  const domainList: any[] = (domains as any)?.data?.items || (domains as any)?.data || domains || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Shield className="w-6 h-6" /> 隐私计算
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            HIPAA Safe Harbor 18 项标识符脱敏 + 差分隐私 + 联邦查询
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="w-4 h-4" /> 新建隐私域
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <Lock className="w-5 h-5 text-blue-500" />
            <span className="font-medium">数据脱敏</span>
          </div>
          <p className="text-sm text-gray-500">HIPAA Safe Harbor 18 项标识符自动识别与脱敏</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <EyeOff className="w-5 h-5 text-green-500" />
            <span className="font-medium">差分隐私</span>
          </div>
          <p className="text-sm text-gray-500">注入校准噪声，保障个体隐私不可逆推</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <Eye className="w-5 h-5 text-purple-500" />
            <span className="font-medium">联邦查询</span>
          </div>
          <p className="text-sm text-gray-500">跨域联合统计，原始数据不出域</p>
        </Card>
      </div>

      {isLoading ? (
        <Card className="p-8 text-center text-gray-500">加载中...</Card>
      ) : domainList.length === 0 ? (
        <Card className="p-8 text-center text-gray-500">
          <Shield className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>暂无隐私域</p>
          <p className="text-xs mt-2">点击右上角"新建隐私域"开始</p>
        </Card>
      ) : (
        <div className="grid gap-4">
          {domainList.map((domain: any) => (
            <Card key={domain.id} className="p-5">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-semibold">{domain.name}</h3>
                    <Badge variant={domain.status === 'active' ? 'green' : 'gray'}>
                      {domain.status || 'unknown'}
                    </Badge>
                  </div>
                  {domain.data_schema && (
                    <div className="mb-2">
                      <p className="text-xs text-gray-500 mb-1">数据 Schema</p>
                      <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                        {JSON.stringify(domain.data_schema, null, 2)}
                      </pre>
                    </div>
                  )}
                  {domain.privacy_params && (
                    <div>
                      <p className="text-xs text-gray-500 mb-1">隐私参数</p>
                      <pre className="text-xs bg-gray-50 p-2 rounded overflow-x-auto">
                        {JSON.stringify(domain.privacy_params, null, 2)}
                      </pre>
                    </div>
                  )}
                  <p className="text-xs text-gray-400 mt-2">
                    创建时间: {domain.created_at ? new Date(domain.created_at).toLocaleString() : '-'}
                  </p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <Card className="p-6 w-[480px]" onClick={(e: any) => e.stopPropagation()}>
            <h3 className="font-semibold mb-4">新建隐私域</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-600 mb-1">域名</label>
                <input
                  type="text"
                  value={newDomain.name}
                  onChange={(e) => setNewDomain({ ...newDomain, name: e.target.value })}
                  className="w-full border rounded px-3 py-2"
                  placeholder="如：临床数据域"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">数据 Schema (JSON)</label>
                <textarea
                  value={newDomain.data_schema}
                  onChange={(e) => setNewDomain({ ...newDomain, data_schema: e.target.value })}
                  className="w-full border rounded px-3 py-2 font-mono text-xs"
                  rows={4}
                  placeholder='{"fields": [{"name": "age", "type": "int"}]}'
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">隐私参数 (JSON)</label>
                <textarea
                  value={newDomain.privacy_params}
                  onChange={(e) => setNewDomain({ ...newDomain, privacy_params: e.target.value })}
                  className="w-full border rounded px-3 py-2 font-mono text-xs"
                  rows={3}
                  placeholder='{"epsilon": 1.0, "delta": 1e-5}'
                />
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="secondary" onClick={() => setShowCreate(false)}>取消</Button>
                <Button
                  loading={createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                  disabled={!newDomain.name}
                >
                  创建
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
