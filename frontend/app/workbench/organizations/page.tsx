'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Plus, Users } from 'lucide-react';
import {
  listOrganizations,
  createOrganization,
  type Organization,
  ORG_TYPE_LABELS,
} from '@/lib/api';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Loading from '@/components/ui/Loading';

export default function OrganizationsPage() {
  const queryClient = useQueryClient();
  const [filterType, setFilterType] = useState<string>('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', org_type: 'pharma', contact_email: '', address: '', capabilities: '' });

  const { data, isLoading } = useQuery({
    queryKey: ['organizations', filterType],
    queryFn: () => listOrganizations({ org_type: filterType || undefined, page_size: 100 }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Partial<Organization>) => createOrganization(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
      setShowCreate(false);
      setForm({ name: '', org_type: 'pharma', contact_email: '', address: '', capabilities: '' });
    },
  });

  const items: Organization[] = data?.data ?? data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Building2 className="w-6 h-6 text-primary-600" />
            机构管理
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            管理科研院所、药企、医院、CRO/CDMO 等机构，分配用户职能
          </p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)}>
          <Plus className="w-4 h-4" />
          新建机构
        </Button>
      </div>

      {/* 创建表单 */}
      {showCreate && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-600">机构名称</label>
              <input
                className="w-full mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如：中科院上海药物研究所"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">机构类型</label>
              <select
                className="w-full mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
                value={form.org_type}
                onChange={(e) => setForm({ ...form, org_type: e.target.value })}
              >
                {Object.entries(ORG_TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">联系邮箱</label>
              <input
                className="w-full mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
                value={form.contact_email}
                onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">地址</label>
              <input
                className="w-full mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs font-medium text-gray-600">能力标签（逗号分隔）</label>
              <input
                className="w-full mt-1 rounded border border-gray-300 px-3 py-2 text-sm"
                value={form.capabilities}
                onChange={(e) => setForm({ ...form, capabilities: e.target.value })}
                placeholder="target_validation, synthesis, clinical"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowCreate(false)}>取消</Button>
            <Button
              disabled={!form.name || createMutation.isPending}
              loading={createMutation.isPending}
              onClick={() =>
                createMutation.mutate({
                  name: form.name,
                  org_type: form.org_type,
                  contact_email: form.contact_email || undefined,
                  address: form.address || undefined,
                  capabilities: form.capabilities
                    ? form.capabilities.split(',').map((s) => s.trim()).filter(Boolean)
                    : undefined,
                })
              }
            >
              创建
            </Button>
          </div>
        </div>
      )}

      {/* 类型筛选 */}
      <div className="flex flex-wrap gap-2">
        <button
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
            !filterType ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
          onClick={() => setFilterType('')}
        >
          全部
        </button>
        {Object.entries(ORG_TYPE_LABELS).map(([k, v]) => (
          <button
            key={k}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filterType === k ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
            onClick={() => setFilterType(k)}
          >
            {v}
          </button>
        ))}
      </div>

      {/* 机构列表 */}
      {isLoading ? (
        <Loading label="加载机构列表..." />
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500">
          暂无机构，点击「新建机构」创建
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((org) => (
            <div key={org.id} className="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Building2 className="w-5 h-5 text-gray-400" />
                  <span className="font-semibold text-gray-900">{org.name}</span>
                </div>
                <Badge variant="blue" value={ORG_TYPE_LABELS[org.org_type] || org.org_type} />
              </div>
              {org.contact_email && (
                <div className="text-xs text-gray-500">{org.contact_email}</div>
              )}
              {org.address && (
                <div className="text-xs text-gray-500">{org.address}</div>
              )}
              {org.capabilities && org.capabilities.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {org.capabilities.map((c) => (
                    <span key={c} className="px-2 py-0.5 rounded bg-gray-100 text-xs text-gray-600">
                      {c}
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-1 text-xs text-gray-400 pt-1">
                <Users className="w-3 h-3" />
                <a href={`/workbench/organizations/${org.id}/users`} className="hover:text-primary-600">
                  查看成员
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
