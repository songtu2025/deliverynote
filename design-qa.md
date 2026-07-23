# DeliveryNote PC 界面验收报告

| 文档属性 | 说明 |
| --- | --- |
| 报告状态 | 已完成的范围验收记录 |
| 验收对象 | DeliveryNote PC Web |
| 功能源码基线 | Git tree `5ac215401475bfe32d30197b24472ca64e0fadc1` |
| 生产前端资源 | `index-pW2kxPpw.js` / `index-CbzC7nbw.css` |
| 最后完整复核 | 2026-07-23（Asia/Shanghai） |
| 需求基线 | [DeliveryNote PC 界面规范](UI_UX_OPTIMIZATION_PLAN.md) |

## 1. 验收结论

当前版本通过已定义的 PC 核心流程、管理员维护流程、自动化测试和生产烟雾检查，可以作为少量内部用户的现有操作基线。

本结论仅适用于本报告列出的范围，不表示：

- 已完成手机端适配；
- 已获得完整 WCAG 合规认证；
- 已完成压力、容量、高可用或灾难恢复认证；
- 历史批次中的全部待处理数量已获得业务确认；
- 任何后续提交无需重新验收。

### 1.1 结果标记

| 标记 | 含义 |
| --- | --- |
| 通过 | 要求已有自动化、浏览器或持久证据支持 |
| 部分覆盖 | 已验证主要行为，但仍有明确未覆盖项 |
| 不适用 | 不属于当前 PC 内部工具的验收范围 |

## 2. 验收范围

### 2.1 已覆盖

- 登录、退出、权限入口和右上角账号区；
- 批次列表、新建批次与独立批次路由；
- 多文件来源顺序、计算状态、数量摘要和待处理筛选；
- 待处理拆分抽屉；
- 单来源、合并 Excel 和分文件 ZIP 下载入口；
- 超收规则当前状态、发布与历史版本；
- 五类基础资料目录；
- 库位服务器草稿、Excel 替换、校验、发布和冲突保护；
- 用户账号和最近 200 条操作记录；
- 北京时间显示；
- 1280×800、1440×900、1920×1080 PC 视口。

### 2.2 未覆盖

- 手机端专项布局；
- 屏幕阅读器完整流程；
- 全页面纯键盘遍历；
- 自动化颜色对比度审计；
- 大数据量分页与性能压测；
- 多 API、多 Worker 或集群部署；
- 灾难恢复演练。

## 3. 环境与证据

### 3.1 证据层级

| 层级 | 说明 |
| --- | --- |
| E1 | 自动化测试：组件、API、核心业务或 Worker |
| E2 | 隔离 QA 环境中的真实 Chrome 操作、截图与结构化记录 |
| E3 | 正式环境只读或低风险烟雾检查 |

单一截图不用于证明数据一致性；单一组件测试不用于证明真实浏览器布局；单一健康检查不用于证明完整业务流程。

### 3.2 隔离 QA 环境

管理员维护证据来自隔离 Docker Compose QA 项目和脱敏数据：

| 项目 | 值 |
| --- | --- |
| 浏览器 | Google Chrome `146.0.7680.71` |
| 视口 | 1280×800、1440×900、1920×1080 |
| 生产数据变更 | 无 |
| 页面整体横向溢出 | 0 px |
| 并发冲突回归 | PostgreSQL 环境 24 次迭代 |
| QA 正式版本 | 验收后保持不变 |
| QA 草稿 | 验收后已放弃 |

### 3.3 持久证据

证据目录：

```text
design/admin-maintenance-qa/
```

| 文件 | 证据内容 |
| --- | --- |
| `01-base-data-catalog-1440x900.png` | 1440×900 基础资料目录 |
| `02-base-data-catalog-1920x1080.png` | 1920×1080 基础资料目录 |
| `02b-base-data-catalog-1280x800.png` | 1280×800 基础资料目录 |
| `03-draft-workspace-1440x900.png` | 库位服务器草稿工作台 |
| `04-create-drawer-1440x900.png` | 新增记录抽屉 |
| `05-edit-drawer-1440x900.png` | 编辑记录抽屉 |
| `06-excel-diff-1440x900.png` | Excel 整表替换预览 |
| `07-publish-errors-1440x900.png` | 发布错误阻断 |
| `08-publish-warnings-1440x900.png` | 发布警告确认 |
| `09-user-accounts-1440x900.png` | 用户账号 |
| `10-audit-log-1440x900.png` | 操作记录 |
| `audit-evidence.json` | QA 环境、步骤、修复和安全结果 |
| `capture-metrics.json` | 视口、页面宽度和草稿清理指标 |

