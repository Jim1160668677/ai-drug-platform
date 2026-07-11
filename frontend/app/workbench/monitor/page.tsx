'use client';

import { useQuery } from '@tanstack/react-query';
import { Activity, Heart, DollarSign, Clock, Cpu, Server } from 'lucide-react';
import axios from 'axios';
import Card from '@/components/ui/Card';
import Badge from '@/components/ui/Badge';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1';

export default function MonitorPage() {
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['health'],
    queryFn: () => axios.get(`${API_BASE}/health`).then((r) => r.data),
    refetchInterval: 30000,
  });

  const { data: costSummary } = useQuery({
    queryKey: ['cost-summary'],
    queryFn: () => axios.get(`${API_BASE}/chat/cost-summary`, {
      headers: typeof window !== 'undefined' ? { Authorization: `Bearer ${localStorage.getItem('ai_drug_token')}` } : {},
    }).then((r) => r.data),
    refetchInterval: 60000,
  });

  const healthData: any = health?.data || health || {};
  const costData: any = costSummary?.data || costSummary || {};

  const services = healthData.services || {};
  const serviceEntries = Object.entries(services);

  const statCards = [
    {
      label: '系统状态',
      value: healthData.status === 'healthy' ? '正常' : healthData.status || '-',
      icon: Heart,
      color: healthData.status === 'healthy' ? 'text-green-500' : 'text-red-500',
      variant: healthData.status === 'healthy' ? 'green' : 'red',
    },
    {
      label: '今日 LLM 成本',
      value: costData.total_cost_usd != null ? `$${Number(costData.total_cost_usd).toFixed(2)}` : '-',
      icon: DollarSign,
      color: 'text-orange-500',
      variant: 'gray',
    },
    {
      label: 'API 请求次数',
      value: costData.request_count != null ? `${costData.request_count}` : '-',
      icon: Activity,
      color: 'text-blue-500',
      variant: 'gray',
    },
    {
      label: '运行模式',
      value: healthData.mode || '-',
      icon: Cpu,
      color: 'text-purple-500',
      variant: 'gray',
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Activity className="w-6 h-6" /> 系统监控
        </h1>
        <p className="text-sm text-gray-500 mt-1">系统健康检查 + LLM 成本统计 + 服务状态（30 秒自动刷新）</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {statCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.label} className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-500">{stat.label}</span>
                <Icon className={`w-5 h-5 ${stat.color}`} />
              </div>
              <div className="flex items-center gap-2">
                <p className="text-xl font-bold">{stat.value}</p>
                <Badge variant={stat.variant as any}>{stat.variant === 'green' ? 'OK' : 'INFO'}</Badge>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Server className="w-5 h-5 text-blue-500" />
            <h3 className="font-semibold">服务状态</h3>
          </div>
          {healthLoading ? (
            <p className="text-center text-gray-500 py-4">加载中...</p>
          ) : serviceEntries.length === 0 ? (
            <p className="text-center text-gray-500 py-4">暂无服务信息</p>
          ) : (
            <div className="space-y-2">
              {serviceEntries.map(([name, status]: [string, any]) => (
                <div key={name} className="flex items-center justify-between py-2 border-b last:border-0">
                  <span className="text-sm font-medium">{name}</span>
                  <Badge variant={status === 'healthy' || status === 'ok' ? 'green' : 'red'}>
                    {typeof status === 'string' ? status : JSON.stringify(status)}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-5 h-5 text-orange-500" />
            <h3 className="font-semibold">LLM 成本分解</h3>
          </div>
          {costData.by_model && Object.keys(costData.by_model).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(costData.by_model).map(([model, cost]: [string, any]) => (
                <div key={model} className="flex items-center justify-between py-2 border-b last:border-0">
                  <span className="text-sm font-mono">{model}</span>
                  <span className="text-sm font-medium text-orange-600">${Number(cost).toFixed(4)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center text-gray-500 py-4">暂无成本数据</p>
          )}
        </Card>
      </div>

      <Card className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="w-5 h-5 text-gray-500" />
          <h3 className="font-semibold">系统信息</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-gray-500">版本</p>
            <p className="font-medium">{healthData.version || '-'}</p>
          </div>
          <div>
            <p className="text-gray-500">环境</p>
            <p className="font-medium">{healthData.environment || '-'}</p>
          </div>
          <div>
            <p className="text-gray-500">时间戳</p>
            <p className="font-medium text-xs">{healthData.timestamp ? new Date(healthData.timestamp).toLocaleString() : '-'}</p>
          </div>
          <div>
            <p className="text-gray-500">数据库</p>
            <p className="font-medium">{healthData.database || '-'}</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
