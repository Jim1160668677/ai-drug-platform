---
kind: frontend_style
name: Streamlit 原生主题与页面风格体系
category: frontend_style
scope:
    - '**'
source_files:
    - precision-drug-design/.streamlit/config.toml
    - precision-drug-design/frontend/app.py
    - "precision-drug-design/frontend/pages/1_\U0001F4C1_项目管理.py"
    - precision-drug-design/frontend/api_client.py
    - precision-drug-design/frontend/auth.py
---

本仓库的前端 UI 完全基于 Streamlit 构建，未引入任何第三方 CSS/SCSS/Tailwind 等样式框架，视觉风格通过 Streamlit 内置的 config.toml 主题配置与 st.set_page_config 统一管控。

### 1. 系统与方法论
- UI 框架：纯 Streamlit（Python），无独立前端工程、无 HTML/CSS 文件。
- 主题管理：通过项目根目录 .streamlit/config.toml 集中定义全局主题色、背景、字体与服务端口。
- 页面级配置：每个页面在入口处调用 st.set_page_config(page_title, page_icon, layout="wide") 设置标题、图标与宽布局。
- 侧边栏导航：主入口 frontend/app.py 使用 st.sidebar.page_link 以 emoji 前缀 + 中文标签组织功能导航。

### 2. 关键文件
- precision-drug-design/.streamlit/config.toml — 全局主题色（primaryColor=#1976D2）、背景色、字体与服务配置。
- precision-drug-design/frontend/app.py — 应用主入口，渲染侧边栏与首页，统一 st.set_page_config。
- precision-drug-design/frontend/pages/*.py — 各业务页面，均遵循相同 set_page_config + require_auth() + 分栏布局模式。
- precision-drug-design/frontend/api_client.py / auth.py — 复用 API 客户端与认证逻辑，避免在各页面重复实现。

### 3. 架构与约定
- 单页多模块：所有页面位于 frontend/pages/ 下，按数字序号 + emoji + 中文命名（如 3_🎯_靶点发现.py），由 Streamlit 自动路由。
- 统一布局：全部页面使用 layout="wide"，并通过 st.columns([n,m]) 进行左右分栏排版。
- 交互反馈：统一使用 st.success / st.error / st.info 消息提示，配合 st.rerun() 刷新状态。
- 数据获取：通过 frontend.api_client.cached_get 带 TTL 缓存访问后端 REST API，减少重复请求。
- 认证守卫：各页面开头调用 require_auth()，未登录则跳转回首页。

### 4. 开发者应遵循的规则
- 新增页面时，首行必须调用 st.set_page_config(page_title=..., page_icon=..., layout="wide")。
- 页面文件名遵循 NN_🔤_中文名.py 编号+emoji+中文命名规范，确保侧边栏顺序可控。
- 所有用户输入使用 st.form 包裹，提交后通过 api_client.get_client().post(...) 调用后端并 invalidate_cache() + st.rerun()。
- 列表展示优先使用 st.expander 折叠详情，操作按钮用 st.columns(3) 三列对齐。
- 全局主题修改仅编辑 .streamlit/config.toml，禁止在页面内硬编码颜色或覆盖主题。
- 不引入自定义 CSS/JS；如需扩展组件，应在 frontend/streamlit_app/components/ 下以 Python 函数封装复用。