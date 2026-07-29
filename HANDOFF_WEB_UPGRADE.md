# DeliveryNote 运维与交接手册

| 文档属性 | 说明 |
| --- | --- |
| 文档状态 | 当前生产 Runbook 与开发交接基线 |
| 适用读者 | 部署维护人员、故障处理人员、后续开发人员 |
| 最后核对 | 2026-07-29（Asia/Shanghai） |
| 生产仓库 | `https://github.com/songtu2025/deliverynote.git` |
| 默认分支 | `master` |
| 生产功能基线 | `master@ed710f8`，Git tree `0499ea2cd6c8e591d036824360bec619d24cc8d6` |

本文记录会随部署变化的运行状态和安全操作步骤。稳定的产品范围、业务契约、权限和文件格式以 [README](README.md) 为准。

## 1. 信息责任边界

| 主题 | 权威来源 |
| --- | --- |
| 产品范围、角色权限、业务不变量、文件契约 | `README.md` |
| 代理工作规则与强制验证要求 | `AGENTS.md` |
| 当前实现行为 | 业务代码与对应自动化测试 |
| 生产提交、容器、资产、批次状态 | 本文最近一次核对记录与生产只读检查 |
| PC 界面要求 | `UI_UX_OPTIMIZATION_PLAN.md` |
| 已执行验收及证据 | `design-qa.md`、`design/admin-maintenance-qa/` |

文档与代码不一致时，不应默认为任一方“自动正确”。先定位差异属于需求变更、实现缺陷还是文档过期，再通过测试和业务口径确认。

## 2. 运行拓扑

```text
Internet / Internal Network
          │ HTTPS
          ▼
宿主机反向代理
          │ 127.0.0.1:18080
          ▼
deliverynote-web (React / Nginx)
          │ /api
          ▼
deliverynote-api (FastAPI) ───── deliverynote_delivery_data
          │                              ▲
          ▼                              │
deliverynote-db (PostgreSQL) ◀── deliverynote-worker
          │
deliverynote_postgres_data
```

生产 Compose 项目名固定为 `deliverynote`。项目名决定数据卷前缀；部署时不得临时更换，否则可能连接到一组新的空数据卷。

| 组件 | 数量 | 持久状态 |
| --- | :---: | --- |
| `web` | 1 | 无；静态前端资源 |
| `api` | 1 | 元数据写入 PostgreSQL，文件写入共享数据卷 |
| `worker` | 1 | 任务状态写入 PostgreSQL，结果写入共享数据卷 |
| `db` | 1 | `deliverynote_postgres_data` |
| 文件存储 | 1 | `deliverynote_delivery_data` |

当前规模固定使用单 API、单 Worker。库位 Excel 导入预览 Token 保存在 API 进程内存中，重启 API 后未发布的导入预览会失效，但服务器草稿中已保存的数据不因此丢失。

## 3. 生产基线

### 3.1 版本与资源

| 项目 | 已核对值 |
| --- | --- |
| 正式地址 | `https://deliverynote.seekwaygroup.com/` |
| 最近部署时间 | 2026-07-29 17:53（Asia/Shanghai） |
| 部署源码树 | 与 `master@ed710f8` 的 Git tree 完全一致 |
| 最新发布分支提交 | `fix/consolidate-import-rows@81e3e40` |
| 前端 JavaScript | `index-BchohicX.js` |
| 前端 CSS | `index-CrS6zE_W.css` |
| Web 回环端口 | `127.0.0.1:18080` |

PR #1 建立完整功能基线，PR #2 重构仓库文档，PR #3 统一批次详情与其他页面的账号顶栏，PR #6 增加待处理原因指导、歧义站点单选和精确超收分配明细。PR #13 修复审校工作流问题。PR #15 通过批量查询和预建匹配索引优化批次读路径，PR #16–#17 将基础资料摘要与 20 行预览合并读取，PR #18 将超收仓库选项改为按需加载，PR #19 将批次概览与异常定位解耦，并加入有容量限制、并发安全的库位资料缓存。PR #22 保留交货导入表第 3 行模板示例，PR #23 合并人工拆分后除数量外完全相同的导入行，避免积加只处理首条记录。