这些文件不包含真实密码、Token 或业务 Excel。

批次工作台的早期截图只存在于开发临时目录，不作为持久证据引用；相关结论由自动化测试和生产浏览器复核支持。这一限制在报告中明确保留，不用不可复核路径补足证据。

## 4. 需求追踪矩阵

### 4.1 导航、账号与时间

| 需求 | 结果 | 证据 |
| --- | :---: | --- |
| `UI-NAV-001`、`UI-NAV-002` | 通过 | E1 `frontend/src/App.test.tsx`；角色入口组件测试 |
| `UI-NAV-003`、`UI-NAV-004` | 通过 | E1 `App.test.tsx` 覆盖 URL 恢复和 `popstate`；E3 刷新、前进、后退复核 |
| `UI-SHELL-001`、`UI-SHELL-002` | 通过 | E1 `App.test.tsx`；E2 管理页面截图 |
| `UI-SHELL-003` | 通过 | E1 `App.test.tsx` 覆盖服务端登出、本地会话清理和返回登录页 |
| `UI-SHELL-004` | 通过 | E1 `frontend/src/dateTime.test.ts`；E3 使用 `America/Los_Angeles` 浏览器时区复核 |
| `UI-SHELL-005` | 通过 | E1 各页面加载、空状态与错误状态测试 |

### 4.2 批次列表与详情

| 需求 | 结果 | 证据 |
| --- | :---: | --- |
| `UI-LIST-001`–`UI-LIST-005` | 通过 | E1 `frontend/src/pages/BatchesPage.test.tsx`；E3 批次列表与新建弹窗复核 |
| `UI-BATCH-001`–`UI-BATCH-005` | 通过 | E1 `frontend/src/pages/BatchDetail.test.tsx`、`App.test.tsx`；E3 批次详情、刷新与返回 |
| `UI-BATCH-006`–`UI-BATCH-010` | 通过 | E1 `BatchDetail.test.tsx` 与后端批次/Worker 测试；E3 页面状态复核 |
| `UI-BATCH-011`、`UI-BATCH-012` | 通过 | E1 待处理主操作、搜索及六类筛选测试；E3 原因筛选复核 |
| `UI-BATCH-013`、`UI-BATCH-014` | 通过 | E1 拆分抽屉与请求状态测试；后端拆分守恒测试 |
| `UI-EXPORT-001`–`UI-EXPORT-005` | 通过 | E1 `BatchDetail.test.tsx`、`tests/test_worker.py`；E3 合并 Excel 与分文件 ZIP 下载 |

补充验证：

- 多文件合并下载与分文件 ZIP 位于同一结果操作区；
- 页面不存在重复的底部导出卡片；
- 合并工作簿包含按来源顺序形成的导入和待处理数据；
- ZIP 只保留逐来源工作簿，不混入合并文件；
- 来源下载、批次合并下载和 ZIP 的文案可区分。

### 4.3 基础资料与库位草稿

| 需求 | 结果 | 证据 |
| --- | :---: | --- |
| `UI-DATA-001`–`UI-DATA-004` | 通过 | E1 `frontend/src/pages/admin/InputDataPanel.test.tsx`；E2 三档基础资料截图 |
| `UI-DATA-005` | 通过 | E1 前端入口测试与 `tests/test_position_drafts.py` 强制草稿流程测试 |
| `UI-DRAFT-001`–`UI-DRAFT-005` | 通过 | E1 `PositionMaintenance.test.tsx`；E2 草稿工作台及新增/编辑抽屉 |
| `UI-DRAFT-006` | 通过 | E1 Excel 导入预览测试；E2 `06-excel-diff-1440x900.png` |
| `UI-DRAFT-007`、`UI-DRAFT-009` | 通过 | E1 发布状态测试；E2 发布错误与警告截图 |
| `UI-DRAFT-008` | 通过 | E1 `tests/test_position_drafts.py`；E2 PostgreSQL 冲突检查 24 次 |

