import { test, expect, type Route } from '@playwright/test';

/**
 * 合成规划 — /workbench/synthesis
 *
 * mock API:POST /api/v1/synthesis/plan
 *   返回 { plan_id, feasibility_label, sa_score, sc_score, total_cost_usd,
 *          cost_per_gram, cost_breakdown, routes, recommendation, is_cost_effective }
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
  await page.route('**/api/v1/synthesis/plan', (route) =>
    mockJson(route, {
      success: true,
      data: {
        plan_id: 'plan-001',
        feasibility_label: 'easy',
        sa_score: 2.5,
        sc_score: 2.0,
        total_cost_usd: 125.5,
        cost_per_gram: 12.55,
        cost_breakdown: { materials: 50, labor: 40, equipment: 20, overhead: 15.5 },
        routes: [{ n_steps: 3, steps: [{ step: 1, reaction: '酯化' }] }],
        n_routes: 1,
        recommendation: '推荐路线 1:3 步合成,成本最低',
        is_cost_effective: true,
      },
      meta: {},
    }),
  );
});

test.describe('合成规划', () => {
  test('渲染标题和 SMILES 输入框(默认值)', async ({ page }) => {
    await page.goto('/workbench/synthesis');
    await expect(page.getByRole('heading', { name: '合成规划', exact: true })).toBeVisible();
    // getByDisplayValue 不是 Playwright API，改用 getByRole('textbox') + toHaveValue
    await expect(page.getByRole('textbox')).toHaveValue('CC(=O)Oc1ccccc1C(=O)O');
  });

  test('渲染 2 个 range 滑块', async ({ page }) => {
    await page.goto('/workbench/synthesis');
    await expect(page.locator('input[type="range"]')).toHaveCount(2);
  });

  test('点击 "生成合成规划" 触发 API', async ({ page }) => {
    await page.goto('/workbench/synthesis');
    await page.getByRole('button', { name: '生成合成规划', exact: true }).click();
    await expect(page.getByText('可行性评估', { exact: true })).toBeVisible();
  });

  test('成功后展示可行性标签和 SAscore', async ({ page }) => {
    await page.goto('/workbench/synthesis');
    await page.getByRole('button', { name: '生成合成规划', exact: true }).click();
    // feasibility_label=easy → FEASIBILITY_LABELS.easy = "易合成"
    await expect(page.getByText('易合成', { exact: true })).toBeVisible();
    // sa_score=2.5 → toFixed(2) = "2.50"
    await expect(page.getByText('2.50', { exact: true })).toBeVisible();
  });

  test('成功后展示 AI 合成推荐', async ({ page }) => {
    await page.goto('/workbench/synthesis');
    await page.getByRole('button', { name: '生成合成规划', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'AI 合成推荐', exact: true })).toBeVisible();
    await expect(page.getByText('推荐路线 1:3 步合成,成本最低', { exact: true })).toBeVisible();
    // 窄视口冒烟
    await expect(page.getByRole('heading', { name: '合成规划', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