### 3.2 服务状态

最近一次核对结果：

- `db`、`api`、`worker`、`web` 共 4 个容器运行；
- PostgreSQL 和 API 健康检查通过；
- 正式 HTTPS `/health` 返回成功；
- PR #23 部署从 `master@ed710f8` 重新构建并替换 `api`、`worker`、`web`，`db` 未替换；
- 生产数据卷仍为 `deliverynote_postgres_data` 与 `deliverynote_delivery_data`。

这些结果是带日期的快照，不替代变更前的现场检查。

### 3.3 验证基线

2026-07-29 当前验证记录：

| 检查 | 结果 |
| --- | --- |
| Ruff 0.15.22 | `delivery_note`、`tests`、`scripts` 通过 |
| Python `unittest` | 139/139 通过 |
| Frontend Vitest | 8 个测试文件，80/80 通过 |
| `pip check` | 通过 |
| Frontend production build | 通过 |
| Docker Compose config | 通过 |
| `git diff --check` | 通过 |
| 正式 HTTPS `/health` | 通过 |
| 正式 Chrome 顶栏对比 | 批次列表与批次详情计算样式一致，失败响应和控制台错误均为 0 |
| 审校原因指导 QA | 四类原因、候选站点单选和超收分配明细通过；页面及抽屉横向溢出均为 0 |
| 正式 Chrome 审校复核 | 真实旧批次正常加载并显示采购核对提示；失败响应、控制台错误和浏览器业务写入均为 0 |
| PR #13 部署后认证只读验收 | 批次 14 锁定版本默认展开、收起与重开正常；超收规则确认框可打开并取消；失败响应、控制台错误和浏览器业务写入均为 0 |
| PR #13 部署后日志 | Web/API 无新增 5xx、异常栈或运行时错误；重试脚本仅产生 1 次已失效会话注销 401 |
| PR #19 批次 14 冷启动验收 | 概览约 308 ms 可见，40 条异常约 2.64 s 完成；加载期间，概览仍可操作 |
| PR #19 异常接口热缓存 | 10 次中位数 46.28 ms，P95 54.24 ms |
| PR #19 浏览器与日志 | 新资源加载成功；失败响应、控制台错误和浏览器业务写入均为 0；API/Web 无 5xx |
| PR #23 GitHub Actions | 后端与 Python、前端测试与构建、提交与 Compose 配置 3 项检查全部通过；CodeRabbit 通过 |
| PR #23 生产拆分导出验收 | 脱敏批次 22 满足 `81 = 46 可导入 + 35 待处理`；25 件人工解决数据与原自动行合并后仅保留 1 条 46 件记录；模板示例行保留 |
| PR #23 部署后日志 | API、Worker、Web 和数据库无新增 5xx、异常栈或任务失败；回环及正式 HTTPS `/health` 均通过 |

前端构建存在约 1.2 MB 单包提示，不是构建失败。当前少量 PC 用户场景未因此出现已知功能问题。

## 4. 安全接续开发

### 4.1 工作目录

服务器 `/root/deliverynote` 主工作区包含用户未提交改动。不得在其中执行拉取、还原、清理、覆盖或提交操作。

使用独立 worktree：

```bash
cd /root/deliverynote
git fetch origin
git worktree add .worktrees/<task-name> -b <task-branch> origin/master
cd .worktrees/<task-name>
```

进入任务 worktree 后：

```bash
cat AGENTS.md
cat README.md
cat HANDOFF_WEB_UPGRADE.md
git status -sb
git diff --check
```

当前文档工作位于：

```text
/root/deliverynote/.worktrees/admin-maintenance
```

### 4.2 修改原则

