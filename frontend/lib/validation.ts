import { z } from 'zod';

// ============= 通用字段 =============
export const requiredString = (label: string, max = 200) =>
  z
    .string()
    .min(1, `${label}不能为空`)
    .max(max, `${label}长度不能超过 ${max} 个字符`);

export const optionalString = (max = 200) =>
  z
    .string()
    .max(max, `长度不能超过 ${max} 个字符`)
    .optional()
    .or(z.literal(''));

// ============= LLM 配置 =============
export const llmConfigSchema = z.object({
  name: requiredString('配置名称', 50),
  provider: optionalString(50),
  access_mode: z.enum(['api_only', 'local_deploy', 'proxy']),
  upstream_protocol: z.enum(['chat_completions', 'completions', 'anthropic']),
  base_url: requiredString('基础 URL', 500).url('URL 格式不正确'),
  api_key: z.string().max(500, 'API 密钥长度不能超过 500').optional().or(z.literal('')),
  test_model: requiredString('测试模型', 100),
  fast_model: optionalString(100),
  deep_model: optionalString(100),
  temperature: z.coerce.number().min(0, '温度 ≥ 0').max(2, '温度 ≤ 2'),
  max_tokens: z.coerce.number().int().min(1, 'Token ≥ 1').max(32000, 'Token ≤ 32000'),
  timeout_sec: z.coerce.number().int().min(1, '超时 ≥ 1 秒').max(600, '超时 ≤ 600 秒'),
  description: optionalString(500),
  is_active: z.boolean(),
});

// 创建场景：API 密钥必填
export const llmConfigCreateSchema = llmConfigSchema.refine(
  (data) => !!data.api_key,
  { path: ['api_key'], message: '请填写 API 密钥' }
);

// ============= 通用工具 =============
export type ValidationResult<T> =
  | { success: true; data: T }
  | { success: false; errors: Record<string, string> };

export function validate<T>(
  schema: z.ZodSchema<T>,
  data: unknown
): ValidationResult<T> {
  const result = schema.safeParse(data);
  if (result.success) {
    return { success: true, data: result.data };
  }
  const errors: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const path = issue.path.join('.') || '_';
    if (!errors[path]) {
      errors[path] = issue.message;
    }
  }
  return { success: false, errors };
}
