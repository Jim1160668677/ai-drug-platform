'use client';

import { useQuery } from '@tanstack/react-query';
import { Grid3x3 } from 'lucide-react';
import { getFunctionMatrix, ORG_TYPE_LABELS, FUNCTION_ROLE_LABELS } from '@/lib/api';
import Loading from '@/components/ui/Loading';

export default function FunctionMatrixPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['function-matrix'],
    queryFn: getFunctionMatrix,
  });

  if (isLoading) return <Loading label="加载职能×机构矩阵..." />;

  const matrix = data?.data ?? data;
  if (!matrix) return null;

  const orgTypes: string[] = matrix.org_types || [];
  const functionRoles: string[] = matrix.function_roles || [];
  const matrixData: Record<string, string[]> = matrix.matrix || {};
  const workspaces: Record<string, string> = matrix.workspaces || {};

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Grid3x3 className="w-6 h-6 text-primary-600" />
          职能×机构矩阵
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          明确"谁在什么机构做什么"——靶点发现/分子设计/用药指导/实验验证各有合法机构
        </p>
      </div>

      {/* 矩阵表格 */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50">
              <th className="px-4 py-3 text-left font-medium text-gray-600 sticky left-0 bg-gray-50">
                职能 / 机构
              </th>
              {orgTypes.map((ot) => (
                <th key={ot} className="px-4 py-3 text-center font-medium text-gray-600">
                  {ORG_TYPE_LABELS[ot] || ot}
                </th>
              ))}
              <th className="px-4 py-3 text-left font-medium text-gray-600">默认工作台</th>
            </tr>
          </thead>
          <tbody>
            {functionRoles.map((fr) => (
              <tr key={fr} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900 sticky left-0 bg-white">
                  {FUNCTION_ROLE_LABELS[fr] || fr}
                </td>
                {orgTypes.map((ot) => {
                  const valid = (matrixData[fr] || []).includes(ot);
                  return (
                    <td key={ot} className="px-4 py-3 text-center">
                      {valid ? (
                        <span className="inline-flex w-6 h-6 items-center justify-center rounded-full bg-green-100 text-green-600 text-xs">
                          ✓
                        </span>
                      ) : (
                        <span className="inline-flex w-6 h-6 items-center justify-center rounded-full bg-gray-100 text-gray-300 text-xs">
                          —
                        </span>
                      )}
                    </td>
                  );
                })}
                <td className="px-4 py-3 text-xs text-primary-600">
                  {workspaces[fr] || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 说明 */}
      <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-4 space-y-2 text-xs text-blue-800">
        <div className="font-semibold">矩阵说明</div>
        <ul className="list-disc list-inside space-y-1">
          <li><strong>靶点发现</strong>：科研院所（基础研究）、药企（转化研究）、医院（临床发现）</li>
          <li><strong>分子设计</strong>：药企（药物化学）、CRO（外包设计）、科研院所（方法研究）</li>
          <li><strong>用药指导</strong>：仅医院（临床医生主导，需处方权）</li>
          <li><strong>实验验证</strong>：科研院所（自建实验室）、CRO/CDMO/检测机构（外包湿实验）</li>
          <li><strong>注册申报</strong>：药企（申办方）、CRO（注册代理）</li>
        </ul>
      </div>
    </div>
  );
}
