import { describe, it, expect } from 'vitest';
import {
  llmConfigSchema,
  llmConfigCreateSchema,
  validate,
  requiredString,
  optionalString,
} from './validation';

describe('llmConfigSchema', () => {
  const valid = {
    name: 'OpenAI',
    provider: 'openai',
    access_mode: 'api_only' as const,
    upstream_protocol: 'chat_completions' as const,
    base_url: 'https://api.openai.com/v1',
    api_key: 'sk-xxx',
    test_model: 'gpt-4',
    fast_model: 'gpt-3.5-turbo',
    deep_model: 'gpt-4',
    temperature: 0.7,
    max_tokens: 4096,
    timeout_sec: 60,
    description: '',
    is_active: true,
  };

  it('接受合法配置', () => {
    expect(llmConfigSchema.safeParse(valid).success).toBe(true);
  });

  it('temperature 边界 0 与 2 通过', () => {
    expect(llmConfigSchema.safeParse({ ...valid, temperature: 0 }).success).toBe(true);
    expect(llmConfigSchema.safeParse({ ...valid, temperature: 2 }).success).toBe(true);
  });

  it('temperature 超出范围拒绝', () => {
    expect(llmConfigSchema.safeParse({ ...valid, temperature: -0.1 }).success).toBe(false);
    expect(llmConfigSchema.safeParse({ ...valid, temperature: 2.1 }).success).toBe(false);
  });

  it('max_tokens 非整数拒绝', () => {
    expect(llmConfigSchema.safeParse({ ...valid, max_tokens: 1.5 }).success).toBe(false);
  });

  it('非法 base_url 拒绝', () => {
    expect(llmConfigSchema.safeParse({ ...valid, base_url: 'not-a-url' }).success).toBe(false);
  });

  it('llmConfigCreateSchema 要求 api_key 必填', () => {
    const r = llmConfigCreateSchema.safeParse({ ...valid, api_key: '' });
    expect(r.success).toBe(false);
    if (!r.success) {
      const issue = r.error.issues.find((i) => i.path.includes('api_key'));
      expect(issue?.message).toBe('请填写 API 密钥');
    }
  });
});

describe('requiredString / optionalString', () => {
  it('requiredString 拒绝空值并使用自定义 label', () => {
    const r = requiredString('姓名').safeParse('');
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues[0].message).toBe('姓名不能为空');
    }
  });

  it('requiredString 拒绝超过 max 的值', () => {
    const r = requiredString('名称', 5).safeParse('abcdef');
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues[0].message).toBe('名称长度不能超过 5 个字符');
    }
  });

  it('optionalString 接受空字符串与 undefined', () => {
    expect(optionalString().safeParse('').success).toBe(true);
    expect(optionalString().safeParse(undefined).success).toBe(true);
  });

  it('optionalString 拒绝超长值', () => {
    expect(optionalString(3).safeParse('abcd').success).toBe(false);
  });
});

describe('validate 函数', () => {
  const validLlmConfig = {
    name: 'OpenAI',
    provider: 'openai',
    access_mode: 'api_only' as const,
    upstream_protocol: 'chat_completions' as const,
    base_url: 'https://api.openai.com/v1',
    api_key: 'sk-xxx',
    test_model: 'gpt-4',
    fast_model: 'gpt-3.5-turbo',
    deep_model: 'gpt-4',
    temperature: 0.7,
    max_tokens: 4096,
    timeout_sec: 60,
    description: '',
    is_active: true,
  };

  it('成功时返回 data', () => {
    const r = validate(llmConfigSchema, validLlmConfig);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data).toEqual(validLlmConfig);
    }
  });

  it('失败时返回 errors 字典', () => {
    const r = validate(llmConfigSchema, { ...validLlmConfig, name: '', test_model: '' });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.errors).toHaveProperty('name');
      expect(r.errors).toHaveProperty('test_model');
    }
  });

  it('refine 错误按 path 归位', () => {
    // llmConfigCreateSchema refine 要求 api_key 必填，路径明确应位于 api_key
    const r = validate(llmConfigCreateSchema, { ...validLlmConfig, api_key: '' });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.errors.api_key).toBe('请填写 API 密钥');
    }
  });
});
