# 精准药物设计系统 — ADMET 功能收尾验证计划（Task #165）

## 一、当前状态分析

### 已完成（Task #163-#164）
- ✅ 后端 SMARTS 功能团匹配 bug 修复（`molecule_designer.py` 行 428-442，`C`→`[#6]`/`N`→`[#7]`/`O`→`[#8]`/`S`→`[#16]`）
- ✅ 后端 8 个单元测试（`test_services_integration.py::TestMoleculeDesigner`，15 passed）
- ✅ 后端 2 个集成测试（`test_api_integration.py::TestMoleculeDesign`，7 passed）
- ✅ 前端 `AdmetModal` + `ExplainModal` 组件（`molecules/page.tsx` 行 506-777）

### 验证结果（已确认）
- ✅ **后端全量回归测试**：`1542 passed, 1 warning in 340.13s`（比上次 1532 多 10 个测试，正好对应本次新增，无回归）
- ✅ **后端单元测试**：15 passed in 34.24s
- ✅ **后端集成测试**：7 passed in 27.57s
- ❌ **前端构建**：失败 — `Module not found: Can't resolve 'plotly.js/dist/plotly'`
- ⏳ **前端测试**：项目有 vitest 配置但无测试文件

### 前端构建问题根因
- `react-plotly.js@2.6.0` 内部 `require('plotly.js/dist/plotly')`
- 项目只安装了 `plotly.js-dist-min@2.32.0`（包名/路径不匹配）
- 直接 `npm install plotly.js` 会触发 ERESOLVE peer dependency 冲突（vite@8.1.3 要求 `@types/node@^20.19.0`，实际 `@types/node@20.14.10`）

---

## 二、实施步骤

### Step 1: 修复前端构建（webpack alias 方案）

**文件**：`g:\软件开发\AI药物\frontend\next.config.js`

**方案**：添加 `webpack` 配置，将 `plotly.js/dist/plotly` 重定向到已安装的 `plotly.js-dist-min`。无需新增 50MB+ 依赖，复用现有包。

**变更内容**：
```js
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      'plotly.js/dist/plotly': 'plotly.js-dist-min',
    };
    return config;
  },
  async rewrites() {
    // ... 保持不变
  },
};
```

**验证**：运行 `npm run build`，预期成功编译。

---

### Step 2: 导出 AdmetModal 和 ExplainModal 以便测试

**文件**：`g:\软件开发\AI药物\frontend\app\workbench\molecules\page.tsx`

**变更**：在 `AdmetModal`（行 506）和 `ExplainModal`（行 656）函数定义前添加 `export` 关键字，使其可被测试文件导入。

```tsx
export function AdmetModal({ ... }) { ... }
export function ExplainModal({ ... }) { ... }
```

**理由**：这两个组件是纯展示型组件（props 驱动），单独导出测试比渲染整个页面（需 mock react-query + API + PlotlyChart）更简单可靠。

---

### Step 3: 编写前端组件单元测试

**新建文件**：`g:\软件开发\AI药物\frontend\app\workbench\molecules\__tests__\modals.test.tsx`

**测试框架**：vitest + @testing-library/react + @testing-library/user-event

**测试用例（8 个）**：

#### AdmetModal（4 个）
1. `test_admet_modal_render_empty` — 无结果时渲染 SMILES 输入框和「预测」按钮
2. `test_admet_modal_submit` — 输入 SMILES 并点击「预测」触发 onSubmit 回调
3. `test_admet_modal_display_result` — 传入 result 数据时展示 8 项指标卡片
4. `test_admet_modal_display_error` — 传入 error 结果时展示红色错误提示

#### ExplainModal（4 个）
5. `test_explain_modal_render_empty` — 无结果时渲染 SMILES 输入框和「解析」按钮
6. `test_explain_modal_submit` — 输入 SMILES 并点击「解析」触发 onSubmit 回调
7. `test_explain_modal_display_result` — 传入 result 数据时展示环系统/功能团/原子组成
8. `test_explain_modal_close` — 点击关闭按钮触发 onClose 回调

**Mock 策略**：
- 不需要 mock API 或 react-query（直接测试纯组件）
- Button 组件可能依赖 clsx，已在 dependencies 中
- 如遇到 lucide-react 图标渲染问题，使用 `vi.mock('lucide-react', ...)` mock 为空组件

---

### Step 4: 运行前端测试和构建验证

**命令序列**：
1. `npm test`（vitest 运行 8 个测试）
2. `npm run build`（next build 生产构建）

**预期结果**：
- vitest: 8 passed
- next build: 编译成功，无 Module not found 错误

---

### Step 5: 完善开发文档

**文件**：`g:\软件开发\AI药物\.trae\documents\精准药物设计系统-ADMET功能开发完成报告.md`

**变更**：
1. 替换 2.3 节「（待全量测试完成后补充）」为实际测试结果：
   - 后端全量回归：1542 passed, 1 warning, 340.13s
   - 前端构建：成功（webpack alias 修复）
   - 前端测试：8 passed
2. 在「三、Bug 修复记录」中新增 Bug #2：前端 plotly.js 依赖缺失
3. 在「四、前端交互说明」补充测试覆盖信息

---

## 三、假设与决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| plotly.js 修复方案 | webpack alias 重定向 | 无需新增 50MB 依赖，复用已安装的 plotly.js-dist-min，改动最小 |
| 前端测试策略 | 导出组件 + 单独测试 | 纯展示型组件，避免 mock 整个页面依赖链，测试更稳定 |
| 测试框架 | vitest + @testing-library/react | 项目已配置，无需额外安装 |
| 是否升级 @types/node | 否 | 不必要，webpack alias 方案绕过了 peer dependency 冲突 |

---

## 四、验证清单

- [ ] `npm run build` 成功，无 plotly.js 错误
- [ ] `npm test` 8 个前端测试全部通过
- [ ] 开发文档 2.3 节已补充全量测试结果
- [ ] 开发文档新增 Bug #2 修复记录
- [ ] 后端全量测试 1542 passed 已记录
