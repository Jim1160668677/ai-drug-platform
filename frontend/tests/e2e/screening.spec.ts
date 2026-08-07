import { test, expect, type Route } from '@playwright/test';

/**
 * 双上下文筛选 — /workbench/screening
 *
 * mock API:
 *   POST /api/v1/screening/dual-context → { amplifiers, n_amplifiers, n_total, summary }
 *   POST /api/v1/screening/vaccine      → { epitopes, gc_content, length }
 *
 * 说明:
 * - dev 跨域,mock 统一注入 CORS 头并处理 OPTIONS 预检。
 * - 后端信封 {success, data, meta} 由 client.ts 解包,mock 需带 meta。
 * - 注入伪造 ai_drug_token cookie 绕过 middleware。
 */

const CORS_HEADERS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type,Authorization',
};

async function mockJson(route: Route, json: unknown, status = 200): Promise<void> {
  if (route.request().method() === 'OPTIONS') {
    await route.fulfill({ status: 204, headers: CORS_HEADERS });
    return;
  }
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(json),
    headers: CORS_HEADERS,
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('ai_drug_token', 'e2e-fake-token');
    localStorage.setItem(
      'ai_drug_user',
      JSON.stringify({ access_token: 'e2e-fake-token', role: 'founder', name: 'Test', email: 'test@test.com' }),
    );
  });
  await page.context().addCookies([
    { name: 'ai_drug_token', value: 'e2e-fake-token', url: 'http://localhost:3000' },
  ]);
  await page.route('**/api/v1/projects', (route) => mockJson(route, { success: true, data: [], meta: {} }));
  await page.route('**/api/v1/screening/dual-context', (route) =>
    mockJson(route, {
      success: true,
      data: {
        amplifiers: [{ smiles: 'CCO', score: 0.45 }],
        n_amplifiers: 1,
        n_total: 3,
        summary: 'CCO 在免疫活跃上下文下效应显著增强',
      },
      meta: {},
    }),
  );
  await page.route('**/api/v1/screening/vaccine', (route) =>
    mockJson(route, {
      success: true,
      data: { epitopes: ['MKL', 'KLL'], gc_content: 0.52, length: 120 },
      meta: {},
    }),
  );
});

test.describe('双上下文筛选', () => {
  test('渲染标题和 2 个模式按钮', async ({ page }) => {
    await page.goto('/workbench/screening');
    await expect(page.getByRole('heading', { name: '双上下文筛选', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '双上下文筛选', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'mRNA 疫苗设计', exact: true })).toBeVisible();
  });

  test('默认筛选模式点击 "开始筛选" 触发 API', async ({ page }) => {
    await page.goto('/workbench/screening');
    await page.getByRole('button', { name: '开始筛选', exact: true }).click();
    await expect(page.getByRole('heading', { name: '完整结果', exact: true })).toBeVisible();
  });

  test('成功后展示条件放大器高亮 "识别到 1 个条件放大器"', async ({ page }) => {
    await page.goto('/workbench/screening');
    await page.getByRole('button', { name: '开始筛选', exact: true }).click();
    await expect(page.getByText('识别到 1 个条件放大器', { exact: true })).toBeVisible();
  });

  test('切换到疫苗模式,无输入点击显示必填错误 "Target ID 和突变序列均为必填"', async ({ page }) => {
    await page.goto('/workbench/screening');
    await page.getByRole('button', { name: 'mRNA 疫苗设计', exact: true }).click();
    await page.getByRole('button', { name: '设计 mRNA 疫苗', exact: true }).click();
    await expect(page.getByText('Target ID 和突变序列均为必填', { exact: true })).toBeVisible();
  });

  test('API 失败时显示错误提示', async ({ page }) => {
    // 覆盖 dual-context 为 500(页面读取 err.response.data.detail)
    await page.route('**/api/v1/screening/dual-context', (route) =>
      mockJson(route, { detail: '服务不可用' }, 500),
    );
    await page.goto('/workbench/screening');
    await page.getByRole('button', { name: '开始筛选', exact: true }).click();
    await expect(page.getByText('服务不可用', { exact: true })).toBeVisible();
    // 窄视口冒烟
    await expect(page.getByRole('heading', { name: '双上下文筛选', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
