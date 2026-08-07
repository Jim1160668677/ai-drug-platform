import { test, expect, type Route } from '@playwright/test';

/**
 * 单细胞分析 — /workbench/cells
 *
 * mock API:POST /api/v1/cells/perturbation
 *   返回 { gene, perturbation_score }
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
  await page.route('**/api/v1/cells/perturbation', (route) =>
    mockJson(route, {
      success: true,
      data: { gene: 'TP53', perturbation_score: 0.8 },
      meta: {},
    }),
  );
});

test.describe('单细胞分析', () => {
  test('渲染标题和 3 个 Tab', async ({ page }) => {
    await page.goto('/workbench/cells');
    await expect(page.getByRole('heading', { name: '单细胞分析', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '基因扰动', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '细胞注释', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '引擎状态', exact: true })).toBeVisible();
  });

  test('默认 perturbation Tab 显示基因符号输入框', async ({ page }) => {
    await page.goto('/workbench/cells');
    await expect(page.getByText('基因符号', { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('EGFR')).toBeVisible();
  });

  test('切换到细胞注释 Tab 显示提示 "细胞注释需上传表达矩阵数据"', async ({ page }) => {
    await page.goto('/workbench/cells');
    await page.getByRole('button', { name: '细胞注释', exact: true }).click();
    await expect(page.getByText(/细胞注释需上传表达矩阵数据/)).toBeVisible();
  });

  test('切换到引擎状态 Tab 显示查询按钮', async ({ page }) => {
    await page.goto('/workbench/cells');
    await page.getByRole('button', { name: '引擎状态', exact: true }).click();
    await expect(page.getByRole('button', { name: '查询引擎状态', exact: true })).toBeVisible();
  });

  test('输入基因后点击预测,验证结果展示', async ({ page }) => {
    await page.goto('/workbench/cells');
    await page.getByPlaceholder('EGFR').fill('TP53');
    await page.getByRole('button', { name: '预测扰动效应', exact: true }).click();
    await expect(page.getByRole('heading', { name: '结果', exact: true })).toBeVisible();
    await expect(page.locator('pre')).toBeVisible();
    // 窄视口冒烟
    await expect(page.getByRole('heading', { name: '单细胞分析', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