- 先阅读相关测试和调用链，再修改业务代码；
- 修复缺陷时先定位或新增可复现测试；
- Web、CLI、Worker 共用核心匹配逻辑；
- 使用明确路径暂存，提交前检查 `git diff --cached --name-only`；
- 不处理与当前任务无关的用户改动；
- 不调用 Superpowers 插件；
- 不使用 `git reset --hard`、`git clean` 或批量删除；
- 不提交 `.env`、真实 Excel、数据库、日志、上传文件或导出结果。

### 4.3 业务安全闸门

涉及匹配、拆分、导出或超收时，至少复核：

1. 文件顺序决定共享采购余额的连续扣减顺序；
2. 供应商成品本地仓仍为第一优先仓；
3. 其他仓库排序保持确定性；
4. 商品锁仓仍能解决 SKU/站点歧义；
5. 拆分数量均为正且总和不变；
6. `交货总量 = 可导入总量 + 待处理总量`；
7. 任一文件失败不留下批次部分结果；
8. CLI、A:G、模板样式、备注和导出命名兼容；
9. 不跨批次扣减采购余额，不做 ERP 回写；
10. 超收规则外数量完整进入待处理。

## 5. 发布 Runbook

以下步骤用于源码或运行配置变更。纯文档变更不需要部署生产容器。

### 5.1 发布前条件

- 已得到本次部署确认；
- 发布提交位于远端，提交 SHA 明确；
- 使用干净的发布 worktree，不使用 `/root/deliverynote` 主工作区；
- `git status -sb` 无意外改动；
- `git diff --check` 通过；
- 与改动范围对应的自动化测试已通过；
- Python 变更已通过 Ruff；
- Python 依赖变更时 `pip check` 通过；
- 前端变更时测试与生产构建通过；
- Compose 或环境变更时 `docker compose config` 通过；
- 已记录变更前容器状态和健康状态。

### 5.2 变更前只读检查

在发布 worktree 中执行，并保持生产项目名和环境文件路径不变：

```bash
WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote ps

curl -fsS https://deliverynote.seekwaygroup.com/health
```

如当前状态已异常，先保留日志和现场信息，不要把发布当作未经诊断的“重启修复”。

### 5.3 构建与配置校验

```bash
WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote config --quiet

WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote build api worker web
```

构建不会替换正在运行的容器。构建失败时停止发布，生产仍保持原容器。

### 5.4 数据库迁移

当前使用一个专用幂等迁移维护超收规则表与待处理分配明细字段：

```bash
WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote run --rm api \
  python -m delivery_note.migrations.overreceipt_rules
```

该迁移创建缺失的超收规则表，并在 `exceptions` 中确保以下三个可空整数字段存在：

- `purchase_allocated_quantity`：本条正常采购分配量；
- `overreceipt_allocated_quantity`：本条超收规则分配量；
- `overreceipt_remaining_quantity`：本条处理后的共享额度余量。

历史待处理记录保持空值，页面明确显示“历史批次暂无额度明细”，不使用规则上限倒推。迁移不改写历史数量，也不改变 Excel 异常明细列或 A:G 导出。迁移只允许使用当前仓库已审查的模块；不要直接对生产数据库执行临时 DDL，也不要删除已有表或列。

### 5.5 更新服务

```bash
WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote up -d api worker web

WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote ps
```

禁止执行：

```bash
docker compose down -v
```

该命令会删除数据库与业务文件数据卷。

### 5.6 发布后验证

至少完成：

```bash
curl -fsS http://127.0.0.1:18080/health
curl -fsS https://deliverynote.seekwaygroup.com/health

WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote ps
```

随后在 PC 浏览器执行与变更范围对应的烟雾检查：

- 登录与退出；
- 批次列表加载；
- 打开一个批次详情并刷新；
- 基础资料状态加载；
- 如涉及批次逻辑，使用脱敏数据创建和计算新批次；
- 如涉及导出，下载并打开对应 Excel/ZIP；
- 如涉及北京时间，使用非北京时间浏览器时区复核；
- 检查浏览器控制台和失败请求。

不要把 `/health` 成功等同于完整业务验收。

### 5.7 发布记录

发布完成后记录：

