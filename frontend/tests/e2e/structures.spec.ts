import { test, expect, type Route } from '@playwright/test';

/**
 * 蛋白结构预测 — /workbench/structures
 *
 * mock API:POST /api/v1/structures/predict
 *   返回 { plddt_mean, source, structure_id, pdb_text }
 *
 * 说明:
 * - dev 环境 API 直连 http://localhost:8000(跨域),axios 以 application/json 发起请求会触发预检,
 *   故 mock 响应统一注入 CORS 头并处理 OPTIONS。
 * - 后端信封 {success, data, meta} 由 lib/api/client.ts 拦截器解包,故 mock 必须带 meta 字段。
 * - /workbench/* 受 middleware 保护(需 ai_drug_token cookie),这里注入伪造 cookie 绕过重定向。
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
  // 伪造登录态(localStorage + cookie),绕过 middleware 重定向
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
  // Header 中的 projects 查询(避免噪声 / 重试)
  await page.route('**/api/v1/projects', (route) => mockJson(route, { success: true, data: [], meta: {} }));
  // 业务 API:结构预测
  await page.route('**/api/v1/structures/predict', (route) =>
    mockJson(route, {
      success: true,
      data: {
        plddt_mean: 85.5,
        source: 'esmfold',
        structure_id: 'str-001',
        pdb_text: 'ATOM      1  N   MET A   1      11.104  6.134  6.504  1.00  0.00           N',
      },
      meta: {},
    }),
  );
});

test.describe('蛋白结构预测', () => {
  test('渲染标题和序列输入框', async ({ page }) => {
    await page.goto('/workbench/structures');
    await expect(page.getByRole('heading', { name: '蛋白结构预测', exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(/MKKLLLIVTAAHCLGGSFVGDVNSNE/)).toBeVisible();
    await expect(page.getByRole('button', { name: '预测结构', exact: true })).toBeVisible();
  });

  test('空输入时按钮 disabled', async ({ page }) => {
    await page.goto('/workbench/structures');
    await expect(page.getByRole('button', { name: '预测结构', exact: true })).toBeDisabled();
  });

  test('输入序列后点击预测,验证 loading 状态(按钮变 "预测中...")', async ({ page }) => {
    // 覆盖 beforeEach 的 mock,加入延迟以稳定捕获 loading 态
    await page.route('**/api/v1/structures/predict', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS_HEADERS });
        return;
      }
      await new Promise<void>((resolve) => {
        setTimeout(() => resolve(), 500);
      });
      await mockJson(route, {
        success: true,
        data: { plddt_mean: 85.5, source: 'esmfold', structure_id: 'str-001', pdb_text: 'ATOM...' },
        meta: {},
      });
    });

    await page.goto('/workbench/structures');
    await page.getByPlaceholder(/MKKLLLIVTAAHCLGGSFVGDVNSNE/).fill('MKKLLLIVTAAHCLGGSFVGDVNSNE');
    await page.getByRole('button', { name: '预测结构', exact: true }).click();
    await expect(page.getByText('预测中...', { exact: true })).toBeVisible();
  });

  test('成功后展示 pLDDT 数值和进度条', async ({ page }) => {
    await page.goto('/workbench/structures');
    await page.getByPlaceholder(/MKKLLLIVTAAHCLGGSFVGDVNSNE/).fill('MKKLLL');
    await page.getByRole('button', { name: '预测结构', exact: true }).click();
    await expect(page.getByText('平均 pLDDT', { exact: true })).toBeVisible();
    // plddt_mean=85.5 → toFixed(2) = "85.50"
    await expect(page.getByText('85.50', { exact: true })).toBeVisible();
    // 进度条填充元素
    await expect(page.locator('.bg-primary-500')).toBeVisible();
  });

  test('API 失败时显示错误提示', async ({ page }) => {
    // 覆盖为 500(页面读取 err.response.data.detail)
    await page.route('**/api/v1/structures/predict', (route) =>
      mockJson(route, { detail: '服务不可用' }, 500),
    );
    await page.goto('/workbench/structures');
    await page.getByPlaceholder(/MKKLLLIVTAAHCLGGSFVGDVNSNE/).fill('MKKLLL');
    await page.getByRole('button', { name: '预测结构', exact: true }).click();
    await expect(page.getByText('服务不可用', { exact: true })).toBeVisible();
    // 窄视口冒烟:标题仍可见、body 未被加 overflow-hidden
    await expect(page.getByRole('heading', { name: '蛋白结构预测', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