安全结果：

- 草稿建立后正式版本发生变化时，旧草稿不能覆盖新版本；
- 发布事务再次校验草稿基线；
- Excel 替换先展示增、改、删、错误和警告；
- 多条警告时内容区域滚动，底部操作保持可达；
- 验收未改变 QA 当前正式版本，临时草稿已清理。

### 4.4 超收规则、用户与审计

| 需求 | 结果 | 证据 |
| --- | :---: | --- |
| `UI-RULE-001`–`UI-RULE-006` | 通过 | E1 `frontend/src/pages/OverreceiptRulesPage.test.tsx` 与后端规则测试；E3 规则页面复核 |
| `UI-ADMIN-001`–`UI-ADMIN-003` | 通过 | E1 `frontend/src/pages/AdminPage.test.tsx`；E2 `09-user-accounts-1440x900.png` |
| `UI-AUDIT-001`、`UI-AUDIT-002` | 通过 | E1 `AdminPage.test.tsx`；E2 `10-audit-log-1440x900.png` |
| `UI-AUDIT-003` | 通过 | E1 `tests/test_position_drafts.py`、`AdminPage.test.tsx`；E2 操作记录截图 |

“恢复/继续库位草稿”的审计事件已专项复核：

- 重复进入现有草稿时写入 `resume_input_draft`；
- 事件记录操作用户、草稿实体 ID 和正式基线版本；
- 前端将事件显示为“继续库位草稿”，不暴露内部英文动作名；
- 相关回归测试为 `test_resuming_existing_draft_records_the_admin_action` 和 `shows draft audit labels and resolves operator names`。

行级自动保存不制造高频审计噪音；草稿创建、继续、Excel 导入、发布和放弃等业务节点保留可理解事件。

### 4.5 可访问性与视口

| 需求 | 结果 | 证据 |
| --- | :---: | --- |
| `UI-A11Y-001`、`UI-A11Y-002` | 通过 | E1 页面测试按可读名称查询控件；E2 表单与筛选截图 |
| `UI-A11Y-003`、`UI-A11Y-004` | 通过 | E2 可见焦点与文字状态复核 |
| `UI-A11Y-005` | 部分覆盖 | 已复核主要弹窗/抽屉；未完成全站纯键盘遍历 |
| `UI-VIEW-001`–`UI-VIEW-004` | 通过 | E2 1280×800、1440×900、1920×1080 截图与 0 px 页面溢出指标 |

## 5. 自动化验证结果

最后完整执行结果：

| 检查 | 结果 |
| --- | --- |
| Frontend Vitest | 8 个测试文件，72/72 通过 |
| Frontend production build | 通过 |
| Python `unittest` | 131/131 通过 |
| `pip check` | 通过 |
| Docker Compose config | 通过 |
| `git diff --check` | 通过 |

前端测试文件：

```text
frontend/src/App.test.tsx
frontend/src/dateTime.test.ts
frontend/src/pages/AdminPage.test.tsx
frontend/src/pages/BatchDetail.test.tsx
frontend/src/pages/BatchesPage.test.tsx
frontend/src/pages/OverreceiptRulesPage.test.tsx
frontend/src/pages/admin/InputDataPanel.test.tsx
frontend/src/pages/admin/PositionMaintenance.test.tsx
```

后端业务、API 与 Worker 结果来自 `tests/` 完整测试集，不只运行单个定向用例。

生产构建仍有单包超过 500 kB 的提示，不是构建失败；当前没有把拆包列为小规模内部使用的发布阻断项。

## 6. 真实浏览器场景

### 6.1 批次流程

已执行：

- 打开批次列表并进入批次详情；
- 点击当前主操作定位待处理区域；
- 使用原因、规模定位和备货定位筛选；
- 打开并关闭拆分抽屉而不保存；
- 下载合并 Excel 和分文件 ZIP；
- 刷新保持当前 `/batches/{id}`；
- 浏览器返回回到批次列表；
- 检查失败请求与控制台错误。