- 发布提交 SHA 与 Git tree；
- 发布时间（Asia/Shanghai）；
- 执行的迁移；
- 容器状态；
- 健康检查；
- 实际执行的自动化测试和浏览器场景；
- 新前端资源名；
- 未覆盖项目和残余风险。

## 6. 回退边界

当前没有通用数据库迁移版本登记，也没有自动应用回退机制。回退必须按变更性质评估：

| 变更类型 | 处理原则 |
| --- | --- |
| 纯前端 | 可从已知提交重新构建 `web`，仍需复核 API 兼容性 |
| 后端但无数据结构变化 | 可从已知提交重新构建 `api`、`worker`，并执行健康和业务烟雾检查 |
| 含数据库结构或数据语义变化 | 不自动回退；先确认旧代码与当前结构兼容 |
| 批次计算或导出错误 | 保留现场与文件，不直接修改生产数据库“修结果” |

超收规则表和待处理分配明细字段均为向前兼容的加法迁移。代码回退时不要尝试删除其表结构、历史版本或可空字段。

任何回退都必须：

- 使用明确的已知提交；
- 使用生产项目名 `deliverynote`；
- 保留两个生产数据卷；
- 不执行 `down -v`；
- 不用 `git reset --hard` 处理发布目录；
- 完成与正常发布相同的后置验证。

## 7. 故障检查

先只读收集证据，再决定是否重启或变更。通用日志命令：

```bash
WEB_PORT=18080 docker compose \
  --env-file /root/deliverynote/.env \
  -p deliverynote logs --tail=200 api worker web db
```

| 现象 | 优先检查 | 禁止的捷径 |
| --- | --- | --- |
| HTTPS 或页面不可达 | 正式 `/health`、回环 `/health`、`web`/`api` 状态、反向代理日志 | 删除容器或数据卷 |
| API 不健康 | `api` 与 `db` 健康状态、数据库连接错误、环境变量是否加载 | 临时修改生产库结构 |
| 登录失败 | API 日志、账号是否停用、密码是否由应用内重置过 | 仅修改 `.env` 并假设旧账号密码被重置 |
| Worker 长时间不完成 | `worker`/`api`/`db` 日志、任务状态、租约与心跳 | 启动第二个 Worker 并行抢任务 |
| 上传被拒绝 | 文件大小、扩展名、Excel 结构、`MAX_UPLOAD_BYTES` | 放宽正式字段校验兼容坏文件 |
| 库位导入预览失效 | API 是否重启、预览是否超过 TTL、草稿修订号 | 绕过修订冲突直接覆盖草稿 |
| 数量不守恒 | 保留批次和来源文件，核对文件顺序、采购快照、规则版本和待处理投影 | 直接改数据库数量 |
| 导出缺失或损坏 | Worker 日志、批次状态、共享文件卷挂载、结果文件是否存在 | 重建 `delivery_data` 卷 |
| 浏览器刷新离开详情 | 当前 URL 是否为 `/batches/{id}`、前端资源是否为预期版本 | 用浏览器缓存问题掩盖路由缺陷 |

若问题影响业务数量，应先复制脱敏场景在非生产环境复现并补测试，再做最小修复。

## 8. 生产数据说明

截至 2026-07-23 的只读核对：

- 共 13 个批次，状态均为 `succeeded`；
- 当前没有 `queued` 或 `running` 任务；
- 历史异常包含测试、重复处理和真实业务记录，聚合数量不能直接视为真实未结业务；
- 批次 8–11 的同名来源文件 SHA-256 相同，是同一原文件的多次处理；
- 批次 12 与批次 11 文件名相同，但 SHA-256 不同，不能据名称认定为重复；
- 批次 11 满足 `7732 = 7221 + 511`，其中 511 件仍需业务人员决定；
- 批次 13 原待处理 107 件，已拆分解决 80 件，当前有效待处理 27 件。

2026-07-29 部署 PR #23 时新增脱敏验收批次 22，名称以
`部署验收-ed710f8-人工拆分-` 开头。该批次只用于验证人工拆分导出兼容性，
应与正式业务批次区分并按数据安全规则保留。

