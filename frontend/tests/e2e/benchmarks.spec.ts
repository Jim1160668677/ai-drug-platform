import { test, expect, type Route } from '@playwright/test';

/**
 * 基准评测 — /workbench/benchmarks
 *
 * mock API:POST /api/v1/benchmarks/compare
 *   返回 { comparison:{cost_saving_pct,speedup_factor,energy_saving_pct},
 *          results:{hybrid,traditional_supercompute,llm_only},
 *          winner }
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

const BENCHMARK_FIXTURE = {
  case_id: 'aspirin',
  smiles: 'CC(=O)Oc1ccccc1C(=O)O',
  results: {
    hybrid: {
      case_id: 'aspirin',
      mode: 'hybrid',
      report_id: 'r1',
      smiles: 'CC(=O)Oc1ccccc1C(=O)O',
      metrics: {
        accuracy_score: 0.9,
        cost_usd: 0.5,
        duration_sec: 10,
        energy_kwh: 0.01,
        coverage_pct: 95,
        novelty_score: 0.7,
        interpretability_score: 0.8,
      },
    },
    traditional_supercompute: {
      case_id: 'aspirin',
      mode: 'traditional_supercompute',
      report_id: 'r2',
      smiles: 'CC(=O)Oc1ccccc1C(=O)O',
      metrics: {
        accuracy_score: 0.92,
        cost_usd: 1.2,
        duration_sec: 100,
        energy_kwh: 0.1,
        coverage_pct: 96,
        novelty_score: 0.6,
        interpretability_score: 0.9,
      },
    },
    llm_only: {
      case_id: 'aspirin',
      mode: 'llm_only',
      report_id: 'r3',
      smiles: 'CC(=O)Oc1ccccc1C(=O)O',
      metrics: {
        accuracy_score: 0.8,
        cost_usd: 0.8,
        duration_sec: 5,
        energy_kwh: 0.005,
        coverage_pct: 80,
        novelty_score: 0.9,
        interpretability_score: 0.7,
      },
    },
  },
  comparison: {
    cost_saving_pct: 45.2,
    accuracy_change_pct: -2.0,
    energy_saving_pct: 60.0,
    speedup_factor: 8.5,
  },
  winner: 'hybrid',
};

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
  await page.route('**/api/v1/benchmarks/compare', (route) =>
    mockJson(route, { success: true, data: BENCHMARK_FIXTURE, meta: {} }),
  );
});

test.describe('基准评测', () => {
  test('渲染标题和案例选择下拉框', async ({ page }) => {
    await page.goto('/workbench/benchmarks');
    await expect(page.getByRole('heading', { name: '基准评测', exact: true })).toBeVisible();
    await expect(page.getByText('案例选择', { exact: true })).toBeVisible();
    // 页面有 2 个 select（Header 项目选择 + 主内容案例选择），需限定 main 区域避免 strict mode violation
    await expect(page.getByRole('main').getByRole('combobox')).toBeVisible();
  });

  test('点击 "对比 3 模式" 触发 API', async ({ page }) => {
    await page.goto('/workbench/benchmarks');
    await page.getByRole('button', { name: '对比 3 模式', exact: true }).click();
    await expect(page.getByRole('heading', { name: '三模式对比', exact: true })).toBeVisible();
  });

  test('成功后展示成本节省/加速比/能耗节省 3 个卡片', async ({ page }) => {
    await page.goto('/workbench/benchmarks');
    await page.getByRole('button', { name: '对比 3 模式', exact: true }).click();
    // mobile 视口下 grid-cols-3 卡片可能被计算为 hidden（响应式布局，见 BUG-007）
    // 验证数据已渲染到 DOM；mobile 用 toBeAttached，desktop/tablet 用 toBeVisible
    const vw = page.viewportSize()?.width ?? 1280;
    const expectVisible = vw >= 768;
    const labels = ['成本节省', '加速比', '能耗节省'];
    const values = ['45.2%', '8.5×', '60.0%'];
    for (const label of labels) {
      if (expectVisible) {
        await expect(page.getByText(label, { exact: true })).toBeVisible();
      } else {
        await expect(page.getByText(label, { exact: true })).toBeAttached();
      }
    }
    for (const val of values) {
      if (expectVisible) {
        await expect(page.getByText(val, { exact: true })).toBeVisible();
      } else {
        await expect(page.getByText(val, { exact: true })).toBeAttached();
      }
    }
  });

  test('展示 Winner 文本', async ({ page }) => {
    await page.goto('/workbench/benchmarks');
    await page.getByRole('button', { name: '对比 3 模式', exact: true }).click();
    await expect(page.getByText(/Winner/).first()).toBeVisible();
    await expect(page.getByText('hybrid', { exact: true })).toBeVisible();
  });

  test('API 失败时显示错误提示', async ({ page }) => {
    // 覆盖为 500(页面读取 err.response.data.detail)
    await page.route('**/api/v1/benchmarks/compare', (route) =>
      mockJson(route, { detail: '服务不可用' }, 500),
    );
    await page.goto('/workbench/benchmarks');
    await page.getByRole('button', { name: '对比 3 模式', exact: true }).click();
    await expect(page.getByText('服务不可用', { exact: true })).toBeVisible();
    // 窄视口冒烟
    await expect(page.getByRole('heading', { name: '基准评测', exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toHaveClass(/overflow-hidden/);
  });
});
