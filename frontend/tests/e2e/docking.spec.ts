import { test, expect, type Route } from '@playwright/test';

/**
 * 分子对接 — /workbench/docking
 *
 * mock API:POST /api/v1/docking/hybrid
 *   返回 { final_ranking, docking_results, report, cost_usd, steps_completed, truncated }
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
  await page.route('**/api/v1/docking/hybrid', (route) =>
    mockJson(route, {
      success: true,
      data: {
        final_ranking: [],
        docking_results: [],
        report: 'Hybrid 对接报告:候选分子未达显著结合阈值。',
        cost_usd: 0.01,
        steps_completed: 5,
        truncated: false,
      },
      meta: {},
    }),
  );
});

test.describe('分子对接', () => {
  test('渲染标题和 3 个模式按钮', async ({ page }) => {
    await page.goto('/workbench/docking');
    await expect(page.getByRole('heading', { name: '分子对接', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Hybrid/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Uni-Mol/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Vina/ })).toBeVisible();
  });

  test('默认 hybrid 模式显示 Target ID 输入框,切换到 unimol 后隐藏', async ({ page }) => {
    await page.goto('/workbench/docking');
    await expect(page.getByText('Target ID（Hybrid 模式必填）', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Uni-Mol/ }).click();
    await expect(page.getByText('Target ID（Hybrid 模式必填）', { exact: true })).toBeHidden();
  });

  test('空输入时按钮 disabled', async ({ page }) => {
    await page.goto('/workbench/docking');
    await expect(page.getByRole('button', { name: '开始对接', exact: true })).toBeDisabled();
  });

  test('hybrid 模式无 target_id 点击显示错误 "Hybrid 模式需要 target_id"', async ({ page }) => {
    await page.goto('/workbench/docking');
    await page.getByPlaceholder('CC(=O)Oc1ccccc1C(=O)O').fill('CCO');
    await page.getByRole('button', { name: '开始对接', exact: true }).click();
    await expect(page.getByText('Hybrid 模式需要 target_id', { exact: true })).toBeVisible();
  });

  test('成功后展示对接结果 JSON', async ({ page }) => {
    await page.goto('/workbench/docking');
    await page.getByPlaceholder('CC(=O)Oc1ccccc1C(=O)O').fill('CCO');
    await page.getByPlaceholder(/00000000-0000-0000-0000-000000000000/).fill('target-001');
    await page.getByRole('button', { name: '开始对接', exact: true }).click();
    await expect(page.getByRole('heading', { name: '对接结果', exact: true })).toBeVisible();
    await expect(page.locator('pre')).toBeVisible();
    // 窄视口冒烟
    await expect(page.getByRole('heading', { name: '分子对接', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