未经业务确认，不得删除、合并或批量修改这些批次。技术人员只负责说明数据关系，不替代业务人员判断哪些记录属于验收、重复或正式处理。

## 9. 超收规则运维口径

- 初始默认关闭；
- `admin` 与 `operator` 都能发布新版本或重新启用历史版本；
- 版本发布后不可修改；
- 新批次锁定创建时启用的规则，旧批次不追溯变化；
- 短尾、中尾、长尾配置绝对件数；
- 仓库采用精确白名单，空列表表示全部禁止；
- 正式仓库名为“供应商成品本地仓”；
- 空定位、未知定位和多 MSKU 定位冲突不获得超收额度；
- 额度在批次内按 `供应商 + SKU + 站点` 共享；
- 先扣采购余额，再按文件顺序扣超收额度；
- 只有采购快照中存在且命中白名单的仓库可以超收；
- 规则外数量继续进入待处理。

发布规则前必须让操作人员确认额度、仓库白名单和版本说明。不得修改历史版本来“修正”已创建批次。

## 10. 数据、安全与备份决策

- 正式凭据仅保存在部署环境，不进入仓库；
- 正式访问使用 HTTPS；
- 两个生产数据卷不得删除或重建；
- 不以数据库直改代替产品操作；
- 不提交业务文件、导出结果或包含业务数据的截图；
- 用户已明确决定当前小规模工具不启用自动备份定时器；
- 仓库中的备份脚本与 systemd 示例保持未启用状态，不把“尚未启用”描述为“已备份”。

“不启用自动备份”是当前运维取舍，不代表删除现有数据卷，也不授权清理任何历史数据。

## 11. 已知限制与扩展触发条件

| 当前限制 | 当前处理 | 重新评估触发条件 |
| --- | --- | --- |
| 单 API、单 Worker | 保持简单部署 | 使用人数、吞吐或任务等待出现可量化瓶颈 |
| 导入预览为进程内 Token | 接受重启后预览失效 | 需要多 API 或长时间恢复预览 |
| 无通用 migration history | 维护专用幂等迁移 | 数据结构变更频率明显增加 |
| 审计只显示最近 200 条 | 满足当前追溯范围 | 业务要求完整检索或合规留存 |
| GitHub Actions 仅做质量检查 | 保持生产发布人工确认 | 需要自动部署时另行评估权限与回退 |
| 前端单包较大 | 当前不做专项拆包 | 实测加载性能影响操作 |
| 无手机端 | PC 为唯一验收范围 | 业务明确提出移动端场景 |
| 无自动备份任务 | 遵循用户当前决定 | 用户重新提出恢复点要求 |

不为追求“架构完整”提前引入平台组件。

## 12. 后续工作顺序

当前没有必须立即开发的新功能。后续按以下优先级处理：

1. 根据真实操作反馈定位明确问题；
2. 由业务人员确认历史批次的业务性质和未结数量；
3. 修改业务逻辑前建立可复现测试；
4. 以最小变更修复，并执行对应验证矩阵；
5. 仅约束新增或修改代码，不为历史格式执行无业务收益的全仓重写；
6. 只有达到上表触发条件后，才评估架构扩展。

## 13. 新会话启动模板

> 请在独立 worktree 中继续任务。先完整阅读 `AGENTS.md`、`README.md` 和 `HANDOFF_WEB_UPGRADE.md`，运行 `git status -sb`、Ruff 与 `git diff --check`。不要进入、覆盖或清理 `/root/deliverynote` 主工作区，其中有用户未提交改动。保持单机、单 API、单 Worker 和 PC 范围；不做 ERP 回写，不跨批次扣减采购余额。修改业务逻辑前先读相关测试与调用链，保持文件顺序共享余额、数量守恒、供应商成品本地仓优先、锁仓、拆分、CLI 和 A:G 导出兼容。不要调用 Superpowers 插件，不要删除 Docker 数据卷。