### 6.2 管理员维护

已执行：

- 查看五类基础资料及其状态；
- 创建或恢复服务器草稿；
- 新增、编辑和筛选库位记录；
- 预览 Excel 整表替换差异；
- 验证错误阻断发布；
- 验证警告显式确认；
- 验证正式版本变化时的草稿冲突保护；
- 查看用户账号；
- 查看草稿和版本相关审计事件；
- 放弃 QA 草稿并确认正式版本不变。

### 6.3 时间与账号

已执行：

- 在浏览器时区 `America/Los_Angeles` 下查看业务时间；
- 确认 API 显式 UTC 时间在页面按 `Asia/Shanghai` 显示；
- 查看头像首字母、用户名和中文角色；
- 对比批次列表与批次详情的顶栏定位、高度、背景、底边框、内边距和账号组件尺寸；
- 触发退出并确认服务端登出、本地会话清理和登录页返回。

## 7. 验收期间关闭的问题

| 问题 | 风险 | 修复 | 复核 |
| --- | --- | --- | --- |
| 发布库位版本时，多条警告会把 1440×900 弹窗底部操作推离视口 | 操作人员无法完成或取消发布 | 限制内容区高度并滚动，保留标题和底部操作 | E2 `07`、`08` 截图 |
| 草稿建立后正式版本变化，旧草稿可能覆盖较新版本 | 数据版本被意外回退 | 维护期间阻止替换，发布事务复核基线并提供放弃出口 | E1 后端测试；E2 PostgreSQL 冲突检查 |
| 批次详情刷新回到列表 | 工作上下文丢失 | 使用独立批次 URL 并从路由恢复详情 | E1 `App.test.tsx`；E3 浏览器刷新 |
| 导出区重复且结果形态不清楚 | 下载入口冗余、用户难以选择 | 合并为结果操作区，区分合并 Excel、分文件 ZIP 和来源结果 | E1 `BatchDetail.test.tsx`；E3 下载复核 |
| 浏览器时区改变页面业务时间 | 不同电脑看到不同业务日期 | API 明确 UTC，前端固定转换北京时间 | E1 `dateTime.test.ts`；E3 非北京时间浏览器 |
| 批次详情账号顶栏与其他页面视觉不一致 | 登录状态在不同页面缺少统一感 | 移除批次专属顶栏覆盖，继续复用统一账号组件 | E1 `App.test.tsx` 计算样式对比；E3 正式 Chrome 1440×900 复核 |

## 8. 残余风险

| 风险 | 当前判断 | 后续触发条件 |
| --- | --- | --- |
| 未完成完整 WCAG 审计 | 当前内部 PC 使用可接受，但不宣称合规 | 出现正式无障碍要求 |
| 批次流程缺少仓库内持久截图 | 自动化和生产浏览器已覆盖，视觉历史证据较弱 | 下一次批次 UI 大改时补充脱敏截图 |
| 前端单包约 1.2 MB | 当前人数和网络环境未显示功能影响 | 实测首屏性能影响操作 |
| 无手机端 | 明确不在当前范围 | 业务提出移动使用场景 |
| 操作记录仅最近 200 条 | 满足当前页面口径 | 需要完整审计检索 |
| 无自动化 CI | 依赖发布前人工执行矩阵 | 协作人数或发布频率上升 |

## 9. 后续变更的最低复核

1. 在变更说明中列出受影响的 `UI-*` 需求编号；
2. 运行前端完整测试和生产构建；
3. 在 1280×800 与 1440×900 检查受影响页面；
4. 检查页面横向溢出、表格操作列、弹窗和抽屉底部操作；
5. 检查按钮、筛选器、表格和图标操作的可读名称；
6. 复核登录失效、刷新、返回和下载；
7. 涉及时间时使用非北京时间浏览器时区；
8. 涉及接口、数量、拆分、超收或导出时运行 Python 完整测试；
9. 只记录实际完成的验证，不把未执行项目写成通过。
